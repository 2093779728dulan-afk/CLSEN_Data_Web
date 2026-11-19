package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;

class DestinationReceiptDatabaseTest {
    static JdbcTemplate db; static TransactionTemplate tx; static ObjectMapper json; static InventoryService inventory;
    static final long SITE=2_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L); static ProductionContext actor=new ProductionContext(SITE,1,Set.of("admin"),"task test");
    static long shipment,source,allocation,binding; static final String BOX="4cd90b14-81cb-47f2-8f51-904a02180c71";
    @BeforeAll static void setup(){
        String url=System.getenv("P2_TEST_JDBC_URL");
        if(url==null||!url.startsWith("jdbc:mysql://127.0.0.1:")||!url.contains("/clsen_p2_contract_test_3?"))throw new IllegalStateException("Explicit isolated P2 schema required");
        Flyway.configure().dataSource(url,System.getenv("P2_TEST_MIGRATION_USER"),System.getenv("P2_TEST_MIGRATION_PASSWORD")).load().migrate();
        var ds=new DriverManagerDataSource(url,System.getenv("P2_TEST_RUNTIME_USER"),System.getenv("P2_TEST_RUNTIME_PASSWORD"));
        db=new JdbcTemplate(ds); tx=new TransactionTemplate(new DataSourceTransactionManager(ds));json=new ObjectMapper();inventory=new InventoryService(db,json,"demo_fixed");
        tx.executeWithoutResult(s->{
            db.update("INSERT INTO production_warehouse(site_id,id,name,type,country) VALUES(?,1,'fictional destination','OWN','US')",SITE);
            db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,1,1,'fictional destination','fictional owner','2025-01-01',?,?)",SITE,"FICTIONAL-P2-"+SITE,UUID.randomUUID().toString());
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,1,1,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1')",SITE);
            db.update("INSERT INTO production_order(site_id,system_number,status) VALUES(?,'P2-order','CONFIRMED')",SITE);long order=last();
            db.update("INSERT INTO production_order_line(site_id,order_id,sku_id,sku_label,catalog_version,expected_units) VALUES(?,?,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1',100)",SITE,order);long orderLine=last();
            String boxes="[{\"id\":\""+BOX+"\",\"number\":\"1\",\"items\":[{\"sku_id\":\"1001\",\"units\":\"100\"}]}]";
            db.update("INSERT INTO production_shipment(site_id,system_number,status,destination_id,destination_type,cartons) VALUES(?,'P2-shipment','CONFIRMED',1,'OWN',?)",SITE,boxes);shipment=last();
            db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1',100)",SITE,shipment);source=last();
            db.update("INSERT INTO production_shipment_allocation(site_id,source_line_id,order_line_id,units) VALUES(?,?,?,100)",SITE,source,orderLine);allocation=last();
        });
    }
    static long last(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    static JsonNode body(Map<String,Object> v){var b=new LinkedHashMap<>(v);b.put("operation_token",UUID.randomUUID().toString());b.put("_catalog",Map.of("1001",Map.of("sku_id","1001","status","active","catalog_version","DEMO_LOCAL_ONLY-v1")));return json.valueToTree(b);}
    static Object command(String path,JsonNode body){return inventory.command(actor,path,body,body.path("operation_token").asText());}
    @Test void realDatabasePartialReceiptReplayAndConcurrentRemaining() throws Exception {
        var b=body(Map.of("shipment_id",String.valueOf(shipment),"expected_shipment_revision","1","reason","explicit fictional mapping","bindings",List.of(Map.of("carton_id",BOX,"source_line_id",String.valueOf(source),"allocation_id",String.valueOf(allocation),"sku_id","1001","units","100"))));
        var bound=json.valueToTree(tx.execute(s->command("destination-bindings",b)));binding=bound.path("bindings").get(0).path("id").asLong();
        // Boundaries use this isolated random site and must fail before inventory is written.
        var line=Map.of("binding_id",String.valueOf(binding),"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","1","pending_units","0","defective_units","0");
        var base=new LinkedHashMap<String,Object>(Map.of("shipment_id",String.valueOf(shipment),"expected_shipment_revision","1","warehouse_id","1","owner_id","1","business_date","2025-02-01","reason","fictional boundaries","lines",List.of(line)));
        var stale=new LinkedHashMap<>(base);stale.put("expected_shipment_revision","999");assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts",body(stale))));
        var otherSite=new ProductionContext(SITE+1,1,Set.of("admin"),"other site");var cross=body(base);assertThrows(ProductionError.class,()->tx.execute(s->inventory.command(otherSite,"destination-receipts",cross,cross.path("operation_token").asText())));
        var wrongOwner=new LinkedHashMap<>(base);wrongOwner.put("owner_id","99");assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts",body(wrongOwner))));
        db.update("INSERT INTO production_warehouse(site_id,id,name,type,country) VALUES(?,2,'fictional uninitialized','OWN','US')",SITE);var uninitialized=new LinkedHashMap<>(base);uninitialized.put("warehouse_id","2");assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts",body(uninitialized))));
        var staleCatalog=new LinkedHashMap<>(base);staleCatalog.put("lines",List.of(Map.of("binding_id",String.valueOf(binding),"sku_id","1001","catalog_version","OLD","qualified_units","1","pending_units","0","defective_units","0")));var oldDraft=json.valueToTree(tx.execute(s->command("destination-receipts",body(staleCatalog))));assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts/"+oldDraft.path("id").asText()+"/confirm",body(Map.of("expected_revision","1")))));
        var fbaDraft=json.valueToTree(tx.execute(s->command("destination-receipts",body(base))));db.update("UPDATE production_warehouse SET type='FBA' WHERE site_id=? AND id=1",SITE);try{assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts/"+fbaDraft.path("id").asText()+"/confirm",body(Map.of("expected_revision","1")))));}finally{db.update("UPDATE production_warehouse SET type='OWN' WHERE site_id=? AND id=1",SITE);}
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,SITE));
        byte[] originalBytes="fictional workbook bytes".getBytes(java.nio.charset.StandardCharsets.UTF_8);
        var upload=body(Map.of("shipment_id",String.valueOf(shipment),"filename","fictional.xlsx","file_base64",Base64.getEncoder().encodeToString(originalBytes)));
        var stored=json.valueToTree(tx.execute(s->command("destination-uploads",upload)));String uploadId=stored.path("upload_id").asText();
        assertArrayEquals(originalBytes,tx.execute(s->inventory.destinationOriginal(actor,uploadId)));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(s->inventory.destinationOriginal(new ProductionContext(SITE,2,Set.of("viewer"),"viewer"),uploadId))).code);
        var first=createDraft(56,2,2,uploadId);var firstInput=body(Map.of("expected_revision","1"));String path="destination-receipts/"+first+"/confirm";
        var posted=tx.execute(s->command(path,firstInput));assertEquals("2025-02-01",json.valueToTree(posted).path("business_date").asText());assertEquals(json.valueToTree(posted),json.valueToTree(tx.execute(s->command(path,firstInput))));
        var altered=(tools.jackson.databind.node.ObjectNode)firstInput.deepCopy();altered.put("expected_revision","99");
        assertEquals("idempotency_content_conflict",assertThrows(ProductionError.class,()->tx.execute(s->command(path,altered))).code);
        var viewer=new ProductionContext(SITE,2,Set.of("viewer"),"viewer");var viewerRequest=body(Map.of("expected_revision","1"));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(s->inventory.command(viewer,path,viewerRequest,viewerRequest.path("operation_token").asText()))).code);
        var change=body(Map.of("expected_revision","1","reason","attempt to void source"));
        var production=new ProductionService(db,json,"demo_fixed");
        assertEquals("destination_receipt_dependency",assertThrows(ProductionError.class,()->tx.execute(s->production.command(actor,"shipments",shipment,"void",change.path("operation_token").asText(),change))).code);
        var changeSource=body(Map.of("expected_revision","1","reason","attempt to correct source"));assertEquals("destination_receipt_dependency",assertThrows(ProductionError.class,()->tx.execute(s->production.command(actor,"shipments",shipment,"correct",changeSource.path("operation_token").asText(),changeSource))).code);
        var second=createDraft(38,0,0,null);var secondInput=body(Map.of("expected_revision","1"));tx.execute(s->command("destination-receipts/"+second+"/confirm",secondInput));
        var balance=db.queryForMap("SELECT qualified_units,pending_units,defective_units FROM inventory_balance WHERE site_id=? AND warehouse_id=1 AND owner_id=1 AND sku_id=1001",SITE);
        assertEquals(94,((Number)balance.get("qualified_units")).longValue());assertEquals(2,((Number)balance.get("pending_units")).longValue());assertEquals(2,((Number)balance.get("defective_units")).longValue());
        long over=createDraft(3,0,0,null);var overRequest=body(Map.of("expected_revision","1"));
        assertEquals("receipt_exceeds_remaining",assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts/"+over+"/confirm",overRequest))).code);
        var settlement=body(Map.of("binding_id",String.valueOf(binding),"units","1","expected_shipment_revision","1","reason","fictional shortage closure"));
        var settled=json.valueToTree(tx.execute(s->command("destination-settlements",settlement)));
        long a=createDraft(1,0,0,null),d=createDraft(1,0,0,null);var gate=new CountDownLatch(1);try(var pool=Executors.newFixedThreadPool(2)){
            var futures=new ArrayList<Future<Boolean>>();for(long id:List.of(a,d))futures.add(pool.submit(()->{gate.await();try{var request=body(Map.of("expected_revision","1"));tx.execute(s->command("destination-receipts/"+id+"/confirm",request));return true;}catch(ProductionError e){return false;}}));
            gate.countDown();assertNotEquals(futures.get(0).get(20,TimeUnit.SECONDS),futures.get(1).get(20,TimeUnit.SECONDS));
        }
        assertEquals(99L,db.queryForObject("SELECT SUM(qualified_units+pending_units+defective_units) FROM inventory_balance WHERE site_id=?",Long.class,SITE));
        var undo=body(Map.of("expected_revision","1","reason","fictional correction"));
        tx.execute(s->command("destination-settlements/"+settled.path("id").asText()+"/reverse",undo));
        assertEquals("REVERSED",db.queryForObject("SELECT status FROM destination_receipt_settlement WHERE site_id=? AND id=?",String.class,SITE,settled.path("id").asLong()));
        assertEquals(99L,db.queryForObject("SELECT SUM(qualified_units+pending_units+defective_units) FROM inventory_balance WHERE site_id=?",Long.class,SITE));
        var correction=body(Map.of("shipment_id",String.valueOf(shipment),"expected_shipment_revision","1","expected_revision","2","warehouse_id","1","owner_id","1","business_date","2025-02-01","reason","fictional correction","lines",List.of(Map.of("binding_id",String.valueOf(binding),"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","55","pending_units","2","defective_units","2"))));
        var corrected=json.valueToTree(tx.execute(s->command("destination-receipts/"+first+"/correct",correction)));
        assertEquals("POSTED",corrected.path("status").asText());assertEquals(String.valueOf(first),corrected.path("replaces_receipt_id").asText());assertEquals(uploadId,corrected.path("upload_id").asText());
        assertEquals("REVERSED",db.queryForObject("SELECT status FROM destination_receipt WHERE site_id=? AND id=?",String.class,SITE,first));
        assertEquals(98L,db.queryForObject("SELECT SUM(qualified_units+pending_units+defective_units) FROM inventory_balance WHERE site_id=?",Long.class,SITE));
        // Independent random-site fixture: consuming the destination stock must block both operations atomically.
        var take=body(Map.of("warehouse_id","1","owner_id","1","kind","OUT","business_date","2025-02-02","reason","fictional downstream consumption","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","94","purpose","CONSUME"))));
        var draft=json.valueToTree(tx.execute(s->command("documents",take)));
        var takeConfirm=body(Map.of("expected_revision",draft.path("revision").asText()));
        var taken=json.valueToTree(tx.execute(s->command("documents/"+draft.path("id").asText()+"/confirm",takeConfirm)));
        long beforeEvents=db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,SITE);
        var reverse=body(Map.of("expected_revision",corrected.path("revision").asText(),"reason","fictional consumed reversal"));
        assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts/"+corrected.path("id").asText()+"/reverse",reverse))).code);
        var retryCorrection=(tools.jackson.databind.node.ObjectNode)correction.deepCopy();retryCorrection.put("operation_token",UUID.randomUUID().toString());retryCorrection.put("expected_revision",corrected.path("revision").asText());
        assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->tx.execute(s->command("destination-receipts/"+corrected.path("id").asText()+"/correct",retryCorrection))).code);
        assertEquals("POSTED",db.queryForObject("SELECT status FROM destination_receipt WHERE site_id=? AND id=?",String.class,SITE,corrected.path("id").asLong()));
        assertEquals(beforeEvents,db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,SITE));
        assertEquals(4L,db.queryForObject("SELECT SUM(qualified_units+pending_units+defective_units) FROM inventory_balance WHERE site_id=?",Long.class,SITE));
        var restore=body(Map.of("expected_revision",taken.path("revision").asText(),"reason","restore fictional consumption"));
        tx.execute(s->command("documents/"+taken.path("id").asText()+"/reverse",restore));
        assertEquals(98L,db.queryForObject("SELECT SUM(qualified_units+pending_units+defective_units) FROM inventory_balance WHERE site_id=?",Long.class,SITE));
    }
    static long createDraft(long q,long p,long d,String upload){
        var data=new LinkedHashMap<String,Object>(Map.of("shipment_id",String.valueOf(shipment),"expected_shipment_revision","1","warehouse_id","1","owner_id","1","business_date","2025-02-01","reason","fictional receipt","lines",List.of(Map.of("binding_id",String.valueOf(binding),"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units",String.valueOf(q),"pending_units",String.valueOf(p),"defective_units",String.valueOf(d)))));
        if(upload!=null)data.put("upload_id",upload);var input=body(data);
        return json.valueToTree(tx.execute(s->command("destination-receipts",input))).path("id").asLong();
    }
}
