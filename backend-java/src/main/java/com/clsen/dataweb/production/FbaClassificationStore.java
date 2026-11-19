package com.clsen.dataweb.production;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Reason allocations accompany inventory events inside the existing site-locked transaction. */
final class FbaClassificationStore {
    static final List<String> REASONS = List.of("WAREHOUSE_DAMAGED", "CARRIER_DAMAGED", "DEFECTIVE", "CUSTOMER_DAMAGED", "OTHER", "UNCLASSIFIED");
    private final JdbcTemplate db;
    private final ObjectMapper json;

    FbaClassificationStore(JdbcTemplate db, ObjectMapper json) {
        this.db = db;
        this.json = json;
    }

    private static long number(Object value) { return InventoryService.n(value); }
    private static long add(long left, long right) { return InventoryService.total(left, right); }
    private static ProductionError invalid(String message) { return new ProductionError(409, "fba_classification_conflict", message); }
    private List<Map<String,Object>> rows(String sql, Object... args) {
        return db.queryForList(sql, args).stream().map(DestinationReceiptStore::normalized).toList();
    }
    static String reason(JsonNode line, JsonNode body) {
        String code = line.path("reason_code").asText(body.path("reason_code").asText("UNCLASSIFIED"));
        if (!REASONS.contains(code)) throw invalid("请选择有效的不可售原因。");
        return code;
    }
    static String disposition(String raw) {
        return switch (raw) {
            case "WAREHOUSE_DAMAGED", "CARRIER_DAMAGED", "DEFECTIVE", "CUSTOMER_DAMAGED" -> raw;
            case "DISTRIBUTOR_DAMAGED", "EXPIRED", "UNSELLABLE" -> "OTHER";
            default -> "UNCLASSIFIED";
        };
    }

    private record Origin(long sku, long event) {}
    private static final class Lot {
        final Origin origin;
        final Map<String,Object> source;
        final Map<String,Long> amounts = new LinkedHashMap<>();
        boolean manual;
        String raw = "";
        String sourceKind = "LEGACY";
        String reportVersion = "";

        Lot(Origin origin, Map<String,Object> source) {
            this.origin = origin;
            this.source = source;
            REASONS.forEach(code -> amounts.put(code, 0L));
        }
        void change(String code, long units) {
            long next = add(amounts.get(code), units);
            if (next < 0) throw invalid("分类来源数量已变化，请核对恢复、更正及原收货记录。");
            amounts.put(code, next);
        }
        long remaining() { return amounts.values().stream().reduce(0L, FbaClassificationStore::add); }
    }
    private static final class Snapshot {
        final LinkedHashMap<Origin,Lot> lots = new LinkedHashMap<>();
        final List<Map<String,Object>> history = new ArrayList<>();
        final List<Map<String,Object>> pending = new ArrayList<>();
        final List<Map<String,Object>> allPending = new ArrayList<>();
        final Map<Long,Long> expected = new LinkedHashMap<>();
        String issue;

        void requireReady() { if (issue != null) throw invalid(issue); }
    }
    private record Allocation(long origin, String reason, long units) {}

    private Snapshot project(ProductionContext context, Map<String,Object> scope, long before) {
        long site = context.site(), warehouse = number(scope.get("warehouse_id")), owner = number(scope.get("owner_id"));
        var events = rows("SELECT id,sku_id,delta_units,document_kind,document_id,revision,reason,actor_name,business_date,created_at FROM inventory_event WHERE site_id=? AND warehouse_id=? AND owner_id=? AND quality='DEFECTIVE' ORDER BY id", site, warehouse, owner);
        var entries = rows("SELECT * FROM fba_inventory_classification WHERE site_id=? AND scope_id=? ORDER BY id", site, scope.get("id"));
        var balances = rows("SELECT sku_id,defective_units FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=? ORDER BY sku_id", site, warehouse, owner);
        var fullNet = new HashMap<Long,Long>();
        var includedNet = new HashMap<Long,Long>();
        for (var event : events) {
            long sku = number(event.get("sku_id")), units = number(event.get("delta_units"));
            fullNet.merge(sku, units, FbaClassificationStore::add);
            if (number(event.get("id")) < before) includedNet.merge(sku, units, FbaClassificationStore::add);
        }
        var snapshot = new Snapshot();
        for (var balance : balances) {
            long sku = number(balance.get("sku_id")), units = number(balance.get("defective_units"));
            long baseline = add(units, -fullNet.getOrDefault(sku, 0L));
            snapshot.expected.put(sku, add(baseline, includedNet.getOrDefault(sku, 0L)));
            if (baseline > 0) {
                var lot = new Lot(new Origin(sku, 0), Map.of("business_date", scope.get("cutoff_on"), "reason", "历史未分类余额", "actor_name", "历史记录", "document_kind", "opening", "document_id", scope.get("id")));
                lot.change("UNCLASSIFIED", baseline);
                snapshot.lots.put(lot.origin, lot);
            }
            if (baseline < 0) snapshot.issue = "分类依据与当前不可售余额需要核对，请先查看库存记录。";
        }
        var byEvent = new HashMap<Long,List<Map<String,Object>>>();
        var transfers = new ArrayList<Map<String,Object>>();
        var resolved = new HashSet<Long>();
        for (var entry : entries) {
            if (entry.get("inventory_event_id") != null) byEvent.computeIfAbsent(number(entry.get("inventory_event_id")), ignored -> new ArrayList<>()).add(entry);
            else if (number(entry.get("after_event_id")) < before) transfers.add(entry);
            if (entry.get("operation_kind").equals("RESOLVE")) resolved.add(number(entry.get("related_id")));
        }
        transfers.sort(Comparator.<Map<String,Object>>comparingLong(entry -> number(entry.get("after_event_id"))).thenComparingLong(entry -> number(entry.get("id"))));
        int transfer = 0;
        try {
            for (var event : events) {
                long eventId = number(event.get("id"));
                if (eventId >= before) break;
                while (transfer < transfers.size() && number(transfers.get(transfer).get("after_event_id")) < eventId) applyTransfer(snapshot, transfers.get(transfer++), resolved);
                long sku = number(event.get("sku_id")), units = number(event.get("delta_units"));
                var allocations = byEvent.getOrDefault(eventId, List.of());
                if (units > 0) {
                    var lot = new Lot(new Origin(sku, eventId), event);
                    snapshot.lots.put(lot.origin, lot);
                    if (allocations.isEmpty()) lot.change("UNCLASSIFIED", units);
                }
                if (allocations.isEmpty()) {
                    if (units < 0) consume(snapshot, sku, -units, null, null, true);
                    snapshot.history.add(history(event, "UNCLASSIFIED", units, "LEGACY", ""));
                } else {
                    long allocated = 0;
                    for (var allocation : allocations) {
                        var origin = new Origin(sku, allocation.get("origin_event_id") == null ? 0 : number(allocation.get("origin_event_id")));
                        var lot = snapshot.lots.get(origin);
                        if (lot == null) throw invalid("分类原记录需要重新核对。");
                        lot.change(allocation.get("reason_code").toString(), number(allocation.get("units")));
                        if (units > 0) {
                            lot.sourceKind = allocation.get("source_kind").toString();
                            lot.raw = allocation.get("raw_disposition").toString();
                            lot.reportVersion = Objects.toString(allocation.get("report_version_id"), "");
                        }
                        allocated = add(allocated, number(allocation.get("units")));
                        var record = history(event, allocation.get("reason_code").toString(), number(allocation.get("units")), allocation.get("source_kind").toString(), lot.raw);
                        record.put("id", "entry:" + allocation.get("id"));
                        record.put("origin_event_id", Long.toString(origin.event));
                        record.put("report_version_id", allocation.get("report_version_id"));
                        snapshot.history.add(record);
                    }
                    if (allocated != units) throw invalid("库存事件与分类分配数量不一致，请核对原记录。");
                }
            }
            while (transfer < transfers.size()) applyTransfer(snapshot, transfers.get(transfer++), resolved);
            var actual = new HashMap<Long,Long>();
            snapshot.lots.values().forEach(lot -> actual.merge(lot.origin.sku, lot.remaining(), FbaClassificationStore::add));
            for (var expected : snapshot.expected.entrySet()) if (!expected.getValue().equals(actual.getOrDefault(expected.getKey(), 0L))) throw invalid("分类合计与不可售余额不一致，请核对库存记录。");
        } catch (ProductionError error) {
            snapshot.issue = error.getMessage();
        }
        // Only the newest unresolved proposal for an origin needs the user's attention.
        var latest = new LinkedHashMap<Origin,Map<String,Object>>();
        for (var entry : snapshot.pending) latest.put(origin(entry), entry);
        snapshot.pending.clear();
        snapshot.pending.addAll(latest.values().stream().filter(entry -> {
            var lot = snapshot.lots.get(origin(entry));
            return lot != null && lot.remaining() > 0;
        }).toList());
        return snapshot;
    }

    private static Origin origin(Map<String,Object> entry) {
        return new Origin(number(entry.get("sku_id")), entry.get("origin_event_id") == null ? 0 : number(entry.get("origin_event_id")));
    }
    private void applyTransfer(Snapshot snapshot, Map<String,Object> entry, Set<Long> resolved) {
        String operation = entry.get("operation_kind").toString();
        if (operation.equals("REVIEW")) {
            if (!resolved.contains(number(entry.get("id")))) {
                snapshot.pending.add(entry);
                snapshot.allPending.add(entry);
            }
            return;
        }
        if (operation.equals("RESOLVE")) return;
        var lot = snapshot.lots.get(origin(entry));
        if (lot == null) throw invalid("分类更正对应的原记录需要重新核对。");
        if (operation.equals("SOURCE")) {
            lot.raw = entry.get("raw_disposition").toString();
            lot.reportVersion = Objects.toString(entry.get("report_version_id"), "");
            lot.manual = entry.get("source_kind").equals("MANUAL");
        } else {
            lot.change(entry.get("reason_code").toString(), number(entry.get("units")));
            if (operation.equals("CORRECT")) lot.manual = true;
        }
        snapshot.history.add(history(entry, entry.get("reason_code").toString(), number(entry.get("units")), entry.get("source_kind").toString(), lot.raw));
    }
    private Map<String,Object> history(Map<String,Object> source, String code, long units, String kind, String raw) {
        var row = new LinkedHashMap<String,Object>();
        row.put("id", (source.containsKey("operation_kind") ? "classification:" : "event:") + source.get("id") + ":" + code);
        row.put("origin_event_id", source.getOrDefault("origin_event_id", source.get("id")));
        row.put("sku_id", source.get("sku_id"));
        row.put("reason_code", code);
        row.put("units", Long.toString(units));
        row.put("business_date", source.get("business_date"));
        row.put("occurred_at", source.get("created_at"));
        row.put("note", source.getOrDefault("note", source.get("reason")));
        row.put("actor_name", source.get("actor_name"));
        row.put("source_kind", kind);
        row.put("raw_disposition", raw);
        row.put("operation_kind", source.getOrDefault("operation_kind", units > 0 ? "ASSIGN" : "CONSUME"));
        row.put("document_kind", source.get("document_kind"));
        row.put("document_id", source.get("document_id"));
        return row;
    }

    private List<Allocation> consume(Snapshot snapshot, long sku, long units, String reason, Set<Long> origins, boolean legacy) {
        var result = new ArrayList<Allocation>();
        for (var lot : snapshot.lots.values()) {
            if (lot.origin.sku != sku || origins != null && !origins.contains(lot.origin.event)) continue;
            for (String code : REASONS) {
                if (reason != null && !reason.equals(code)) continue;
                long taken = Math.min(units, lot.amounts.get(code));
                if (taken == 0) continue;
                lot.change(code, -taken);
                result.add(new Allocation(lot.origin.event, code, taken));
                units -= taken;
                if (units == 0) return result;
            }
        }
        if (units != 0) throw invalid(legacy ? "历史不可售事件与余额需要核对。" : "所选原因的可恢复数量不足，或原记录已有下游处理，请重新核对。");
        return result;
    }
    private List<Map<String,Object>> documentEvents(ProductionContext c, Map<String,Object> scope, String kind, long document, long revision) {
        return rows("SELECT * FROM inventory_event WHERE site_id=? AND warehouse_id=? AND owner_id=? AND quality='DEFECTIVE' AND document_kind=? AND document_id=? AND revision=? ORDER BY id", c.site(), scope.get("warehouse_id"), scope.get("owner_id"), kind, document, revision);
    }
    private long watermark(ProductionContext c, Map<String,Object> scope) {
        return db.queryForObject("SELECT COALESCE(MAX(id),0) FROM inventory_event WHERE site_id=? AND warehouse_id=? AND owner_id=?", Long.class, c.site(), scope.get("warehouse_id"), scope.get("owner_id"));
    }
    private void insert(ProductionContext c, Map<String,Object> scope, long sku, Long event, long origin, long after, String entry, String code, long units, String operation, String source, String raw, String reportVersion, Long related, String token, String note, String date) {
        db.update("INSERT INTO fba_inventory_classification(site_id,scope_id,sku_id,inventory_event_id,origin_event_id,after_event_id,entry_key,reason_code,units,operation_kind,source_kind,raw_disposition,report_version_id,related_id,operation_token,note,actor_id,actor_name,business_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", c.site(), scope.get("id"), sku, event, origin == 0 ? null : origin, after, entry, code, units, operation, source, raw, reportVersion.isEmpty() ? null : Long.parseLong(reportVersion), related, token, note, c.actor(), c.actorName(), date);
    }
    private void annotate(ProductionContext c, Map<String,Object> scope, Map<String,Object> event, List<Allocation> allocations, String token, String source, String raw, String version) {
        long eventId = number(event.get("id"));
        for (var allocation : allocations) insert(c, scope, number(event.get("sku_id")), eventId, allocation.origin, eventId, "event:" + eventId + ":" + allocation.origin + ":" + allocation.reason, allocation.reason, allocation.units, allocation.units > 0 ? "ASSIGN" : "CONSUME", source, raw, version, null, token, event.get("reason").toString(), event.get("business_date").toString());
    }

    void recordQuality(ProductionContext c, Map<String,Object> scope, JsonNode body, long revision, String token) {
        var events = documentEvents(c, scope, "fba_quality", number(scope.get("id")), revision);
        if (events.isEmpty()) return;
        var snapshot = project(c, scope, number(events.getFirst().get("id")));
        snapshot.requireReady();
        for (var event : events) {
            long sku = number(event.get("sku_id")), units = number(event.get("delta_units"));
            JsonNode line = null;
            for (var candidate : body.path("lines")) if (InventoryService.positive(candidate, "sku_id") == sku) line = candidate;
            if (line == null) throw invalid("分类对应商品需要重新核对。");
            var allocations = new ArrayList<Allocation>();
            if (units > 0) {
                String code = reason(line, body);
                if (code.equals("OTHER") && body.path("reason").asText().isBlank()) throw invalid("其他原因请填写说明。");
                allocations.add(new Allocation(number(event.get("id")), code, units));
            }
            else if (line.has("reason_allocations")) {
                long total = 0;
                var seen = new HashSet<String>();
                for (var part : line.path("reason_allocations")) {
                    String code = reason(part, json.createObjectNode());
                    long amount = InventoryService.positive(part, "units");
                    if (!seen.add(code)) throw invalid("同一商品的恢复原因请合并填写。");
                    allocations.addAll(consume(snapshot, sku, amount, code, null, false));
                    total = add(total, amount);
                }
                if (total != -units) throw invalid("恢复总量必须等于各原因分配数量之和。");
            } else {
                var availableReasons = new HashSet<String>();
                snapshot.lots.values().stream().filter(lot -> lot.origin.sku == sku).forEach(lot -> lot.amounts.forEach((code, amount) -> { if (amount > 0) availableReasons.add(code); }));
                if (availableReasons.size() > 1) throw invalid("该商品存在多种不可售原因，请选择各原因的恢复数量。");
                allocations.addAll(consume(snapshot, sku, -units, null, null, false));
            }
            if (units < 0) allocations.replaceAll(part -> new Allocation(part.origin, part.reason, -part.units));
            annotate(c, scope, event, allocations, token, "MANUAL", "", "");
        }
    }

    void recordReceipt(ProductionContext c, Map<String,Object> scope, long receipt, Long correction, String raw, String token) {
        recordDocument(c, scope, "fba_receipt", receipt, 1, token, "REPORT", Map.of(), raw, correction);
    }
    void recordAction(ProductionContext c, Map<String,Object> scope, long action, long revision, String token, JsonNode body, boolean reversed) {
        var reasons = new HashMap<Long,JsonNode>();
        for (var line : body.path("lines")) reasons.put(InventoryService.positive(line, "sku_id"), line);
        recordDocument(c, scope, "fba_return", action, revision, token, body.hasNonNull("report_return_key") ? "REPORT" : "MANUAL", reasons, "", reversed ? action : null);
    }
    private void recordDocument(ProductionContext c, Map<String,Object> scope, String kind, long document, long revision, String token, String source, Map<Long,JsonNode> reasons, String raw, Long correction) {
        var events = documentEvents(c, scope, kind, document, revision);
        if (events.isEmpty()) return;
        var snapshot = project(c, scope, number(events.getFirst().get("id")));
        snapshot.requireReady();
        for (var event : events) {
            long sku = number(event.get("sku_id")), units = number(event.get("delta_units"));
            JsonNode line = reasons.getOrDefault(sku, json.createObjectNode());
            String disposition = line.path("raw_disposition").asText(raw);
            String version = line.path("report_version_id").asText("");
            List<Allocation> allocations;
            boolean inheritedManual = false;
            if (units > 0 && correction != null && kind.equals("fba_receipt")) {
                var inherited = new LinkedHashMap<String,Long>();
                for (var prior : documentEvents(c, scope, kind, correction, 1)) {
                    for (var part : rows("SELECT origin_event_id,reason_code,units FROM fba_inventory_classification WHERE site_id=? AND scope_id=? AND inventory_event_id=?", c.site(), scope.get("id"), prior.get("id"))) {
                        inherited.merge(part.get("reason_code").toString(), -number(part.get("units")), FbaClassificationStore::add);
                        var original = snapshot.lots.get(new Origin(sku, part.get("origin_event_id") == null ? 0 : number(part.get("origin_event_id"))));
                        inheritedManual |= original != null && original.manual;
                    }
                }
                // Earlier positive corrections have already restored part of this negative event.
                for (var part : rows("SELECT c.reason_code,SUM(c.units) AS units FROM fba_receipt_event r JOIN inventory_event e ON e.site_id=r.site_id AND e.document_kind='fba_receipt' AND e.document_id=r.id JOIN fba_inventory_classification c ON c.site_id=e.site_id AND c.inventory_event_id=e.id WHERE r.site_id=? AND r.scope_id=? AND r.correction_of=? AND r.units>0 GROUP BY c.reason_code", c.site(), scope.get("id"), correction)) inherited.merge(part.get("reason_code").toString(), -number(part.get("units")), FbaClassificationStore::add);
                var parts = new ArrayList<Allocation>();
                long remaining = units;
                for (String code : REASONS) {
                    long amount = Math.min(remaining, Math.max(0, inherited.getOrDefault(code, 0L)));
                    if (amount > 0) parts.add(new Allocation(number(event.get("id")), code, amount));
                    remaining -= amount;
                }
                if (remaining > 0) parts.add(new Allocation(number(event.get("id")), "UNCLASSIFIED", remaining));
                allocations = parts;
            } else if (units > 0) allocations = List.of(new Allocation(number(event.get("id")), disposition.isEmpty() ? reason(line, json.createObjectNode()) : disposition(disposition), units));
            else {
                Set<Long> origins = null;
                if (correction != null) {
                    origins = new HashSet<>();
                    for (var prior : documentEvents(c, scope, kind, correction, 1)) if (number(prior.get("sku_id")) == sku) origins.add(number(prior.get("id")));
                }
                allocations = consume(snapshot, sku, -units, null, origins, false).stream().map(part -> new Allocation(part.origin, part.reason, -part.units)).toList();
            }
            annotate(c, scope, event, allocations, token, source, disposition, version);
            if (inheritedManual) {
                long eventId = number(event.get("id"));
                insert(c, scope, sku, null, eventId, eventId, "inherit:" + eventId, disposition(disposition), 0, "SOURCE", "MANUAL", disposition, version, null, token, "沿用原接收记录的人工分类", event.get("business_date").toString());
                if (allocations.stream().anyMatch(part -> !part.reason.equals(disposition(disposition)))) insert(c, scope, sku, null, eventId, eventId, "review:" + eventId, disposition(disposition), 0, "REVIEW", "REPORT", disposition, version, null, token, "更正后的原报告分类与人工决定不同，请核对", event.get("business_date").toString());
            }
        }
    }

    Object summary(ProductionContext c, Map<String,Object> scope) {
        var snapshot = project(c, scope, Long.MAX_VALUE);
        var totals = new LinkedHashMap<String,String>();
        for (String code : REASONS) totals.put(code, Long.toString(snapshot.lots.values().stream().mapToLong(lot -> lot.amounts.get(code)).reduce(0L, FbaClassificationStore::add)));
        var result = new LinkedHashMap<String,Object>();
        result.put("scope_id", scope.get("id"));
        result.put("revision", scope.get("revision"));
        result.put("ready", snapshot.issue == null);
        result.put("issue", snapshot.issue);
        result.put("totals", snapshot.issue == null ? totals : Map.of());
        result.put("items", snapshot.issue == null ? currentRows(snapshot) : List.of());
        result.put("pending", snapshot.pending);
        result.put("stock_effect", false);
        return result;
    }
    private List<Map<String,Object>> currentRows(Snapshot snapshot) {
        var result = new ArrayList<Map<String,Object>>();
        for (var lot : snapshot.lots.values()) for (String code : REASONS) {
            long units = lot.amounts.get(code);
            if (units == 0) continue;
            var row = history(lot.source, code, units, lot.sourceKind, lot.raw);
            row.put("id", "origin:" + lot.origin.sku + ":" + lot.origin.event + ":" + code);
            row.put("origin_event_id", Long.toString(lot.origin.event));
            row.put("sku_id", Long.toString(lot.origin.sku));
            row.put("manual_override", lot.manual);
            row.put("report_version_id", lot.reportVersion);
            addReference(row);
            result.add(row);
        }
        return result;
    }
    Object details(ProductionContext c, Map<String,Object> scope, Map<String,String> query) {
        var snapshot = project(c, scope, Long.MAX_VALUE);
        snapshot.requireReady();
        String view = query.getOrDefault("view", "current"), code = query.getOrDefault("reason_code", ""), sku = query.getOrDefault("sku_id", "");
        if (!Set.of("current", "history").contains(view) || !code.isEmpty() && !REASONS.contains(code)) throw invalid("请选择有效的分类或记录视图。");
        int page = page(query.getOrDefault("page", "1"), Integer.MAX_VALUE), size = page(query.getOrDefault("page_size", "20"), 100);
        String from = query.getOrDefault("from", ""), to = query.getOrDefault("to", "");
        if (!from.isEmpty()) InventoryService.day(from);
        if (!to.isEmpty()) InventoryService.day(to);
        if (!from.isEmpty() && !to.isEmpty() && from.compareTo(to) > 0) throw invalid("开始日期不能晚于结束日期。");
        Collections.reverse(snapshot.history);
        var items = (view.equals("current") ? currentRows(snapshot) : snapshot.history).stream().filter(row -> code.isEmpty() || code.equals(row.get("reason_code"))).filter(row -> sku.isEmpty() || sku.equals(row.get("sku_id"))).filter(row -> from.isEmpty() || row.get("business_date").toString().compareTo(from) >= 0).filter(row -> to.isEmpty() || row.get("business_date").toString().compareTo(to) <= 0).toList();
        long offset = (long)(page - 1) * size;
        var selected = items.stream().skip(offset).limit(size).toList();
        selected.forEach(this::addReference);
        return Map.of("items", selected, "total", items.size(), "page", page, "page_size", size, "view", view, "stock_effect", false);
    }
    private void addReference(Map<String,Object> row) {
        if (row.get("document_kind") == null && row.get("origin_event_id") != null) {
            var original = rows("SELECT document_kind,document_id FROM inventory_event WHERE id=?", row.get("origin_event_id"));
            if (!original.isEmpty()) row.putAll(original.getFirst());
        }
        if ("fba_receipt".equals(row.get("document_kind"))) {
            var found = rows("SELECT batch_id FROM fba_receipt_event WHERE id=?", row.get("document_id"));
            if (!found.isEmpty()) row.put("batch_id", found.getFirst().get("batch_id"));
        }
    }
    private static int page(String raw, int maximum) {
        try { int value = Integer.parseInt(raw); if (value > 0 && value <= maximum) return value; } catch (NumberFormatException ignored) { }
        throw invalid("请使用有效页码及每页数量。");
    }

    void correct(ProductionContext c, Map<String,Object> scope, JsonNode body, String token) {
        var snapshot = project(c, scope, Long.MAX_VALUE);
        snapshot.requireReady();
        long sku = InventoryService.positive(body, "sku_id");
        String note = InventoryService.text(body, "reason", 2000);
        if (note.isBlank()) throw invalid("请填写分类核对说明。");
        if (body.hasNonNull("review_id")) {
            long review = InventoryService.positive(body, "review_id");
            var pending = snapshot.pending.stream().filter(row -> number(row.get("id")) == review && number(row.get("sku_id")) == sku).findFirst().orElseThrow(() -> invalid("报告分类待核记录已变化，请重新读取。"));
            var lot = snapshot.lots.get(origin(pending));
            if (body.path("accept_report").asBoolean()) {
                reclassify(c, scope, lot, null, pending.get("reason_code").toString(), lot.remaining(), token, note, false, pending.get("raw_disposition").toString(), Objects.toString(pending.get("report_version_id"), ""));
                source(c, scope, lot, pending.get("reason_code").toString(), pending.get("raw_disposition").toString(), Objects.toString(pending.get("report_version_id"), ""), token, note);
            }
            resolve(c, scope, lot, snapshot, token, note);
        } else {
            long origin = InventoryService.number(body, "origin_event_id");
            var lot = snapshot.lots.get(new Origin(sku, origin));
            if (lot == null) throw invalid("分类原记录不存在或范围不一致。");
            String from = body.path("from_reason").asText(), target = body.path("reason_code").asText();
            if (!REASONS.contains(from) || !REASONS.contains(target) || from.equals(target)) throw invalid("请选择不同的有效分类。");
            reclassify(c, scope, lot, from, target, InventoryService.positive(body, "units"), token, note, true, lot.raw, lot.reportVersion);
        }
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?", c.site(), scope.get("id"));
    }
    private void reclassify(ProductionContext c, Map<String,Object> scope, Lot lot, String from, String target, long units, String token, String note, boolean manual, String raw, String version) {
        long available = from == null ? lot.remaining() : lot.amounts.get(from);
        if (units > available) throw invalid("分类更正数量超过当前可归属数量。");
        long after = watermark(c, scope);
        String operation = manual ? "CORRECT" : "REPORT_CORRECT";
        long remaining = from == null ? units - lot.amounts.get(target) : units;
        for (String code : REASONS) {
            if (code.equals(target) || from != null && !from.equals(code)) continue;
            long moved = Math.min(remaining, lot.amounts.get(code));
            if (moved == 0) continue;
            String prefix = operation + ":" + token + ":" + lot.origin.event + ":" + code + ":" + target;
            insert(c, scope, lot.origin.sku, null, lot.origin.event, after, prefix + ":out", code, -moved, operation, manual ? "MANUAL" : "REPORT", raw, version, null, token, note, today());
            insert(c, scope, lot.origin.sku, null, lot.origin.event, after, prefix + ":in", target, moved, operation, manual ? "MANUAL" : "REPORT", raw, version, null, token, note, today());
            remaining -= moved;
        }
        if (remaining != 0) throw invalid("分类更正数量与来源不一致。");
    }
    private static String today() { return LocalDate.now(ZoneId.of("America/Los_Angeles")).toString(); }
    private void source(ProductionContext c, Map<String,Object> scope, Lot lot, String code, String raw, String version, String token, String note) {
        insert(c, scope, lot.origin.sku, null, lot.origin.event, watermark(c, scope), "source:" + token + ":" + lot.origin.event, code, 0, "SOURCE", "REPORT", raw, version, null, token, note, today());
    }
    private void resolve(ProductionContext c, Map<String,Object> scope, Lot lot, Snapshot snapshot, String token, String note) {
        for (var pending : snapshot.allPending) if (origin(pending).equals(lot.origin)) insert(c, scope, lot.origin.sku, null, lot.origin.event, watermark(c, scope), "resolve:" + token + ":" + pending.get("id"), pending.get("reason_code").toString(), 0, "RESOLVE", "MANUAL", pending.get("raw_disposition").toString(), Objects.toString(pending.get("report_version_id"), ""), number(pending.get("id")), token, note, today());
    }

    void reportReason(ProductionContext c, Map<String,Object> scope, long action, JsonNode line, String token) {
        var snapshot = project(c, scope, Long.MAX_VALUE);
        snapshot.requireReady();
        String raw = line.path("raw_disposition").asText(""), code = line.path("reason_code").asText(disposition(raw)), version = line.path("report_version_id").asText("");
        for (var event : documentEvents(c, scope, "fba_return", action, 1)) {
            var lot = snapshot.lots.get(new Origin(number(event.get("sku_id")), number(event.get("id"))));
            if (lot == null) continue;
            if (lot.manual && lot.amounts.entrySet().stream().anyMatch(entry -> !entry.getKey().equals(code) && entry.getValue() > 0)) {
                String key = "review:" + lot.origin.event + ":" + version + ":" + code;
                if (db.queryForObject("SELECT COUNT(*) FROM fba_inventory_classification WHERE site_id=? AND scope_id=? AND entry_key=?", Long.class, c.site(), scope.get("id"), key) == 0) insert(c, scope, lot.origin.sku, null, lot.origin.event, watermark(c, scope), key, code, 0, "REVIEW", "REPORT", raw, version, null, token, "新报告分类与人工决定不同，请核对", today());
            } else {
                reclassify(c, scope, lot, null, code, lot.remaining(), token, "已发布退货日报分类更新", false, raw, version);
                source(c, scope, lot, code, raw, version, token, "采用已发布报告处置字段");
                resolve(c, scope, lot, snapshot, token, "报告分类已核对一致");
            }
        }
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?", c.site(), scope.get("id"));
    }

    Map<String,Long> reportOverride(ProductionContext c, Map<String,Object> scope, long action) {
        var snapshot = project(c, scope, Long.MAX_VALUE);
        snapshot.requireReady();
        for (var event : documentEvents(c, scope, "fba_return", action, 1)) {
            var lot = snapshot.lots.get(new Origin(number(event.get("sku_id")), number(event.get("id"))));
            if (lot != null && lot.manual) return new LinkedHashMap<>(lot.amounts);
        }
        return Map.of();
    }

    void inheritReportOverride(ProductionContext c, Map<String,Object> scope, long action, Map<String,Long> previous, JsonNode line, String token) {
        if (previous.isEmpty() || !line.path("quality").asText().equals("DEFECTIVE")) return;
        var snapshot = project(c, scope, Long.MAX_VALUE);
        snapshot.requireReady();
        String reported = reason(line, json.createObjectNode());
        for (var event : documentEvents(c, scope, "fba_return", action, 1)) {
            var lot = snapshot.lots.get(new Origin(number(event.get("sku_id")), number(event.get("id"))));
            long remaining = lot.remaining();
            for (String code : REASONS) {
                long amount = Math.min(remaining, previous.getOrDefault(code, 0L));
                if (amount > 0 && !code.equals(reported)) reclassify(c, scope, lot, reported, code, amount, token, "沿用原退货记录的人工分类", true, lot.raw, lot.reportVersion);
                remaining -= amount;
            }
        }
        reportReason(c, scope, action, line, token);
    }
}
