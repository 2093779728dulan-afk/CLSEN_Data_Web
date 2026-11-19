package com.clsen.dataweb.production;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
class FbaUnifiedReceiptsDatabaseTest {
    static JdbcTemplate db;
    static TransactionTemplate tx;
    static ObjectMapper json;
    InventoryService inventory;
    ProductionContext actor;
    long site,scope,shipment,binding,secondBinding;
    static final Map<String,Object> CATALOG=Map.of( "1001",Map.of("sku_id","1001","style_id","2001","code","SIM-BLACK-L","label","SIM-BLACK-L","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"), "1002",Map.of("sku_id","1002","style_id","2001","code","SIM-BLACK-M","label","SIM-BLACK-M","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"));
    @BeforeAll static void connect() {
        String url=System.getenv("FBA_TEST_JDBC_URL");
        if(url==null||!url.startsWith("jdbc:mysql://127.0.0.1:")||!url.contains("/clsen_fba_contract?"))throw new IllegalStateException("Explicit owned FBA test schema required");
        Flyway.configure().dataSource(url,System.getenv("FBA_TEST_MIGRATION_USER"),System.getenv("FBA_TEST_MIGRATION_PASSWORD")).load().migrate();
        var source=new DriverManagerDataSource(url,System.getenv("FBA_TEST_RUNTIME_USER"),System.getenv("FBA_TEST_RUNTIME_PASSWORD"));
        db=new JdbcTemplate(source);
        tx=new TransactionTemplate(new DataSourceTransactionManager(source));
        json=new ObjectMapper();
    }
    @BeforeEach void setup()throws Exception {
        site=2_000_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L);
        actor=new ProductionContext(site,1,Set.of("data_manager"),"SIMULATED unified receipt test");
        inventory=new InventoryService(db,json,"demo_fixed");
        var enabled=InventoryService.class.getDeclaredField("fbaEnabled");
        enabled.setAccessible(true);
        enabled.setBoolean(inventory,true);
        tx.executeWithoutResult(t-> {
            db.update("INSERT INTO production_warehouse(site_id,id,name,type,country,profile) VALUES(?,2,'SIM FBA','FBA','US',?)",site,"{\"seller_account\":\"SIM\",\"marketplace\":\"amazon_us\"}");
            db.update("INSERT INTO production_shipment(site_id,system_number,status,destination_id,destination_type,owner_id,cartons) VALUES(?,'SIM-SHIP','CONFIRMED',2,'FBA',1,'[]')",site);
            shipment=last();
            binding=source(1001,100);
            secondBinding=source(1002,20);
        });
        var init=new LinkedHashMap<String,Object>();
        init.putAll(Map.of("warehouse_id","2","owner_id","1","owner_name","SIM owner","seller_account","SIM","marketplace","amazon_us","report_source_scope_id","1","store_evidence","SIM store","cutoff_on","2026-10-01","reason","SIM explicit zero opening"));
        init.putAll(Map.of("explicit_zero_opening",true,"simulated",true,"_fba_scope",Map.of("id","1","seller_account","SIM","marketplace","amazon_us"),"_fba_identities",Map.of("1001",Map.of("seller_sku","SIM-BLACK-L","match",Base64.getEncoder().encodeToString("SIM-BLACK-L".getBytes())),"1002",Map.of("seller_sku","SIM-BLACK-M","match",Base64.getEncoder().encodeToString("SIM-BLACK-M".getBytes()))),"identities",List.of(Map.of("sku_id","1001","seller_sku","SIM-BLACK-L","fnsku","SIM-FN1","asin","SIM-AS1","reason","SIM identity"),Map.of("sku_id","1002","seller_sku","SIM-BLACK-M","fnsku","SIM-FN2","asin","SIM-AS2","reason","SIM identity"))));
        scope=call("fba-scopes",init).path("scopes").get(0).path("id").asLong();
        assertEquals(2,db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND tracked=TRUE",Long.class,site,scope));
        call("fba-tracking",Map.of("scope_id",scope,"expected_revision","1","sku_ids",List.of("1001","1002"),"reason","SIM tracked"));
        reference();
    }
    long last() {
        return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
    }
    long source(long sku,long units) {
        db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,?,'SIM','DEMO_LOCAL_ONLY-v1',?)",site,shipment,sku,units);
        long source=last();
        db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,'',?,?,1,1,'SIM','SIM source')",site,shipment,source,sku,units);
        return last();
    }
    JsonNode body(Map<String,?> values) {
        var result=(tools.jackson.databind.node.ObjectNode)json.valueToTree(values);
        for(var entry:values.entrySet())if(entry.getValue() instanceof Number)result.put(entry.getKey(),entry.getValue().toString());
        result.put("operation_token",UUID.randomUUID().toString());
        result.set("_catalog",json.valueToTree(CATALOG));
        if(result.path("draft_payload").isObject()&&!result.path("draft_payload").has("reference_link_id")){
            var references=db.queryForList("SELECT id FROM fba_reference WHERE site_id=? AND shipment_id=?",site,shipment);
            if(references.size()==1)((tools.jackson.databind.node.ObjectNode)result.path("draft_payload")).put("reference_link_id",references.getFirst().get("id").toString());
        }
        return result;
    }
    JsonNode command(String path,JsonNode value) {
        return json.valueToTree(tx.execute(t->inventory.command(actor,path,value,value.path("operation_token").asText())));
    }
    JsonNode call(String path,Map<String,?> values) {
        return command(path,body(values));
    }
    long balance(long sku) {
        return db.queryForObject("SELECT qualified_units FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=?",Long.class,site,sku);
    }
    long events() {
        return db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=?",Long.class,site);
    }
    Map<String,Object> line(String id,long sku,String quantity,long source) {
        return new LinkedHashMap<>(Map.of("line_id",id,"sku_id",Long.toString(sku),"quantity",quantity,"selected",true,"allocations",quantity.equals("0")?List.of():List.of(Map.of("binding_id",Long.toString(source),"units",quantity))));
    }
    JsonNode draft(List<Map<String,Object>> lines) {
        return call("fba-unified-save",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","draft_payload",Map.of("business_date","2026-11-05","reason","SIM actual warehouse acceptance","lines",lines)));
    }
    JsonNode confirm(JsonNode draft) {
        return call("fba-unified-confirm",Map.of("batch_id",draft.path("id").asText(),"expected_revision",draft.path("revision").asText()));
    }
    void reference() {
        if(db.queryForObject("SELECT COUNT(*) FROM fba_reference WHERE site_id=? AND scope_id=? AND reference_key=?",Long.class,site,scope,"SIM-REF".getBytes())>0)return;
        call("fba-references",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","reference_id","SIM-REF","reason","SIM confirmed platform reference"));
    }
    Map<String,Object> reportRow(int number,String quantity) {
        return Map.of("source_row",number,"raw",Map.of("MSKU","SIM-BLACK-L","FNSKU","SIM-FN1","ASIN","SIM-AS1","Store","SIM store","Country","US","Reference ID","SIM-REF","Event Type","Receipts","Disposition","SELLABLE","Date and Time","2026-11-05T10:00:00-08:00"),"quantity",quantity,"occurred_at","2026-11-05T10:00:00-08:00","business_date","2026-11-05","seller_match",Base64.getEncoder().encodeToString("SIM-BLACK-L".getBytes()),"fingerprint",String.format("%064d",Integer.parseInt(quantity)),"same_file_candidates",List.of());
    }
    JsonNode upload(String file,String quantity) {
        return call("fba-uploads",Map.of("scope_id",scope,"filename",file+".csv","file_base64",Base64.getEncoder().encodeToString(file.getBytes()),"_parsed",Map.of("rows",List.of(reportRow(2,quantity)),"issues",List.of())));
    }
    @Test void originalReportExcessKeepsInventoryAndSourceAllocationSeparate() {
        reference();
        var report=upload("SIM-original-over-receipt","102");
        var decision=new LinkedHashMap<String,Object>(Map.of("source_row","2","decision","NEW","event_key","SIM-original-excess","reason","SIM original report received 102 against 100 shipped","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","100"))));
        var saved=call("fba-batch-save",Map.of("batch_id",report.path("id").asText(),"expected_revision","1","reason","SIM source difference","decisions",List.of(decision)));
        assertEquals("fba_allocation_invalid",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM missing excess decision"))).code);
        assertEquals(0,balance(1001));
        decision.put("source_excess_units","3");
        decision.put("source_excess_reason","SIM original report differs from packing list");
        var wrong=call("fba-batch-save",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"reason","SIM invalid difference","decisions",List.of(decision)));
        assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",wrong.path("id").asText(),"expected_revision",wrong.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM invalid difference")));
        decision.put("source_excess_units","2");
        var valid=call("fba-batch-save",Map.of("batch_id",wrong.path("id").asText(),"expected_revision",wrong.path("revision").asText(),"reason","SIM verified difference","decisions",List.of(decision)));
        var command=body(Map.of("batch_id",valid.path("id").asText(),"expected_revision",valid.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM original receipt quantity remains 102"));
        var posted=command("fba-batch-confirm",command);
        assertEquals(posted,command("fba-batch-confirm",command));
        assertEquals(102,balance(1001));
        assertEquals(100,db.queryForObject("SELECT SUM(units) FROM fba_event_allocation WHERE site_id=? AND binding_id=?",Long.class,site,binding));
        assertEquals(0,balance(1002));
        assertEquals(1,events());
    }
    @Test void missingReferenceKeepsDraftButRequiresExplicitReferenceBeforePosting() {
        db.update("DELETE FROM fba_reference WHERE site_id=?",site);
        var draft=draft(List.of(line("1",1001,"60",binding),line("2",1002,"4",secondBinding),line("3",1002,"0",secondBinding)));
        assertEquals(0,balance(1001));
        assertEquals(0,events());
        var restored=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-batches/"+draft.path("id").asText(),Map.of())));
        assertEquals("60",restored.path("draft_payload").path("lines").get(0).path("quantity").asText());
        var payload=body(Map.of("batch_id",draft.path("id").asText(),"expected_revision",draft.path("revision").asText()));
        var missingCommand=payload;
        assertEquals("fba_reference_required",assertThrows(ProductionError.class,()->command("fba-unified-confirm",missingCommand)).code);
        reference();
        var resumed=call("fba-unified-save",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","batch_id",draft.path("id").asText(),"expected_revision",draft.path("revision").asText(),"draft_payload",json.convertValue(restored.path("draft_payload"),Map.class)));
        payload=body(Map.of("batch_id",resumed.path("id").asText(),"expected_revision",resumed.path("revision").asText()));
        var posted=command("fba-unified-confirm",payload);
        assertEquals("64",posted.path("added_units").asText());
        assertEquals(posted,command("fba-unified-confirm",payload));
        assertEquals(60,balance(1001));
        assertEquals(4,balance(1002));
        assertEquals(2,events());
        var fact=db.queryForMap("SELECT reference_id,occurred_at,time_precision,shipment_id,business_date FROM fba_receipt_event WHERE site_id=? AND sku_id=1001",site);
        assertNotNull(fact.get("reference_id"));
        assertNull(fact.get("occurred_at"));
        assertEquals("DAY",fact.get("time_precision"));
        assertEquals(shipment,((Number)fact.get("shipment_id")).longValue());
        var state=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-state",Map.of("warehouse_id","2"))));
        assertEquals("64",state.path("shipment_totals").get(0).path("received_units").asText());
        var over=draft(List.of(line("1",1002,"1",secondBinding),line("2",1001,"41",binding)));
        assertEquals("fba_receipt_exceeds_source",assertThrows(ProductionError.class,()->confirm(over)).code);
        assertEquals(4,balance(1002));
        assertEquals(2,events());
        var viewer=new ProductionContext(site,2,Set.of("viewer"),"SIM viewer");
        var value=body(Map.of("batch_id",over.path("id").asText(),"expected_revision","1"));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(t->inventory.command(viewer,"fba-unified-confirm",value,value.path("operation_token").asText()))).code);
    }
    @ParameterizedTest @CsvSource( {
        "60,60,0","100,60,40","40,0,40"
    }) void reportCoveragePostsOnlyConfirmedNewQuantity(String reportUnits,String linked,String added) {
        confirm(draft(List.of(line("1",1001,"60",binding))));
        long manual=db.queryForObject("SELECT id FROM fba_receipt_event WHERE site_id=?",Long.class,site);
        reference();
        var report=upload("SIM-report",reportUnits);
        var line=line("1",1001,reportUnits,binding);
        line.put("batch_id",report.path("id").asText());
        line.put("source_row","2");
        line.put("receipt_links",linked.equals("0")?List.of():List.of(Map.of("event_id",Long.toString(manual),"units",linked)));
        line.put("independent_occurrence",linked.equals("0"));
        line.put("allocations",added.equals("0")?List.of():List.of(Map.of("binding_id",Long.toString(binding),"units",added)));
        var posted=confirm(draft(List.of(line)));
        assertEquals(added,posted.path("added_units").asText());
        assertEquals(linked,posted.path("linked_units").asText());
        assertEquals(60+Long.parseLong(added),balance(1001));
        var current=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-state",Map.of("warehouse_id","2"))));
        assertEquals(linked.equals("0")?0:1,current.path("receipt_links").size());
        var duplicate=upload("SIM-second-file",reportUnits);
        long original=db.queryForObject("SELECT event_id FROM fba_receipt_resolution WHERE site_id=? AND batch_id=? AND source_row=2",Long.class,site,report.path("id").asLong());
        call("fba-batch-save",Map.of("batch_id",duplicate.path("id").asText(),"expected_revision","1","reason","SIM same platform event","decisions",List.of(Map.of("source_row","2","decision","SAME","existing_event_id",Long.toString(original),"reason","SIM exact report event"))));
        long count=events();
        call("fba-batch-confirm",Map.of("batch_id",duplicate.path("id").asText(),"expected_revision","2","source_rows",List.of("2"),"reason","SIM duplicate evidence only"));
        assertEquals(count,events());
        assertFalse(duplicate.path("rows").get(0).path("existing_candidates").isEmpty());
        if(!linked.equals("0")) {
            var attempted=line("1",1001,"1",binding);
            attempted.put("batch_id",upload("SIM-extra-report","1").path("id").asText());
            attempted.put("source_row","2");
            attempted.put("receipt_links",List.of(Map.of("event_id",Long.toString(manual),"units","1")));
            attempted.put("allocations",List.of());
            var bad=draft(List.of(attempted));
            assertEquals("fba_coverage_invalid",assertThrows(ProductionError.class,()->confirm(bad)).code);
            assertEquals(count,events());
        }
    }
    @Test void importedEditAndManualRowCommitAtomicallyWithImmutableSource() {
        reference();
        var report=upload("SIM-original-10","10");
        var imported=line("1",1001,"8",binding);
        imported.put("batch_id",report.path("id").asText());
        imported.put("source_row","2");
        var missing=draft(List.of(imported));
        assertThrows(ProductionError.class,()->confirm(missing));
        assertEquals(0,events());
        imported.put("adjustment_reason","SIM actual count eight");
        var posted=confirm(draft(List.of(imported,line("2",1002,"2",secondBinding))));
        assertEquals("10",posted.path("added_units").asText());
        assertEquals(8,balance(1001));
        assertEquals(2,balance(1002));
        var source=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-batches/"+report.path("id").asText(),Map.of())));
        assertEquals("10",source.path("rows").get(0).path("quantity").asText());
        assertEquals("8",source.path("decisions").get(0).path("quantity").asText());
        assertArrayEquals("SIM-original-10".getBytes(),tx.execute(t->inventory.fbaOriginal(actor,report.path("id").asLong())));
    }
    @Test void concurrentDraftsShareTheCurrentSourceCapacity()throws Exception {
        var a=draft(List.of(line("1",1001,"60",binding)));
        var b=draft(List.of(line("1",1001,"60",binding)));
        var start=new CountDownLatch(1);
        var pool=Executors.newFixedThreadPool(2);
        try {
            var futures=List.of(pool.submit(()-> {
                start.await();
                try {
                    confirm(a);
                    return "posted";
                }
                catch(ProductionError ex) {
                    return ex.code;
                }
            }),pool.submit(()-> {
                start.await();
                try {
                    confirm(b);
                    return "posted";
                }
                catch(ProductionError ex) {
                    return ex.code;
                }
            }));
            start.countDown();
            var results=List.of(futures.get(0).get(20,TimeUnit.SECONDS),futures.get(1).get(20,TimeUnit.SECONDS));
            assertTrue(results.contains("posted"));
            assertTrue(results.contains("fba_receipt_exceeds_source"));
            assertEquals(60,balance(1001));
            assertEquals(1,events());
        }
        finally {
            pool.shutdownNow();
        }
    }
    @Test void multiShipmentOriginalRetainsOtherRowsAndRejectsCrossSource() {
        reference();
        var outside=new LinkedHashMap<String,Object>(reportRow(3,"2"));
        var raw=(tools.jackson.databind.node.ObjectNode)json.valueToTree(outside.get("raw"));
        raw.put("Reference ID","OTHER-REF");
        outside.put("raw",raw);
        var report=call("fba-uploads",Map.of("scope_id",Long.toString(scope),"filename","SIM-multi.csv","file_base64",Base64.getEncoder().encodeToString("SIM multi original".getBytes()),"_parsed",Map.of("rows",List.of(reportRow(2,"10"),outside),"issues",List.of())));
        var selected=line("1",1001,"10",binding);
        selected.put("batch_id",report.path("id").asText());
        selected.put("source_row","2");
        confirm(draft(List.of(selected)));
        var current=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-batches/"+report.path("id").asText(),Map.of())));
        assertEquals(2,current.path("rows").size());
        assertEquals(1,current.path("resolved").size());
        assertEquals("PARTIAL",current.path("status").asText());
        selected.put("source_row","3");
        selected.put("quantity","2");
        selected.put("allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","2")));
        var wrong=draft(List.of(selected));
        assertThrows(ProductionError.class,()->confirm(wrong));
        assertEquals(10,balance(1001));
    }
    @Test void linkedManualReceiptCorrectionCannotInvalidateReportCoverage() {
        var manualDraft=draft(List.of(line("1",1001,"60",binding)));
        confirm(manualDraft);
        reference();
        long event=db.queryForObject("SELECT id FROM fba_receipt_event WHERE site_id=?",Long.class,site);
        var report=upload("SIM linked evidence","60");
        var selected=line("1",1001,"60",binding);
        selected.put("batch_id",report.path("id").asText());
        selected.put("source_row","2");
        selected.put("allocations",List.of());
        selected.put("receipt_links",List.of(Map.of("event_id",Long.toString(event),"units","60")));
        confirm(draft(List.of(selected)));
        var correction=new LinkedHashMap<String,Object>(reportRow(2,"1"));
        correction.put("quantity","-1");
        correction.put("fingerprint","b".repeat(64));
        var source=call("fba-uploads",Map.of("scope_id",Long.toString(scope),"filename","SIM-negative.csv","file_base64",Base64.getEncoder().encodeToString("SIM negative evidence".getBytes()),"_parsed",Map.of("rows",List.of(correction),"issues",List.of())));
        call("fba-batch-save",Map.of("batch_id",source.path("id").asText(),"expected_revision","1","reason","SIM negative correction","decisions",List.of(Map.of("source_row","2","decision","NEW","event_key","SIM-negative","correction_of","manual-"+manualDraft.path("id").asText()+"-1","reason","SIM correction","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","-1"))))));
        assertEquals("fba_coverage_dependency",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",source.path("id").asText(),"expected_revision","2","source_rows",List.of("2"),"reason","SIM correction blocked by coverage"))).code);
        assertEquals(60,balance(1001));
        assertEquals(1,events());
    }
    @Test void restoredCorrectionRetainsTheFullManualCoverageCapacity() {
        var original=draft(List.of(line("1",1001,"60",binding)));
        confirm(original);
        reference();
        String originalKey="manual-"+original.path("id").asText()+"-1";
        for(var correction:List.of(Map.of("quantity","-1","key","SIM-minus","target",originalKey),Map.of("quantity","1","key","SIM-plus","target","SIM-minus"))) {
            var row=new LinkedHashMap<String,Object>(reportRow(2,"1"));
            row.put("quantity",correction.get("quantity"));
            row.put("fingerprint",correction.get("key").equals("SIM-minus")?"c".repeat(64):"d".repeat(64));
            var report=call("fba-uploads",Map.of("scope_id",Long.toString(scope),"filename","SIM-correction.csv","file_base64",Base64.getEncoder().encodeToString(correction.get("key").getBytes()),"_parsed",Map.of("rows",List.of(row),"issues",List.of())));
            call("fba-batch-save",Map.of("batch_id",report.path("id").asText(),"expected_revision","1","reason","SIM correction evidence","decisions",List.of(Map.of("source_row","2","decision","NEW","event_key",correction.get("key"),"correction_of",correction.get("target"),"independent_occurrence",true,"reason","SIM correction evidence","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units",correction.get("quantity")))))));
            call("fba-batch-confirm",Map.of("batch_id",report.path("id").asText(),"expected_revision","2","source_rows",List.of("2"),"reason","SIM correction evidence"));
        }
        assertEquals(60,balance(1001));
        assertEquals("60",upload("SIM later full report","60").path("rows").get(0).path("receipt_candidates").get(0).path("uncovered_units").asText());
    }

    void removeNewIdentity() {
        db.update("DELETE FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=1002",site,scope);
        db.update("DELETE FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1002",site);
    }
    @Test void automaticallyConnectsReviewedProductWithinDraftTransactionAndReplays() {
        removeNewIdentity();
        var failed=body(Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1",
            "_auto_setup",autoSetup(),"draft_payload",Map.of("business_date","2026-11-05","reason","SIM auto draft",
            "lines",List.of(line("1",1002,"4",secondBinding),line("1",1001,"1",binding)))));
        assertThrows(ProductionError.class,()->command("fba-unified-save",failed));
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=1002",Long.class,site,scope));
        assertEquals(0,events());
        var valid=body(Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1",
            "_auto_setup",autoSetup(),"draft_payload",Map.of("business_date","2026-11-05","reason","SIM auto draft",
            "lines",List.of(line("1",1002,"4",secondBinding)))));
        var saved=command("fba-unified-save",valid);
        ((tools.jackson.databind.node.ObjectNode)valid).remove("_auto_setup");
        assertEquals(saved,command("fba-unified-save",valid));
        assertEquals(0,balance(1002));
        var confirmed=confirm(saved);
        assertEquals("4",confirmed.path("added_units").asText());
        assertEquals(4,balance(1002));
        assertEquals(1,events());
    }
    @Test void failedReceiptRollsBackAutomaticProductSetup() {
        removeNewIdentity();
        var over=draft(List.of(line("1",1002,"21",secondBinding)));
        var input=body(Map.of("batch_id",over.path("id").asText(),"expected_revision",over.path("revision").asText(),"_auto_setup",autoSetup()));
        assertEquals("fba_receipt_exceeds_source",assertThrows(ProductionError.class,()->command("fba-unified-confirm",input)).code);
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=1002",Long.class,site,scope));
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1002",Long.class,site));
        assertEquals(0,events());
    }
    @Test void reportUploadAutomaticallyConnectsReviewedProductWithoutPostingStock() {
        removeNewIdentity();
        var row=new LinkedHashMap<String,Object>(reportRow(2,"6"));
        row.put("raw",Map.of("MSKU","SIM-BLACK-M","FNSKU","SIM-FN2","ASIN","SIM-AS2","Store","SIM store","Country","US","Reference ID","SIM-REF","Event Type","Receipts","Disposition","SELLABLE","Date and Time","2026-11-05T10:00:00-08:00"));
        row.put("seller_match",Base64.getEncoder().encodeToString("SIM-BLACK-M".getBytes()));
        var input=body(Map.of("scope_id",scope,"filename","SIM-first-product.csv","file_base64",Base64.getEncoder().encodeToString("SIM first product source".getBytes()),"_auto_setup",autoSetup(),"_parsed",Map.of("rows",List.of(row),"issues",List.of())));
        var uploaded=command("fba-uploads",input);
        assertEquals("1002",uploaded.path("rows").get(0).path("identity").path("sku_id").asText());
        assertEquals("true",uploaded.path("rows").get(0).path("identity").path("tracked").asText());
        assertEquals(0,balance(1002));
        assertEquals(0,events());
        ((tools.jackson.databind.node.ObjectNode)input).remove("_auto_setup");
        assertEquals(uploaded,command("fba-uploads",input));
    }
    Map<String,Object> autoSetup() {
        var setup=extension();
        setup.put("catalog_version","DEMO_LOCAL_ONLY-v1");
        return setup;
    }
    Map<String,Object> extension() {
        return new LinkedHashMap<>(Map.of("scope_id",Long.toString(scope),"expected_revision",db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,site,scope),
            "store_evidence","SIM store","explicit_zero_opening",true,"identities_confirmed",true,"reason","SIM connect existing master SKU",
            "_fba_scope",Map.of("id","1","seller_account","SIM"),
            "_fba_identities",Map.of("1002",Map.of("seller_sku","SIM-BLACK-M","match",Base64.getEncoder().encodeToString("SIM-BLACK-M".getBytes()))),
            "identities",List.of(Map.of("sku_id","1002","seller_sku","SIM-BLACK-M","fnsku","SIM-FN2","asin","SIM-AS2","reason","SIM retained source"))));
    }
    @Test void connectsExistingSkuAndResumesTheOriginalReceiptDraft() {
        confirm(draft(List.of(line("1",1001,"10",binding))));
        removeNewIdentity();
        var original=draft(List.of(line("1",1002,"4",secondBinding)));
        assertEquals("fba_not_tracked",assertThrows(ProductionError.class,()->confirm(original)).code);
        var input=body(extension());
        var connected=command("fba-extend-identities",input);
        assertEquals(connected,command("fba-extend-identities",input));
        assertEquals(10,balance(1001)); assertEquals(0,balance(1002)); assertEquals(1,events());
        confirm(original);
        assertEquals(10,balance(1001)); assertEquals(4,balance(1002)); assertEquals(2,events());
    }
    @Test void rejectsUnconfirmedZeroAndRollsBackPartiallyConnectedRows() {
        removeNewIdentity();
        var missing=extension(); missing.put("explicit_zero_opening",false);
        assertEquals("fba_opening_required",assertThrows(ProductionError.class,()->call("fba-extend-identities",missing)).code);
        var conflict=extension();
        var lines=new ArrayList<Object>((List<?>)conflict.get("identities"));
        lines.add(Map.of("sku_id","1001","seller_sku","SIM-BLACK-L","fnsku","SIM-FN1","asin","SIM-AS1","reason","SIM existing"));
        conflict.put("identities",lines);
        conflict.put("_fba_identities",Map.of("1001",Map.of("seller_sku","SIM-BLACK-L","match",Base64.getEncoder().encodeToString("SIM-BLACK-L".getBytes())),"1002",Map.of("seller_sku","SIM-BLACK-M","match",Base64.getEncoder().encodeToString("SIM-BLACK-M".getBytes()))));
        assertEquals("fba_identity_exists",assertThrows(ProductionError.class,()->call("fba-extend-identities",conflict)).code);
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=1002",Long.class,site,scope));
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1002",Long.class,site));
        var stale=extension(); stale.put("expected_revision","1");
        assertEquals("fba_revision_conflict",assertThrows(ProductionError.class,()->call("fba-extend-identities",stale)).code);
        var viewer=new ProductionContext(site,2,Set.of("viewer"),"SIM viewer");
        var input=body(extension());
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(t->inventory.command(viewer,"fba-extend-identities",input,input.path("operation_token").asText()))).code);
    }

    JsonNode classificationState() {
        return json.valueToTree(tx.execute(t->inventory.read(actor,"fba-state",Map.of("warehouse_id","2"))));
    }
    JsonNode classification() { return classificationState().path("classification_summary").path(Long.toString(scope)); }
    long scopeRevision() { return db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,site,scope); }
    JsonNode adjust(String target,List<Map<String,Object>> lines) {
        return call("fba-quality",Map.of("scope_id",scope,"expected_revision",scopeRevision(),"from_quality",target.equals("DEFECTIVE")?"QUALIFIED":"DEFECTIVE","target_quality",target,"business_date","2026-11-06","reason","SIM physical check","lines",lines));
    }
    JsonNode correct(JsonNode origin,String target,String quantity) {
        return call("fba-classification-correct",Map.of("scope_id",scope,"expected_revision",scopeRevision(),"sku_id",origin.path("sku_id").asText(),"origin_event_id",origin.path("origin_event_id").asText(),"from_reason",origin.path("reason_code").asText(),"reason_code",target,"units",quantity,"reason","SIM verified classification"));
    }
    @Test void classificationsConserveBalancesRestoreByReasonAndRollbackInvalidBatches() throws Exception {
        confirm(draft(List.of(line("1",1001,"20",binding),line("2",1002,"5",secondBinding))));
        adjust("DEFECTIVE",List.of(Map.of("sku_id","1001","units","3","reason_code","WAREHOUSE_DAMAGED"),Map.of("sku_id","1002","units","2","reason_code","DEFECTIVE")));
        adjust("DEFECTIVE",List.of(Map.of("sku_id","1001","units","2","reason_code","CUSTOMER_DAMAGED")));
        assertTrue(classification().path("ready").asBoolean());
        assertEquals("3",classification().path("totals").path("WAREHOUSE_DAMAGED").asText());
        assertThrows(ProductionError.class,()->adjust("QUALIFIED",List.of(Map.of("sku_id","1001","units","1"))));
        adjust("QUALIFIED",List.of(Map.of("sku_id","1001","units","1","reason_allocations",List.of(Map.of("reason_code","CUSTOMER_DAMAGED","units","1")))));
        assertEquals("1",classification().path("totals").path("CUSTOMER_DAMAGED").asText());
        assertThrows(ProductionError.class,()->adjust("QUALIFIED",List.of(Map.of("sku_id","1001","units","2","reason_allocations",List.of(Map.of("reason_code","CUSTOMER_DAMAGED","units","2"))))));
        long before=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site);
        assertThrows(ProductionError.class,()->adjust("DEFECTIVE",List.of(Map.of("sku_id","1001","units","1","reason_code","OTHER"),Map.of("sku_id","1002","units","1","reason_code","WRONG"))));
        assertEquals(before,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site));
        var origin=classification().path("items").get(0);
        correct(origin,"CARRIER_DAMAGED","1");
        assertEquals(before,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site));
        assertEquals("1",classification().path("totals").path("CARRIER_DAMAGED").asText());
        var details=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-classifications",Map.of("scope_id",Long.toString(scope),"view","history","page_size","2"))));
        assertEquals(2,details.path("items").size());assertTrue(details.path("total").asInt()>2);
        var command=body(Map.of("scope_id",scope,"expected_revision",scopeRevision(),"from_quality","QUALIFIED","target_quality","DEFECTIVE","business_date","2026-11-06","reason","SIM idempotent","lines",List.of(Map.of("sku_id","1001","units","1","reason_code","DEFECTIVE"))));
        assertEquals(command("fba-quality",command),command("fba-quality",command));
        var viewer=new ProductionContext(site,2,Set.of("viewer"),"SIM viewer");
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(t->inventory.command(viewer,"fba-quality",command,command.path("operation_token").asText()))).code);
        var other=new ProductionContext(site+1,2,Set.of("viewer"),"SIM other site");
        assertThrows(ProductionError.class,()->tx.execute(t->inventory.read(other,"fba-classifications",Map.of("scope_id",Long.toString(scope)))));
        var gate=new CountDownLatch(1);long revision=scopeRevision();
        try(var pool=Executors.newFixedThreadPool(2)) {
            var tasks=new ArrayList<Future<Boolean>>();
            for(int i=0;i<2;i++)tasks.add(pool.submit(()-> {gate.await();try {call("fba-quality",Map.of("scope_id",scope,"expected_revision",revision,"from_quality","QUALIFIED","target_quality","DEFECTIVE","business_date","2026-11-06","reason","SIM concurrent classification","lines",List.of(Map.of("sku_id","1001","units","1","reason_code","DEFECTIVE"))));return true;}catch(ProductionError e){assertEquals("fba_revision_conflict",e.code);return false;}}));
            gate.countDown();assertNotEquals(tasks.get(0).get(20,TimeUnit.SECONDS),tasks.get(1).get(20,TimeUnit.SECONDS));
        }
        var current=classification();long sum=0;for(var value:current.path("totals"))sum+=value.asLong();
        assertEquals(db.queryForObject("SELECT SUM(defective_units) FROM inventory_balance WHERE site_id=?",Long.class,site),sum);
    }
    @Test void reportReasonChangesAndQuantityRevisionsPreserveManualDecisions() {
        var returned=new LinkedHashMap<String,Object>(Map.of("sku_id","1001","units","3","quality","DEFECTIVE","reason_code","WAREHOUSE_DAMAGED","raw_disposition","WAREHOUSE_DAMAGED","customer_order_ref","SIM-ORDER","source_event_ref","report-return:SIM","occurred_at","2026-11-06T10:00:00-08:00","report_version_id","101"));
        var sync=new LinkedHashMap<String,Object>(Map.of("scope_id",scope,"_report_source_scope_id","1","_trusted_report_returns",List.of(returned),"_report_set_complete",true,"report_version_ids",List.of("101"),"reason","SIM published actual return"));
        call("fba-report-sync",sync);long count=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site);
        call("fba-report-sync",sync);assertEquals(count,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site));
        returned.put("reason_code","DEFECTIVE");returned.put("raw_disposition","DEFECTIVE");returned.put("report_version_id","102");
        call("fba-report-sync",sync);assertEquals(count,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,site));assertEquals("3",classification().path("totals").path("DEFECTIVE").asText());
        correct(classification().path("items").get(0),"CUSTOMER_DAMAGED","3");
        returned.put("reason_code","CARRIER_DAMAGED");returned.put("raw_disposition","CARRIER_DAMAGED");returned.put("report_version_id","103");returned.put("units","4");
        call("fba-report-sync",sync);
        assertTrue(classification().path("ready").asBoolean(),classification().toString());
        assertEquals("3",classification().path("totals").path("CUSTOMER_DAMAGED").asText());
        assertEquals("1",classification().path("totals").path("CARRIER_DAMAGED").asText());
        assertEquals(1,classification().path("pending").size());
        returned.put("units","5");returned.put("report_version_id","104");call("fba-report-sync",sync);
        assertEquals(1,classification().path("pending").size(),"Superseded report origins must leave the current review queue");
        var review=classification().path("pending").get(0);
        call("fba-classification-correct",Map.of("scope_id",scope,"expected_revision",scopeRevision(),"sku_id","1001","review_id",review.path("id").asText(),"accept_report",false,"reason","SIM retain manual decision"));
        assertTrue(classification().path("pending").isEmpty());
        returned.put("reason_code","WAREHOUSE_DAMAGED");returned.put("raw_disposition","WAREHOUSE_DAMAGED");returned.put("report_version_id","105");
        call("fba-report-sync",sync);review=classification().path("pending").get(0);
        call("fba-classification-correct",Map.of("scope_id",scope,"expected_revision",scopeRevision(),"sku_id","1001","review_id",review.path("id").asText(),"accept_report",true,"reason","SIM accept current original evidence"));
        assertTrue(classification().path("pending").isEmpty());assertEquals("5",classification().path("totals").path("WAREHOUSE_DAMAGED").asText());
        sync.put("_trusted_report_returns",List.of());call("fba-report-sync",sync);assertEquals("0",classification().path("totals").path("WAREHOUSE_DAMAGED").asText());
    }
    @Test void legacyBalancesCanBeClassifiedAndRestoredWithoutInventingStockEvents() {
        db.update("UPDATE inventory_balance SET defective_units=5 WHERE site_id=? AND sku_id=1001",site);
        assertEquals("5",classification().path("totals").path("UNCLASSIFIED").asText());
        correct(classification().path("items").get(0),"DEFECTIVE","2");
        assertEquals("3",classification().path("totals").path("UNCLASSIFIED").asText());
        adjust("QUALIFIED",List.of(Map.of("sku_id","1001","units","2","reason_allocations",List.of(Map.of("reason_code","DEFECTIVE","units","2")))));
        assertEquals("0",classification().path("totals").path("DEFECTIVE").asText());assertEquals(2,balance(1001));
    }

    JsonNode classifiedReceipt(String key,String quantity,String correction) {
        var row=new LinkedHashMap<String,Object>(reportRow(2,quantity));
        var raw=(tools.jackson.databind.node.ObjectNode)json.valueToTree(row.get("raw"));raw.put("Disposition","WAREHOUSE_DAMAGED");row.put("raw",raw);row.put("quality","DEFECTIVE");
        var uploaded=call("fba-uploads",Map.of("scope_id",scope,"filename",key+".csv","file_base64",Base64.getEncoder().encodeToString(key.getBytes()),"_parsed",Map.of("rows",List.of(row),"issues",List.of())));
        var decision=Map.of("source_row","2","decision","NEW","event_key",key,"correction_of",correction,"independent_occurrence",true,"reason","SIM source correction","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units",quantity)));
        var saved=call("fba-batch-save",Map.of("batch_id",uploaded.path("id").asText(),"expected_revision","1","reason","SIM damaged receipt source","decisions",List.of(decision)));
        return call("fba-batch-confirm",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM checked damaged goods"));
    }
    @Test void receiptCorrectionsInheritReasonsAndRetainManualSourceConflicts() {
        reference();classifiedReceipt("SIM-damage","3","");
        assertEquals("3",classification().path("totals").path("WAREHOUSE_DAMAGED").asText());
        correct(classification().path("items").get(0),"CUSTOMER_DAMAGED","3");
        classifiedReceipt("SIM-damage-minus","-2","SIM-damage");
        assertEquals("1",classification().path("totals").path("CUSTOMER_DAMAGED").asText());
        classifiedReceipt("SIM-damage-plus-one","1","SIM-damage-minus");
        classifiedReceipt("SIM-damage-plus-two","1","SIM-damage-minus");
        var result=classification();assertTrue(result.path("ready").asBoolean(),result.toString());
        assertEquals("3",result.path("totals").path("CUSTOMER_DAMAGED").asText());
        assertEquals("0",result.path("totals").path("WAREHOUSE_DAMAGED").asText());assertEquals(2,result.path("pending").size());
    }

    void countSku(long sku,String units,String date) {
        call("fba-stocktake",Map.of("scope_id",scope,"expected_revision",
            new FbaInventoryStore(db,json,inventory).scopeContext(actor,scope) instanceof Map<?,?> value ? value.get("revision").toString() : "",
            "business_date",date,"reason","SIM verified physical snapshot",
            "lines",List.of(Map.of("sku_id",Long.toString(sku),"balance_revision",
                db.queryForObject("SELECT revision FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=?",Long.class,site,sku).toString(),
                "units",units))));
    }
    @Test void snapshotCoveredReceiptAndManualIntakeCannotBeAddedAgain() {
        reference();
        countSku(1001,"0","2026-11-06");
        var report=upload("SIM-snapshot-covered","10");
        assertEquals("SNAPSHOT_COVERED",report.path("rows").get(0).path("posting_block").asText());
        assertEquals("2026-11-06",report.path("rows").get(0).path("snapshot_on").asText());
        var saved=call("fba-batch-save",Map.of("batch_id",report.path("id").asText(),"expected_revision","1","reason","SIM retained review",
            "decisions",List.of(Map.of("source_row","2","decision","NEW","event_key","SIM-covered","reason","SIM must not recount","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","10"))))));
        assertEquals("fba_snapshot_covered",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM blocked"))).code);
        assertEquals("fba_snapshot_covered",assertThrows(ProductionError.class,()->confirm(draft(List.of(line("1",1001,"10",binding))))).code);
        assertEquals(0,balance(1001));assertEquals(0,events());
        // Partial snapshots cannot cover another SKU or another quality.
        var other=confirm(draft(List.of(line("1",1002,"4",secondBinding))));
        assertEquals("4",other.path("added_units").asText());assertEquals(4,balance(1002));
        classifiedReceipt("SIM-damage-not-counted","3","");
        assertEquals(3,db.queryForObject("SELECT defective_units FROM inventory_balance WHERE site_id=? AND sku_id=1001",Long.class,site));
    }
    @Test void ledgerNonReceiptsRemainReviewOnlyEvenWithoutParserIssues() {
        reference();
        var row=new LinkedHashMap<String,Object>(reportRow(2,"10"));
        var raw=(tools.jackson.databind.node.ObjectNode)json.valueToTree(row.get("raw"));raw.put("Event Type","CustomerReturns");row.put("raw",raw);
        var uploaded=call("fba-uploads",Map.of("scope_id",scope,"filename","SIM-return.csv","file_base64",Base64.getEncoder().encodeToString("SIM-return".getBytes()),"_parsed",Map.of("rows",List.of(row),"issues",List.of())));
        assertEquals("CUSTOMER_RETURN",uploaded.path("rows").get(0).path("ledger_kind").asText());
        var saved=call("fba-batch-save",Map.of("batch_id",uploaded.path("id").asText(),"expected_revision","1","reason","SIM cannot use receipt writer",
            "decisions",List.of(Map.of("source_row","2","decision","NEW","event_key","SIM-not-receipt","reason","SIM invalid route","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","10"))))));
        assertEquals("fba_source_issue",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM blocked"))).code);
        assertEquals(0,balance(1001));assertEquals(0,events());
    }

    @Test void originalNegativeReceiptCannotBeChangedToPositiveQuantity() {
        reference();var report=upload("SIM-signed-direction","-1");
        var saved=call("fba-batch-save",Map.of("batch_id",report.path("id").asText(),"expected_revision","1","reason","SIM sign regression",
            "decisions",List.of(Map.of("source_row","2","decision","NEW","event_key","SIM-sign-flip","reason","SIM invalid sign","quantity","1","adjustment_reason","SIM still cannot change direction","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","1"))))));
        assertEquals("fba_quantity_invalid",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",saved.path("id").asText(),"expected_revision",saved.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM blocked"))).code);
        assertEquals(0,balance(1001));assertEquals(0,events());
    }
    @Test void returnAlreadyCoveredByCountCannotBeReversedIntoCurrentStock() {
        reference();confirm(draft(List.of(line("1",1001,"10",binding))));
        var sale=call("fba-actions",Map.of("scope_id",scope,"kind","FULFILLMENT","event_key","SIM-snapshot-sale","occurred_at","2026-11-06T10:00:00-08:00","physical_fact_confirmed",true,"reason","SIM actual sale","lines",List.of(Map.of("sku_id","1001","units","2","source_event_ref","SIM-snapshot-sale-event","customer_order_ref","SIM-order"))));
        var saleAction=sale.path("actions").get(0);
        var returned=call("fba-actions",Map.of("scope_id",scope,"kind","RETURN","event_key","SIM-snapshot-return","fulfillment_id",saleAction.path("id").asText(),"occurred_at","2026-11-07T10:00:00-08:00","physical_fact_confirmed",true,"reason","SIM physical return","lines",List.of(Map.of("sku_id","1001","units","1","quality","QUALIFIED","source_event_ref","SIM-snapshot-return-event","customer_order_ref","SIM-order"))));
        var action=returned.path("actions").get(0);
        countSku(1001,"9","2026-11-08");
        assertEquals("fba_snapshot_covered",assertThrows(ProductionError.class,()->call("fba-action-reverse",Map.of("action_id",action.path("id").asText(),"expected_revision",action.path("revision").asText(),"reason","SIM cannot reverse covered history"))).code);
        assertEquals(9,balance(1001));
    }

    @Test void manualReceiptUsesChosenReferenceAndRejectsCrossReferenceCoverageAndCorrection() {
        call("fba-references",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","reference_id","SIM-SECOND","reason","SIM second platform shipment"));
        long chosen=db.queryForObject("SELECT id FROM fba_reference WHERE site_id=? AND reference_key=?",Long.class,site,"SIM-SECOND".getBytes());
        var saved=call("fba-unified-save",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","draft_payload",Map.of("reference_link_id",Long.toString(chosen),"business_date","2026-11-05","reason","SIM selected second reference","lines",List.of(line("1",1001,"20",binding)))));
        confirm(saved);
        long manual=db.queryForObject("SELECT id FROM fba_receipt_event WHERE site_id=?",Long.class,site);
        assertEquals(chosen,db.queryForObject("SELECT reference_id FROM fba_receipt_event WHERE site_id=?",Long.class,site));
        var report=upload("SIM other shipment evidence","20");
        assertTrue(report.path("rows").get(0).path("receipt_candidates").isEmpty());
        var linked=Map.of("source_row","2","decision","NEW","event_key","SIM bad link","reason","SIM cannot link second reference","receipt_links",List.of(Map.of("event_id",Long.toString(manual),"units","20")),"allocations",List.of());
        var reviewed=call("fba-batch-save",Map.of("batch_id",report.path("id").asText(),"expected_revision","1","decisions",List.of(linked),"reason","SIM review"));
        assertEquals("fba_coverage_invalid",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",reviewed.path("id").asText(),"expected_revision",reviewed.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM reject wrong reference"))).code);
        var negative=upload("SIM wrong reference correction","-1");
        var decision=Map.of("source_row","2","decision","NEW","event_key","SIM bad correction","reason","SIM wrong reference","correction_of","manual-"+saved.path("id").asText()+"-1","allocations",List.of(Map.of("binding_id",Long.toString(binding),"units","-1")));
        var correction=call("fba-batch-save",Map.of("batch_id",negative.path("id").asText(),"expected_revision","1","decisions",List.of(decision),"reason","SIM review"));
        assertEquals("fba_correction_conflict",assertThrows(ProductionError.class,()->call("fba-batch-confirm",Map.of("batch_id",correction.path("id").asText(),"expected_revision",correction.path("revision").asText(),"source_rows",List.of("2"),"reason","SIM reject wrong reference"))).code);
        assertEquals(20,balance(1001));assertEquals(1,events());
    }
    @Test void referencesCanBeCorrectedBeforeReceiptButNotAfterPosting() {
        long link=db.queryForObject("SELECT id FROM fba_reference WHERE site_id=?",Long.class,site);
        var before=draft(List.of(line("1",1001,"10",binding)));
        call("fba-references",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","reference_link_id",Long.toString(link),"expected_reference_number","SIM-REF","reference_id","SIM-CORRECTED","reason","SIM fix reference before acceptance"));
        assertEquals("fba_source_conflict",assertThrows(ProductionError.class,()->confirm(before)).code);
        assertEquals("fba_source_conflict",assertThrows(ProductionError.class,()->call("fba-unified-save",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","batch_id",before.path("id").asText(),"expected_revision",before.path("revision").asText(),"draft_payload",json.convertValue(before.path("draft_payload"),Map.class)))).code);
        var corrected=draft(List.of(line("1",1001,"10",binding)));confirm(corrected);
        assertEquals("fba_reference_in_use",assertThrows(ProductionError.class,()->call("fba-references",Map.of("scope_id",scope,"shipment_id",shipment,"expected_shipment_revision","1","reference_link_id",Long.toString(link),"expected_reference_number","SIM-CORRECTED","reference_id","SIM-REF","reason","SIM cannot overwrite receipt identity"))).code);
        assertEquals(10,balance(1001));
    }
    @Test void salesCoveredBySnapshotDoNotDeductAgainAndWithdrawalKeepsSnapshot() {
        countSku(1001,"10","2026-11-10");
        var sale=Map.of("sku_id","1001","report_units","3","business_date","2026-11-09","occurred_at","2026-11-09T12:00:00-08:00","report_version_ids",List.of("201"));
        var sync=Map.of("scope_id",scope,"_report_source_scope_id","1","_trusted_report_returns",List.of(),"_trusted_report_sales",List.of(sale),"_report_set_complete",true,"report_version_ids",List.of("201"),"reason","SIM snapshot covers historical sale");
        call("fba-report-sync",sync);call("fba-report-sync",sync);
        assertEquals(10,balance(1001));
        call("fba-report-sync",Map.of("scope_id",scope,"_report_source_scope_id","1","_trusted_report_returns",List.of(),"_trusted_report_sales",List.of(),"_report_set_complete",true,"report_version_ids",List.of(),"reason","SIM withdraw covered historical sale"));
        assertEquals(10,balance(1001));
    }
    @Test void countedExistingReportSaleCanBeRevisedWithoutReversingCountedInventory() {
        countSku(1001,"10","2026-11-08");
        var sale=new LinkedHashMap<String,Object>(Map.of("sku_id","1001","report_units","3","business_date","2026-11-09","occurred_at","2026-11-09T12:00:00-08:00","report_version_ids",List.of("201")));
        var sync=new LinkedHashMap<String,Object>(Map.of("scope_id",scope,"_report_source_scope_id","1","_trusted_report_returns",List.of(),"_trusted_report_sales",List.of(sale),"_report_set_complete",true,"report_version_ids",List.of("201"),"reason","SIM published sale"));
        call("fba-report-sync",sync);assertEquals(7,balance(1001));
        countSku(1001,"10","2026-11-10");sale.put("report_units","4");call("fba-report-sync",sync);
        assertEquals(10,balance(1001));
        sync.put("_trusted_report_sales",List.of());call("fba-report-sync",sync);assertEquals(10,balance(1001));
    }
    @Test void qualityChangeChecksBothSidesOfLatestSnapshot() {
        countSku(1001,"10","2026-11-10");
        for(var direction:List.of(List.of("QUALIFIED","DEFECTIVE"),List.of("DEFECTIVE","QUALIFIED"))){
            assertEquals("fba_snapshot_covered",assertThrows(ProductionError.class,()->call("fba-quality",Map.of("scope_id",scope,"expected_revision",scopeRevision(),"from_quality",direction.get(0),"target_quality",direction.get(1),"business_date","2026-11-09","reason","SIM historical quality change","lines",List.of(Map.of("sku_id","1001","units","2","reason_code","WAREHOUSE_DAMAGED"))))).code);
        }
        assertEquals(10,balance(1001));
    }

    @Test void qualifiedManualReceiptIsNotACandidateForDamagedReportReceipt() {
        confirm(draft(List.of(line("1",1001,"10",binding))));
        classifiedReceipt("SIM-separate-damaged-intake","2","");
        assertEquals(10,balance(1001));
        assertEquals(2,db.queryForObject("SELECT defective_units FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1001",Long.class,site));
        assertEquals(2,events());
    }
}
