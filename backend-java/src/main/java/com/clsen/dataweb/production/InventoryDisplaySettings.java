package com.clsen.dataweb.production;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Site-wide inventory table selection. Commands share the inventory site lock. */
final class InventoryDisplaySettings {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final InventoryService inventory;

    InventoryDisplaySettings(JdbcTemplate db, ObjectMapper json, InventoryService inventory) {
        this.db = db;
        this.json = json;
        this.inventory = inventory;
    }

    Object read(ProductionContext context) {
        var rows = db.queryForList("SELECT style_ids,sku_alert_settings,revision FROM inventory_display_settings WHERE site_id=?", context.site());
        return Map.of("style_ids", rows.isEmpty() ? json.createArrayNode() : json.readTree(rows.getFirst().get("style_ids").toString()),
                "sku_alert_settings", rows.isEmpty() || rows.getFirst().get("sku_alert_settings") == null ? json.createObjectNode() : json.readTree(rows.getFirst().get("sku_alert_settings").toString()),
                "revision", rows.isEmpty() ? "0" : rows.getFirst().get("revision").toString(),
                "can_manage", context.roles().contains("admin") || context.roles().contains("data_manager"));
    }

    Object save(ProductionContext context, JsonNode input, String token) {
        context.requireWrite();
        JsonNode before = json.valueToTree(read(context));
        long revision = InventoryService.number(input, "expected_revision");
        if (revision != before.path("revision").asLong())
            throw new ProductionError(409, "display_revision_conflict", "展示款号已被其他管理人员更新，请重新读取后再保存。");
        var selection = input.path("style_ids");
        if (!selection.isArray() || selection.size() > 1000)
            throw new ProductionError(422, "invalid_display_styles", "请选择有效的展示款号，每次最多1000款。");
        var identities = new HashMap<String,Long>();
        for (var sku : input.path("_catalog")) {
            if (!sku.path("status").asText().equals("active")) continue;
            String id = sku.path("style_id").asText();
            identities.put(id.isBlank() ? "sku-" + sku.path("sku_id").asText() : id, sku.path("sku_id").asLong());
        }
        var ids = new TreeSet<String>();
        for (var value : selection) {
            String id = value.asText();
            Long sku = identities.get(id);
            if (sku != null) inventory.displayIdentity(context.site(), input, sku);
            else if (!id.matches("history:[1-9][0-9]{0,18}") || db.queryForObject(
                    "SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND sku_id=?", Long.class,
                    context.site(), id.substring("history:".length())) == 0)
                throw new ProductionError(409, "display_style_unavailable", "所选款号已停用、不属于当前站点或身份尚未就绪，请重新核对选择。");
            if (!ids.add(id)) throw new ProductionError(422, "duplicate_display_style", "展示款号重复，请重新核对选择。");
        }
        JsonNode alerts = before.path("sku_alert_settings");
        if (input.has("sku_alert_settings")) {
            var changes = input.path("sku_alert_settings");
            if (!changes.isObject()) throw new ProductionError(422, "invalid_sku_alerts", "请提供按FBA范围及SKU保存的提醒设置。");
            var merged = (tools.jackson.databind.node.ObjectNode) alerts.deepCopy();
            for (var scopeEntry : changes.properties()) {
                String scopeId = scopeEntry.getKey();
                if (!scopeId.matches("[1-9][0-9]{0,18}") || db.queryForObject("SELECT COUNT(*) FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND s.id=? AND w.status='ACTIVE'", Long.class, context.site(), scopeId) != 1)
                    throw new ProductionError(409, "alert_scope_unavailable", "提醒范围已停用或不属于当前站点，请重新读取。");
                if (!scopeEntry.getValue().isObject()) throw new ProductionError(422, "invalid_sku_alerts", "SKU提醒设置格式无效。");
                var scopeAlerts = merged.path(scopeId).isObject() ? (tools.jackson.databind.node.ObjectNode) merged.path(scopeId).deepCopy() : json.createObjectNode();
                for (var entry : scopeEntry.getValue().properties()) {
                    String skuId = entry.getKey();
                    if (!skuId.matches("[1-9][0-9]{0,18}") || !input.path("_catalog").has(skuId))
                        throw new ProductionError(409, "alert_sku_unavailable", "所选SKU不属于当前目录，请重新读取。");
                    inventory.identity(context.site(), input, Long.parseLong(skuId));
                    if (db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?", Long.class, context.site(), scopeId, skuId) != 1)
                        throw new ProductionError(409, "alert_sku_unavailable", "所选SKU尚未关联该FBA范围。");
                    long threshold = InventoryService.number(entry.getValue(), "threshold");
                    if (!entry.getValue().path("replenish").isBoolean()) throw new ProductionError(422, "invalid_sku_alerts", "请选择是否继续补货。");
                    scopeAlerts.set(skuId, json.valueToTree(Map.of("threshold", Long.toString(threshold), "replenish", entry.getValue().path("replenish").asBoolean())));
                }
                merged.set(scopeId, scopeAlerts);
            }
            alerts = merged;
        }
        db.update("INSERT INTO inventory_display_settings(site_id,style_ids,sku_alert_settings,revision,actor_id,actor_name) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE style_ids=VALUES(style_ids),sku_alert_settings=VALUES(sku_alert_settings),revision=VALUES(revision),actor_id=VALUES(actor_id),actor_name=VALUES(actor_name)",
                context.site(), json.writeValueAsString(ids), json.writeValueAsString(alerts), revision + 1, context.actor(), context.actorName());
        Object result = read(context);
        inventory.audit(context, "stock_display", 0, revision + 1, token, "SET_DISPLAY_STYLES", "设置库存总览展示款号", before, result);
        return result;
    }
}
