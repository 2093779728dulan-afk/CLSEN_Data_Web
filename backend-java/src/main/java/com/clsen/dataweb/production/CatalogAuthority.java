package com.clsen.dataweb.production;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Read-only product authority on the same MySQL transaction as stock and dispatch. */
final class CatalogAuthority {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final String schema;
    private final Set<Long> allowed = new HashSet<>();
    private final boolean enabled;
    private final boolean approvedCatalogScope;

    CatalogAuthority(JdbcTemplate db, ObjectMapper json, String mode, String schema, String skuScope) {
        this.db=db; this.json=json; this.schema=schema;
        enabled=mode.equals("catalog_transactional");
        approvedCatalogScope=enabled && skuScope.equals("approved_catalog");
        if (!enabled) return;
        // These explicitly paired local stores prevent QA/real naked-ID reuse.
        String database = db.queryForObject("SELECT DATABASE()",String.class);
        boolean production = "clsen_production".equals(database);
        String expected = Map.of(
            "clsen_production", "clsen_data",
            "clsen_orders_qa_sku_20261015", "clsen_data_test_production_catalog_20261015",
            "clsen_orders_manual_qa_20261016", "clsen_data_test_manual_tables_20261016",
            "clsen_orders_guangzhou_trial_20261015", "clsen_control_guangzhou_trial_20261015",
            "clsen_orders_production_backup_b_v1_1_0_20261017", "clsen_control_production_backup_b_v1_1_0_20261017",
            "clsen_stock_test_real_20261110", "clsen_data_test_real_20261110"
        ).get(database);
        if (database != null && database.matches("clsen_production_test_[a-z0-9_]{1,32}"))
            expected = "clsen_data_test_" + database.substring("clsen_production_test_".length());
        if (expected==null || !expected.equals(schema))
            throw new IllegalArgumentException("Catalog schema must match its explicitly paired local stock database");
        if (approvedCatalogScope) {
            if (realCatalog() && !production) throw new IllegalArgumentException("Approved-catalog scope is limited to paired production or isolated QA stores");
            return;
        }
        for (String value:skuScope.split(",",-1)) {
            if (!value.matches("[1-9][0-9]{0,18}")) throw new IllegalArgumentException("An explicit stable SKU scope is required");
            try { allowed.add(Long.parseLong(value)); }
            catch (NumberFormatException error) { throw new IllegalArgumentException("Stable SKU scope exceeds supported IDs"); }
        }
    }
    boolean enabled() { return enabled; }
    String schema() { return schema; }
    Set<Long> allowedSkus(long site) {
        if (!approvedCatalogScope) return Set.copyOf(allowed);
        var result = new HashSet<Long>();
        for (var row : db.queryForList(activeMembersSql(), site))
            result.add(Long.parseLong(row.get("sku_id").toString()));
        return result;
    }
    boolean permits(long site, long sku) {
        if (!approvedCatalogScope) return allowed.contains(sku);
        return !db.queryForList(activeMembersSql()+" AND m.sku_id=?", site, sku).isEmpty();
    }
    private String activeMembersSql() {
        return """
            SELECT m.sku_id
            FROM `%s`.product_catalog_publications p
            JOIN `%s`.product_catalog_sku_members m
              ON m.site_id=p.site_id AND m.catalog_version_id=p.current_catalog_version_id
            JOIN `%s`.product_sku_revisions r
              ON r.site_id=m.site_id AND r.id=m.sku_revision_id AND r.sku_id=m.sku_id
            JOIN `%s`.product_catalog_style_members sm
              ON sm.site_id=m.site_id AND sm.catalog_version_id=m.catalog_version_id AND sm.style_id=r.style_id
            JOIN `%s`.product_style_revisions sr
              ON sr.site_id=sm.site_id AND sr.id=sm.style_revision_id AND sr.style_id=sm.style_id
            WHERE p.site_id=? AND r.status='enabled' AND sr.status='enabled'
            """.formatted(schema,schema,schema,schema,schema);
    }
    boolean realCatalog() { return enabled && Set.of(
        "clsen_data",
        "clsen_control_guangzhou_trial_20261015",
        "clsen_control_production_backup_b_v1_1_0_20261017",
        "clsen_data_test_real_20261110"
    ).contains(schema); }

    JsonNode current(long site, JsonNode body, long sku) {
        if (!enabled || !approvedCatalogScope && !allowed.contains(sku))
            throw new ProductionError(403,"sku_scope_forbidden","该商品不在本次启用范围内，请保留待核。");
        return currentForDisplay(site,body,sku);
    }

    /** Display selection validates catalog membership independently of stock-write scope. */
    JsonNode currentForDisplay(long site, JsonNode body, long sku) {
        if (!enabled) throw new ProductionError(403,"sku_scope_forbidden","当前商品目录身份尚未启用。");
        // Catalog approval locks this same pointer before publishing a new version.
        // The shared lock stays held until the stock/shipment transaction commits.
        var pointers=db.queryForList("SELECT current_catalog_version_id,catalog_publication_revision FROM `"+schema+"`.product_catalog_publications WHERE site_id=? LOCK IN SHARE MODE",site);
        if (pointers.isEmpty() || pointers.getFirst().get("current_catalog_version_id")==null)
            throw new ProductionError(409,"catalog_unavailable","当前站点尚无可确认的已批准商品目录。");
        var pointer=pointers.getFirst();
        long version=Long.parseLong(pointer.get("current_catalog_version_id").toString());
        String identityVersion=version+":"+pointer.get("catalog_publication_revision");
        var supplied=body.path("_catalog").path(Long.toString(sku));
        if (!supplied.path("catalog_version").asText().equals(identityVersion))
            throw new ProductionError(409,"catalog_revision_conflict","商品目录已变化，请重新读取商品并预览；本次未保存。");
        var members=db.queryForList("""
            SELECT r.sku_id,r.style_id,r.internal_display_sku,r.code_status,
                   r.standard_color,r.standard_size,r.status AS sku_status,
                   sr.style_code,sr.status AS style_status
            FROM `%s`.product_catalog_sku_members m
            JOIN `%s`.product_sku_revisions r
              ON r.id=m.sku_revision_id AND r.site_id=m.site_id AND r.sku_id=m.sku_id
            JOIN `%s`.product_catalog_style_members sm
              ON sm.catalog_version_id=m.catalog_version_id AND sm.site_id=m.site_id
             AND sm.style_id=r.style_id
            JOIN `%s`.product_style_revisions sr
              ON sr.id=sm.style_revision_id AND sr.site_id=sm.site_id
             AND sr.style_id=sm.style_id
            WHERE m.site_id=? AND m.catalog_version_id=? AND m.sku_id=?
            """.formatted(schema,schema,schema,schema),site,version,sku);
        if (members.size()!=1 || !"enabled".equals(members.getFirst().get("sku_status")) || !"enabled".equals(members.getFirst().get("style_status")))
            throw new ProductionError(409,"sku_identity_unavailable","商品不存在、已停用或不属于当前站点，不能确认库存或发货。");
        var row=members.getFirst();
        var result=new LinkedHashMap<String,Object>();
        result.put("sku_id",Long.toString(sku)); result.put("style_id",row.get("style_id").toString());
        result.put("standard_color",row.get("standard_color")); result.put("standard_size",row.get("standard_size"));
        result.put("code",row.get("internal_display_sku")); result.put("code_status",row.get("code_status"));
        result.put("label",row.get("style_code")+" · "+Objects.toString(row.get("internal_display_sku"),"正式SKU待补")+" · "+row.get("standard_color")+" / "+row.get("standard_size"));
        result.put("status","active"); result.put("catalog_version",identityVersion); result.put("contract_version","2");
        return json.valueToTree(result);
    }
}
