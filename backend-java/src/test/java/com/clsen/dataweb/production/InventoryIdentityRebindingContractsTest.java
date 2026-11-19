package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.sql.DriverManager;
import java.util.*;
import java.util.concurrent.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.util.ReflectionTestUtils;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.NONE,properties="PRODUCTION_IDENTITY_REBIND_ENABLED=true")
class InventoryIdentityRebindingContractsTest {
    @Autowired InventoryService stock;
    @Autowired JdbcTemplate db;
    @Autowired ObjectMapper json;
    ProductionContext context;
    long old1,old2,order,shipment,line1,line2,source1,source2,document;
    @BeforeAll static void prepare() throws Exception {
        String url=System.getenv("PRODUCTION_DATABASE_URL");
        if(url==null||!url.contains("/clsen_orders_b_v1_1_0_test?"))throw new IllegalStateException("Only the existing disposable test schema is permitted");
        String user=System.getenv("PRODUCTION_MIGRATION_USER"),password=System.getenv("PRODUCTION_MIGRATION_PASSWORD");
        Flyway.configure().dataSource(url,user,password).load().migrate();
        try(var c=DriverManager.getConnection(url,user,password);var s=c.createStatement()){
            s.execute("CREATE TABLE IF NOT EXISTS production_backup_sku_crosswalk(old_sku_id BIGINT PRIMARY KEY,target_sku_id BIGINT UNIQUE,status VARCHAR(16) NOT NULL,match_rule VARCHAR(64) NOT NULL,old_identity VARCHAR(500) NOT NULL,target_identity VARCHAR(500)) ENGINE=InnoDB");
        }
    }
    long inserted(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    @BeforeEach void seed(){
        context=new ProductionContext(Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000)+7_000_000,1,Set.of("admin"),"rebind.contract.admin");
        old1=900_000_000_000L+context.site()*2;old2=old1+1;
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,1,1,'QA','UNASSIGNED','2026-10-14',?,?)",context.site(),"QA-"+context.site(),UUID.randomUUID().toString());
        for(long sku:List.of(old1,old2)){
            String label=sku==old1?"1123 · 正式SKU待补 · SKY BLUE / M":"3104 · 正式SKU待补 · Army / S";
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version,qualified_units) VALUES(?,1,1,?,?,'UNMAPPED_FROM_23040_V7',?)",context.site(),sku,label,sku==old1?5:0);
            db.update("INSERT INTO production_backup_sku_crosswalk VALUES(?,?,'PENDING','QA',?,NULL)",sku-900_000_000_000L,sku,label);
        }
        db.update("INSERT INTO production_order(site_id,system_number,status,business_date) VALUES(?,?,'CONFIRMED','2026-10-16')",context.site(),"QA-O-"+context.site());order=inserted();
        db.update("INSERT INTO production_shipment(site_id,system_number,status,business_date,stock_tracked,warehouse_id,owner_id) VALUES(?,?,'CONFIRMED','2026-10-16',TRUE,1,1)",context.site(),"QA-S-"+context.site());shipment=inserted();
        long[] lines=new long[2],sources=new long[2];int i=0;
        for(long sku:List.of(old1,old2)){
            int amount=sku==old1?5:3;
            db.update("INSERT INTO production_order_line(site_id,order_id,sku_id,sku_label,catalog_version,expected_units) VALUES(?,?,?,'QA','OLD',?)",context.site(),order,sku,amount);lines[i]=inserted();
            db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,?,'QA','OLD',?)",context.site(),shipment,sku,amount);sources[i]=inserted();
            db.update("INSERT INTO production_shipment_allocation(site_id,source_line_id,order_line_id,units) VALUES(?,?,?,?)",context.site(),sources[i],lines[i],amount);
            db.update("INSERT INTO inventory_shipment_position VALUES(?,?,?,1,1,?,?)",context.site(),shipment,sources[i],sku,amount);
            db.update("INSERT INTO inventory_event(site_id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,operation_token,actor_id,actor_name,reason,business_date) VALUES(?,1,1,?,'QUALIFIED',?,'opening',1,1,?,1,'QA','QA source','2026-10-14')",context.site(),sku,sku==old1?10:3,UUID.randomUUID().toString());
            db.update("INSERT INTO inventory_event(site_id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,operation_token,actor_id,actor_name,reason,business_date) VALUES(?,1,1,?,'QUALIFIED',?,'shipment',?,1,?,1,'QA','QA dispatched','2026-10-16')",context.site(),sku,-amount,shipment,UUID.randomUUID().toString());i++;
        }
        line1=lines[0];line2=lines[1];source1=sources[0];source2=sources[1];
        db.update("INSERT INTO inventory_document(site_id,warehouse_id,owner_id,kind,business_date,reason,line_items,actor_id,actor_name) VALUES(?,1,1,'ADJUST','2026-10-14','QA unapplied historical draft',?,1,'QA')",context.site(),"[{\"sku_id\":\""+old1+"\",\"units\":\"99\"}]");document=inserted();
    }
    @AfterEach void clean(){
        ReflectionTestUtils.setField(stock,"identityRebindingEnabled",true);
        for(String table:List.of("inventory_shipment_reservation","inventory_shipment_position","inventory_event","inventory_reservation","inventory_hold","inventory_plan","inventory_loan","inventory_document","inventory_balance","inventory_scope","inventory_site_lock","production_shipment_allocation","production_shipment_source_line","production_order_line","production_shipment","production_order","production_revision","production_command"))db.update("DELETE FROM "+table+" WHERE site_id=?",context.site());
        db.update("DELETE FROM production_backup_sku_crosswalk WHERE old_sku_id IN (?,?)",old1-900_000_000_000L,old2-900_000_000_000L);
    }
    JsonNode body(){
        var b=new LinkedHashMap<String,Object>();b.put("operation_token",UUID.randomUUID().toString());b.put("warehouse_id","1");b.put("owner_id","1");b.put("expected_total_units","5");b.put("expected_catalog_version","DEMO_LOCAL_ONLY-v1");b.put("identity_key_version","catalog_identity_key_v1");b.put("reason","QA explicit identity conversion with quantities unchanged");b.put("source_reference","QA saved source revision 8");
        b.put("mappings",List.of(Map.of("old_sku_id",Long.toString(old1),"target_sku_id","1001","expected_revision","1","expected_units","5","evidence","QA row1"),Map.of("old_sku_id",Long.toString(old2),"target_sku_id","1002","expected_revision","1","expected_units","0","evidence","QA row2")));
        b.put("_catalog",Map.of("1001",Map.of("status","active","label","1123 · QA-SKY-M · Sky Blue / M","catalog_version","DEMO_LOCAL_ONLY-v1"),"1002",Map.of("status","active","label","3104 · 3104-Army-S · Army / S","catalog_version","DEMO_LOCAL_ONLY-v1")));
        b.put("expected_order_line_ids",List.of(Long.toString(line1),Long.toString(line2)));b.put("expected_shipment_source_ids",List.of(Long.toString(source1),Long.toString(source2)));
        b.put("expected_orders_revisions",Map.of(Long.toString(order),"1"));b.put("expected_shipments_revisions",Map.of(Long.toString(shipment),"1"));b.put("expected_stock_revisions",Map.of(Long.toString(document),"1"));return json.valueToTree(b);
    }
    JsonNode apply(JsonNode b){return json.valueToTree(stock.command(context,"identity-rebindings",b,b.path("operation_token").asText()));}
    long count(String table){return db.queryForObject("SELECT COUNT(*) FROM "+table+" WHERE site_id=?",Long.class,context.site());}
    @Test void convertsReferencesKeepsHistoryAndZeroBalanceAndReplaysWithoutSideEffects(){
        var original=db.queryForList("SELECT * FROM inventory_event WHERE site_id=? ORDER BY id",context.site());var b=body();
        var result=apply(b);assertEquals(2,result.path("converted_records").asInt());assertEquals("0",result.path("physical_net_change").asText());
        assertEquals(5L,db.queryForObject("SELECT SUM(qualified_units) FROM inventory_balance WHERE site_id=?",Long.class,context.site()));
        assertEquals(0L,db.queryForObject("SELECT qualified_units FROM inventory_balance WHERE site_id=? AND sku_id=1002",Long.class,context.site()));
        assertEquals(8L,db.queryForObject("SELECT SUM(expected_units) FROM production_order_line WHERE site_id=?",Long.class,context.site()));
        assertEquals(8L,db.queryForObject("SELECT SUM(actual_units) FROM production_shipment_source_line WHERE site_id=?",Long.class,context.site()));
        assertEquals("DRAFT",db.queryForObject("SELECT status FROM inventory_document WHERE site_id=? AND id=?",String.class,context.site(),document));
        assertEquals(original,db.queryForList("SELECT * FROM inventory_event WHERE site_id=? AND document_kind<>'identity' ORDER BY id",context.site()));
        assertEquals(5L,db.queryForObject("SELECT SUM(delta_units) FROM inventory_event WHERE site_id=? AND sku_id=1001",Long.class,context.site()));
        assertEquals(0L,db.queryForObject("SELECT SUM(delta_units) FROM inventory_event WHERE site_id=? AND sku_id=?",Long.class,context.site(),old1));
        long events=count("inventory_event"),history=count("production_revision");var replay=apply(b);for(var field:result.properties())assertEquals(field.getValue().asText(),replay.path(field.getKey()).asText());assertEquals(events,count("inventory_event"));assertEquals(history,count("production_revision"));
    }
    @Test void staleQuantityOrDuplicateTargetRejectsEntireBatch(){
        var b=body();((tools.jackson.databind.node.ObjectNode)b.path("mappings").get(1)).put("expected_units","1");
        assertEquals("identity_rebind_conflict",assertThrows(ProductionError.class,()->apply(b)).code);
        assertEquals(2L,db.queryForObject("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND sku_id>=900000000000",Long.class,context.site()));assertEquals(0,count("production_command"));
    }
    @Test void lateAuditFailureRollsBackBalancesReferencesCrosswalkEventsAndReceipt(){
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,operation_token,reason,after_value) VALUES(?,'orders',?,2,1,?,'QA collision','{}')",context.site(),order,UUID.randomUUID().toString());
        assertThrows(org.springframework.dao.DataIntegrityViolationException.class,()->apply(body()));
        assertEquals(2L,db.queryForObject("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND sku_id>=900000000000",Long.class,context.site()));assertEquals(4,count("inventory_event"));assertEquals(1,count("production_revision"));assertEquals(0,count("production_command"));
        assertEquals(2L,db.queryForObject("SELECT COUNT(*) FROM production_backup_sku_crosswalk WHERE old_sku_id IN (?,?) AND status='PENDING'",Long.class,old1-900_000_000_000L,old2-900_000_000_000L));
    }
    @Test void disabledAndNonAdminAndWrongSiteCannotConvert(){
        ReflectionTestUtils.setField(stock,"identityRebindingEnabled",false);
        assertEquals("identity_rebinding_disabled",assertThrows(ProductionError.class,()->apply(body())).code);
        ReflectionTestUtils.setField(stock,"identityRebindingEnabled",true);var b=body();
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->stock.command(new ProductionContext(context.site(),2,Set.of("data_manager")),"identity-rebindings",b,b.path("operation_token").asText())).code);
        assertEquals("identity_rebind_conflict",assertThrows(ProductionError.class,()->stock.command(new ProductionContext(context.site()+1,1,Set.of("admin")),"identity-rebindings",b,b.path("operation_token").asText())).code);
        assertEquals(0,count("production_command"));
    }
    @Test void staleDocumentRevisionAndCatalogAndTargetCollisionAreRejected(){
        var b=body();((tools.jackson.databind.node.ObjectNode)b.path("expected_orders_revisions")).put(Long.toString(order),"2");assertEquals("identity_rebind_conflict",assertThrows(ProductionError.class,()->apply(b)).code);
        var stale=(tools.jackson.databind.node.ObjectNode)body();stale.put("expected_catalog_version","STALE");assertEquals("identity_rebind_conflict",assertThrows(ProductionError.class,()->apply(stale)).code);
        db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,1,1,1001,'QA','QA')",context.site());assertEquals("identity_rebind_conflict",assertThrows(ProductionError.class,()->apply(body())).code);
    }
    @Test void concurrentCommandsCannotConvertTwice() throws Exception {
        var a=body();var b=body();var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)){
            var first=pool.submit(()->{start.await();try{apply(a);return "saved";}catch(ProductionError e){return e.code;}});
            var second=pool.submit(()->{start.await();try{apply(b);return "saved";}catch(ProductionError e){return e.code;}});
            start.countDown();assertEquals(Set.of("saved","identity_rebind_conflict"),Set.of(first.get(20,TimeUnit.SECONDS),second.get(20,TimeUnit.SECONDS)));
        }
        assertEquals(1,count("production_command"));assertEquals(5L,db.queryForObject("SELECT SUM(qualified_units) FROM inventory_balance WHERE site_id=?",Long.class,context.site()));
    }
    @Test void historicalStockCorrectionResolvesTheNewIdentityWithoutRewritingOriginalEvents(){
        db.update("UPDATE inventory_document SET status='POSTED' WHERE site_id=? AND id=?",context.site(),document);
        db.update("UPDATE inventory_event SET delta_units=9 WHERE site_id=? AND sku_id=? AND document_kind='opening'",context.site(),old1);
        db.update("INSERT INTO inventory_event(site_id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,operation_token,actor_id,actor_name,reason,business_date) VALUES(?,1,1,?,'QUALIFIED',1,'stock',?,1,?,1,'QA','QA old stock fact','2026-10-14')",context.site(),old1,document,UUID.randomUUID().toString());
        apply(body());
        @SuppressWarnings("unchecked") var inverse=(List<InventoryService.Delta>)ReflectionTestUtils.invokeMethod(stock,"inverse",context,document);
        assertEquals(1,inverse.size());assertEquals(1001L,inverse.getFirst().key().sku());assertEquals(-1L,inverse.getFirst().units());
        assertEquals(old1,db.queryForObject("SELECT sku_id FROM inventory_event WHERE site_id=? AND document_kind='stock'",Long.class,context.site()));
    }
}
