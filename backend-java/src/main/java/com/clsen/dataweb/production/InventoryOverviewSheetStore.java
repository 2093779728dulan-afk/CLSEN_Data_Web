package com.clsen.dataweb.production;

import java.time.LocalDate;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

/** Read facts under InventoryService's repeatable-read transaction. No commands. */
final class InventoryOverviewSheetStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final InventoryService inventory;

    InventoryOverviewSheetStore(JdbcTemplate db, ObjectMapper json, InventoryService inventory) {
        this.db = db;
        this.json = json;
        this.inventory = inventory;
    }

    private List<Map<String,Object>> rows(String sql, Object... args) {
        return db.queryForList(sql, args).stream().map(DestinationReceiptStore::normalized).toList();
    }

    Object options(ProductionContext c) {
        return Map.of("domestic", rows("SELECT s.warehouse_id,s.owner_id,w.name warehouse_name,w.type,w.status,s.owner_name,s.cutoff_on FROM inventory_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND w.type IN ('OWN','FACTORY','THIRD_PARTY') AND w.status='ACTIVE' ORDER BY s.warehouse_id,s.owner_id", c.site()),
                "fba", rows("SELECT s.id,s.warehouse_id,s.owner_id,w.name warehouse_name,s.store_evidence,s.report_source_scope_id,s.marketplace,s.cutoff_on,s.revision FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND w.status='ACTIVE' AND s.marketplace='US' ORDER BY s.id", c.site()));
    }

    Object read(ProductionContext c, Map<String,String> q) {
        long warehouse = positive(q, "domestic_warehouse_id"), owner = positive(q, "domestic_owner_id"), scopeId = positive(q, "fba_scope_id");
        LocalDate asOf = InventoryService.day(q.getOrDefault("as_of", ""));
        var domestic = rows("SELECT s.*,w.type,w.status FROM inventory_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND s.warehouse_id=? AND s.owner_id=? AND w.type IN ('OWN','FACTORY','THIRD_PARTY') AND w.status='ACTIVE'", c.site(), warehouse, owner);
        if (domestic.isEmpty()) throw new ProductionError(409, "sheet_scope_unavailable", "所选成品仓/货主尚未建账或已停用，请重新选择。");
        var fba = rows("SELECT s.*,w.status FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND s.id=? AND w.status='ACTIVE' AND s.marketplace='US'", c.site(), scopeId);
        if (fba.isEmpty()) throw new ProductionError(409, "sheet_scope_unavailable", "所选美国FBA范围不存在或已停用。");
        var scope = fba.getFirst();
        var orders = rows("SELECT o.*,f.name factory_name FROM production_order o LEFT JOIN production_factory f ON f.site_id=o.site_id AND f.id=o.factory_id WHERE o.site_id=? AND o.status='CONFIRMED' AND o.business_date<=? AND ((o.receipt_warehouse_id=? AND o.receipt_owner_id=?) OR o.receipt_warehouse_id IS NULL OR o.receipt_owner_id IS NULL) ORDER BY o.id", c.site(), asOf, warehouse, owner);
        var ids = orders.stream().map(order -> order.get("id")).toList();
        var lines = ProductionService.orderLinesFor(db, c.site(), ids);
        var decisions = rows("SELECT document_id,operation_kind,id FROM production_revision WHERE site_id=? AND document_kind='orders' AND operation_kind IN ('COMPLETE_PRODUCTION','REOPEN_PRODUCTION') ORDER BY id DESC", c.site());
        for (var order : orders) {
            order.put("lines", lines.stream().filter(line -> Objects.equals(line.get("order_id"), order.get("id"))).toList());
            ProductionService.productionCompletion(order, decisions);
        }
        var result = new LinkedHashMap<String,Object>();
        result.put("resolved_scope", Map.of("domestic", domestic.getFirst(), "fba", scope));
        result.put("report_scope_count", db.queryForObject("SELECT COUNT(*) FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND s.report_source_scope_id=? AND w.status='ACTIVE'", Long.class, c.site(), scope.get("report_source_scope_id")));
        result.put("orders", orders);
        result.put("order_shipments", rows("SELECT a.order_line_id,a.units,s.business_date FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id WHERE a.site_id=? AND a.is_active=TRUE AND x.is_active=TRUE AND s.status='CONFIRMED' AND x.fulfillment_mode='PRODUCTION_DIRECT' ORDER BY a.id", c.site()));
        result.put("production_revisions", rows("SELECT document_id,revision,operation_kind,effective_date,before_value,after_value FROM production_revision WHERE site_id=? AND document_kind='orders' ORDER BY id", c.site()));
        result.put("domestic_stock", inventory.read(c, "availability", Map.of("warehouse_id", Long.toString(warehouse), "owner_id", Long.toString(owner))));
        result.put("fba_state", inventory.read(c, "fba-state", Map.of("warehouse_id", scope.get("warehouse_id").toString())));
        result.put("events", rows("SELECT id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,reason,business_date FROM inventory_event WHERE site_id=? AND ((warehouse_id=? AND owner_id=?) OR (warehouse_id=? AND owner_id=?)) ORDER BY id", c.site(), warehouse, owner, scope.get("warehouse_id"), scope.get("owner_id")));
        // Current source dates replace the dates attached to correction deltas.
        result.put("stock_sources", rows("SELECT id,warehouse_id,owner_id,status,revision,business_date,kind,line_items FROM inventory_document WHERE site_id=? AND ((warehouse_id=? AND owner_id=?) OR (warehouse_id=? AND owner_id=?)) ORDER BY id", c.site(), warehouse, owner, scope.get("warehouse_id"), scope.get("owner_id")));
        result.put("shipment_sources", rows("SELECT id,status,revision,business_date,warehouse_id,owner_id,destination_id FROM production_shipment WHERE site_id=? AND ((warehouse_id=? AND owner_id=?) OR (destination_id=? AND owner_id=?)) ORDER BY id", c.site(), warehouse, owner, scope.get("warehouse_id"), scope.get("owner_id")));
        result.put("identity_changes", rows("SELECT document_id,operation_kind,after_value FROM production_revision WHERE site_id=? AND document_kind='identity' ORDER BY id", c.site()));
        result.put("occupancy_history", rows("SELECT document_kind,document_id,after_value FROM production_revision WHERE site_id=? AND document_kind IN ('reservation','hold') ORDER BY id", c.site()));
        result.put("transit", new WarehouseTransitStore(db, json, inventory).sheetSources(c, scope, asOf));
        result.put("settings", new InventoryDisplaySettings(db, json, inventory).read(c));
        result.put("as_of", asOf.toString());
        return result;
    }

    private long positive(Map<String,String> query, String field) {
        return ProductionService.positive(json.getNodeFactory().textNode(query.getOrDefault(field, "")), field);
    }
}
