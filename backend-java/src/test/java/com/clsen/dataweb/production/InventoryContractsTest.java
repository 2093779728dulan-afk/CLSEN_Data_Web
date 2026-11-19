package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.NONE)
class InventoryContractsTest {
    @Autowired InventoryService stock;
    @Autowired ProductionService production;
    @Autowired ProductionFiles files;
    @Autowired ObjectMapper json;
    @Autowired JdbcTemplate db;
    ProductionContext context;
    @BeforeAll static void migrate() {
        String url=System.getenv("PRODUCTION_DATABASE_URL");
        if(url==null||!url.contains("/clsen_orders_b_v1_1_0_test?"))throw new IllegalStateException("Only the dedicated task test schema may be used");
        Flyway.configure().dataSource(url,System.getenv("PRODUCTION_MIGRATION_USER"),System.getenv("PRODUCTION_MIGRATION_PASSWORD")).load().migrate();
    }
    @BeforeEach void scope(){context=new ProductionContext(Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000)+2_000_000,1,Set.of("admin"),"contract.admin");}
    @AfterEach void cleanup(){
        db.update("UPDATE production_order SET factory_id=NULL WHERE site_id=?",context.site());
        for(String table:List.of("destination_receipt_line","destination_receipt","destination_receipt_settlement","destination_receipt_upload","destination_shipment_binding"))db.update("DELETE FROM "+table+" WHERE site_id=?",context.site());
        for(String table:List.of("production_factory_warehouse","production_directory_revision","production_warehouse","production_factory"))db.update("DELETE FROM "+table+" WHERE site_id=?",context.site());
        for(String table:List.of("inventory_event","inventory_shipment_reservation","inventory_shipment_position","production_business_source","production_preview","production_source","production_shipment_allocation","production_shipment_source_line","production_shipment","inventory_plan","inventory_loan","inventory_reservation","inventory_hold","inventory_document","inventory_balance","inventory_scope","inventory_display_settings","inventory_site_lock","production_order_line","production_order","production_revision","production_command")) db.update("DELETE FROM "+table+" WHERE site_id=?",context.site());
    }
    JsonNode body(Map<String,Object> values){
        var all=new LinkedHashMap<>(values);all.put("operation_token",UUID.randomUUID().toString());
        var catalog=Map.of("1001",Map.of("sku_id","1001","code","DEMO-SKU-BLUE-M","label","虚构蓝色 M","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"),"1002",Map.of("sku_id","1002","code","DEMO-SKU-BLUE-L","label","虚构蓝色 L","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"));
        all.put("_catalog",catalog);
        all.put("_resolved_codes",Map.of("DEMO-SKU-BLUE-M",catalog.get("1001"),"DEMO-SKU-BLUE-L",catalog.get("1002")));
        return json.valueToTree(all);
    }
    JsonNode command(String path,Map<String,Object> input){var b=body(input);return json.valueToTree(stock.command(context,path,b,b.path("operation_token").asText()));}
    void opening(String amount){command("openings/confirm",Map.of("warehouse_id","1","owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-OPEN-"+context.site(),"reason","独立虚构期初","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units",amount))));}
    JsonNode firstReceipt(List<Map<String,Object>> lines){return command("documents",Map.of("warehouse_id","1","owner_id","1","kind","IN","business_date","2026-10-14","reason","新规格首次到货","lines",lines));}
    JsonNode secondSkuBalance(){return json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id","1","owner_id","1","sku_id","1002")));}
    long secondSkuRows(String table){return db.queryForObject("SELECT COUNT(*) FROM "+table+" WHERE site_id=? AND warehouse_id=1 AND owner_id=1 AND sku_id=1002",Long.class,context.site());}
    JsonNode displayInput(String revision, List<String> ids) {
        var input = (tools.jackson.databind.node.ObjectNode) body(Map.of("expected_revision", revision, "style_ids", ids));
        ((tools.jackson.databind.node.ObjectNode) input.path("_catalog").path("1001")).put("style_id", "2001");
        ((tools.jackson.databind.node.ObjectNode) input.path("_catalog").path("1002")).put("style_id", "2002");
        return input;
    }
    @Test void lightAvailabilityProjectionsMatchFullStockAndPreserveScopeIsolation() {
        opening("10");
        db.update("UPDATE inventory_balance SET pending_units=3,defective_units=2,unassessed_units=1 WHERE site_id=?",context.site());
        var full=json.valueToTree(stock.read(context,"availability",Map.of()));
        var summary=json.valueToTree(stock.read(context,"availability",Map.of("projection","summary")));
        var scopes=json.valueToTree(stock.read(context,"availability",Map.of("projection","scopes")));
        assertEquals("16",summary.path("items").get(0).path("on_hand_units").asText());
        assertEquals(full.path("items").get(0).path("on_hand_units"),summary.path("items").get(0).path("on_hand_units"));
        assertEquals(full.path("scopes").size(),scopes.path("scopes").size());
        assertTrue(scopes.path("items").isEmpty());assertFalse(scopes.path("scopes").get(0).has("opening_metadata"));
        assertFalse(summary.path("items").get(0).has("dispatch_allowed_units"));
        assertTrue(json.valueToTree(stock.read(context,"availability",Map.of("projection","summary","warehouse_id","2"))).path("items").isEmpty());
        assertTrue(json.valueToTree(stock.read(context,"availability",Map.of("projection","scopes","owner_id","2"))).path("scopes").isEmpty());
        var other=new ProductionContext(context.site()+1,1,Set.of("viewer"),"other");
        assertTrue(json.valueToTree(stock.read(other,"availability",Map.of("projection","summary"))).path("items").isEmpty());
        assertTrue(full.path("items").get(0).has("dispatch_allowed_units"));
        assertThrows(ProductionError.class,()->stock.read(context,"availability",Map.of("projection","unknown")));
    }
    @Test void lightAvailabilityPreservesUninitializedAndEmptyScopeSemantics() {
        var empty=json.valueToTree(stock.read(context,"availability",Map.of("projection","summary")));
        assertTrue(empty.path("items").isEmpty());assertTrue(empty.path("scopes").isEmpty());
        opening("10");db.update("DELETE FROM inventory_event WHERE site_id=?",context.site());
        db.update("DELETE FROM inventory_balance WHERE site_id=?",context.site());
        var initialized=json.valueToTree(stock.read(context,"availability",Map.of("projection","summary")));
        assertTrue(initialized.path("items").isEmpty());assertEquals(1,initialized.path("scopes").size());
    }
    @Test void sharedDisplayIsSiteScopedRoleControlledAndIdempotent() {
        var manager = new ProductionContext(context.site(), 42, Set.of("data_manager"), "display.manager");
        var viewer = new ProductionContext(context.site(), 43, Set.of("viewer"), "display.viewer");
        var input = displayInput("0", List.of("2001"));
        String token = input.path("operation_token").asText();
        var saved = json.valueToTree(stock.command(manager, "display-settings", input, token));
        assertEquals("1", saved.path("revision").asText());
        assertEquals(saved, json.valueToTree(stock.command(manager, "display-settings", input, token)));
        var visible = json.valueToTree(stock.read(viewer, "display-settings", Map.of()));
        assertEquals(List.of("2001"), json.convertValue(visible.path("style_ids"), List.class));
        assertFalse(visible.path("can_manage").asBoolean());
        assertEquals("role_forbidden", assertThrows(ProductionError.class, () -> stock.command(viewer, "display-settings", input, token)).code);
        var otherSite = new ProductionContext(context.site() + 1, 43, Set.of("viewer"));
        assertTrue(json.valueToTree(stock.read(otherSite, "display-settings", Map.of())).path("style_ids").isEmpty());
        assertEquals(1, db.queryForObject("SELECT COUNT(*) FROM production_revision WHERE site_id=? AND document_kind='stock_display'", Integer.class, context.site()));
    }
    @Test void sharedDisplayRejectsStaleInvalidOrDuplicateSelectionsAndAllowsClear() {
        var first = displayInput("0", List.of("2001"));
        stock.command(context, "display-settings", first, first.path("operation_token").asText());
        for (var test : List.of(Map.entry(displayInput("0", List.of("2002")), "display_revision_conflict"), Map.entry(displayInput("1", List.of("9999")), "display_style_unavailable"), Map.entry(displayInput("1", List.of("2001", "2001")), "duplicate_display_style"))) {
            var input = test.getKey();
            assertEquals(test.getValue(), assertThrows(ProductionError.class, () -> stock.command(context, "display-settings", input, input.path("operation_token").asText())).code);
        }
        var clear = displayInput("1", List.of());
        var saved = json.valueToTree(stock.command(context, "display-settings", clear, clear.path("operation_token").asText()));
        assertTrue(saved.path("style_ids").isEmpty());
        assertEquals("2", saved.path("revision").asText());
    }
    @Test void sharedDisplayConcurrentManagersCannotOverwriteEachOther() throws Exception {
        var start = new CountDownLatch(1);
        var pool = Executors.newFixedThreadPool(2);
        try {
            var jobs = new ArrayList<Future<String>>();
            for (String id : List.of("2001", "2002")) jobs.add(pool.submit(() -> {
                var input = displayInput("0", List.of(id));
                start.await();
                try { stock.command(context, "display-settings", input, input.path("operation_token").asText()); return "saved"; }
                catch (ProductionError error) { return error.code; }
            }));
            start.countDown();
            var results = List.of(jobs.get(0).get(10, TimeUnit.SECONDS), jobs.get(1).get(10, TimeUnit.SECONDS));
            assertEquals(1, Collections.frequency(results, "saved"));
            assertEquals(1, Collections.frequency(results, "display_revision_conflict"));
        } finally { pool.shutdownNow(); }
        assertEquals("1", json.valueToTree(stock.read(context, "display-settings", Map.of())).path("revision").asText());
    }
    @Test void sharedDisplayFailureRollsBackConfigurationAndCommandReceipt() {
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,operation_token,reason,after_value) VALUES(?,'stock_display',0,1,1,?,'TEST_COLLISION','{}')", context.site(), UUID.randomUUID().toString());
        var input = displayInput("0", List.of("2001"));
        assertThrows(org.springframework.dao.DataIntegrityViolationException.class, () -> stock.command(context, "display-settings", input, input.path("operation_token").asText()));
        assertEquals("0", json.valueToTree(stock.read(context, "display-settings", Map.of())).path("revision").asText());
        assertEquals(0, db.queryForObject("SELECT COUNT(*) FROM production_command WHERE site_id=?", Integer.class, context.site()));
    }
    @Test void sharedDisplayManagementDoesNotRequireInventoryPostingToBeEnabled() throws Exception {
        InventoryService target = org.springframework.test.util.AopTestUtils.getTargetObject(stock);
        Object writes = org.springframework.test.util.ReflectionTestUtils.getField(target, "writesEnabled");
        Object inventoryWrites = org.springframework.test.util.ReflectionTestUtils.getField(target, "inventoryWritesEnabled");
        try {
            org.springframework.test.util.ReflectionTestUtils.setField(target, "writesEnabled", false);
            org.springframework.test.util.ReflectionTestUtils.setField(target, "inventoryWritesEnabled", false);
            var input = displayInput("0", List.of("2001"));
            assertEquals("1", json.valueToTree(stock.command(context, "display-settings", input, input.path("operation_token").asText())).path("revision").asText());
        } finally {
            org.springframework.test.util.ReflectionTestUtils.setField(target, "writesEnabled", writes);
            org.springframework.test.util.ReflectionTestUtils.setField(target, "inventoryWritesEnabled", inventoryWrites);
        }
    }
    @Test void firstReceiptProductionPreviewIsZeroAndConfirmationInitializesOnce(){
        opening("10");var input=body(Map.of("save_mode","confirm","business_date","2026-10-14","manual_source_note","新规格生产实收","lines",List.of(Map.of("sku_id","1002","expected_units","3"))));
        var order=json.valueToTree(production.command(context,"orders",null,"create",input.path("operation_token").asText(),input));
        var draft=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","3","purpose","PRODUCTION_RECEIPT","production_allocations",List.of(receiptAllocation(order,"3")))));
        String path="documents/"+draft.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));
        assertEquals("0",preview.path("impacts").get(0).path("on_hand_before").asText());assertEquals("3",preview.path("impacts").get(0).path("on_hand_after").asText());
        assertEquals(0,secondSkuRows("inventory_balance"));assertEquals(0,secondSkuRows("inventory_event"));
        var confirm=body(Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));String token=confirm.path("operation_token").asText();
        var posted=json.valueToTree(stock.command(context,path+"/confirm",confirm,token));assertEquals(posted,json.valueToTree(stock.command(context,path+"/confirm",confirm,token)));
        assertEquals("3",secondSkuBalance().path("on_hand_units").asText());assertEquals("10",availability().path("on_hand_units").asText());assertEquals("3",orderDetail(order).path("received_units").asText());
        assertEquals(1,secondSkuRows("inventory_balance"));assertEquals(2,secondSkuRows("inventory_event"));
    }
    @Test void firstReceiptMixedQualitiesAndExistingBalancesRemainAdditive(){
        opening("10");var draft=firstReceipt(List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","2","purpose","RECEIPT"),Map.of("sku_id","1002","quality","PENDING","units","3","purpose","RECEIPT"),Map.of("sku_id","1002","quality","DEFECTIVE","units","4","purpose","OTHER")));
        String path="documents/"+draft.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));
        var posted=command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        assertEquals("12",availability().path("on_hand_units").asText());assertEquals("7",secondSkuBalance().path("on_hand_units").asText());assertEquals("0",secondSkuBalance().path("free_available_units").asText());assertEquals(3,secondSkuRows("inventory_event"));
        command(path+"/reverse",Map.of("expected_revision",posted.path("revision").asText(),"reason","冲销首次入库测试"));
        assertEquals("0",secondSkuBalance().path("on_hand_units").asText());assertEquals("10",availability().path("on_hand_units").asText());assertEquals(1,secondSkuRows("inventory_balance"));
    }
    @Test void firstReceiptConcurrentConfirmationsDoNotResetTheNewSku() throws Exception {
        opening("10");var one=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","1","purpose","RECEIPT")));var two=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","2","purpose","RECEIPT")));
        var start=new CountDownLatch(1);var pool=Executors.newFixedThreadPool(2);
        try{var first=pool.submit(()->{start.await();return command("documents/"+one.path("id").asText()+"/confirm",Map.of("expected_revision","1"));});var second=pool.submit(()->{start.await();return command("documents/"+two.path("id").asText()+"/confirm",Map.of("expected_revision","1"));});start.countDown();assertEquals("POSTED",first.get(10,TimeUnit.SECONDS).path("status").asText());assertEquals("POSTED",second.get(10,TimeUnit.SECONDS).path("status").asText());}finally{pool.shutdownNow();}
        assertEquals("3",secondSkuBalance().path("on_hand_units").asText());assertEquals(1,secondSkuRows("inventory_balance"));assertEquals(3,secondSkuRows("inventory_event"));
    }
    @Test void firstReceiptPreviewDetectsAConcurrentFirstReceipt(){
        opening("10");var one=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","4","purpose","RECEIPT")));var two=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","6","purpose","RECEIPT")));String path="documents/"+two.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));
        command("documents/"+one.path("id").asText()+"/confirm",Map.of("expected_revision","1"));assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()))).code);
        var refreshed=command(path+"/preview",Map.of("expected_revision","1"));assertEquals("4",refreshed.path("impacts").get(0).path("on_hand_before").asText());command(path+"/confirm",Map.of("expected_revision","1","preview_hash",refreshed.path("preview_hash").asText()));assertEquals("10",secondSkuBalance().path("on_hand_units").asText());assertEquals(3,secondSkuRows("inventory_event"));
    }
    @Test void firstReceiptFailureRollsBackInitializationAndEvents(){
        opening("10");var draft=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","3","purpose","RECEIPT")));String path="documents/"+draft.path("id").asText();
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,operation_token,reason,after_value) VALUES(?,'stock',?,2,1,?,'TEST_COLLISION','{}')",context.site(),draft.path("id").asLong(),UUID.randomUUID().toString());var input=body(Map.of("expected_revision","1"));
        assertThrows(org.springframework.dao.DataIntegrityViolationException.class,()->stock.command(context,path+"/confirm",input,input.path("operation_token").asText()));assertEquals(0,secondSkuRows("inventory_balance"));assertEquals(0,secondSkuRows("inventory_event"));assertEquals("DRAFT",json.valueToTree(stock.read(context,path,Map.of())).path("status").asText());
    }
    @Test void firstReceiptCorrectionCanReplaceWithANewSkuAndReverse(){
        opening("10");
        var received=movement("IN","2","RECEIPT");
        String path="documents/"+received.path("id").asText();
        var replacement=Map.of("sku_id","1002","quality","QUALIFIED","units","3","purpose","RECEIPT");
        var input=new LinkedHashMap<String,Object>(Map.of("expected_revision",received.path("revision").asText(),"reason","原入库规格更正为新规格","lines",List.of(replacement)));
        input.put("mode","correct");
        var preview=command(path+"/preview",input);
        assertEquals(0,secondSkuRows("inventory_balance"));
        input.put("preview_hash",preview.path("preview_hash").asText());
        var corrected=command(path+"/correct",input);
        assertEquals("10",availability().path("on_hand_units").asText());
        assertEquals("3",secondSkuBalance().path("on_hand_units").asText());
        assertEquals(2,secondSkuRows("inventory_event"));
        command(path+"/reverse",Map.of("expected_revision",corrected.path("revision").asText(),"reason","冲销已更正入库"));
        assertEquals("10",availability().path("on_hand_units").asText());
        assertEquals("0",secondSkuBalance().path("on_hand_units").asText());
    }
    @Test void firstCountEstablishesSnapshotWithoutManufacturingAnInboundReceipt(){
        var directory=body(Map.of("name","QA counted warehouse","type","OWN","country","CN"));
        production.directorySave(context,"warehouses",null,directory.path("operation_token").asText(),directory);
        opening("10");
        var line=Map.<String,Object>of("sku_id","1002","quality","QUALIFIED","units","7","purpose","COUNT","counted_on","2026-10-14","evidence","QA original stocktake cell E12");
        var draft=command("documents",Map.of("warehouse_id","1","owner_id","1","kind","ADJUST","business_date","2026-10-14","reason","QA original stocktake snapshot","lines",List.of(line)));
        String path="documents/"+draft.path("id").asText();
        var preview=command(path+"/preview",Map.of("expected_revision","1"));
        assertEquals(0,secondSkuRows("inventory_balance"));
        var input=body(Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        var posted=json.valueToTree(stock.command(context,path+"/confirm",input,input.path("operation_token").asText()));
        assertEquals(posted,json.valueToTree(stock.command(context,path+"/confirm",input,input.path("operation_token").asText())));
        assertEquals("7",secondSkuBalance().path("on_hand_units").asText());
        assertEquals("10",availability().path("on_hand_units").asText());
        assertEquals(2,secondSkuRows("inventory_event"));
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM inventory_document WHERE site_id=? AND kind='IN'",Long.class,context.site()));
        var missing=new LinkedHashMap<String,Object>(line);missing.remove("evidence");
        var invalid=command("documents",Map.of("warehouse_id","1","owner_id","1","kind","ADJUST","business_date","2026-10-14","reason","QA missing evidence","lines",List.of(missing)));
        assertEquals("stocktake_evidence_required",assertThrows(ProductionError.class,()->command("documents/"+invalid.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);
        assertEquals("7",secondSkuBalance().path("on_hand_units").asText());
    }
    @Test void firstReceiptDoesNotInitializeUnopenedScopesOrHistoricalGaps(){
        var unopened=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","1","purpose","RECEIPT")));assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->command("documents/"+unopened.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);
        command("openings/confirm",Map.of("warehouse_id","1","owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-OPEN-"+context.site(),"reason","已有规格期初","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","10"),Map.of("sku_id","1002","quality","QUALIFIED","units","5"))));
        db.update("DELETE FROM inventory_balance WHERE site_id=? AND warehouse_id=1 AND owner_id=1 AND sku_id=1002",context.site());assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->command("documents/"+unopened.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);assertEquals(0,secondSkuRows("inventory_balance"));assertEquals(1,secondSkuRows("inventory_event"));
    }
    @Test void firstReceiptKeepsOutflowReturnAndCutoffChecks(){
        opening("10");for(String purpose:List.of("RETURN","SALES_RETURN")){var draft=firstReceipt(List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","1","purpose",purpose)));assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->command("documents/"+draft.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);}
        var out=command("documents",Map.of("warehouse_id","1","owner_id","1","kind","OUT","business_date","2026-10-14","reason","未有库存不能出库","lines",List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","1","purpose","CONSUME"))));assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->command("documents/"+out.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);
        var prior=command("documents",Map.of("warehouse_id","1","owner_id","1","kind","IN","business_date","2026-09-30","reason","期初截止前收货","lines",List.of(Map.of("sku_id","1002","quality","QUALIFIED","units","1","purpose","RECEIPT"))));assertEquals("before_opening_cutoff",assertThrows(ProductionError.class,()->command("documents/"+prior.path("id").asText()+"/preview",Map.of("expected_revision","1"))).code);assertEquals(0,secondSkuRows("inventory_balance"));
    }
    @Test void directoryStateBlocksNewPostingButRetainsSuccessfulReplay(){
        opening("10");
        var profile=body(Map.of("name","QA scoped warehouse","type","OWN","country","CN"));
        var warehouse=json.valueToTree(production.directorySave(context,"warehouses",null,profile.path("operation_token").asText(),profile));
        var input=body(Map.of("warehouse_id",warehouse.path("id").asText(),"owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-DIRECTORY-"+context.site(),"reason","explicit zero fictional","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","0"))));
        var posted=json.valueToTree(stock.command(context,"openings/confirm",input,input.path("operation_token").asText()));
        var change=body(Map.of("name","QA scoped warehouse","expected_revision","1","status","INACTIVE","reason","QA paused"));production.directorySave(context,"warehouses",warehouse.path("id").asLong(),change.path("operation_token").asText(),change);
        assertEquals(posted,json.valueToTree(stock.command(context,"openings/confirm",input,input.path("operation_token").asText())));
        assertEquals("warehouse_not_operational",assertThrows(ProductionError.class,()->command("documents",Map.of("warehouse_id",warehouse.path("id").asText(),"owner_id","1","kind","IN","business_date","2026-10-23","reason","must refuse","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","2","purpose","OTHER"))))).code);
        var scoped=json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id",warehouse.path("id").asText(),"owner_id","1")));
        assertEquals(1,scoped.path("scopes").size());assertEquals(1,scoped.path("items").size());assertEquals("0",scoped.path("items").get(0).path("on_hand_units").asText());
        assertEquals("10",availability().path("on_hand_units").asText());
        var fba=body(Map.of("name","FBA QA","type","FBA","country","US","seller_account","fictional","marketplace","US"));var platform=json.valueToTree(production.directorySave(context,"warehouses",null,fba.path("operation_token").asText(),fba));
        ((tools.jackson.databind.node.ObjectNode)input).put("warehouse_id",platform.path("id").asText());((tools.jackson.databind.node.ObjectNode)input).put("operation_token",UUID.randomUUID().toString());
        assertEquals("warehouse_not_operational",assertThrows(ProductionError.class,()->stock.command(context,"openings/confirm",input,input.path("operation_token").asText())).code);
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=?",Long.class,context.site(),platform.path("id").asLong()));
    }
    JsonNode availability(){return json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id","1","owner_id","1","sku_id","1001")));}
    Map<String,Object> receiptLine(String units,Object allocations){return Map.of("sku_id","1001","quality","QUALIFIED","units",units,"purpose","PRODUCTION_RECEIPT","production_allocations",allocations);}
    Map<String,Object> receiptAllocation(JsonNode order,String units){return Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"units",units);}
    JsonNode receiptDraft(Map<String,Object> line){return command("documents",Map.of("kind","IN","business_date","2026-10-14","reason","虚构生产实收到仓","lines",List.of(line)));}
    JsonNode orderDetail(JsonNode order){return json.valueToTree(production.get(context,"orders",order.path("id").asLong()));}
    JsonNode orderAction(JsonNode order,String action,Map<String,Object> input){var values=new LinkedHashMap<>(input);values.put("expected_revision",order.path("revision").asText());values.put("reason","虚构来源变更");var b=body(values);return json.valueToTree(production.command(context,"orders",order.path("id").asLong(),action,b.path("operation_token").asText(),b));}
    @Test void manualProductionCompletionIsExplicitRevisionedReversibleAndQuantityNeutral(){
        opening("0");var order=order();
        assertEquals("OPEN",order.path("production_completion_state").asText());
        assertFalse(order.path("production_completion_ready").asBoolean());
        assertEquals("production_completion_not_ready",assertThrows(ProductionError.class,()->orderAction(order,"complete-production",Map.of())).code);
        var progress=orderAction(order,"production-progress",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"produced_units","20"))));
        assertFalse(progress.path("production_completion_ready").asBoolean());
        var draft=receiptDraft(receiptLine("20",List.of(receiptAllocation(order,"20"))));
        String path="documents/"+draft.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));
        command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        var ready=orderDetail(order);assertTrue(ready.path("production_completion_ready").asBoolean());assertEquals("OPEN",ready.path("production_completion_state").asText());
        var input=body(Map.of("expected_revision",ready.path("revision").asText()));
        var viewer=new ProductionContext(context.site(),2,Set.of("viewer"));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->production.command(viewer,"orders",order.path("id").asLong(),"complete-production",input.path("operation_token").asText(),input)).code);
        var other=new ProductionContext(context.site()+9_000_000,1,Set.of("admin"));
        assertEquals("document_not_found",assertThrows(ProductionError.class,()->production.command(other,"orders",order.path("id").asLong(),"complete-production",input.path("operation_token").asText(),input)).code);
        long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());
        var completed=json.valueToTree(production.command(context,"orders",order.path("id").asLong(),"complete-production",input.path("operation_token").asText(),input));
        assertEquals(completed,json.valueToTree(production.command(context,"orders",order.path("id").asLong(),"complete-production",input.path("operation_token").asText(),input)));
        assertEquals("COMPLETED",orderDetail(order).path("production_completion_state").asText());
        assertEquals("0",completed.path("actual_units").asText());assertEquals("20",completed.path("received_units").asText());
        assertEquals("OPEN",completed.path("tracking_state").asText());assertEquals("0",completed.path("closed_units").asText());
        assertEquals("COMPLETE_PRODUCTION",completed.path("history").get(0).path("operation_kind").asText());
        assertEquals("contract.admin",completed.path("history").get(0).path("actor_name").asText());
        assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
        var stale=body(Map.of("expected_revision",ready.path("revision").asText()));
        assertEquals("revision_conflict",assertThrows(ProductionError.class,()->production.command(context,"orders",order.path("id").asLong(),"reopen-production",stale.path("operation_token").asText(),stale)).code);
        var correction=orderAction(completed,"production-progress",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"produced_units","18"))));
        assertFalse(correction.path("production_completion_ready").asBoolean());assertEquals("COMPLETED",correction.path("production_completion_state").asText());
        var listed=json.valueToTree(production.list(context,"orders","","","","","","",1,20));assertEquals("COMPLETED",listed.path("items").get(0).path("production_completion_state").asText());
        var reopened=orderAction(correction,"reopen-production",Map.of());assertEquals("OPEN",reopened.path("production_completion_state").asText());
        assertEquals("18",reopened.path("lines").get(0).path("produced_units").asText());assertEquals("20",availability().path("on_hand_units").asText());
    }
    JsonNode progressList(String progress,int page,int size,String status,String query,ProductionContext scope){return json.valueToTree(production.list(scope,"orders",query,status,"","","","",page,size,"",false,"unknown","","",progress));}
    @Test void completionFiltersBeforePagingCountsAndExportsWithoutChangingFacts() throws Exception {
        opening("0");var done=order();
        orderAction(done,"production-progress",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("order_line_id",done.path("lines").get(0).path("id").asText(),"produced_units","20"))));
        var receipt=receiptDraft(receiptLine("20",List.of(receiptAllocation(done,"20"))));String path="documents/"+receipt.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        var completed=orderAction(orderDetail(done),"complete-production",Map.of());
        var active=order();var discarded=order();orderAction(discarded,"void",Map.of());
        var draftInput=body(Map.of("save_mode","draft","business_date","2026-10-14","business_number","FILTER-DRAFT","lines",List.of(Map.of("sku_id","1001","expected_units","20"))));
        var draft=json.valueToTree(production.command(context,"orders",null,"create",draftInput.path("operation_token").asText(),draftInput));
        long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());
        var first=progressList("active",1,1,"","",context);var second=progressList("active",2,1,"","",context);
        assertEquals(2,first.path("total").asInt());assertEquals(2,first.path("progress_counts").path("active").asInt());assertEquals(1,first.path("progress_counts").path("completed").asInt());assertEquals(4,first.path("progress_counts").path("all").asInt());
        assertEquals(Set.of(active.path("id").asText(),draft.path("id").asText()),Set.of(first.path("items").get(0).path("id").asText(),second.path("items").get(0).path("id").asText()));
        assertEquals(completed.path("id"),progressList("completed",1,1,"","",context).path("items").get(0).path("id"));
        assertEquals(1,progressList("all",1,20,"DRAFT","FILTER-DRAFT",context).path("total").asInt());assertEquals(1,progressList("all",1,20,"VOID","",context).path("total").asInt());
        assertEquals(0,progressList("all",1,20,"","",new ProductionContext(context.site()+9_000_000,1,Set.of("viewer"))).path("total").asInt());
        assertEquals(4,json.valueToTree(production.list(context,"orders","","","","","","",1,20)).path("total").asInt());
        assertEquals("invalid_production_progress",assertThrows(ProductionError.class,()->progressList("bad",1,20,"","",context)).code);
        try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(files.export(context,"orders","","","","","","","","","","unknown","completed")))){assertEquals(1,book.getSheetAt(0).getLastRowNum());assertEquals(completed.path("system_number").asText(),book.getSheetAt(0).getRow(1).getCell(0).getStringCellValue());}
        orderAction(completed,"reopen-production",Map.of());assertEquals(3,progressList("active",1,20,"","",context).path("total").asInt());assertEquals(0,progressList("completed",1,20,"","",context).path("total").asInt());
        assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
    }
    @Test void traceWarehouseAndExplicitOrderFiltersApplyBeforePagination() {
        opening("10");var one=order();var two=order();var unrelated=order();
        db.update("UPDATE production_order SET receipt_warehouse_id=? WHERE site_id=? AND id=?",77,context.site(),one.path("id").asLong());
        db.update("UPDATE production_order SET receipt_warehouse_id=? WHERE site_id=? AND id=?",77,context.site(),two.path("id").asLong());
        var first=json.valueToTree(production.list(context,"orders","","","","","","",1,1,"",false,"","77","","all"));
        var second=json.valueToTree(production.list(context,"orders","","","","","","",2,1,"",false,"","77","","all"));
        assertEquals(2,first.path("total").asInt());assertEquals(2,first.path("progress_counts").path("all").asInt());
        assertEquals(Set.of(one.path("id").asText(),two.path("id").asText()),Set.of(first.path("items").get(0).path("id").asText(),second.path("items").get(0).path("id").asText()));
        assertEquals(0,json.valueToTree(production.list(new ProductionContext(context.site()+9000000,1,Set.of("viewer")),"orders","","","","","","",1,5,"",false,"","77","","all")).path("total").asInt());
        assertThrows(ProductionError.class,()->production.list(context,"orders","","","","","","",1,5,"",false,"","0","","all"));
        var shipment=ship(one,"2");
        var associated=json.valueToTree(production.list(context,"orders","","","","","","",1,5,"",false,"","1","","all"));
        assertEquals(1,associated.path("total").asInt());assertEquals(one.path("id"),associated.path("items").get(0).path("id"));
        var batches=json.valueToTree(stock.read(context,"transit-batches",Map.of("warehouse_id","1","order_id",one.path("id").asText(),"page_size","1")));
        assertEquals(1,batches.path("total").asInt());assertEquals("whole_batch",batches.path("detail_scope").asText());assertEquals(shipment.path("id"),batches.path("items").get(0).path("id"));
        assertEquals(0,json.valueToTree(stock.read(context,"transit-batches",Map.of("warehouse_id","77","order_id",one.path("id").asText()))).path("total").asInt());
        assertEquals(0,json.valueToTree(stock.read(context,"transit-batches",Map.of("order_id",unrelated.path("id").asText()))).path("total").asInt());
        assertThrows(ProductionError.class,()->stock.read(context,"transit-batches",Map.of("warehouse_id","0")));
        assertThrows(ProductionError.class,()->stock.read(context,"transit-batches",Map.of("order_id","0")));
    }
    @Test void completeChainsGroupBeforeFilteringPagingAndKeepScopeAndLegacyReads(){
        opening("10");var one=order();var two=order();var unrelated=order();
        var factoryBody=body(Map.of("name","Fictional chain factory"));var factory=json.valueToTree(production.createFactory(context,factoryBody.path("operation_token").asText(),factoryBody));
        for(var o:List.of(one,two))db.update("UPDATE production_order SET factory_id=?,receipt_warehouse_id=1,receipt_owner_id=1 WHERE site_id=? AND id=?",factory.path("id").asLong(),context.site(),o.path("id").asLong());
        var a=json.valueToTree(production.chains(context,Map.of("chain_progress","all","page_size","1")));
        assertEquals(2,a.path("total").asInt());assertEquals(2,a.path("chain_counts").path("active").asInt());assertEquals(1,a.path("items").size());
        var target=json.valueToTree(production.chains(context,Map.of("trace_kind","order","trace_id",one.path("id").asText())));
        assertEquals(2,target.path("items").get(0).path("orders").size());assertEquals("complete_chain_groups",target.path("detail_scope").asText());
        var shipment=ship(one,"2");
        target=json.valueToTree(production.chains(context,Map.of("trace_kind","shipment","trace_id",shipment.path("id").asText())));
        assertEquals(1,target.path("items").get(0).path("shipments").size());
        assertEquals("2",target.path("items").get(0).path("orders").get(0).path("fulfillment_lines").get(0).path("shipped_units").asText());
        assertEquals(0,json.valueToTree(production.chains(context,Map.of("chain_progress","completed"))).path("total").asInt());
        assertEquals(0,json.valueToTree(production.chains(new ProductionContext(context.site()+9000000,1,Set.of("viewer")),Map.of("chain_progress","all"))).path("total").asInt());
        assertEquals(3,json.valueToTree(production.list(context,"orders","","","","","","",1,20)).path("total").asInt());
        assertThrows(ProductionError.class,()->production.chains(context,Map.of("warehouse_id","0")));
        assertThrows(ProductionError.class,()->production.chains(context,Map.of("warehouse_id","unknown")));
        assertThrows(ProductionError.class,()->production.chains(context,Map.of("trace_kind","order","trace_id","unknown")));
        assertThrows(ProductionError.class,()->production.chains(context,Map.of("chain_progress","bad")));
        assertEquals(unrelated.path("id"),json.valueToTree(production.chains(context,Map.of("trace_kind","order","trace_id",unrelated.path("id").asText()))).path("items").get(0).path("orders").get(0).path("id"));
    }
    @Test void completedChainReadUsesPostedReceiptsAndRetainsHistoricalRouteBesideNewFreight(){
        opening("10");db.update("INSERT INTO production_warehouse(site_id,id,name,type,country) VALUES(?,1,'Fictional source','OWN','CN')",context.site());var profile=body(Map.of("name","Fictional destination","type","OWN","country","US"));
        var warehouse=json.valueToTree(production.directorySave(context,"warehouses",null,profile.path("operation_token").asText(),profile));String destination=warehouse.path("id").asText();
        command("openings/confirm",Map.of("warehouse_id",destination,"owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-CHAIN-DEST","reason","task-only zero opening","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","0"))));
        var input=new LinkedHashMap<String,Object>();input.putAll(Map.of("save_mode","confirm","dispatch_purpose","WAREHOUSE_DISPATCH","business_date","2026-10-14","warehouse_id","1","owner_id","1","destination_id",destination,"destination_type","WAREHOUSE","manual_source_note","fictional route history"));input.put("cartons",List.of(Map.of("number","CHAIN-BOX","items",List.of(Map.of("sku_id","1001","units","2")))));input.put("sources",List.of(Map.of("sku_id","1001","actual_units","2","fulfillment_mode","WAREHOUSE_STOCK","allocations",List.of())));
        var b=body(input);var sent=json.valueToTree(production.command(context,"shipments",null,"create",b.path("operation_token").asText(),b));String sid=sent.path("id").asText();
        var bound=command("destination-bindings",Map.of("shipment_id",sid,"expected_shipment_revision","1","reason","fictional source binding","bindings",List.of(Map.of("carton_id",sent.path("cartons").get(0).path("id").asText(),"source_line_id",sent.path("sources").get(0).path("id").asText(),"sku_id","1001","units","2"))));
        String binding=bound.path("bindings").get(0).path("id").asText();
        assertEquals(0,json.valueToTree(production.chains(context,Map.of("chain_progress","completed"))).path("total").asInt());
        var draft=command("destination-receipts",Map.of("shipment_id",sid,"expected_shipment_revision","1","warehouse_id",destination,"owner_id","1","business_date","2026-10-15","reason","fictional actual receipt","lines",List.of(Map.of("binding_id",binding,"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","2","pending_units","0","defective_units","0"))));
        command("destination-receipts/"+draft.path("id").asText()+"/confirm",Map.of("expected_revision",draft.path("revision").asText()));
        b=body(input);production.command(context,"shipments",null,"create",b.path("operation_token").asText(),b);
        long facts=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());
        var completed=json.valueToTree(production.chains(new ProductionContext(context.site(),2,Set.of("viewer")),Map.of("chain_progress","completed","page_size","1")));
        assertEquals(1,completed.path("total").asInt());assertEquals(1,completed.path("chain_counts").path("active").asInt());assertEquals(1,completed.path("chain_counts").path("completed").asInt());assertEquals(sid,completed.path("items").get(0).path("shipments").get(0).path("id").asText());assertTrue(completed.path("items").get(0).path("completed").asBoolean());
        assertEquals(facts,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
    }
    @Test void productionCompletionNeverOffsetsOneSkuShortfallWithAnotherSkuOverage(){
        command("openings/confirm",Map.of("warehouse_id","1","owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-COMPLETE-"+context.site(),"reason","fictional multi SKU zero opening","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","0"),Map.of("sku_id","1002","quality","QUALIFIED","units","0"))));
        var input=body(Map.of("save_mode","confirm","business_date","2026-10-14","manual_source_note","fictional multi SKU completion","lines",List.of(Map.of("sku_id","1001","expected_units","20"),Map.of("sku_id","1002","expected_units","20"))));
        var order=json.valueToTree(production.command(context,"orders",null,"create",input.path("operation_token").asText(),input));
        var a=order.path("lines").get(0).path("id").asText();var b=order.path("lines").get(1).path("id").asText();
        var progress=orderAction(order,"production-progress",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("order_line_id",a,"produced_units","40"),Map.of("order_line_id",b,"produced_units","0"))));
        var draft=command("documents",Map.of("kind","IN","business_date","2026-10-14","reason","fictional multi SKU receipt","lines",List.of(receiptLine("20",List.of(Map.of("order_line_id",a,"units","20"))),Map.of("sku_id","1002","quality","QUALIFIED","units","20","purpose","PRODUCTION_RECEIPT","production_allocations",List.of(Map.of("order_line_id",b,"units","20"))))));
        String path="documents/"+draft.path("id").asText();var preview=command(path+"/preview",Map.of("expected_revision","1"));command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        var detail=orderDetail(order);assertEquals("40",detail.path("received_units").asText());assertFalse(detail.path("production_completion_ready").asBoolean());
        assertEquals("production_completion_not_ready",assertThrows(ProductionError.class,()->orderAction(detail,"complete-production",Map.of())).code);
    }
    @Test void productionReceiptSeparatesReceiptFromDispatchAndSupportsCorrectionAndReverse(){
        opening("10");var one=order();var two=order();
        var draft=receiptDraft(receiptLine("25",List.of(receiptAllocation(one,"22"),receiptAllocation(two,"3"))));
        String path="documents/"+draft.path("id").asText();
        assertEquals("0",orderDetail(one).path("received_units").asText());
        var preview=command(path+"/preview",Map.of("expected_revision","1"));
        assertEquals(2,preview.path("production_sources").size());assertEquals("10",availability().path("on_hand_units").asText());
        var b=body(Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        var posted=json.valueToTree(stock.command(context,path+"/confirm",b,b.path("operation_token").asText()));
        assertEquals(posted,json.valueToTree(stock.command(context,path+"/confirm",b,b.path("operation_token").asText())));
        assertEquals("35",availability().path("on_hand_units").asText());
        var detail=orderDetail(one);assertEquals("22",detail.path("received_units").asText());assertEquals("22",detail.path("lines").get(0).path("received_units").asText());assertEquals("0",detail.path("actual_units").asText());
        assertEquals("3",orderDetail(two).path("received_units").asText());
        var listed=json.valueToTree(production.list(context,"orders","","","","","","",1,20));
        assertEquals("22",java.util.stream.StreamSupport.stream(listed.path("items").spliterator(),false).filter(item->item.path("id").equals(one.path("id"))).findFirst().orElseThrow().path("received_units").asText());
        assertEquals("downstream_receipt_exists",assertThrows(ProductionError.class,()->orderAction(one,"void",Map.of())).code);
        var correction=Map.<String,Object>of("expected_revision","2","mode","correct","reason","实收更正","lines",List.of(receiptLine("6",List.of(receiptAllocation(one,"2"),receiptAllocation(two,"4")))));
        var cp=command(path+"/preview",correction);var corrected=new LinkedHashMap<>(correction);corrected.put("preview_hash",cp.path("preview_hash").asText());command(path+"/correct",corrected);
        assertEquals("16",availability().path("on_hand_units").asText());assertEquals("2",orderDetail(one).path("received_units").asText());
        command(path+"/reverse",Map.of("expected_revision","3","reason","虚构录入错误冲销"));
        assertEquals("10",availability().path("on_hand_units").asText());assertEquals("0",orderDetail(one).path("received_units").asText());assertEquals("REVERSED",orderDetail(one).path("receipts").get(0).path("status").asText());
        orderAction(one,"void",Map.of());
    }
    @Test void productionReceiptRejectsWrongScopeSkuPurposeAndNonconservingAllocations(){
        var order=order();var allocation=receiptAllocation(order,"2");
        assertEquals("receipt_allocation_mismatch",assertThrows(ProductionError.class,()->receiptDraft(receiptLine("3",List.of(allocation)))).code);
        assertEquals("receipt_allocations_required",assertThrows(ProductionError.class,()->receiptDraft(receiptLine("2",List.of()))).code);
        assertEquals("duplicate_receipt_allocation",assertThrows(ProductionError.class,()->receiptDraft(receiptLine("4",List.of(allocation,allocation)))).code);
        var wrongSku=new LinkedHashMap<>(receiptLine("2",List.of(allocation)));wrongSku.put("sku_id","1002");
        assertEquals("receipt_source_invalid",assertThrows(ProductionError.class,()->receiptDraft(wrongSku)).code);
        var wrongPurpose=new LinkedHashMap<>(receiptLine("2",List.of(allocation)));wrongPurpose.put("purpose","RECEIPT");
        assertEquals("receipt_purpose_invalid",assertThrows(ProductionError.class,()->receiptDraft(wrongPurpose)).code);
        var other=new ProductionContext(context.site()+1,1,Set.of("admin"),"other");var b=body(Map.of("kind","IN","business_date","2026-10-14","reason","跨范围拒绝","lines",List.of(receiptLine("2",List.of(allocation)))));
        assertEquals("receipt_source_invalid",assertThrows(ProductionError.class,()->stock.command(other,"documents",b,b.path("operation_token").asText())).code);
    }
    @Test void productionReceiptRevalidatesSourceAtConfirmAndBindsPreviewToOrderRevision(){
        opening("0");var order=order();var draft=receiptDraft(receiptLine("2",List.of(receiptAllocation(order,"2"))));String path="documents/"+draft.path("id").asText();
        var preview=command(path+"/preview",Map.of("expected_revision","1"));
        var changed=orderAction(order,"demand-changes",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("sku_id","1001","expected_units","30"))));
        assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()))).code);
        orderAction(changed,"void",Map.of());
        assertEquals("receipt_source_invalid",assertThrows(ProductionError.class,()->command(path+"/confirm",Map.of("expected_revision","1"))).code);
        assertEquals("0",availability().path("on_hand_units").asText());assertEquals("DRAFT",json.valueToTree(stock.read(context,"documents/"+draft.path("id").asText(),Map.of())).path("status").asText());
    }
    @Test void productionReceiptPreventsRemovingAnActivelyReferencedOrderLine(){
        opening("0");var order=order();movement("IN",receiptLine("2",List.of(receiptAllocation(order,"2"))));
        assertEquals("downstream_receipt_exists",assertThrows(ProductionError.class,()->orderAction(order,"demand-changes",Map.of("effective_date","2026-10-14","lines",List.of(Map.of("sku_id","1002","expected_units","5"))))).code);
        assertEquals("2",orderDetail(order).path("received_units").asText());
    }
    @Test void productionReceiptConfirmationAndSourceVoidSerializeWithoutDanglingReceipt() throws Exception {
        opening("0");var order=order();var draft=receiptDraft(receiptLine("2",List.of(receiptAllocation(order,"2"))));
        var start=new CountDownLatch(1);var pool=Executors.newFixedThreadPool(2);
        try {
            var receipt=pool.submit(()->{start.await();try{command("documents/"+draft.path("id").asText()+"/confirm",Map.of("expected_revision","1"));return "POSTED";}catch(ProductionError e){return e.code;}});
            var source=pool.submit(()->{start.await();try{orderAction(order,"void",Map.of());return "VOID";}catch(ProductionError e){return e.code;}});
            start.countDown();String received=receipt.get(10,TimeUnit.SECONDS),voided=source.get(10,TimeUnit.SECONDS);
            assertTrue(received.equals("POSTED")&&voided.equals("downstream_receipt_exists")||received.equals("receipt_source_invalid")&&voided.equals("VOID"),received+" / "+voided);
            assertEquals(received.equals("POSTED")?"2":"0",availability().path("on_hand_units").asText());
        } finally {pool.shutdownNow();}
    }
    @Test void previewShowsPhysicalAndFreeBeforeAfterWithoutWriting() {
        opening("10");
        command("holds",Map.of("warehouse_id","1","sku_id","1001","units","2","reason","虚构冻结"));
        var draft=command("documents",Map.of("kind","OUT","business_date","2026-10-14","reason","虚构领用","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","3","purpose","CONSUME"))));
        String path="documents/"+draft.path("id").asText();
        var preview=command(path+"/preview",Map.of("expected_revision","1"));
        var impact=preview.path("impacts").get(0);
        assertEquals("10",impact.path("on_hand_before").asText());assertEquals("7",impact.path("on_hand_after").asText());
        assertEquals("8",impact.path("free_before").asText());assertEquals("5",impact.path("free_after").asText());
        assertEquals("10",availability().path("on_hand_units").asText());
        command(path+"/confirm",Map.of("expected_revision","1","preview_hash",preview.path("preview_hash").asText()));
        assertEquals("7",availability().path("on_hand_units").asText());assertEquals("5",availability().path("free_available_units").asText());
        var corrected=command(path+"/preview",Map.of("expected_revision","2","mode","correct","reason","原三件更正为两件","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","2","purpose","CONSUME"))));
        assertEquals("7",corrected.path("impacts").get(0).path("on_hand_before").asText());assertEquals("8",corrected.path("impacts").get(0).path("on_hand_after").asText());
        assertEquals("6",corrected.path("impacts").get(0).path("free_after").asText());
        var pending=command("documents",Map.of("kind","IN","business_date","2026-10-14","reason","虚构待检实收","lines",List.of(Map.of("sku_id","1001","quality","PENDING","units","2","purpose","RECEIPT"))));
        var pendingPreview=command("documents/"+pending.path("id").asText()+"/preview",Map.of("expected_revision","1"));
        assertEquals("9",pendingPreview.path("impacts").get(0).path("on_hand_after").asText());assertEquals("5",pendingPreview.path("impacts").get(0).path("free_after").asText());
        var count=command("documents",Map.of("kind","ADJUST","business_date","2026-10-14","reason","虚构实盘","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","1","purpose","COUNT","counted_on","2026-10-14","evidence","FICTIONAL"))));
        var shortage=command("documents/"+count.path("id").asText()+"/preview",Map.of("expected_revision","1"));
        assertTrue(shortage.path("impacts").get(0).path("free_after").isNull());
        assertEquals("7",availability().path("on_hand_units").asText());
    }
    JsonNode movement(String kind,String units,String purpose){return movement(kind,Map.of("sku_id","1001","quality","QUALIFIED","units",units,"purpose",purpose,"borrower","虚构借用人"));}
    JsonNode movement(String kind,Map<String,Object> line){
        var draft=command("documents",Map.of("warehouse_id","1","owner_id","1","kind",kind,"business_date","2026-10-14","reason","虚构库存变动","lines",List.of(line)));
        command("documents/"+draft.path("id").asText()+"/preview",Map.of("expected_revision",draft.path("revision").asText()));
        return command("documents/"+draft.path("id").asText()+"/confirm",Map.of("expected_revision",draft.path("revision").asText()));
    }
    JsonNode order(){var b=body(Map.of("save_mode","confirm","business_date","2026-10-14","manual_source_note","虚构库存合同订单","lines",List.of(Map.of("sku_id","1001","expected_units","20"))));return json.valueToTree(production.command(context,"orders",null,"create",b.path("operation_token").asText(),b));}
    JsonNode ship(JsonNode order,String amount){var b=body(Map.of("save_mode","confirm","dispatch_purpose","OUTWARD_ORDER","business_date","2026-10-14","manual_source_note","虚构独立发货","overage_reason","真实数量演练","sources",List.of(Map.of("sku_id","1001","actual_units",amount,"allocations",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"units",amount))))));return json.valueToTree(production.command(context,"shipments",null,"create",b.path("operation_token").asText(),b));}
    JsonNode shipPlan(JsonNode order,String amount,String planId){var b=body(Map.of("save_mode","confirm","dispatch_purpose","OUTWARD_ORDER","warehouse_id","1","business_date","2026-10-14","manual_source_note","虚构计划关联发货","overage_reason","真实数量演练","sources",List.of(Map.of("sku_id","1001","plan_id",planId,"actual_units",amount,"allocations",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"units",amount))))));return json.valueToTree(production.command(context,"shipments",null,"create",b.path("operation_token").asText(),b));}
    JsonNode outPlan(String amount){return command("plans",Map.of("warehouse_id","1","sku_id","1001","direction","OUT","planned_on","2026-10-20","units",amount,"source_reference","虚构销售出库安排","reason","预计销售发货"));}
    String completed(String planId){return db.queryForObject("SELECT completed_units FROM inventory_plan WHERE site_id=? AND id=?",String.class,context.site(),planId);}
    @Test void loanAndConsumptionCannotUseFutureStockForDispatch(){
        opening("10");var loan=movement("OUT","7","BORROW");assertEquals("3",availability().path("free_available_units").asText());assertEquals("7",availability().path("loan_outstanding_units").asText());
        var order=order();assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->ship(order,"7")).code);assertEquals("3",availability().path("on_hand_units").asText());
        ship(order,"3");assertEquals("0",availability().path("free_available_units").asText());
        String loanId=loan.path("loan_ids").get(0).asText();movement("IN",Map.of("sku_id","1001","quality","PENDING","units","2","purpose","RETURN","loan_id",loanId));
        assertEquals("2",availability().path("on_hand_units").asText());assertEquals("0",availability().path("free_available_units").asText());assertEquals("5",availability().path("loan_outstanding_units").asText());
        assertEquals("return_exceeds_outstanding",assertThrows(ProductionError.class,()->movement("IN",Map.of("sku_id","1001","quality","QUALIFIED","units","6","purpose","RETURN","loan_id",loanId))).code);
        command("loans/"+loanId+"/settle",Map.of("expected_revision","2","units","5","reason","虚构在外转消耗"));assertEquals("2",availability().path("on_hand_units").asText());
    }
    @Test void reservationsAndHoldsExplainOwnAllowanceAndShortage(){
        opening("10");var order=order();String line=order.path("lines").get(0).path("id").asText();
        command("reservations",Map.of("warehouse_id","1","owner_id","1","sku_id","1001","order_line_id",line,"units","8","expected_balance_revision",availability().path("revision").asText(),"reason","虚构预留"));
        assertEquals("2",availability().path("free_available_units").asText());assertEquals("10",json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id","1","sku_id","1001","order_line_id",line))).path("dispatch_allowed_units").asText());
        movement("ADJUST",Map.of("sku_id","1001","quality","QUALIFIED","units","3","purpose","COUNT","counted_on","2026-10-14","evidence","虚构实盘3"));
        assertEquals("shortage",availability().path("state").asText());assertTrue(availability().path("free_available_units").isNull());assertEquals("stock_shortage",assertThrows(ProductionError.class,()->ship(order,"3")).code);
    }
    @Test void repeatedOpeningAndReplayNeverChangeBalancesTwice(){
        opening("10");assertEquals("opening_exists",assertThrows(ProductionError.class,()->opening("10")).code);
        var draft=command("documents",Map.of("warehouse_id","1","kind","OUT","business_date","2026-10-14","reason","虚构消耗","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","7","purpose","CONSUME"))));
        var b=body(Map.of("expected_revision",draft.path("revision").asText()));String path="documents/"+draft.path("id").asText()+"/confirm";
        assertEquals(json.valueToTree(stock.command(context,path,b,b.path("operation_token").asText())),json.valueToTree(stock.command(context,path,b,b.path("operation_token").asText())));assertEquals("3",availability().path("on_hand_units").asText());
    }
    @Test void simultaneousBorrowAndDispatchCannotOverspend() throws Exception {
        opening("10");var order=order();var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)){
            var a=pool.submit(()->{start.await();try{movement("OUT","7","CONSUME");return true;}catch(ProductionError e){return false;}});
            var b=pool.submit(()->{start.await();try{ship(order,"7");return true;}catch(ProductionError e){return false;}});
            start.countDown();assertNotEquals(a.get(15,TimeUnit.SECONDS),b.get(15,TimeUnit.SECONDS));
        } assertEquals("3",availability().path("on_hand_units").asText());
    }
    @Test void wrongRoleAndSiteAndUnknownAreNotZero(){
        assertEquals("not_ready",availability().path("state").asText());assertTrue(availability().path("free_available_units").isNull());opening("10");
        var viewer=new ProductionContext(context.site(),2,Set.of("viewer"),"contract.viewer");var b=body(Map.of());assertEquals("role_forbidden",assertThrows(ProductionError.class,()->stock.command(viewer,"documents",b,b.path("operation_token").asText())).code);
        assertEquals("not_ready",json.valueToTree(stock.read(new ProductionContext(context.site()+1_000_000,1,Set.of("admin")),"availability",Map.of("warehouse_id","1","sku_id","1001"))).path("state").asText());
    }
    static String futureDate(int days){return java.time.LocalDate.now(java.time.ZoneOffset.UTC).plusDays(days).toString();}
    static String forecastDate(){return java.time.LocalDate.now(java.time.ZoneOffset.UTC).plusDays(30).toString();}
    @Test void forecastUsesRemainingPlansAndDoesNotDoubleCountReservations(){
        opening("10");var loan=movement("OUT",Map.of("sku_id","1001","quality","QUALIFIED","units","7","purpose","BORROW","borrower","借用对象","due_on",futureDate(20)));String id=loan.path("loan_ids").get(0).asText();
        var f=json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate())));assertEquals("10",f.path("items").get(0).path("projected_on_hand_units").asText());
        movement("IN",Map.of("sku_id","1001","quality","PENDING","units","2","purpose","RETURN","loan_id",id));
        f=json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate())));assertEquals("10",f.path("items").get(0).path("projected_on_hand_units").asText());assertEquals("5",f.path("items").get(0).path("plans").get(0).path("remaining_units").asText());
        command("loans/"+id+"/settle",Map.of("expected_revision","2","units","3","reason","在外3件转消耗"));f=json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate())));assertEquals("7",f.path("items").get(0).path("projected_on_hand_units").asText());
        var receipt=command("plans",Map.of("warehouse_id","1","sku_id","1001","direction","IN","planned_on",futureDate(20),"units","4","source_reference","虚构生产收货安排","reason","明确到货安排"));
        movement("IN",Map.of("sku_id","1001","quality","QUALIFIED","units","1","purpose","RECEIPT","plan_id",receipt.path("id").asText()));
        command("plans/"+receipt.path("id").asText()+"/cancel",Map.of("expected_revision","2","units","2","reason","取消两件"));f=json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate())));assertEquals("9",f.path("items").get(0).path("projected_on_hand_units").asText());assertEquals("4",availability().path("free_available_units").asText());
    }
    @Test void linkedShipmentCompletesPlanOnlyWithConfirmedActualAndRestoresOnCorrectionAndVoid(){
        opening("10");var plan=outPlan("7");var order=order();String planId=plan.path("id").asText(),line=order.path("lines").get(0).path("id").asText();
        var draftBody=body(Map.of("save_mode","draft","dispatch_purpose","OUTWARD_ORDER","warehouse_id","1","business_date","2026-10-14","manual_source_note","虚构计划草稿","sources",List.of(Map.of("sku_id","1001","plan_id",planId,"actual_units","3","allocations",List.of(Map.of("order_line_id",line,"units","3"))))));
        var draft=json.valueToTree(production.command(context,"shipments",null,"create",draftBody.path("operation_token").asText(),draftBody));assertEquals("0",completed(planId));assertEquals("10",availability().path("on_hand_units").asText());
        var confirm=body(Map.of("expected_revision",draft.path("revision").asText(),"warehouse_id","1"));var shipment=json.valueToTree(production.command(context,"shipments",Long.parseLong(draft.path("id").asText()),"confirm",confirm.path("operation_token").asText(),confirm));
        assertEquals("3",completed(planId));assertEquals("7",availability().path("on_hand_units").asText());assertEquals(planId,shipment.path("sources").get(0).path("plan_id").asText());
        var source=shipment.path("sources").get(0);var correct=body(Map.of("expected_revision",shipment.path("revision").asText(),"reason","实际只发两件","dispatch_purpose","OUTWARD_ORDER","warehouse_id","1","business_date","2026-10-14","manual_source_note","虚构计划草稿","sources",List.of(Map.of("id",source.path("id").asText(),"sku_id","1001","plan_id",planId,"actual_units","2","allocations",List.of(Map.of("order_line_id",line,"units","2"))))));
        var changed=json.valueToTree(production.command(context,"shipments",Long.parseLong(shipment.path("id").asText()),"correct",correct.path("operation_token").asText(),correct));assertEquals("2",completed(planId));assertEquals("8",availability().path("on_hand_units").asText());
        var voidBody=body(Map.of("expected_revision",changed.path("revision").asText(),"reason","虚构发货作废"));production.command(context,"shipments",Long.parseLong(shipment.path("id").asText()),"void",voidBody.path("operation_token").asText(),voidBody);assertEquals("0",completed(planId));assertEquals("10",availability().path("on_hand_units").asText());
    }
    @Test void linkedShipmentRejectsOverCompletionWithoutPartialStockOrOrderChange(){
        opening("10");var plan=outPlan("3");var order=order();String planId=plan.path("id").asText();
        assertEquals("plan_completion_exceeded",assertThrows(ProductionError.class,()->shipPlan(order,"4",planId)).code);
        assertEquals("0",completed(planId));assertEquals("10",availability().path("on_hand_units").asText());assertEquals("0",production.get(context,"orders",Long.parseLong(order.path("id").asText())).get("actual_units").toString());
        var shipment=shipPlan(order,"2",planId);assertEquals("2",completed(planId));assertEquals("8",availability().path("on_hand_units").asText());
        var same=json.valueToTree(production.get(context,"shipments",Long.parseLong(shipment.path("id").asText())));assertEquals(planId,same.path("sources").get(0).path("plan_id").asText());
    }
    @Test void concurrentShipmentsCannotBothCompleteTheSameRemainingPlan() throws Exception {
        opening("10");var plan=outPlan("3");var order=order();String planId=plan.path("id").asText();var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)){
            var first=pool.submit(()->{start.await();try{shipPlan(order,"2",planId);return "saved";}catch(ProductionError e){return e.code;}});
            var second=pool.submit(()->{start.await();try{shipPlan(order,"2",planId);return "saved";}catch(ProductionError e){return e.code;}});
            start.countDown();assertEquals(Set.of("saved","plan_completion_exceeded"),Set.of(first.get(15,TimeUnit.SECONDS),second.get(15,TimeUnit.SECONDS)));
        }
        assertEquals("2",completed(planId));assertEquals("8",availability().path("on_hand_units").asText());
    }
    @Test void qualityScrapAndSourceProjectionStayConsistent(){
        opening("10");movement("MOVE",Map.of("sku_id","1001","quality","QUALIFIED","target_quality","DEFECTIVE","units","2","purpose","QUALITY","location_from","A1","location_to","待处理区"));assertEquals("10",availability().path("on_hand_units").asText());assertEquals("8",availability().path("free_available_units").asText());
        movement("OUT",Map.of("sku_id","1001","quality","DEFECTIVE","units","1","purpose","SCRAP"));assertEquals("9",availability().path("on_hand_units").asText());assertEquals("8",availability().path("free_available_units").asText());
        assertEquals("quality_not_dispatchable",assertThrows(ProductionError.class,()->movement("OUT",Map.of("sku_id","1001","quality","DEFECTIVE","units","1","purpose","CONSUME"))).code);
        assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->movement("MOVE",Map.of("sku_id","1001","quality","QUALIFIED","target_quality","QUALIFIED","units","20","purpose","LOCATION","location_from","A1","location_to","A2"))).code);
        assertEquals(9L,db.queryForObject("SELECT SUM(delta_units) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
    }
    @Test void shortageCanRecoverByExplicitReleaseAndFrozenStockDoesNotLeaveWarehouse(){
        opening("10");var order=order();var r=command("reservations",Map.of("warehouse_id","1","sku_id","1001","order_line_id",order.path("lines").get(0).path("id").asText(),"units","8","reason","预留八件"));
        var h=command("holds",Map.of("warehouse_id","1","sku_id","1001","units","1","reason","冻结一件"));assertEquals("1",availability().path("free_available_units").asText());assertEquals("10",availability().path("on_hand_units").asText());
        movement("ADJUST",Map.of("sku_id","1001","quality","QUALIFIED","units","3","purpose","COUNT","counted_on","2026-10-14","evidence","实盘三件"));assertTrue(availability().path("free_available_units").isNull());
        command("reservations/"+r.path("id").asText()+"/release",Map.of("expected_revision","1","units","6","reason","处理盘亏预留缺口"));assertEquals("0",availability().path("free_available_units").asText());
        command("holds/"+h.path("id").asText()+"/release",Map.of("expected_revision","1","reason","解除冻结"));assertEquals("1",availability().path("free_available_units").asText());
    }
    @Test void documentCorrectionRetainsEventsAndRejectsConsumedReceiptReversal(){
        opening("10");var take=movement("OUT","7","CONSUME");var fixed=command("documents/"+take.path("id").asText()+"/correct",Map.of("expected_revision",take.path("revision").asText(),"reason","原记录七改六，实物未另外取走","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","6","purpose","CONSUME"))));
        assertEquals("POSTED",fixed.path("status").asText());assertEquals("4",availability().path("on_hand_units").asText());
        var received=movement("IN","2","RECEIPT");movement("OUT","6","CONSUME");assertEquals("0",availability().path("on_hand_units").asText());assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->command("documents/"+received.path("id").asText()+"/reverse",Map.of("expected_revision",received.path("revision").asText(),"reason","入库已被消费"))).code);assertEquals("0",availability().path("on_hand_units").asText());
        var history=json.valueToTree(stock.read(context,"history",Map.of("actor_id","1")));boolean named=false;for(var item:history.path("items"))named|=item.path("actor_name").asText().equals("contract.admin");assertTrue(named);assertTrue(db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site())>5);
    }
    @Test void multiLineFailureAndExpectedBalanceRevisionRollBackWholeCommand(){
        opening("10");var draft=command("documents",Map.of("warehouse_id","1","kind","OUT","business_date","2026-10-14","reason","两行共十一件","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","6","purpose","TAKE"),Map.of("sku_id","1001","quality","QUALIFIED","units","5","purpose","TAKE"))));
        assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->command("documents/"+draft.path("id").asText()+"/confirm",Map.of("expected_revision","1"))).code);assertEquals("10",availability().path("on_hand_units").asText());assertEquals(1L,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
        String revision=availability().path("revision").asText();command("holds",Map.of("warehouse_id","1","sku_id","1001","units","1","expected_balance_revision",revision,"reason","先冻结"));assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->command("holds",Map.of("warehouse_id","1","sku_id","1001","units","1","expected_balance_revision",revision,"reason","旧预览"))).code);
    }
    @Test void shipmentCorrectionChecksExtraStockAndAllocationChangeDoesNotDeductAgain(){
        opening("10");var o=order();var s=ship(o,"7");long id=s.path("id").asLong();
        var b=body(Map.of("expected_revision",s.path("revision").asText(),"reason","七改十一","business_date","2026-10-14","sources",List.of(Map.of("id",s.path("sources").get(0).path("id").asText(),"sku_id","1001","actual_units","11","allocations",List.of(Map.of("order_line_id",o.path("lines").get(0).path("id").asText(),"units","11"))))));assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->production.command(context,"shipments",id,"correct",b.path("operation_token").asText(),b)).code);assertEquals("3",availability().path("on_hand_units").asText());
        var a=body(Map.of("expected_revision",s.path("revision").asText(),"reason","同一分配核对","sources",json.convertValue(s.path("sources"),List.class)));long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());production.command(context,"shipments",id,"allocation-corrections",a.path("operation_token").asText(),a);assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));assertEquals("3",availability().path("on_hand_units").asText());
    }
    @Test void assigningWarehouseShipmentAfterReceiptRetainsBindingsAndInventoryEvents(){
        var profile=body(Map.of("name","QA attribution source","type","OWN","country","CN"));
        String warehouse=json.valueToTree(production.directorySave(context,"warehouses",null,profile.path("operation_token").asText(),profile)).path("id").asText();
        profile=body(Map.of("name","QA attribution destination","type","OWN","country","CN"));
        String destination=json.valueToTree(production.directorySave(context,"warehouses",null,profile.path("operation_token").asText(),profile)).path("id").asText();
        for(String target:List.of(warehouse,destination))command("openings/confirm",Map.of("warehouse_id",target,"owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-ATTR-"+target,"reason","虚构归属测试期初","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units",target.equals(warehouse)?"10":"0"))));
        var order=order();
        var create=new LinkedHashMap<String,Object>();create.putAll(Map.of("save_mode","confirm","dispatch_purpose","WAREHOUSE_DISPATCH","business_date","2026-10-14","warehouse_id",warehouse,"owner_id","1","destination_id",destination,"destination_type","WAREHOUSE","manual_source_note","QA independent stock shipment"));
        create.put("sources",List.of(Map.of("sku_id","1001","actual_units","7","fulfillment_mode","WAREHOUSE_STOCK","allocations",List.of())));
        var input=body(create);var shipment=json.valueToTree(production.command(context,"shipments",null,"create",input.path("operation_token").asText(),input));
        long shipmentId=shipment.path("id").asLong();
        long binding=db.queryForObject("SELECT id FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND is_active=TRUE",Long.class,context.site(),shipmentId);
        var receipt=command("destination-receipts",Map.of("shipment_id",Long.toString(shipmentId),"expected_shipment_revision","1","warehouse_id",destination,"owner_id","1","business_date","2026-10-15","reason","QA received actual goods","lines",List.of(Map.of("binding_id",Long.toString(binding),"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","7","pending_units","0","defective_units","0"))));
        command("destination-receipts/"+receipt.path("id").asText()+"/confirm",Map.of("expected_revision",receipt.path("revision").asText()));
        long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());
        var source=new LinkedHashMap<String,Object>(json.convertValue(shipment.path("sources").get(0),Map.class));
        source.put("allocations",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"units","7")));
        var attribution=body(Map.of("expected_revision","1","reason","QA explicitly confirm order attribution","sources",List.of(source)));
        var changedWarehouse=(tools.jackson.databind.node.ObjectNode)attribution.deepCopy();changedWarehouse.put("warehouse_id",destination);changedWarehouse.put("operation_token",UUID.randomUUID().toString());
        assertEquals("allocation_only",assertThrows(ProductionError.class,()->production.command(context,"shipments",shipmentId,"allocation-corrections",changedWarehouse.path("operation_token").asText(),changedWarehouse)).code);
        production.command(context,"shipments",shipmentId,"allocation-corrections",attribution.path("operation_token").asText(),attribution);
        production.command(context,"shipments",shipmentId,"allocation-corrections",attribution.path("operation_token").asText(),attribution);
        assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
        assertEquals(binding,db.queryForObject("SELECT id FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND is_active=TRUE",Long.class,context.site(),shipmentId));
        assertEquals("7",orderDetail(order).path("actual_units").asText());
        var board=json.valueToTree(production.list(context,"orders","","CONFIRMED","","","","",1,5));
        assertEquals("7",board.path("items").get(0).path("fulfillment_lines").get(0).path("shipped_units").asText());
        assertEquals("7",board.path("items").get(0).path("fulfillment_lines").get(0).path("received_units").asText());
        var linked=json.valueToTree(production.chains(context,Map.of("chain_progress","all")));
        assertEquals("7",linked.path("items").get(0).path("orders").get(0).path("fulfillment_lines").get(0).path("received_units").asText());
        create.put("sources",List.of(Map.of("sku_id","1001","actual_units","1","fulfillment_mode","WAREHOUSE_STOCK","allocations",List.of(Map.of("order_line_id",order.path("lines").get(0).path("id").asText(),"units","1")))));
        var next=body(create);var direct=json.valueToTree(production.command(context,"shipments",null,"create",next.path("operation_token").asText(),next));
        assertEquals("1",direct.path("sources").get(0).path("allocations").get(0).path("units").asText());
        assertEquals("8",orderDetail(order).path("actual_units").asText());

    }
    @Test void mixedWarehouseAndProductionDirectShipmentOnlyDeductsWarehouseLinesAndCanBeCorrected(){
        opening("10");
        var orderBody=body(Map.of("save_mode","confirm","business_date","2026-10-14","manual_source_note","虚构混合来源订单","lines",List.of(Map.of("sku_id","1001","expected_units","4"),Map.of("sku_id","1002","expected_units","30"))));
        var order=json.valueToTree(production.command(context,"orders",null,"create",orderBody.path("operation_token").asText(),orderBody));
        String line1=order.path("lines").get(0).path("id").asText(),line2=order.path("lines").get(1).path("id").asText();
        var shipmentBody=body(Map.of("save_mode","confirm","dispatch_purpose","OUTWARD_ORDER","warehouse_id","1","business_date","2026-10-14","manual_source_note","仓库与生产直发混合装箱","sources",List.of(
            Map.of("sku_id","1001","fulfillment_mode","WAREHOUSE_STOCK","actual_units","4","allocations",List.of(Map.of("order_line_id",line1,"units","4"))),
            Map.of("sku_id","1002","fulfillment_mode","PRODUCTION_DIRECT","actual_units","30","allocations",List.of(Map.of("order_line_id",line2,"units","30")))
        )));
        var shipment=json.valueToTree(production.command(context,"shipments",null,"create",shipmentBody.path("operation_token").asText(),shipmentBody));
        assertEquals("6",availability().path("on_hand_units").asText());
        assertEquals("34",json.valueToTree(production.get(context,"orders",order.path("id").asLong())).path("actual_units").asText());
        assertEquals(1L,db.queryForObject("SELECT COUNT(*) FROM inventory_shipment_position WHERE site_id=? AND shipment_id=? AND units>0",Long.class,context.site(),shipment.path("id").asLong()));
        assertEquals("PRODUCTION_DIRECT",shipment.path("sources").get(1).path("fulfillment_mode").asText());

        var correctedSources=json.createArrayNode();
        for(var source:shipment.path("sources")){
            var value=(tools.jackson.databind.node.ObjectNode)source.deepCopy();
            value.put("fulfillment_mode","PRODUCTION_DIRECT");value.putNull("plan_id");correctedSources.add(value);
        }
        var correction=body(Map.of("expected_revision",shipment.path("revision").asText(),"reason","第一行实际也是生产直发","business_date","2026-10-14","sources",correctedSources));
        var corrected=json.valueToTree(production.command(context,"shipments",shipment.path("id").asLong(),"correct",correction.path("operation_token").asText(),correction));
        assertEquals("10",availability().path("on_hand_units").asText());
        assertEquals("34",json.valueToTree(production.get(context,"orders",order.path("id").asLong())).path("actual_units").asText());
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM inventory_shipment_position WHERE site_id=? AND shipment_id=? AND units>0",Long.class,context.site(),corrected.path("id").asLong()));
    }
    @Test void productionDirectShipmentCannotConsumeAnOutboundPlan(){
        opening("10");var order=order();String planId=outPlan("4").path("id").asText();String line=order.path("lines").get(0).path("id").asText();
        var shipment=body(Map.of("save_mode","confirm","dispatch_purpose","OUTWARD_ORDER","warehouse_id","1","business_date","2026-10-14","manual_source_note","虚构生产直发","sources",List.of(Map.of("sku_id","1001","fulfillment_mode","PRODUCTION_DIRECT","plan_id",planId,"actual_units","4","allocations",List.of(Map.of("order_line_id",line,"units","4"))))));
        assertEquals("direct_shipment_plan_forbidden",assertThrows(ProductionError.class,()->production.command(context,"shipments",null,"create",shipment.path("operation_token").asText(),shipment)).code);
        assertEquals("10",availability().path("on_hand_units").asText());assertEquals("0",completed(planId));
    }
    @Test void draftWarehouseSurvivesConfirmationRatherThanSwitchingToFirstScope(){
        opening("10");command("openings/confirm",Map.of("warehouse_id","2","owner_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-SECOND-"+context.site(),"reason","第二虚构仓","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","9"))));var o=order();
        var b=body(Map.of("save_mode","draft","warehouse_id","2","owner_id","1","dispatch_purpose","OUTWARD_ORDER","business_date","2026-10-14","manual_source_note","第二仓虚构发货","sources",List.of(Map.of("sku_id","1001","actual_units","8","allocations",List.of(Map.of("order_line_id",o.path("lines").get(0).path("id").asText(),"units","8"))))));
        var draft=json.valueToTree(production.command(context,"shipments",null,"create",b.path("operation_token").asText(),b));assertEquals("2",draft.path("warehouse_id").asText());
        b=body(Map.of("expected_revision",draft.path("revision").asText()));production.command(context,"shipments",draft.path("id").asLong(),"confirm",b.path("operation_token").asText(),b);
        assertEquals("10",availability().path("on_hand_units").asText());assertEquals("1",json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id","2","sku_id","1001"))).path("on_hand_units").asText());
    }
    @Test void correctingRecordedShipmentRestoresTheOriginalReservationConsumption(){
        opening("10");var o=order();command("reservations",Map.of("warehouse_id","1","sku_id","1001","order_line_id",o.path("lines").get(0).path("id").asText(),"units","8","reason","明确预留八件"));var s=ship(o,"7");assertEquals("1",availability().path("reserved_units").asText());
        var b=body(Map.of("expected_revision",s.path("revision").asText(),"reason","录错七件，实际五件","business_date","2026-10-14","sources",List.of(Map.of("id",s.path("sources").get(0).path("id").asText(),"sku_id","1001","actual_units","5","allocations",List.of(Map.of("order_line_id",o.path("lines").get(0).path("id").asText(),"units","5"))))));
        var corrected=json.valueToTree(production.command(context,"shipments",s.path("id").asLong(),"correct",b.path("operation_token").asText(),b));assertEquals("5",availability().path("on_hand_units").asText());assertEquals("3",availability().path("reserved_units").asText());assertEquals("2",availability().path("free_available_units").asText());
        b=body(Map.of("expected_revision",corrected.path("revision").asText(),"reason","虚构录入错误，实物从未发出"));production.command(context,"shipments",s.path("id").asLong(),"void",b.path("operation_token").asText(),b);assertEquals("10",availability().path("on_hand_units").asText());assertEquals("8",availability().path("reserved_units").asText());assertEquals("2",availability().path("free_available_units").asText());
    }
    @Test void excelConfirmationUsesCurrentStockAndCannotSelectStocklessMode() throws Exception {
        opening("10");movement("OUT","7","BORROW");var order=order();
        try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(files.template("shipments","v1")));var out=new java.io.ByteArrayOutputStream()){
            var row=book.getSheetAt(0).createRow(1);var values=List.of("虚构库存文件出货","2026-10-14",order.path("system_number").asText(),"DEMO-SKU-BLUE-M","7","虚构库存合同");for(int i=0;i<values.size();i++)row.createCell(i).setCellValue(values.get(i));book.write(out);
            var preview=json.valueToTree(files.preview(context,"shipments",body(Map.of("file_base64",Base64.getEncoder().encodeToString(out.toByteArray()),"filename","fictional-stock.xlsx","mode","create"))));assertTrue(preview.path("issues").isEmpty());
            var b=body(Map.of("stock_tracked",false));assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->files.confirm(context,preview.path("preview_id").asText(),b.path("operation_token").asText(),b)).code);assertEquals("3",availability().path("on_hand_units").asText());assertEquals("0",json.valueToTree(production.get(context,"orders",order.path("id").asLong())).path("actual_units").asText());
        }
    }
    @Test void failureAfterPostingRollsBackBalanceEventsStatusAndReceipt(){
        opening("10");var draft=command("documents",Map.of("warehouse_id","1","kind","OUT","business_date","2026-10-14","reason","测试落库中途故障","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","7","purpose","CONSUME"))));
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,operation_token,reason,after_value) VALUES(?,'stock',?,2,1,?,'TEST_COLLISION','{}')",context.site(),draft.path("id").asLong(),UUID.randomUUID().toString());var b=body(Map.of("expected_revision","1"));
        assertThrows(org.springframework.dao.DataIntegrityViolationException.class,()->stock.command(context,"documents/"+draft.path("id").asText()+"/confirm",b,b.path("operation_token").asText()));assertEquals("10",availability().path("on_hand_units").asText());assertEquals(1L,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));assertEquals("DRAFT",json.valueToTree(stock.read(context,"documents/"+draft.path("id").asText(),Map.of())).path("status").asText());assertEquals("command_result_unknown",assertThrows(ProductionError.class,()->production.commandResult(context,b.path("operation_token").asText())).code);
    }
    JsonNode correction(JsonNode doc,List<Map<String,Object>> lines){
        String path="documents/"+doc.path("id").asText();
        var input=new LinkedHashMap<String,Object>(Map.of("expected_revision",doc.path("revision").asText(),"mode","correct","reason","独立虚构原记录更正","lines",lines));
        long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());var before=availability();
        var preview=command(path+"/preview",input);assertEquals(before,availability());assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
        input.put("preview_hash",preview.path("preview_hash").asText());var corrected=command(path+"/correct",input);assertEquals("POSTED",corrected.path("status").asText());return corrected;
    }
    @Test void postedCorrectionPreviewHashRejectsStaleStockAndReplayDoesNotReapply(){
        opening("10");var taken=movement("OUT","7","CONSUME");String path="documents/"+taken.path("id").asText();
        var input=new LinkedHashMap<String,Object>(Map.of("expected_revision",taken.path("revision").asText(),"mode","correct","reason","七件录错为六件","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","6","purpose","CONSUME"))));
        var preview=command(path+"/preview",input);assertEquals("3",availability().path("on_hand_units").asText());assertEquals("1",preview.path("changes").get(0).path("delta_units").asText());assertEquals(1,preview.path("changes").size());
        command("holds",Map.of("warehouse_id","1","sku_id","1001","units","1","reason","预览后冻结一件"));input.put("preview_hash",preview.path("preview_hash").asText());
        assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->command(path+"/correct",input)).code);assertEquals("3",availability().path("on_hand_units").asText());
        input.remove("preview_hash");preview=command(path+"/preview",input);input.put("preview_hash",preview.path("preview_hash").asText());var b=body(input);String token=b.path("operation_token").asText();
        var result=json.valueToTree(stock.command(context,path+"/correct",b,token));assertEquals("POSTED",result.path("status").asText());assertEquals("4",availability().path("on_hand_units").asText());
        long events=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site());assertEquals(result,json.valueToTree(stock.command(context,path+"/correct",b,token)));assertEquals(events,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,context.site()));
    }
    @Test void correctedBorrowRetainsLoanIdentityAndUpdatesItsSkuAndForecast(){
        command("openings/confirm",Map.of("warehouse_id","1","cutoff_on","2026-10-01","source_reference","FICTIONAL-TWO-SKUS-"+context.site(),"reason","独立虚构双SKU期初","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","10"),Map.of("sku_id","1002","quality","QUALIFIED","units","10"))));
        var borrowed=movement("OUT",Map.of("sku_id","1001","quality","QUALIFIED","units","7","purpose","BORROW","borrower","借用人甲","due_on",futureDate(20)));String loan=borrowed.path("loan_ids").get(0).asText();
        var newLines=List.<Map<String,Object>>of(Map.of("sku_id","1002","quality","QUALIFIED","units","6","purpose","BORROW","borrower","借用人乙","due_on",futureDate(21)));
        var input=new LinkedHashMap<String,Object>(Map.of("expected_revision",borrowed.path("revision").asText(),"mode","correct","reason","更正借出SKU","lines",newLines));var preview=command("documents/"+borrowed.path("id").asText()+"/preview",input);
        command("loans/"+loan+"/reschedule",Map.of("expected_revision","1","due_on",futureDate(22),"reason","更正预览后修改归还日"));input.put("preview_hash",preview.path("preview_hash").asText());
        assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->command("documents/"+borrowed.path("id").asText()+"/correct",input)).code);
        var corrected=correction(borrowed,newLines);assertEquals(loan,corrected.path("loan_ids").get(0).asText());assertEquals("10",availability().path("on_hand_units").asText());
        var second=json.valueToTree(stock.read(context,"availability",Map.of("warehouse_id","1","sku_id","1002")));assertEquals("4",second.path("on_hand_units").asText());assertEquals("6",second.path("loan_outstanding_units").asText());
        assertEquals("1002",db.queryForObject("SELECT sku_id FROM inventory_loan WHERE site_id=? AND id=?",String.class,context.site(),loan));assertEquals("借用人乙",db.queryForObject("SELECT borrower FROM inventory_loan WHERE site_id=? AND id=?",String.class,context.site(),loan));
        assertEquals("1002",db.queryForObject("SELECT sku_id FROM inventory_plan WHERE site_id=? AND loan_id=?",String.class,context.site(),loan));
        var forecast=json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate())));for(var item:forecast.path("items"))assertEquals("10",item.path("projected_on_hand_units").asText());
    }
    @Test void partialReturnAndCompletedReceiptCorrectionsKeepRelationsAndNetStock(){
        opening("10");var borrowed=movement("OUT",Map.of("sku_id","1001","quality","QUALIFIED","units","7","purpose","BORROW","borrower","虚构借用人","due_on",futureDate(20)));String loan=borrowed.path("loan_ids").get(0).asText();
        var returned=movement("IN",Map.of("sku_id","1001","quality","PENDING","units","2","purpose","RETURN","loan_id",loan));
        returned=correction(returned,List.of(Map.of("sku_id","1001","quality","PENDING","units","3","purpose","RETURN","loan_id",loan)));assertEquals("6",availability().path("on_hand_units").asText());assertEquals("3",availability().path("free_available_units").asText());assertEquals("4",availability().path("loan_outstanding_units").asText());
        assertEquals("10",json.valueToTree(stock.read(context,"forecast",Map.of("as_of",forecastDate()))).path("items").get(0).path("projected_on_hand_units").asText());
        command("documents/"+returned.path("id").asText()+"/reverse",Map.of("expected_revision",returned.path("revision").asText(),"reason","虚构归还录入错误"));assertEquals("3",availability().path("on_hand_units").asText());assertEquals("7",availability().path("loan_outstanding_units").asText());
        var plan=command("plans",Map.of("warehouse_id","1","sku_id","1001","direction","IN","planned_on",futureDate(20),"units","4","source_reference","虚构收货安排","reason","安排四件"));String planId=plan.path("id").asText();
        var receipt=movement("IN",Map.of("sku_id","1001","quality","QUALIFIED","units","2","purpose","RECEIPT","plan_id",planId));movement("OUT","5","CONSUME");assertEquals("0",availability().path("on_hand_units").asText());
        receipt=correction(receipt,List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","3","purpose","RECEIPT","plan_id",planId)));assertEquals("1",availability().path("on_hand_units").asText());
        assertEquals("3",db.queryForObject("SELECT completed_units FROM inventory_plan WHERE site_id=? AND id=?",String.class,context.site(),planId));
        correction(receipt,List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","3","purpose","RECEIPT","plan_id",planId)));assertEquals("1",availability().path("on_hand_units").asText());assertEquals("3",db.queryForObject("SELECT completed_units FROM inventory_plan WHERE site_id=? AND id=?",String.class,context.site(),planId));
    }
    @Test void oldStocktakeCannotOverwriteNewerFacts(){
        opening("10");movement("OUT","7","TAKE");assertEquals("stocktake_cutoff_stale",assertThrows(ProductionError.class,()->movement("ADJUST",Map.of("sku_id","1001","quality","QUALIFIED","units","10","purpose","COUNT","counted_on","2026-10-12","evidence","旧盘点不能覆盖十四日取走事实"))).code);assertEquals("3",availability().path("on_hand_units").asText());
    }
}
