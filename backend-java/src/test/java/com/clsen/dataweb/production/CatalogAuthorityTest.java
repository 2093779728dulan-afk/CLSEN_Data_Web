package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

class CatalogAuthorityTest {
    final ObjectMapper json = new ObjectMapper();
    JdbcTemplate database() {
        var db = mock(JdbcTemplate.class);
        when(db.queryForObject("SELECT DATABASE()", String.class)).thenReturn("clsen_orders_qa_sku_20261015");
        when(db.queryForList(contains("product_catalog_publications"), eq(1L))).thenReturn(List.of(Map.of("current_catalog_version_id",48L,"catalog_publication_revision",48L)));
        when(db.queryForList(contains("product_catalog_sku_members"), eq(1L), eq(48L), eq(24L))).thenReturn(List.of(new HashMap<>(Map.of("sku_id",24L,"style_id",23L,"style_code","QA-ENTRY-3305a0","internal_display_sku","QA-ENTRY-3305a0-NEW","standard_color","Olive","standard_size","M","sku_status","enabled","style_status","enabled","code_status","confirmed"))));
        return db;
    }
    tools.jackson.databind.JsonNode body(String version) {
        return json.valueToTree(Map.of("_catalog",Map.of("24",Map.of("sku_id","24","contract_version","2","status","active","catalog_version",version,"label","forged label"))));
    }
    CatalogAuthority authority(JdbcTemplate db) { return new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","24"); }

    @Test void manualExperienceUsesItsOwnExplicitPair() {
        var db=database();
        when(db.queryForObject("SELECT DATABASE()",String.class)).thenReturn("clsen_orders_manual_qa_20261016");
        var isolated=new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_manual_tables_20261016","1,2,3");
        assertTrue(isolated.enabled()); assertFalse(isolated.realCatalog());
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_control_guangzhou_trial_20261015","1,2,3"));
    }

    @Test void productionBackupUsesOnlyItsDedicatedOrdersClone() {
        var db=database();
        when(db.queryForObject("SELECT DATABASE()",String.class)).thenReturn("clsen_orders_production_backup_b_v1_1_0_20261017");
        var authority=new CatalogAuthority(db,json,"catalog_transactional","clsen_control_production_backup_b_v1_1_0_20261017","1,2,3");
        assertTrue(authority.enabled()); assertTrue(authority.realCatalog());
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_control_guangzhou_trial_20261015","1,2,3"));
    }

    @Test void locksTheCurrentPublicationAndReturnsAuthoritativeIdentity() {
        var db=database(); var result=authority(db).current(1,body("48:48"),24);
        assertEquals("24",result.path("sku_id").asText());
        assertEquals("Olive",result.path("standard_color").asText());
        assertEquals("48:48",result.path("catalog_version").asText());
        assertFalse(result.path("label").asText().contains("forged"));
        verify(db).queryForList(contains("LOCK IN SHARE MODE"),eq(1L));
    }
    @Test void displaySelectionAcceptsApprovedNewSkusWhileStockWritesKeepTheirScope() {
        var db=database();
        var authority=new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","1");
        assertEquals("sku_scope_forbidden",assertThrows(ProductionError.class,()->authority.current(1,body("48:48"),24)).code);
        assertEquals("24",authority.currentForDisplay(1,body("48:48"),24).path("sku_id").asText());
        assertEquals("catalog_revision_conflict",assertThrows(ProductionError.class,()->authority.currentForDisplay(1,body("48:47"),24)).code);
        assertEquals("catalog_unavailable",assertThrows(ProductionError.class,()->authority.currentForDisplay(2,body("48:48"),24)).code);
    }
    @Test void rejectsStalePublicationBeforeReadingItsMembers() {
        var db=database();
        assertEquals("catalog_revision_conflict",assertThrows(ProductionError.class,()->authority(db).current(1,body("48:47"),24)).code);
        verify(db,never()).queryForList(contains("product_catalog_sku_members"),any(),any(),any());
    }
    @Test void missingSiteAndDisallowedSkuDoNotFallBackToThePayload() {
        var db=database();
        assertEquals("catalog_unavailable",assertThrows(ProductionError.class,()->authority(db).current(2,body("48:48"),24)).code);
        assertEquals("sku_scope_forbidden",assertThrows(ProductionError.class,()->authority(db).current(1,body("48:48"),25)).code);
    }
    @Test void disabledOrMissingSkuCannotConfirm() {
        var db=database();
        when(db.queryForList(contains("product_catalog_sku_members"),eq(1L),eq(48L),eq(24L))).thenReturn(List.of(Map.of("sku_id",24L,"sku_status","disabled","style_status","enabled")));
        assertEquals("sku_identity_unavailable",assertThrows(ProductionError.class,()->authority(db).current(1,body("48:48"),24)).code);
        when(db.queryForList(contains("product_catalog_sku_members"),eq(1L),eq(48L),eq(24L))).thenReturn(List.of());
        assertEquals("sku_identity_unavailable",assertThrows(ProductionError.class,()->authority(db).current(1,body("48:48"),24)).code);
    }
    @Test void rejectsWrongDatabasePairAndEmptyOrMalformedScope() {
        var db=database();
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","other_schema","24"));
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015",""));
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","24,not-an-id"));
    }
    @Test void productionAndDisposableStoresRequireMatchingCatalogs() {
        var db=database();
        when(db.queryForObject("SELECT DATABASE()",String.class)).thenReturn("clsen_production");
        var live=new CatalogAuthority(db,json,"catalog_transactional","clsen_data","approved_catalog");
        assertTrue(live.enabled());assertTrue(live.realCatalog());
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","approved_catalog"));
        when(db.queryForObject("SELECT DATABASE()",String.class)).thenReturn("clsen_production_test_release_123");
        assertTrue(new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_release_123","approved_catalog").enabled());
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_release_other","approved_catalog"));
    }
    @Test void disabledModeDoesNotReadAnyCatalogOrDatabase() {
        var db=mock(JdbcTemplate.class);
        assertFalse(new CatalogAuthority(db,json,"disabled","","").enabled());
        verifyNoInteractions(db);
    }
    org.springframework.mock.web.MockHttpServletRequest request(String method,String path) {
        var request=new org.springframework.mock.web.MockHttpServletRequest(method,"/internal/production/"+path);
        request.addHeader("Authorization","Bearer "+"t".repeat(48));request.addHeader("X-Production-Site","1");
        request.addHeader("X-Production-Actor","1");request.addHeader("X-Production-Roles","admin");return request;
    }
    @Test void readOnlyRejectsAllMutationMethodsBeforeControllers() throws Exception {
        for(String method:List.of("POST","PUT","DELETE","PATCH"))for(String path:List.of("inventory/openings/confirm","orders","shipments","files/orders/preview","files/previews/example/confirm")) {
            var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),false).doFilter(request(method,path),response,chain);
            assertEquals(403,response.getStatus());assertTrue(response.getContentAsString().contains("production_read_only"));
            assertTrue(response.getContentAsString().contains("当前环境仅开放查询"));verifyNoInteractions(chain);
        }
    }
    @Test void readOnlyAllowsQueriesAndWritableModeKeepsExistingCommands() throws Exception {
        for(String method:List.of("GET","HEAD","POST")) {
            var request=request(method,"orders");var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),method.equals("POST")).doFilter(request,response,chain);
            verify(chain).doFilter(request,response);
        }
    }
    @Test void openingOnlyModeDoesNotOpenOtherBusinessWrites() throws Exception {
        for(String path:List.of("inventory/openings/preview","inventory/openings/confirm","inventory/documents","orders","shipments","files/orders/preview")) {
            var request=request("POST",path);var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),false,true).doFilter(request,response,chain);
            if(path.startsWith("inventory/openings/"))verify(chain).doFilter(request,response);
            else {assertEquals(403,response.getStatus());verifyNoInteractions(chain);}
        }
    }
    @Test void inventoryOnlyModeAllowsDailyStockAndKeepsOtherWritesClosed() throws Exception {
        for(String path:List.of("inventory/documents","inventory/documents/1/preview","inventory/documents/1/confirm","inventory/holds","inventory/holds/1/release","inventory/reservations","inventory/loans/1/settle","inventory/plans","inventory/plans/1/cancel","inventory/openings/preview","inventory/openings/confirm","orders","shipments","files/orders/preview","inventory/unknown","inventory/documents-extra")) {
            var request=request("POST",path);var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),false,false,true).doFilter(request,response,chain);
            if(path.startsWith("inventory/") && Set.of("documents","holds","reservations","loans","plans").contains(path.split("/")[1]))verify(chain).doFilter(request,response);
            else {assertEquals(403,response.getStatus());verifyNoInteractions(chain);}
        }
    }
    @Test void dailyModeAllowsOnlyTheTwoPostSourceChecks() throws Exception {
        for(boolean enabled:List.of(false,true))for(String method:List.of("POST","PUT","DELETE"))for(String path:List.of("sources/orders/check","sources/shipments/check","sources/orders/check/extra","sources/inventory/check")) {
            var request=request(method,path);var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),false,false,true,enabled).doFilter(request,response,chain);
            boolean allowed=enabled&&method.equals("POST")&&Set.of("sources/orders/check","sources/shipments/check").contains(path);
            if(allowed)verify(chain).doFilter(request,response);
            else {assertEquals(403,response.getStatus());verifyNoInteractions(chain);}
        }
    }
    @Test void orderShipmentAndInventoryModeKeepsOpeningAndUnrelatedWritesClosed() throws Exception {
        for(String method:List.of("POST","PUT","DELETE"))for(String path:List.of("orders","orders/1/confirm","shipments","shipments/1/confirm","inventory/openings/preview","inventory/documents","files/orders/preview")) {
            var request=request(method,path);var response=new org.springframework.mock.web.MockHttpServletResponse();var chain=mock(jakarta.servlet.FilterChain.class);
            new InternalIdentityFilter("t".repeat(48),false,false,true,true).doFilter(request,response,chain);
            if(path.equals("orders")||path.startsWith("orders/")||path.equals("shipments")||path.startsWith("shipments/")||(method.equals("POST")&&path.equals("inventory/documents")))verify(chain).doFilter(request,response);
            else {assertEquals(403,response.getStatus());assertTrue(response.getContentAsString().contains("库存期初仍未启用"));verifyNoInteractions(chain);}
        }
    }
    @Test void approvedCatalogScopeSeesNewPublicationsWithoutRecreatingAuthority() {
        var db=database();
        var authority=new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","approved_catalog");
        var row=new HashMap<String,Object>(Map.of("sku_id",25L,"style_id",23L,"style_code","QA-NEW","internal_display_sku","QA-NEW-Blue-M","standard_color","Blue","standard_size","M","sku_status","enabled","style_status","enabled","code_status","confirmed"));
        when(db.queryForList(contains("product_catalog_sku_members"),eq(1L),eq(49L),eq(25L))).thenReturn(List.of(row));
        assertEquals("sku_identity_unavailable",assertThrows(ProductionError.class,()->authority.current(1,json.valueToTree(Map.of("_catalog",Map.of("25",Map.of("catalog_version","48:48")))),25)).code);
        when(db.queryForList(contains("product_catalog_publications"),eq(1L))).thenReturn(List.of(Map.of("current_catalog_version_id",49L,"catalog_publication_revision",49L)));
        var newBody=json.valueToTree(Map.of("_catalog",Map.of("25",Map.of("catalog_version","49:49"))));
        assertEquals("25",authority.current(1,newBody,25).path("sku_id").asText());
        assertEquals("catalog_revision_conflict",assertThrows(ProductionError.class,()->authority.current(1,body("48:48"),25)).code);
        assertEquals("catalog_unavailable",assertThrows(ProductionError.class,()->authority.current(2,newBody,25)).code);
        row.put("sku_status","disabled");
        assertEquals("sku_identity_unavailable",assertThrows(ProductionError.class,()->authority.current(1,newBody,25)).code);
    }
    @Test void approvedCatalogScopeRefreshesReadMembershipAndKeepsSiteIsolation() {
        var db=database();
        var authority=new CatalogAuthority(db,json,"catalog_transactional","clsen_data_test_production_catalog_20261015","approved_catalog");
        when(db.queryForList(contains("r.status='enabled'"),eq(1L))).thenReturn(List.of(Map.of("sku_id",24L)),List.of(Map.of("sku_id",24L),Map.of("sku_id",25L)));
        when(db.queryForList(contains("AND m.sku_id=?"),eq(1L),eq(25L))).thenReturn(List.of(Map.of("sku_id",25L)),List.of());
        assertEquals(Set.of(24L),authority.allowedSkus(1));
        assertEquals(Set.of(24L,25L),authority.allowedSkus(1));
        assertTrue(authority.permits(1,25));
        assertFalse(authority.permits(1,25));
        assertTrue(authority.allowedSkus(2).isEmpty());
        assertFalse(authority.permits(2,25));
    }
    @Test void approvedCatalogScopeCannotEnableARealCatalog() {
        var db=database();
        when(db.queryForObject("SELECT DATABASE()",String.class)).thenReturn("clsen_orders_guangzhou_trial_20261015");
        assertThrows(IllegalArgumentException.class,()->new CatalogAuthority(db,json,"catalog_transactional","clsen_control_guangzhou_trial_20261015","approved_catalog"));
    }

}
