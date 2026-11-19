package com.clsen.dataweb.production;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** One explicitly enabled source revision; no client-supplied stock or quality defaults. */
final class RealOpeningSource {
    static final String WAREHOUSE_BASIS="NORMAL_DISPATCHABLE_V1";
    private final JdbcTemplate db; private final ObjectMapper json; private final CatalogAuthority catalog;
    private final String review,warehouseName; private final long revision,warehouse;
    RealOpeningSource(JdbcTemplate db,ObjectMapper json,CatalogAuthority catalog,String review,long revision,long warehouse,String warehouseName) {
        this.db=db;this.json=json;this.catalog=catalog;this.review=review;this.revision=revision;this.warehouse=warehouse;this.warehouseName=warehouseName;
        if(!review.isEmpty() && (!catalog.enabled() || !UUID.fromString(review).toString().equals(review) || revision<1 || warehouse<1 || warehouseName.isBlank() || warehouseName.length()>120))throw new IllegalArgumentException("Opening requires an explicit source revision, warehouse and catalog scope");
    }
    boolean enabled(){return !review.isEmpty();}
    static Set<Long> additionalSkuIds(JsonNode previous,JsonNode current) {
        for(String field:List.of("review_id","source_digest","quantity_basis"))
            if(previous.path(field).asText().isEmpty() || !previous.path(field).equals(current.path(field)))
                throw new ProductionError(409,"opening_extension_conflict","补齐必须沿用原仓库表及正常可发口径，不能替换已登记来源。");
        var next=new HashMap<Long,JsonNode>();
        for(var cell:current.path("source_cells"))if(next.put(Long.parseLong(cell.path("sku_id").asText()),cell)!=null)
            throw new ProductionError(409,"opening_extension_conflict","同一商品不能重复补齐。");
        if(!previous.path("source_cells").isArray() || previous.path("source_cells").isEmpty())
            throw new ProductionError(409,"opening_extension_conflict","原期初没有完整来源，不能直接补齐。");
        for(var old:previous.path("source_cells")) {
            var match=next.remove(Long.parseLong(old.path("sku_id").asText()));
            for(String field:List.of("source_key","size","cell","units"))if(match==null || !old.path(field).equals(match.path(field)))
                throw new ProductionError(409,"opening_extension_conflict","已登记规格的来源、数量或商品身份发生变化，请保留原记录并单独核对。");
        }
        if(next.isEmpty())throw new ProductionError(409,"opening_extension_empty","本批规格均已登记，无需重复补齐。");
        return Set.copyOf(next.keySet());
    }
    static Map<Long,Long> supersedingDeltas(JsonNode previous,JsonNode current) {
        if(previous.path("review_id").asText().isEmpty() || current.path("review_id").asText().isEmpty()
            || previous.path("review_id").equals(current.path("review_id"))
            || !WAREHOUSE_BASIS.equals(previous.path("quantity_basis").asText())
            || !previous.path("quantity_basis").equals(current.path("quantity_basis")))
            throw supersessionConflict();
        var old=indexedCells(previous);var corrected=indexedCells(current);var deltas=new LinkedHashMap<Long,Long>();
        for(var entry:old.entrySet()) {
            var next=corrected.get(entry.getKey());
            if(next==null || !entry.getValue().path("size").equals(next.path("size")))throw supersessionConflict();
            long delta=Math.subtractExact(cellUnits(next),cellUnits(entry.getValue()));if(delta!=0)deltas.put(entry.getKey(),delta);
        }
        for(var entry:corrected.entrySet())if(!old.containsKey(entry.getKey()))deltas.put(entry.getKey(),cellUnits(entry.getValue()));
        if(deltas.isEmpty())throw new ProductionError(409,"opening_supersession_empty","更正版与当前期初数量一致，无需重复接替。");
        return Map.copyOf(deltas);
    }
    private static Map<Long,JsonNode> indexedCells(JsonNode metadata) {
        if(!metadata.path("source_cells").isArray() || metadata.path("source_cells").isEmpty())throw supersessionConflict();
        var cells=new LinkedHashMap<Long,JsonNode>();long total=0;
        try {
            for(var cell:metadata.path("source_cells")) {
                long sku=Long.parseLong(cell.path("sku_id").asText());if(sku<1 || cell.path("size").asText().isEmpty() || cells.put(sku,cell)!=null)throw supersessionConflict();
                total=Math.addExact(total,cellUnits(cell));
            }
            if(!Long.toString(total).equals(metadata.path("total_units").asText()))throw supersessionConflict();
        } catch(NumberFormatException|ArithmeticException e) { throw supersessionConflict(); }
        return cells;
    }
    private static long cellUnits(JsonNode cell) {
        String units=cell.path("units").asText();if(!units.matches("0|[1-9][0-9]{0,17}"))throw supersessionConflict();
        try{return Long.parseLong(units);}catch(NumberFormatException e){throw supersessionConflict();}
    }
    private static ProductionError supersessionConflict(){return new ProductionError(409,"opening_supersession_conflict","更正版必须保留原已登记规格的稳定商品身份，并明确列出全部原规格；本次未修改库存。");}
    private ProductionError mismatch(){return new ProductionError(409,"opening_source_mismatch","期初必须与已保存来源的日期、尺码数量及仓库表正常可发口径一致，请重新读取预览。");}
    private boolean acceptedRealSource(JsonNode source) {
        if("REAL_SOURCE".equals(source.path("source_kind").asText()))return true;
        return "MANUAL".equals(source.path("source_kind").asText())
            && "manual_table_v1".equals(source.path("source_format").asText())
            && source.path("manual_batch_id").asText().matches("[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
            && source.path("source_manifest_digest").asText().matches("[0-9a-f]{64}")
            && source.path("summary").path("unknown_cells").asInt(-1)==0
            && source.path("unconfirmed_rows").isArray()
            && source.path("unconfirmed_rows").isEmpty();
    }
    private Set<Long> expectedSourceSkus(JsonNode source,JsonNode overrides) {
        var expected=new HashSet<Long>();
        for(String group:List.of("rows","unconfirmed_rows","outside_rows"))for(var row:source.path(group)) {
            String key=row.path("source_key").asText();var rowOverride=overrides.path("rows").path(key);
            String location=rowOverride.has("location")?rowOverride.path("location").asText():row.path("location_group").asText();
            if(!"WAREHOUSE_1".equals(location))continue;
            for(var entry:overrides.path("products").path(key).properties()) {
                var link=entry.getValue();if(!link.path("active").asBoolean())continue;
                String size=entry.getKey();var quantity=row.path("quantities").path(size);
                String units=rowOverride.has(size)?rowOverride.path(size).asText():"LITERAL".equals(quantity.path("state").asText())?quantity.path("units").asText():"";
                if(!units.matches("0|[1-9][0-9]{0,17}"))throw mismatch();
                if(!"0".equals(units) && !expected.add(Long.parseLong(link.path("sku_id").asText())))throw new ProductionError(409,"opening_product_link_invalid","同一商品不能对应库存表中的多个规格，请先重新核对对应。");
            }
        }
        return expected;
    }
    JsonNode validate(long site,JsonNode body) { return validate(site,body,null); }
    JsonNode validate(long site,JsonNode body,JsonNode previous) {
        String reference="REVIEW:"+review+":"+revision;
        if(!enabled() || !review.equals(body.path("review_id").asText()) || !Long.toString(revision).equals(body.path("expected_review_revision").asText()) || !Long.toString(warehouse).equals(body.path("warehouse_id").asText()) || !"1".equals(body.path("owner_id").asText()) || !reference.equals(body.path("source_reference").asText()))throw new ProductionError(403,"opening_scope_forbidden","该期初不在本次批准的来源、修订或仓库范围内。");
        var headers=db.queryForList("SELECT revision,source_digest,source_snapshot_json FROM `"+catalog.schema()+"`.production_inventory_reviews WHERE site_id=? AND review_id=UNHEX(REPLACE(?,'-','')) LOCK IN SHARE MODE",site,review);
        if(headers.isEmpty())throw new ProductionError(404,"inventory_review_not_found","当前站点没有此核对单。");
        var header=headers.getFirst();
        if(Long.parseLong(header.get("revision").toString())!=revision)throw new ProductionError(409,"inventory_review_revision_conflict","库存核对单已变化，请重新读取来源；本次未登记期初。");
        JsonNode source=json.readTree(header.get("source_snapshot_json").toString());
        var revisions=db.queryForList("SELECT effective_overrides_json FROM `"+catalog.schema()+"`.production_inventory_review_revisions WHERE site_id=? AND review_id=UNHEX(REPLACE(?,'-','')) AND revision=?",site,review,revision);
        if(revisions.size()!=1)throw mismatch();
        JsonNode overrides=json.readTree(revisions.getFirst().get("effective_overrides_json").toString());
        String date=overrides.has("stocktaken_on")?overrides.path("stocktaken_on").asText():source.path("stocktaken_on").asText();
        if(!"WAREHOUSE_1".equals(source.path("scope").asText()) || catalog.realCatalog()&&!acceptedRealSource(source) || date.isEmpty() || !date.equals(body.path("cutoff_on").asText()))throw mismatch();
        InventoryService.day(date);
        var lines=body.path("lines");if(!lines.isArray())throw new ProductionError(403,"opening_scope_forbidden","仅能启用本次明确批准的完整商品范围。");
        var expectedSkus=expectedSourceSkus(source,overrides);
        var allowedSkus=catalog.allowedSkus(site);
        var seen=new HashSet<Long>();var cells=new ArrayList<Map<String,Object>>();long total=0;
        for(var line:lines) {
            long sku=InventoryService.positive(line,"sku_id");
            if(!allowedSkus.contains(sku) || !seen.add(sku))throw new ProductionError(403,"opening_scope_forbidden","期初商品不在批准范围内，或同一商品被重复登记。");
            String key=InventoryService.text(line,"source_key",240),size=InventoryService.text(line,"source_size",16);
            JsonNode row=null;int matches=0;
            for(String group:List.of("rows","unconfirmed_rows","outside_rows"))for(var candidate:source.path(group))if(candidate.path("source_key").asText().equals(key)){row=candidate;matches++;}
            if(matches!=1)throw mismatch();
            var rowOverride=overrides.path("rows").path(key);var quantity=row.path("quantities").path(size);
            String location=rowOverride.has("location")?rowOverride.path("location").asText():row.path("location_group").asText();
            String units=rowOverride.has(size)?rowOverride.path(size).asText():"LITERAL".equals(quantity.path("state").asText())?quantity.path("units").asText():"";
            if(!"WAREHOUSE_1".equals(location) || !units.matches("0|[1-9][0-9]{0,17}") || !units.equals(InventoryService.text(line,"units",19)) || line.has("quality")&&!"QUALIFIED".equals(line.path("quality").asText()))throw mismatch();
            var link=overrides.path("products").path(key).path(size);var current=catalog.current(site,body,sku);
            boolean currentVersion=(link.path("catalog_version_id").asText()+":"+link.path("catalog_publication_revision").asText()).equals(current.path("catalog_version").asText());
            boolean previouslyValidated=false;if(previous!=null)for(var old:previous.path("source_cells"))if(Long.toString(sku).equals(old.path("sku_id").asText()) && key.equals(old.path("source_key").asText()) && size.equals(old.path("size").asText()) && quantity.path("cell").asText().equals(old.path("cell").asText()) && units.equals(old.path("units").asText())){previouslyValidated=true;break;}
            if(!link.path("active").asBoolean() || !Long.toString(sku).equals(link.path("sku_id").asText()) || !currentVersion&&!previouslyValidated || !link.path("style_id").asText().equals(current.path("style_id").asText()) || !link.path("standard_color").asText().equals(current.path("standard_color").asText()) || !link.path("standard_size").asText().equals(current.path("standard_size").asText()) || !size.equals(link.path("standard_size").asText()) || !quantity.path("cell").asText().equals(link.path("cell").asText()))throw new ProductionError(409,"opening_product_link_invalid","已保存商品对应不存在、已失效或目录已变化，请先重新核对对应。");
            total=InventoryService.total(total,Long.parseLong(units));
            cells.add(Map.of("source_key",key,"size",size,"cell",link.path("cell").asText(),"sku_id",Long.toString(sku),"units",units,"catalog_version",current.path("catalog_version").asText()));
        }
        if(!seen.equals(expectedSkus))throw new ProductionError(403,"opening_scope_forbidden","仅能启用本次明确批准的完整商品范围。");
        var metadata=new LinkedHashMap<String,Object>();metadata.put("review_id",review);metadata.put("review_revision",Long.toString(revision));metadata.put("source_digest",header.get("source_digest"));metadata.put("source_cells",cells);metadata.put("total_units",Long.toString(total));metadata.put("warehouse_name",warehouseName);metadata.put("owner_state","UNASSIGNED");metadata.put("quality_state","QUALIFIED");metadata.put("quantity_basis",WAREHOUSE_BASIS);metadata.put("owner_tracking","DEFERRED");metadata.put("cutoff_precision","DATE");metadata.put("precise_cutoff",null);metadata.put("cutoff_note",overrides.path("cutoff_note").asText());
        return json.valueToTree(metadata);
    }
}
