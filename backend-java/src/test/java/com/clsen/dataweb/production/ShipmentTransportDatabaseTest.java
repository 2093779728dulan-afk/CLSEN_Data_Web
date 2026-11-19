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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class ShipmentTransportDatabaseTest {
    static JdbcTemplate db;static TransactionTemplate tx;static InventoryService inventory;static ObjectMapper json;
    static final long SITE=3_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L);
    static final ProductionContext ACTOR=new ProductionContext(SITE,1,Set.of("admin"),"fictional transport tester");
    static long shipment,sourceWarehouse,destinationWarehouse;static String before;
    @BeforeAll static void prepare(){
        String url=System.getenv("P4_TEST_JDBC_URL");
        if(url==null || !url.startsWith("jdbc:mysql://127.0.0.1:") || !url.contains("/clsen_p4_transport_contract?"))throw new IllegalStateException("Explicit isolated P4 contract schema required");
        Flyway.configure().dataSource(url,System.getenv("P4_TEST_MIGRATION_USER"),System.getenv("P4_TEST_MIGRATION_PASSWORD")).load().migrate();
        db=new JdbcTemplate(new DriverManagerDataSource(url,System.getenv("P4_TEST_RUNTIME_USER"),System.getenv("P4_TEST_RUNTIME_PASSWORD")));tx=new TransactionTemplate(new DataSourceTransactionManager(db.getDataSource()));json=new ObjectMapper();inventory=new InventoryService(db,json,"demo_fixed");
        tx.executeWithoutResult(s->{
            db.update("INSERT INTO production_warehouse(site_id,name,type,country) VALUES(?,'P4 fictional source','OWN','US')",SITE);sourceWarehouse=last();
            db.update("INSERT INTO production_warehouse(site_id,name,type,country) VALUES(?,'P4 fictional destination','OWN','US')",SITE);destinationWarehouse=last();
            for(long warehouse:List.of(sourceWarehouse,destinationWarehouse)){
                db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,?,1,'fictional warehouse','fictional owner','2026-01-01',?,?)",SITE,warehouse,"P4-FICTIONAL-"+warehouse,UUID.randomUUID().toString());
                db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version,qualified_units) VALUES(?,?,1,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1',?)",SITE,warehouse,warehouse==sourceWarehouse?20:98);
            }
            var orderLines=new ArrayList<Long>();
            for(long amount:List.of(60L,40L)){
                db.update("INSERT INTO production_order(site_id,system_number,status) VALUES(?,?,'CONFIRMED')",SITE,"P4-order-"+amount);long order=last();
                db.update("INSERT INTO production_order_line(site_id,order_id,sku_id,sku_label,catalog_version,expected_units) VALUES(?,?,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1',?)",SITE,order,amount);orderLines.add(last());
            }
            String box=UUID.randomUUID().toString();
            String cartons="[{\"id\":\""+box+"\",\"number\":\"P4-box\",\"items\":[{\"sku_id\":\"1001\",\"units\":\"100\"}]}]";
            db.update("INSERT INTO production_shipment(site_id,system_number,status,warehouse_id,owner_id,destination_id,destination_type,cartons) VALUES(?,'P4-shipment','CONFIRMED',?,1,?,'WAREHOUSE',?)",SITE,sourceWarehouse,destinationWarehouse,cartons);shipment=last();
            db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,1001,'fictional SKU','DEMO_LOCAL_ONLY-v1',100)",SITE,shipment);long source=last();
            db.update("INSERT INTO destination_receipt(site_id,shipment_id,shipment_revision,warehouse_id,owner_id,business_date,reason,status,actor_id,actor_name) VALUES(?,?,1,?,1,'2026-10-28','fictional receipt fixture','POSTED',1,'tester')",SITE,shipment,destinationWarehouse);long receipt=last();
            for(int i=0;i<2;i++){
                long amount=i==0?60:40;db.update("INSERT INTO production_shipment_allocation(site_id,source_line_id,order_line_id,units) VALUES(?,?,?,?)",SITE,source,orderLines.get(i),amount);long allocation=last();
                db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,allocation_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,?,?,1001,?,1,1,'tester','fixture')",SITE,shipment,source,allocation,box,amount);long binding=last();
                db.update("INSERT INTO destination_receipt_line(site_id,receipt_id,binding_id,sku_id,catalog_version,qualified_units) VALUES(?,?,?,1001,'DEMO_LOCAL_ONLY-v1',?)",SITE,receipt,binding,i==0?60:38);
            }
        });before=facts();
    }
    static long last(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    static String facts(){return json.writeValueAsString(List.of(db.queryForList("SELECT warehouse_id,owner_id,sku_id,qualified_units,pending_units,defective_units,revision FROM inventory_balance WHERE site_id=? ORDER BY warehouse_id",SITE),db.queryForList("SELECT source_line_id,order_line_id,units FROM production_shipment_allocation WHERE site_id=? ORDER BY id",SITE),db.queryForList("SELECT * FROM inventory_event WHERE site_id=? ORDER BY id",SITE),db.queryForList("SELECT expected_units,is_active FROM production_order_line WHERE site_id=? ORDER BY id",SITE)));}
    static Map<String,Object> scope(){return new LinkedHashMap<>(Map.of("shipment_id",Long.toString(shipment),"expected_shipment_revision","1","expected_warehouse_id",Long.toString(sourceWarehouse),"expected_owner_id","1","expected_destination_id",Long.toString(destinationWarehouse)));}
    static JsonNode body(Map<String,Object> fields){var value=new LinkedHashMap<>(fields);value.put("operation_token",UUID.randomUUID().toString());value.put("_catalog",Map.of("1001",Map.of("sku_id","1001","status","active","catalog_version","DEMO_LOCAL_ONLY-v1")));return json.valueToTree(value);}
    static JsonNode command(String path,JsonNode input){return json.valueToTree(tx.execute(s->inventory.command(ACTOR,path,input,input.path("operation_token").asText())));}
    static Map<String,Object> recordBody(){var b=scope();b.putAll(Map.of("expected_revision","0","carrier","fictional carrier","tracking_number","000P4-001","arrival_local","2026-10-30T12:00","arrival_timezone","Asia/Shanghai","source_reference","fictional dispatch evidence"));return b;}
    static Map<String,Object> nodeBody(JsonNode state,String kind){var b=scope();b.putAll(Map.of("transport_id",state.path("record").path("id").asText(),"expected_transport_revision",state.path("record").path("revision").asText(),"event_kind",kind,"occurred_local",kind.equals("SIGNED")?"2026-10-29T12:00":"2026-10-28T10:00","timezone","Asia/Shanghai","source_reference","fictional carrier evidence","location","fictional hub","description","manual evidence"));if(kind.equals("SIGNED"))b.put("signed_units","100");return b;}
    @Test void metadataRevisionsNeverPostInventoryAndRejectBoundaryConflicts() throws Exception {
        assertFalse(json.valueToTree(inventory.read(ACTOR,"transport-state",Map.of("shipment_id",Long.toString(shipment)))).path("registered").asBoolean());
        var input=body(recordBody());var registered=command("transport-records",input);long recordId=registered.path("record").path("id").asLong();
        assertEquals(registered,command("transport-records",input));
        var changed=(tools.jackson.databind.node.ObjectNode)input.deepCopy();changed.put("carrier","other carrier");assertEquals("idempotency_content_conflict",assertThrows(ProductionError.class,()->command("transport-records",changed)).code);
        var wrong=recordBody();wrong.put("expected_owner_id","999");assertEquals("transport_scope_conflict",assertThrows(ProductionError.class,()->command("transport-records",body(wrong))).code);
        var stale=recordBody();stale.put("expected_shipment_revision","999");assertEquals("transport_revision_conflict",assertThrows(ProductionError.class,()->command("transport-records",body(stale))).code);
        var viewer=new ProductionContext(SITE,2,Set.of("viewer"));assertEquals(403,assertThrows(ProductionError.class,()->tx.execute(s->inventory.command(viewer,"transport-records",input,input.path("operation_token").asText()))).status);
        assertEquals(404,assertThrows(ProductionError.class,()->inventory.read(new ProductionContext(SITE+1,1,Set.of("admin")),"transport-state",Map.of("shipment_id",Long.toString(shipment)))).status);
        var transit=command("transport-events",body(nodeBody(registered,"IN_TRANSIT")));assertEquals("IN_TRANSIT",transit.path("status").asText());assertEquals("98",transit.path("destination_received_units").asText());assertEquals(before,facts());
        var signedBody=body(nodeBody(transit,"SIGNED"));var signed=command("transport-events",signedBody);assertEquals(signed,command("transport-events",signedBody));assertEquals(2,signed.path("events").size());assertEquals("100",signed.path("latest_event").path("signed_units").asText());assertEquals("98",signed.path("destination_received_units").asText());
        String eventId=signed.path("latest_event").path("id").asText();var correction=nodeBody(signed,"SIGNED");correction.putAll(Map.of("expected_revision","1","signed_units","99","reason","correct fictional carrier total"));var corrected=command("transport-events/"+eventId+"/correct",body(correction));assertEquals("2",corrected.path("latest_event").path("revision").asText());assertEquals("99",corrected.path("latest_event").path("signed_units").asText());assertEquals(before,facts());
        assertEquals("transport_revision_conflict",assertThrows(ProductionError.class,()->command("transport-events/"+eventId+"/correct",body(correction))).code);
        var raceA=new LinkedHashMap<>(correction);raceA.put("expected_revision","2");raceA.put("description","concurrent A");var raceB=new LinkedHashMap<>(raceA);raceB.put("description","concurrent B");
        try(var pool=Executors.newFixedThreadPool(2)){
            var ready=new CountDownLatch(2);var start=new CountDownLatch(1);var tasks=new ArrayList<Future<String>>();
            for(var data:List.of(raceA,raceB))tasks.add(pool.submit(()->{ready.countDown();start.await();try{command("transport-events/"+eventId+"/correct",body(data));return "ok";}catch(ProductionError error){return error.code;}}));
            assertTrue(ready.await(5,TimeUnit.SECONDS));start.countDown();var outcomes=new HashSet<String>();for(var task:tasks)outcomes.add(task.get(20,TimeUnit.SECONDS));assertEquals(Set.of("ok","transport_revision_conflict"),outcomes);
        }
        var update=recordBody();update.putAll(Map.of("expected_revision","1","carrier","corrected carrier","reason","correct carrier evidence"));var updated=command("transport-records/"+recordId+"/correct",body(update));assertEquals("2",updated.path("record").path("revision").asText());assertEquals(2,updated.path("record").path("source_snapshot").path("sources").get(0).path("allocations").size());assertEquals(before,facts());assertTrue(updated.path("history").size()>=6);
        db.update("UPDATE production_shipment SET revision=revision+1 WHERE site_id=? AND id=?",SITE,shipment);
        var oldNode=nodeBody(updated,"ARRIVED");oldNode.put("expected_shipment_revision","2");assertEquals("transport_revision_conflict",assertThrows(ProductionError.class,()->command("transport-events",body(oldNode))).code);
        assertFalse(json.valueToTree(inventory.read(ACTOR,"transport-state",Map.of("shipment_id",Long.toString(shipment)))).path("source_revision_current").asBoolean());assertEquals(before,facts());
    }
    @Test void explicitTimezonesPreserveInstantsAndRejectAmbiguousLocalTime(){
        assertEquals("2026-10-28T02:00:00Z",ShipmentTransportStore.time("2026-10-28T10:00","Asia/Shanghai").toString());
        assertEquals("2026-11-01T06:30:00Z",ShipmentTransportStore.time("2026-11-01T01:30","-05:00").toString());
        assertThrows(ProductionError.class,()->ShipmentTransportStore.time("2026-11-01T01:30","America/New_York"));
        assertThrows(ProductionError.class,()->ShipmentTransportStore.time("2026-03-08T02:30","America/New_York"));
    }
}
