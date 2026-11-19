package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class RealOpeningSourceTest {
    JsonNode expansion(String units,String cell,String sku) {
        return new ObjectMapper().valueToTree(Map.of("review_id","same-review","source_digest","same-digest","quantity_basis","NORMAL_DISPATCHABLE_V1","source_cells",List.of(Map.of("sku_id",sku,"source_key","sheet!2","size","M","cell",cell,"units",units))));
    }
    @Test void extendsOnlyNewSpecificationsAndPreservesExistingSourceCells() {
        var previous=expansion("9","E2","24");
        var current=(tools.jackson.databind.node.ObjectNode)previous.deepCopy();
        ((tools.jackson.databind.node.ArrayNode)current.path("source_cells")).add(expansion("5","F2","25").path("source_cells").get(0));
        assertEquals(Set.of(25L),RealOpeningSource.additionalSkuIds(previous,current));
        assertEquals("opening_extension_empty",assertThrows(ProductionError.class,()->RealOpeningSource.additionalSkuIds(previous,previous)).code);
        assertEquals("opening_extension_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.additionalSkuIds(previous,expansion("10","E2","24"))).code);
        assertEquals("opening_extension_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.additionalSkuIds(previous,expansion("9","F2","24"))).code);
        assertEquals("opening_extension_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.additionalSkuIds(previous,expansion("9","E2","25"))).code);
        var other=(tools.jackson.databind.node.ObjectNode)current.deepCopy();other.put("source_digest","other-source");
        assertEquals("opening_extension_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.additionalSkuIds(previous,other)).code);
    }
    @Test void correctedSourceMayChangeExistingQuantitiesAndAddSkusButCannotDropOldSkus() {
        var previous=json.valueToTree(Map.of(
            "review_id","old-review","review_revision","8","source_digest","old-digest","quantity_basis","NORMAL_DISPATCHABLE_V1","total_units","19",
            "source_cells",List.of(
                Map.of("sku_id","24","source_key","old!2","size","M","cell","E2","units","9"),
                Map.of("sku_id","25","source_key","old!3","size","L","cell","F3","units","10")
            )));
        var corrected=json.valueToTree(Map.of(
            "review_id","new-review","review_revision","1","source_digest","new-digest","quantity_basis","NORMAL_DISPATCHABLE_V1","total_units","26",
            "source_cells",List.of(
                Map.of("sku_id","24","source_key","new!4","size","M","cell","E4","units","11"),
                Map.of("sku_id","25","source_key","new!5","size","L","cell","F5","units","10"),
                Map.of("sku_id","26","source_key","new!6","size","S","cell","D6","units","5")
            )));
        assertEquals(Map.of(24L,2L,26L,5L),RealOpeningSource.supersedingDeltas(previous,corrected));
        var missing=(tools.jackson.databind.node.ObjectNode)corrected.deepCopy();((tools.jackson.databind.node.ArrayNode)missing.path("source_cells")).remove(1);missing.put("total_units","16");
        assertEquals("opening_supersession_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.supersedingDeltas(previous,missing)).code);
        var wrongSize=(tools.jackson.databind.node.ObjectNode)corrected.deepCopy();((tools.jackson.databind.node.ObjectNode)wrongSize.path("source_cells").get(0)).put("size","XL");
        assertEquals("opening_supersession_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.supersedingDeltas(previous,wrongSize)).code);
        var sameReview=(tools.jackson.databind.node.ObjectNode)corrected.deepCopy();sameReview.put("review_id","old-review");
        assertEquals("opening_supersession_conflict",assertThrows(ProductionError.class,()->RealOpeningSource.supersedingDeltas(previous,sameReview)).code);
    }
    final ObjectMapper json=new ObjectMapper();
    final String review="7fa34135-5e2a-4dbc-94fa-c08427b13966";
    final JdbcTemplate db=mock(JdbcTemplate.class);
    final CatalogAuthority catalog=mock(CatalogAuthority.class);
    Map<String,Object> link=new HashMap<>(Map.of("active",true,"sku_id","24","style_id","23","standard_size","M","standard_color","Olive","cell","E2","catalog_version_id","48","catalog_publication_revision","48"));
    Map<String,Object> snapshot=new HashMap<>(Map.of("source_kind","FICTIONAL","scope","WAREHOUSE_1","stocktaken_on","2026-10-14","rows",List.of(Map.of("source_key","测试表!2","location_group","WAREHOUSE_1","quantities",Map.of("M",Map.of("state","LITERAL","units","9","cell","E2"))))));
    RealOpeningSource source() {
        when(catalog.enabled()).thenReturn(true);when(catalog.schema()).thenReturn("clsen_data_test_production_catalog_20261015");when(catalog.allowedSkus(1L)).thenReturn(Set.of(24L));
        when(catalog.current(eq(1L),any(),eq(24L))).thenReturn(json.valueToTree(Map.of("sku_id","24","style_id","23","standard_size","M","standard_color","Olive","catalog_version","48:48")));
        when(db.queryForList(contains("production_inventory_reviews"),eq(1L),eq(review))).thenReturn(List.of(Map.of("revision",3,"source_digest","test-digest","source_snapshot_json",json.writeValueAsString(snapshot))));
        when(db.queryForList(contains("production_inventory_review_revisions"),eq(1L),eq(review),eq(3L))).thenReturn(List.of(Map.of("effective_overrides_json",json.writeValueAsString(Map.of("products",Map.of("测试表!2",Map.of("M",link)))))));
        return new RealOpeningSource(db,json,catalog,review,3,3164016,"虚构来源核对仓");
    }
    JsonNode body() { return json.valueToTree(Map.of("review_id",review,"expected_review_revision","3","warehouse_id","3164016","owner_id","1","source_reference","REVIEW:"+review+":3","cutoff_on","2026-10-14","lines",List.of(Map.of("sku_id","24","source_key","测试表!2","source_size","M","quality","QUALIFIED","units","9")))); }
    @Test void usesLockedSavedSourceAndKeepsDeferredFactsUnknown() {
        var result=source().validate(1,body());
        assertEquals("UNASSIGNED",result.path("owner_state").asText());assertEquals("QUALIFIED",result.path("quality_state").asText());
        assertEquals("NORMAL_DISPATCHABLE_V1",result.path("quantity_basis").asText());assertEquals("DEFERRED",result.path("owner_tracking").asText());
        assertEquals("DATE",result.path("cutoff_precision").asText());assertTrue(result.path("precise_cutoff").isNull());
        assertEquals("9",result.path("source_cells").get(0).path("units").asText());
        verify(db).queryForList(contains("LOCK IN SHARE MODE"),eq(1L),eq(review));
    }
    @Test void warehouseConventionDoesNotRequirePerSkuQualityInput() {
        var s=source();var b=body();((tools.jackson.databind.node.ObjectNode)b.path("lines").get(0)).remove("quality");
        assertEquals("QUALIFIED",s.validate(1,b).path("quality_state").asText());
    }
    @Test void rejectsChangedQuantityAndContradictoryConvention() {
        var s=source();var b=body();((tools.jackson.databind.node.ObjectNode)b.path("lines").get(0)).put("units","10");
        assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->s.validate(1,b)).code);
        var q=body();((tools.jackson.databind.node.ObjectNode)q.path("lines").get(0)).put("quality","PENDING");
        assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->s.validate(1,q)).code);
    }
    @Test void rejectsOtherReviewAndStaleRevision() {
        var s=source();var b=(tools.jackson.databind.node.ObjectNode)body();b.put("review_id",UUID.randomUUID().toString());
        assertEquals("opening_scope_forbidden",assertThrows(ProductionError.class,()->s.validate(1,b)).code);
        when(db.queryForList(contains("production_inventory_reviews"),eq(1L),eq(review))).thenReturn(List.of(Map.of("revision",4)));
        assertEquals("inventory_review_revision_conflict",assertThrows(ProductionError.class,()->s.validate(1,body())).code);
    }
    @Test void refusesInactiveOrStaleSavedCorrespondence() {
        link.put("active",false);var first=source();assertEquals("opening_product_link_invalid",assertThrows(ProductionError.class,()->first.validate(1,body())).code);
        link.put("active",true);link.put("catalog_version_id","47");var current=source();
        assertEquals("opening_product_link_invalid",assertThrows(ProductionError.class,()->current.validate(1,body())).code);
    }
    @Test void extensionReusesAnUnchangedPreviouslyValidatedCellAcrossCatalogVersions() {
        link.put("catalog_version_id","47");var s=source();
        var previous=json.valueToTree(Map.of("source_cells",List.of(Map.of("sku_id","24","source_key","测试表!2","size","M","cell","E2","units","9"))));
        assertEquals("48:48",s.validate(1,body(),previous).path("source_cells").get(0).path("catalog_version").asText());
    }
    @Test void doesNotAcceptAClientSkuOutsideTheExplicitBatch() {
        var s=source();var b=body();((tools.jackson.databind.node.ObjectNode)b.path("lines").get(0)).put("sku_id","14");
        assertEquals("opening_scope_forbidden",assertThrows(ProductionError.class,()->s.validate(1,b)).code);
    }
    @Test void catalogSkusAbsentFromTheSavedInventorySourceDoNotBlockTheCompleteSourceRange() {
        var s=source();when(catalog.allowedSkus(1L)).thenReturn(Set.of(24L,25L));
        assertEquals("9",s.validate(1,body()).path("total_units").asText());
    }
    @Test void missingDateOrQuantityCannotBecomeZero() {
        snapshot.remove("stocktaken_on");var s=source();assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->s.validate(1,body())).code);
    }
    @Test void realCatalogRejectsFictionalEvidenceAndDisabledConfigStaysClosed() {
        var s=source();when(catalog.realCatalog()).thenReturn(true);
        assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->s.validate(1,body())).code);
        assertFalse(new RealOpeningSource(db,json,catalog,"",0,0,"").enabled());
    }
    @Test void realCatalogAcceptsOnlyACompleteReviewedManualInventorySnapshot() {
        snapshot.put("source_kind","MANUAL");snapshot.put("source_format","manual_table_v1");
        snapshot.put("manual_batch_id","2063ba76-bd44-4a03-bc44-5c439519f284");snapshot.put("source_manifest_digest","a".repeat(64));
        snapshot.put("summary",Map.of("unknown_cells",0));snapshot.put("unconfirmed_rows",List.of());
        var s=source();when(catalog.realCatalog()).thenReturn(true);
        assertEquals("9",s.validate(1,body()).path("total_units").asText());
        snapshot.remove("manual_batch_id");
        var missingBatch=source();
        assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->missingBatch.validate(1,body())).code);
        snapshot.put("manual_batch_id","2063ba76-bd44-4a03-bc44-5c439519f284");snapshot.put("summary",Map.of("unknown_cells",1));
        var unresolvedQuantity=source();
        assertEquals("opening_source_mismatch",assertThrows(ProductionError.class,()->unresolvedQuantity.validate(1,body())).code);
    }
}
