package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
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

class WarehouseTransitDatabaseTest {
    static JdbcTemplate db;static TransactionTemplate tx;static ObjectMapper json;static InventoryService inventory;static ProductionService production;static long source,destination;
    static long SITE;
    static ProductionContext ACTOR;
    static final Map<String,Object> CATALOG=Map.of("1001",Map.of("sku_id","1001","style_id","2001","code","SIM-SKU","label","SIM-SKU","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"));
    @BeforeEach void setup(){
        SITE=5_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L);
        ACTOR=new ProductionContext(SITE,1,Set.of("data_manager"),"SIMULATED warehouse transit");
        String url=System.getenv("FBA_TEST_JDBC_URL");if(url==null||!url.startsWith("jdbc:mysql://127.0.0.1:")||!url.contains("/clsen_fba_contract?"))throw new IllegalStateException("Explicit owned contract schema required");
        Flyway.configure().dataSource(url,System.getenv("FBA_TEST_MIGRATION_USER"),System.getenv("FBA_TEST_MIGRATION_PASSWORD")).load().migrate();
        var ds=new DriverManagerDataSource(url,System.getenv("FBA_TEST_RUNTIME_USER"),System.getenv("FBA_TEST_RUNTIME_PASSWORD"));db=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));json=new ObjectMapper();inventory=new InventoryService(db,json,"demo_fixed");production=new ProductionService(db,json,"demo_fixed");
        tx.executeWithoutResult(t->{for(int i=0;i<2;i++){
            db.update("INSERT INTO production_warehouse(site_id,name,type,country) VALUES(?,?,'OWN','US')",SITE,"SIMULATED transit "+i);long warehouse=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);if(i==0)source=warehouse;else destination=warehouse;
            db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,?,1,'SIM warehouse','SIM owner','2026-09-30',?,?)",SITE,warehouse,"SIM explicit opening "+warehouse,UUID.randomUUID().toString());
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version,qualified_units) VALUES(?,?,1,1001,'SIM-SKU','DEMO_LOCAL_ONLY-v1',?)",SITE,warehouse,i==0?20:0);
        }});
    }
    static Map<String,Object> map(Object...pairs){var v=new LinkedHashMap<String,Object>();for(int i=0;i<pairs.length;i+=2)v.put(pairs[i].toString(),pairs[i+1]);return v;}
    static JsonNode body(Map<String,Object> fields){var v=new LinkedHashMap<>(fields);v.put("operation_token",UUID.randomUUID().toString());v.put("_catalog",CATALOG);return json.valueToTree(v);}
    static JsonNode command(String path,JsonNode b){return json.valueToTree(tx.execute(t->inventory.command(ACTOR,path,b,b.path("operation_token").asText())));}
    static JsonNode shipment(Map<String,Object> fields){var b=body(fields);return json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",null,"create",b.path("operation_token").asText(),b)));}
    static Map<String,Object> transfer(long units){return map("save_mode","confirm","dispatch_purpose","LOGISTICS_TRANSFER","business_date","2026-10-28","warehouse_id",Long.toString(source),"owner_id","1","destination_id",Long.toString(destination),"destination_type","WAREHOUSE","destination","SIM destination","manual_source_note","SIMULATED independent warehouse leg "+UUID.randomUUID(),"cartons",List.of(map("number","SIM-BOX","items",List.of(map("sku_id","1001","units",Long.toString(units))))),"sources",List.of(map("sku_id","1001","actual_units",Long.toString(units),"fulfillment_mode","WAREHOUSE_STOCK","allocations",List.of())));}
    static long balance(long warehouse){return db.queryForObject("SELECT qualified_units FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=1 AND sku_id=1001",Long.class,SITE,warehouse);}
    static JsonNode read(long warehouse,String direction){return json.valueToTree(tx.execute(t->new WarehouseTransitStore(db,json,inventory).read(ACTOR,Map.of("warehouse_id",Long.toString(warehouse),"owner_id","1","direction",direction),Instant.parse("2026-10-29T06:30:00Z"))));}
    @Test void transferUsesOneStockTransactionAndProjectsPartialReceiptAndTimes()throws Exception{
        var transfer=transfer(10);var b=body(transfer);var created=json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",null,"create",b.path("operation_token").asText(),b)));assertEquals(created,json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",null,"create",b.path("operation_token").asText(),b))));
        long shipment=created.path("id").asLong();assertEquals(10,balance(source));assertEquals(0,balance(destination));assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM production_shipment_allocation WHERE site_id=?",Long.class,SITE));
        var first=read(destination,"incoming").path("items").get(0);assertEquals("UNREGISTERED",first.path("stage").asText());assertTrue(first.path("unreceived_units").isNull());
        var binding=body(map("shipment_id",Long.toString(shipment),"expected_shipment_revision","1","reason","SIM explicit carton-source allocation without production order","bindings",List.of(map("carton_id",created.path("cartons").get(0).path("id").asText(),"source_line_id",created.path("sources").get(0).path("id").asText(),"sku_id","1001","units","10"))));
        var bound=command("destination-bindings",binding);String bindingId=bound.path("bindings").get(0).path("id").asText();
        var scope=map("shipment_id",Long.toString(shipment),"expected_shipment_revision","1","expected_warehouse_id",Long.toString(source),"expected_owner_id","1","expected_destination_id",Long.toString(destination));
        var record=new LinkedHashMap<>(scope);record.putAll(map("expected_revision","0","carrier","SIM carrier","tracking_number","SIM-TRANSIT-01","arrival_local","2026-10-29T12:00","arrival_timezone","Asia/Shanghai","source_reference","SIM receipt evidence"));var recorded=command("transport-records",body(record));
        var node=new LinkedHashMap<>(scope);node.putAll(map("transport_id",recorded.path("record").path("id").asText(),"expected_transport_revision","1","event_kind","DISPATCHED","occurred_local","2026-10-28T08:00","timezone","Asia/Shanghai","source_reference","SIM actual departure"));command("transport-events",body(node));
        var moving=read(destination,"incoming").path("items").get(0);assertEquals("IN_TRANSIT",moving.path("stage").asText());assertTrue(moving.path("eta_overdue").asBoolean());assertEquals("10",moving.path("unreceived_units").asText());assertEquals(moving,read(source,"outgoing").path("items").get(0));
        node.putAll(map("event_kind","ARRIVED","occurred_local","2026-10-29T09:00"));command("transport-events",body(node));var arrival=read(destination,"incoming").path("items").get(0);assertEquals("ARRIVAL_CHECK",arrival.path("stage").asText());assertEquals("25",arrival.path("duration_hours").asText());assertFalse(arrival.path("eta_overdue").asBoolean());assertEquals(0,balance(destination));
        var receipt=command("destination-receipts",body(map("shipment_id",Long.toString(shipment),"expected_shipment_revision","1","warehouse_id",Long.toString(destination),"owner_id","1","business_date","2026-10-29","reason","SIM partial physical arrival","lines",List.of(map("binding_id",bindingId,"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","4","pending_units","0","defective_units","0")))));
        var confirm=body(map("expected_revision",receipt.path("revision").asText(),"reason","SIM confirm actual receipt"));String confirmPath="destination-receipts/"+receipt.path("id").asText()+"/confirm";var posted=command(confirmPath,confirm);assertEquals(posted,command(confirmPath,confirm));assertEquals(10,balance(source));assertEquals(4,balance(destination));assertEquals("6",read(destination,"incoming").path("items").get(0).path("unreceived_units").asText());
        var sameWarehouse=transfer(1);sameWarehouse.put("destination_id",Long.toString(source));assertEquals("transfer_scope_invalid",assertThrows(ProductionError.class,()->shipment(sameWarehouse)).code);
        var ownerWrong=transfer(1);ownerWrong.put("owner_id","99");assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->shipment(ownerWrong)).code);
        try(var pool=Executors.newFixedThreadPool(2)){var gate=new CountDownLatch(1);var tasks=new ArrayList<Future<Boolean>>();for(int i=0;i<2;i++)tasks.add(pool.submit(()->{gate.await();try{shipment(transfer(6));return true;}catch(ProductionError e){assertEquals("insufficient_available_stock",e.code);return false;}}));gate.countDown();assertNotEquals(tasks.get(0).get(20,TimeUnit.SECONDS),tasks.get(1).get(20,TimeUnit.SECONDS));}assertEquals(4,balance(source));assertEquals(4,balance(destination));
        var viewer=new ProductionContext(SITE,2,Set.of("viewer"));var blocked=body(transfer(1));assertEquals(403,assertThrows(ProductionError.class,()->tx.execute(t->production.command(viewer,"shipments",null,"create",blocked.path("operation_token").asText(),blocked))).status);
        assertEquals(0,json.valueToTree(new WarehouseTransitStore(db,json,inventory).read(ACTOR,Map.of("warehouse_id",Long.toString(destination),"owner_id","99"),Instant.now())).path("total").asInt());
        var locations=json.valueToTree(tx.execute(t->inventory.read(ACTOR,"sku-locations",Map.of("sku_id","1001"))));assertEquals(2,locations.path("total").asInt());assertEquals(2,locations.path("items").size());assertEquals("1001",locations.path("sku_id").asText());
        assertEquals(0,json.valueToTree(new WarehouseTransitStore(db,json,inventory).read(ACTOR,Map.of("warehouse_id",Long.toString(destination),"sku_id","1002"),Instant.now())).path("total").asInt());
        db.update("INSERT INTO production_warehouse(site_id,name,type,country) VALUES(?,'SIM uninitialized destination','THIRD_PARTY','US')",SITE);var withUnknown=json.valueToTree(tx.execute(t->inventory.read(ACTOR,"sku-locations",Map.of("sku_id","1001"))));assertEquals(3,withUnknown.path("total").asInt());assertTrue(withUnknown.path("items").get(2).path("balance").isNull());
    }
    @Test void stageDoesNotInventTransitOrReceipt(){assertEquals("UNREGISTERED",WarehouseTransitStore.classify(8L,0,"REGISTERED",false));assertEquals("ARRIVAL_CHECK",WarehouseTransitStore.classify(8L,0,"SIGNED",false));assertEquals("EXCEPTION",WarehouseTransitStore.classify(0L,0,"EXCEPTION",true));assertEquals("RECEIVED",WarehouseTransitStore.classify(0L,0,"SIGNED",true));}
}
