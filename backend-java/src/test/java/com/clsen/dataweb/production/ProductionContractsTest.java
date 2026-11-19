package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.JsonNode;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.NONE)
class ProductionContractsTest {
    @Autowired ProductionService service;
    @Autowired ProductionFiles files;
    @Autowired ObjectMapper json;
    @Autowired JdbcTemplate db;
    ProductionContext context;
    @BeforeAll static void migrate() {
        String url=System.getenv("PRODUCTION_DATABASE_URL");
        if(url==null || !url.contains("/clsen_orders_b_v1_1_0_test?"))throw new IllegalStateException("Only the dedicated test schema may be used");
        Flyway.configure().dataSource(url,System.getenv("PRODUCTION_MIGRATION_USER"),System.getenv("PRODUCTION_MIGRATION_PASSWORD")).load().migrate();
    }
    @BeforeEach void scope(){context=new ProductionContext(Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000)+10_000,1,Set.of("admin"));}
    @AfterEach void cleanup() {
        db.update("DELETE FROM production_factory_warehouse WHERE site_id=?",context.site());
        db.update("DELETE FROM production_directory_revision WHERE site_id=?",context.site());
        db.update("DELETE FROM production_warehouse WHERE site_id=?",context.site());
        db.update("UPDATE production_shipment_source_line SET replaces_source_id=NULL WHERE site_id=?",context.site());
        for(String table:List.of("production_business_source","production_preview","production_source","production_shipment_allocation","production_shipment_source_line","production_shipment","production_order_line","production_order","production_factory","production_revision","production_command"))db.update("DELETE FROM "+table+" WHERE site_id=?",context.site());
        db.update("DELETE FROM inventory_scope WHERE site_id=?",context.site());
    }
    JsonNode command(Map<String,Object> body) {
        var input=new LinkedHashMap<>(body);input.put("operation_token",UUID.randomUUID().toString());
        input.put("_catalog",Map.of("1001",Map.of("sku_id","1001","label","DEMO-SKU-BLUE-M","code","DEMO-SKU-BLUE-M","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"),"1002",Map.of("sku_id","1002","label","DEMO-SKU-BLUE-L","code","DEMO-SKU-BLUE-L","status","active","catalog_version","DEMO_LOCAL_ONLY-v1")));
        input.put("_resolved_codes",Map.of("DEMO-SKU-BLUE-M",((Map<?,?>)input.get("_catalog")).get("1001"),"DEMO-SKU-BLUE-L",((Map<?,?>)input.get("_catalog")).get("1002")));
        return json.valueToTree(input);
    }
    Map<String,Object> order(String qty) {return run("orders",null,"create",command(Map.of("manual_source_note","fictional separate order request","save_mode","confirm","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1001","expected_units",qty)))));}
    Map<String,Object> run(String kind,Long id,String action,JsonNode body) {
        return json.convertValue(service.command(context,kind,id,action,body.path("operation_token").asText(),body),Map.class);
    }
    long id(Map<String,Object> document){return Long.parseLong(document.get("id").toString());}
    String line(Map<String,Object> document){return ((List<Map<String,Object>>)document.get("lines")).getFirst().get("id").toString();}
    JsonNode shipment(String qty,String line,String mode){return command(Map.of("overage_reason","fictional actual-shipment explanation","save_mode",mode,"business_date","2026-10-12","sources",List.of(Map.of("sku_id","1001","actual_units",qty,"allocations",List.of(Map.of("order_line_id",line,"units",qty))))));}
    @Test void productionProgressIsSeparateRevisionedAndIdempotent() {
        var order=order("100");
        assertEquals("0",((List<Map<String,Object>>)order.get("lines")).getFirst().get("produced_units"));
        var input=command(Map.of("expected_revision","1","effective_date","2026-10-22","reason","factory reports 80 completed","lines",List.of(Map.of("order_line_id",line(order),"produced_units","80"))));
        var changed=run("orders",id(order),"production-progress",input);
        assertEquals("80",((List<Map<String,Object>>)changed.get("lines")).getFirst().get("produced_units"));
        assertEquals("0",changed.get("actual_units"));assertEquals("0",changed.get("received_units"));
        assertEquals(changed,run("orders",id(order),"production-progress",input));
        assertEquals("2",changed.get("revision"));
        assertEquals("PRODUCTION_PROGRESS",((List<Map<String,Object>>)changed.get("history")).getFirst().get("operation_kind"));
        var stale=command(Map.of("expected_revision","1","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"produced_units","0"))));
        assertEquals("revision_conflict",assertThrows(ProductionError.class,()->run("orders",id(order),"production-progress",stale)).code);
        assertEquals("invalid_integer",assertThrows(ProductionError.class,()->run("orders",id(order),"production-progress",command(Map.of("expected_revision","2","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"produced_units","-1")))))).code);
        assertEquals("reason_required",assertThrows(ProductionError.class,()->run("orders",id(order),"production-progress",command(Map.of("expected_revision","2","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"produced_units","70")))))).code);
    }
    @Test void manualProductionStatusIsScopedRevisionedAndDoesNotChangeQuantities() {
        var order=order("100");
        db.update("UPDATE production_order_line SET produced_units=NULL WHERE site_id=? AND id=?",context.site(),line(order));
        var input=command(Map.of("expected_revision","1","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"production_status","等待面料 · 测试"))));
        var updated=run("orders",id(order),"production-progress",input);
        var item=((List<Map<String,Object>>)updated.get("lines")).getFirst();
        assertEquals("等待面料 · 测试",item.get("production_status"));
        assertNull(item.get("produced_units"));
        assertEquals("0",updated.get("actual_units"));assertEquals("0",updated.get("received_units"));
        assertEquals(updated,run("orders",id(order),"production-progress",input));
        assertEquals("PRODUCTION_STATUS",((List<Map<String,Object>>)updated.get("history")).getFirst().get("operation_kind"));
        assertEquals("revision_conflict",assertThrows(ProductionError.class,()->run("orders",id(order),"production-progress",command(Map.of("expected_revision","1","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"production_status","覆盖")))))).code);
        var other=order("10");
        assertEquals("order_link_invalid",assertThrows(ProductionError.class,()->run("orders",id(order),"production-progress",command(Map.of("expected_revision","2","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(other),"production_status","错单")))))).code);
        var viewer=new ProductionContext(context.site(),2,Set.of("viewer"));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->service.command(viewer,"orders",id(order),"production-progress",input.path("operation_token").asText(),input)).code);
        var cleared=run("orders",id(order),"production-progress",command(Map.of("expected_revision","2","effective_date","2026-10-22","lines",List.of(Map.of("order_line_id",line(order),"production_status","")))));
        assertEquals("",((List<Map<String,Object>>)cleared.get("lines")).getFirst().get("production_status"));
        assertNull(((List<Map<String,Object>>)cleared.get("lines")).getFirst().get("produced_units"));
    }
    @Test void newDraftAndConfirmationStartUnproducedButLegacyUnknownIsPreserved() {
        var draft=run("orders",null,"create",command(Map.of("save_mode","draft","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1001","expected_units","20")))));
        assertEquals("0",((List<Map<String,Object>>)draft.get("lines")).getFirst().get("produced_units"));
        var confirmed=run("orders",id(draft),"confirm",command(Map.of("expected_revision","1","manual_source_note","new simulated order, not started")));
        assertEquals("0",((List<Map<String,Object>>)confirmed.get("lines")).getFirst().get("produced_units"));
        db.update("UPDATE production_order_line SET produced_units=NULL WHERE site_id=? AND order_id=?",context.site(),id(confirmed));
        var corrected=run("orders",id(confirmed),"correct",command(Map.of("expected_revision","2","business_date","2026-10-12","reason","correct legacy demand without inventing production","lines",List.of(Map.of("sku_id","1001","expected_units","21")))));
        assertNull(((List<Map<String,Object>>)corrected.get("lines")).getFirst().get("produced_units"));
    }
    @Test void factoriesAreSiteScopedSearchableAndNeverGuessedForLegacyOrders() {
        var input=command(Map.of("name","QA Factory Alpha"));
        var factory=json.convertValue(service.createFactory(context,input.path("operation_token").asText(),input),Map.class);
        assertEquals(factory,json.convertValue(service.createFactory(context,input.path("operation_token").asText(),input),Map.class));
        var order=run("orders",null,"create",command(Map.of("save_mode","confirm","business_date","2026-10-22","factory_id",factory.get("id"),"lines",List.of(Map.of("sku_id","1001","expected_units","100")))));
        assertEquals("QA Factory Alpha",order.get("factory_name"));
        assertEquals(1L,service.list(context,"orders","Alpha","","","","","",1,20,"",false,"").get("total"));
        assertEquals(1L,service.list(context,"orders","","","","","","",1,20,"",false,factory.get("id").toString()).get("total"));
        assertEquals("factory_scope_invalid",assertThrows(ProductionError.class,()->service.command(new ProductionContext(context.site()+2_000_000,1,Set.of("admin")),"orders",null,"create",input.path("operation_token").asText(),commandWithToken(Map.of("save_mode","draft","factory_id",factory.get("id"),"lines",List.of(Map.of("sku_id","1001","expected_units","1"))),input.path("operation_token").asText()))).code);
        var legacy=order("10");assertNull(legacy.get("factory_id"));assertNull(legacy.get("factory_name"));
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->service.createFactory(new ProductionContext(context.site(),2,Set.of("viewer")),input.path("operation_token").asText(),input)).code);
    }
    @Test void factoryCreationPersistsManagedProfileWithoutCreatingStock() {
        var input=command(Map.of("name","Managed factory","region","Guangzhou","contact","Demo contact"));
        var factory=json.convertValue(service.createFactory(context,input.path("operation_token").asText(),input),Map.class);
        assertEquals("1",factory.get("revision"));
        assertEquals("ACTIVE",factory.get("status"));
        assertEquals("Guangzhou",factory.get("region"));
        assertEquals("Demo contact",factory.get("contact"));
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=?",Long.class,context.site()));
    }
    Map<String,Object> directory(String kind,Long id,Map<String,Object> fields){var input=command(fields);return json.convertValue(service.directorySave(context,kind,id,input.path("operation_token").asText(),input),Map.class);}
    @Test void plannedReceiptWarehouseDoesNotRequireOpeningButRemainsScoped(){
        var warehouse=directory("warehouses",null,Map.of("name","QA planned empty warehouse","type","FACTORY","country","CN"));
        var input=command(Map.of("manual_source_note","fictional planned warehouse test","save_mode","confirm","business_date","2026-10-12","receipt_warehouse_id",warehouse.get("id"),"receipt_owner_id","1","lines",List.of(Map.of("sku_id","1001","expected_units","5"))));
        var order=run("orders",null,"create",input);
        assertEquals(warehouse.get("id"),order.get("receipt_warehouse_id"));
        assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=?",Integer.class,context.site()));
        assertEquals("warehouse_scope_invalid",assertThrows(ProductionError.class,()->run("orders",null,"create",command(Map.of("save_mode","draft","receipt_warehouse_id",warehouse.get("id"),"receipt_owner_id","99","lines",List.of(Map.of("sku_id","1001","expected_units","5")))))).code);
        var fba=directory("warehouses",null,Map.of("name","QA non receipt FBA","type","FBA","country","US","seller_account","QA account","marketplace","US"));
        var wrong=command(Map.of("save_mode","draft","receipt_warehouse_id",fba.get("id"),"receipt_owner_id","1","lines",List.of(Map.of("sku_id","1001","expected_units","5"))));
        assertEquals("warehouse_scope_invalid",assertThrows(ProductionError.class,()->run("orders",null,"create",wrong)).code);
        directory("warehouses",id(warehouse),Map.of("name","QA planned empty warehouse","status","INACTIVE","expected_revision","1","reason","test inactive directory"));
        assertEquals("warehouse_scope_invalid",assertThrows(ProductionError.class,()->run("orders",null,"create",command(Map.of("save_mode","draft","receipt_warehouse_id",warehouse.get("id"),"receipt_owner_id","1","lines",List.of(Map.of("sku_id","1001","expected_units","5")))))).code);
    }
    @Test void warehouseProfilesAreRevisionedScopedAndDoNotOpenInventory(){
        var warehouse=directory("warehouses",null,Map.of("name","QA overseas","type","THIRD_PARTY","country","US"));
        assertEquals("UNINITIALIZED",warehouse.get("inventory_state"));
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=?",Long.class,context.site()));
        var factory=directory("factories",null,Map.of("name","QA managed","warehouse_ids",List.of(warehouse.get("id"))));
        assertEquals(List.of(warehouse.get("id")),factory.get("warehouse_ids"));
        var input=command(Map.of("name","Renamed warehouse","expected_revision","1","reason","correct profile","status","INACTIVE"));
        var changed=json.convertValue(service.directorySave(context,"warehouses",id(warehouse),input.path("operation_token").asText(),input),Map.class);
        assertEquals("2",changed.get("revision"));assertEquals(2,((List<?>)changed.get("history")).size());
        assertEquals(changed,json.convertValue(service.directorySave(context,"warehouses",id(warehouse),input.path("operation_token").asText(),input),Map.class));
        assertEquals("warehouse_not_operational",assertThrows(ProductionError.class,()->ProductionDirectory.requireOperational(db,context.site(),id(warehouse))).code);
        assertEquals("revision_conflict",assertThrows(ProductionError.class,()->directory("warehouses",id(warehouse),Map.of("name","Stale","expected_revision","1","reason","stale"))).code);
        assertEquals("directory_not_found",assertThrows(ProductionError.class,()->service.directoryDetail(new ProductionContext(context.site()+2_000_000,1,Set.of("admin")),"warehouses",id(warehouse))).code);
        var fba=directory("warehouses",null,Map.of("name","FBA QA","type","FBA","country","US","seller_account","QA account","marketplace","US"));
        assertEquals("NOT_CONNECTED",fba.get("inventory_state"));
        assertEquals("warehouse_not_operational",assertThrows(ProductionError.class,()->ProductionDirectory.requireOperational(db,context.site(),id(fba))).code);
    }
    @Test void destinationUsesStableIdAndRetainsHistoricalSnapshot(){
        var destination=directory("warehouses",null,Map.of("name","QA receiving hub","type","LOCATION","country","CN"));
        var body=command(Map.of("save_mode","confirm","business_date","2026-10-23","destination_id",destination.get("id"),"destination_type","LOCATION","lines",List.of(Map.of("sku_id","1001","expected_units","10"))));
        var order=run("orders",null,"create",body);assertEquals(destination.get("id"),order.get("destination_id"));assertEquals("QA receiving hub",order.get("destination"));
        directory("warehouses",id(destination),Map.of("name","Renamed QA hub","expected_revision","1","reason","rename"));
        assertEquals("QA receiving hub",service.get(context,"orders",id(order)).get("destination"));
        var other=directory("warehouses",null,Map.of("name","QA second destination","type","THIRD_PARTY","country","US"));
        var firstBody=(tools.jackson.databind.node.ObjectNode)shipment("3",line(order),"confirm");firstBody.put("destination_id",destination.get("id").toString());firstBody.put("destination_type","LOCATION");
        var first=run("shipments",null,"create",firstBody);
        var secondBody=(tools.jackson.databind.node.ObjectNode)shipment("2",line(order),"confirm");secondBody.put("destination_id",other.get("id").toString());secondBody.put("destination_type","WAREHOUSE");
        var second=run("shipments",null,"create",secondBody);
        assertEquals("Renamed QA hub",first.get("destination"));assertEquals("QA second destination",second.get("destination"));
        var current=service.get(context,"orders",id(order));
        run("orders",id(order),"correct",command(Map.of("business_date","2026-10-23","expected_revision",current.get("revision"),"reason","change planned destination only","destination_id",other.get("id"),"destination_type","WAREHOUSE","lines",List.of(Map.of("sku_id","1001","expected_units","10")))));
        assertEquals(destination.get("id"),service.get(context,"shipments",id(first)).get("destination_id"));
        assertEquals("Renamed QA hub",service.get(context,"shipments",id(first)).get("destination"));
        assertEquals("directory_not_found",assertThrows(ProductionError.class,()->run("orders",null,"create",command(Map.of("save_mode","draft","destination_type","WAREHOUSE","destination_id","999999999","lines",List.of(Map.of("sku_id","1001","expected_units","1")))))).code);
    }
    JsonNode commandWithToken(Map<String,Object> body,String token){var result=(tools.jackson.databind.node.ObjectNode)command(body);result.put("operation_token",token);return result;}
    @Test void packingConservesSkuQuantitiesAndStoresDestination() {
        var order=order("100");
        var input=(tools.jackson.databind.node.ObjectNode)shipment("20",line(order),"draft");
        input.put("destination","fictional Guangzhou hub");
        input.set("cartons",json.valueToTree(List.of(Map.of("number","A001","items",List.of(Map.of("sku_id","1001","units","10"))))));
        var draft=run("shipments",null,"create",input);
        assertEquals("fictional Guangzhou hub",draft.get("destination"));
        assertEquals("carton_quantity_mismatch",assertThrows(ProductionError.class,()->run("shipments",id(draft),"confirm",command(Map.of("expected_revision","1")))).code);
        input.put("expected_revision","1");input.put("operation_token",UUID.randomUUID().toString());
        input.set("cartons",json.valueToTree(List.of(Map.of("number","A001","items",List.of(Map.of("sku_id","1001","units","20"))))));
        var ready=run("shipments",id(draft),"update",input);
        var confirmed=run("shipments",id(draft),"confirm",command(Map.of("expected_revision",ready.get("revision"))));
        assertEquals(1,((List<?>)confirmed.get("cartons")).size());assertEquals("20",service.get(context,"orders",id(order)).get("actual_units"));
        var box=(Map<?,?>)((List<?>)confirmed.get("cartons")).getFirst();assertNotNull(box.get("id"));
        var change=(tools.jackson.databind.node.ObjectNode)shipment("20",line(order),"confirm");change.put("expected_revision",confirmed.get("revision").toString());change.put("reason","correct destination");change.put("destination","fictional second hub");change.set("cartons",json.valueToTree(confirmed.get("cartons")));
        var corrected=run("shipments",id(draft),"correct",change);assertEquals(box.get("id"),((Map<?,?>)((List<?>)corrected.get("cartons")).getFirst()).get("id"));
    }
    @Test void batchesCorrectionsVoidAndSignedOverage() {
        var order=order("100");var first=run("shipments",null,"create",shipment("40",line(order),"confirm"));var second=run("shipments",null,"create",shipment("30",line(order),"confirm"));
        assertEquals("70",service.get(context,"orders",id(order)).get("actual_units"));
        var correction=(tools.jackson.databind.node.ObjectNode)shipment("35",line(order),"confirm");correction.put("expected_revision","1");correction.put("reason","correct 40 to 35");var changed=run("shipments",id(first),"correct",correction);
        assertEquals("65",service.get(context,"orders",id(order)).get("actual_units"));assertEquals(2,((List<?>)changed.get("history")).size());
        run("shipments",id(first),"void",command(Map.of("expected_revision","2","reason","void corrected record")));
        assertEquals("30",service.get(context,"orders",id(order)).get("actual_units"));
        run("shipments",null,"create",shipment("80",line(order),"confirm"));assertEquals("-10",service.get(context,"orders",id(order)).get("difference_units"));
        var draft=run("shipments",null,"create",shipment("10",line(order),"draft"));assertEquals("110",service.get(context,"orders",id(order)).get("actual_units"));
        run("shipments",id(draft),"delete",command(Map.of("expected_revision","1")));
        assertNotNull(second);
    }
    @Test void idempotencyAndPrecisionAreStable() {
        var input=command(Map.of("save_mode","confirm","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1001","expected_units","9007199254740993"))));
        var first=run("orders",null,"create",input);var replay=run("orders",null,"create",input);
        assertEquals(first,replay);assertEquals("9007199254740993",first.get("expected_units"));
        ((tools.jackson.databind.node.ObjectNode)input).put("notes","changed");assertEquals("idempotency_content_conflict",assertThrows(ProductionError.class,()->run("orders",null,"create",input)).code);
    }
    @Test void allocationsAndReferencesHaveRealBoundaries() {
        var a=order("100");var b=order("100");
        var cross=command(Map.of("save_mode","confirm","business_date","2026-10-12","sources",List.of(Map.of("sku_id","1001","actual_units","70","allocations",List.of(Map.of("order_line_id",line(a),"units","40"),Map.of("order_line_id",line(b),"units","30"))))));
        run("shipments",null,"create",cross);assertEquals("40",service.get(context,"orders",id(a)).get("actual_units"));assertEquals("30",service.get(context,"orders",id(b)).get("actual_units"));
        assertEquals("downstream_shipment_exists",assertThrows(ProductionError.class,()->run("orders",id(a),"void",command(Map.of("expected_revision",service.get(context,"orders",id(a)).get("revision"),"reason","invalid void")))).code);
        var wrong=(tools.jackson.databind.node.ObjectNode)shipment("10",line(a),"confirm");((tools.jackson.databind.node.ObjectNode)wrong.path("sources").get(0)).put("sku_id","1002");assertEquals("order_link_invalid",assertThrows(ProductionError.class,()->run("shipments",null,"create",wrong)).code);
        var partial=(tools.jackson.databind.node.ObjectNode)shipment("10",line(a),"confirm");((tools.jackson.databind.node.ObjectNode)partial.path("sources").get(0)).put("actual_units","20");assertEquals("allocation_incomplete",assertThrows(ProductionError.class,()->run("shipments",null,"create",partial)).code);
        assertEquals("document_not_found",assertThrows(ProductionError.class,()->service.get(new ProductionContext(context.site()+2_000_000,1,Set.of("admin")),"orders",id(a))).code);
        assertEquals("role_forbidden",assertThrows(ProductionError.class,()->service.command(new ProductionContext(context.site(),2,Set.of("viewer")),"orders",null,"create",cross.path("operation_token").asText(),cross)).code);
    }
    @Test void staleRevisionCannotOverwrite() {
        var a=order("100");JsonNode input=command(Map.of("expected_revision","1","business_date","2026-10-12","reason","first","lines",List.of(Map.of("sku_id","1001","expected_units","90"))));run("orders",id(a),"correct",input);
        ((tools.jackson.databind.node.ObjectNode)input).put("operation_token",UUID.randomUUID().toString());assertEquals("revision_conflict",assertThrows(ProductionError.class,()->run("orders",id(a),"correct",input)).code);
    }
    @Test void simultaneousVoidAndShipmentNeverOrphan() throws Exception {
        var a=order("100");var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            Future<Boolean> shipment=pool.submit(()->{start.await();try{run("shipments",null,"create",shipment("40",line(a),"confirm"));return true;}catch(ProductionError e){return false;}});
            Future<Boolean> voidOrder=pool.submit(()->{start.await();try{run("orders",id(a),"void",command(Map.of("expected_revision","1","reason","concurrency check")));return true;}catch(ProductionError e){return false;}});
            start.countDown();boolean shipped=shipment.get(15,TimeUnit.SECONDS),voided=voidOrder.get(15,TimeUnit.SECONDS);assertNotEquals(shipped,voided);
            var result=service.get(context,"orders",id(a));assertEquals(shipped?"CONFIRMED":"VOID",result.get("status"));assertEquals(shipped?"40":"0",result.get("actual_units"));
        }
    }
    JsonNode fileInput(String kind,String quantity,String sku,String orderNumber,Long target,String reason,boolean formula) throws Exception {
        try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook();var output=new java.io.ByteArrayOutputStream()) {
            var sheet=book.createSheet(kind.equals("orders")?"预计订单_v1":"实际出货_v1");
            List<String> headers=kind.equals("orders")?List.of("业务订单号","下单日期","SKU","预计数量","备注"):List.of("业务出货单号","实际出货日期","对应系统订单号","SKU","本次实际出货数量","备注");
            var head=sheet.createRow(0);for(int i=0;i<headers.size();i++)head.createCell(i).setCellValue(headers.get(i));
            List<String> values=kind.equals("orders")?List.of("DEMO-EXCEL","2026-10-12",sku,quantity,"fictional"):List.of("DEMO-EXCEL-SHIP","2026-10-12",orderNumber,sku,quantity,"fictional");
            var row=sheet.createRow(1);for(int i=0;i<values.size();i++)row.createCell(i).setCellValue(values.get(i));
            if(formula)row.getCell(kind.equals("orders")?3:4).setCellFormula("20+20");
            book.write(output);var body=new LinkedHashMap<String,Object>();body.put("filename","fictional.xlsx");body.put("file_base64",Base64.getEncoder().encodeToString(output.toByteArray()));body.put("mode",target==null?"create":"correct");body.put("reason",reason);if(target!=null)body.put("target_id",target.toString());return command(body);
        }
    }
    @Test void workbenchExcelKeepsContextAndCreatesOnlyAnIdempotentDraft() throws Exception {
        var factory=directory("factories",null,Map.of("name","QA import factory"));
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,900,2,'QA warehouse','QA owner','2026-10-23','fictional import scope',?)",context.site(),UUID.randomUUID().toString());
        var destination=directory("warehouses",null,Map.of("name","QA import destination","type","LOCATION","country","CN"));
        var input=(tools.jackson.databind.node.ObjectNode)fileInput("orders","17","DEMO-SKU-BLUE-M","",null,"",false);
        input.put("workbench_order",true);input.put("factory_id",factory.get("id").toString());input.put("receipt_warehouse_id","900");input.put("receipt_owner_id","2");input.put("destination_id",destination.get("id").toString());input.put("destination_type","LOCATION");
        var preview=json.valueToTree(files.preview(context,"orders",input));
        assertTrue(preview.path("issues").isEmpty());assertEquals("draft",preview.path("command").path("save_mode").asText());
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM production_order WHERE site_id=?",Long.class,context.site()));
        var confirm=command(Map.of());var saved=json.convertValue(files.confirm(context,preview.path("preview_id").asText(),confirm.path("operation_token").asText(),confirm),Map.class);
        assertEquals("DRAFT",saved.get("status"));assertEquals(factory.get("id"),saved.get("factory_id"));assertEquals("900",saved.get("receipt_warehouse_id"));assertEquals("2",saved.get("receipt_owner_id"));assertEquals("QA import destination",saved.get("destination"));
        assertEquals("17",saved.get("expected_units"));assertEquals("0",saved.get("actual_units"));assertFalse(((List<?>)saved.get("file_sources")).isEmpty());
        var retry=command(Map.of());assertEquals(saved.get("id"),json.convertValue(files.confirm(context,preview.path("preview_id").asText(),retry.path("operation_token").asText(),retry),Map.class).get("id"));
        assertThrows(ProductionError.class,()->files.confirm(new ProductionContext(context.site(),2,Set.of("admin")),preview.path("preview_id").asText(),retry.path("operation_token").asText(),retry));
        var invalid=input.deepCopy();invalid.put("receipt_owner_id","99");assertThrows(ProductionError.class,()->files.preview(context,"orders",invalid));
        var foreign=input.deepCopy();foreign.put("factory_id","9223372036854775806");assertThrows(ProductionError.class,()->files.preview(context,"orders",foreign));
        var next=input.deepCopy();next.put("file_base64",fileInput("orders","18","DEMO-SKU-BLUE-M","",null,"",false).path("file_base64").asText());
        var stale=json.valueToTree(files.preview(context,"orders",next));directory("factories",id(factory),Map.of("name","QA import factory","status","INACTIVE","expected_revision","1","reason","QA stop new orders"));
        var operation=command(Map.of());assertEquals("factory_inactive",assertThrows(ProductionError.class,()->files.confirm(context,stale.path("preview_id").asText(),operation.path("operation_token").asText(),operation)).code);
    }
    @Test void workbenchV3UsesScopedIdsAndRejectsDuplicateOrForeignSpecs() throws Exception {
        var factory=directory("factories",null,Map.of("name","QA v3 factory"));
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,900,1,'QA warehouse','QA owner','2026-10-23','QA v3',?)",context.site(),UUID.randomUUID().toString());
        for(String variant:List.of("valid","unknown","duplicate"))try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(files.template("orders","v3")));var output=new java.io.ByteArrayOutputStream()) {
            var sheet=book.getSheetAt(0);var row=sheet.createRow(1);
            List<String> values=List.of("QA-V3","2026-10-23",variant.equals("unknown")?"999999999":"1001","8","fictional","","","","","");
            for(int i=0;i<values.size();i++)row.createCell(i).setCellValue(values.get(i));
            if(variant.equals("duplicate")){var repeated=sheet.createRow(2);for(int i=0;i<values.size();i++)repeated.createCell(i).setCellValue(values.get(i));}
            book.write(output);
            var body=(tools.jackson.databind.node.ObjectNode)command(Map.of("workbench_order",true,"factory_id",factory.get("id"),"receipt_warehouse_id","900","receipt_owner_id","1","file_base64",Base64.getEncoder().encodeToString(output.toByteArray()),"filename","qa-v3.xlsx","mode","create"));
            body.remove("_resolved_codes");((tools.jackson.databind.node.ObjectNode)body.path("_catalog").path("1001")).put("code","");
            var preview=json.valueToTree(files.preview(context,"orders",body));
            assertEquals(variant.equals("valid"),preview.path("issues").isEmpty());
            if(variant.equals("valid")) {
                assertEquals("1001",preview.path("rows").get(0).path("sku_id").asText());
                var save=command(Map.of());assertEquals("DRAFT",json.convertValue(files.confirm(context,preview.path("preview_id").asText(),save.path("operation_token").asText(),save),Map.class).get("status"));
                body.put("workbench_order",false);assertThrows(ProductionError.class,()->files.preview(context,"orders",body));
            }
        }
    }
    @Test void excelUsesSameCoreAndRejectsInvalidRows() throws Exception {
        var p=json.valueToTree(files.preview(context,"orders",fileInput("orders","100","DEMO-SKU-BLUE-M","",null,"",false)));
        assertTrue(p.path("issues").isEmpty());var confirm=command(Map.of());String token=confirm.path("operation_token").asText();
        var saved=json.convertValue(files.confirm(context,p.path("preview_id").asText(),token,confirm),Map.class);
        var replay=json.convertValue(files.confirm(context,p.path("preview_id").asText(),token,confirm),Map.class);assertEquals(saved,replay);
        var second=command(Map.of());var duplicate=json.convertValue(files.confirm(context,p.path("preview_id").asText(),second.path("operation_token").asText(),second),Map.class);assertEquals(saved.get("id"),duplicate.get("id"));assertEquals("1",duplicate.get("revision"));
        assertFalse(json.valueToTree(files.preview(context,"orders",fileInput("orders","40","UNKNOWN","",null,"",false))).path("issues").isEmpty());
        assertFalse(json.valueToTree(files.preview(context,"orders",fileInput("orders","40","DEMO-SKU-BLUE-M","",null,"",true))).path("issues").isEmpty());
        assertFalse(json.valueToTree(files.preview(context,"shipments",fileInput("shipments","40","DEMO-SKU-BLUE-M","PO-UNKNOWN",null,"",false))).path("issues").isEmpty());
        byte[] export=files.export(context,"orders","","","","","","","","");
        try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(export))) {assertEquals("100",book.getSheetAt(0).getRow(1).getCell(5).getStringCellValue());}
    }
    @Test void staleExcelPreviewCannotCorrectNewRevision() throws Exception {
        var a=order("100");var p=json.valueToTree(files.preview(context,"orders",fileInput("orders","90","DEMO-SKU-BLUE-M","",id(a),"file correction",false)));
        run("orders",id(a),"correct",command(Map.of("expected_revision","1","business_date","2026-10-12","reason","another editor","lines",List.of(Map.of("sku_id","1001","expected_units","80")))));
        var confirm=command(Map.of());assertEquals("revision_conflict",assertThrows(ProductionError.class,()->files.confirm(context,p.path("preview_id").asText(),confirm.path("operation_token").asText(),confirm)).code);
        assertEquals("80",service.get(context,"orders",id(a)).get("expected_units"));
    }
    static class QueryCounter extends JdbcTemplate {
        int queries; final List<String> sql=new ArrayList<>();
        QueryCounter(javax.sql.DataSource source){super(source);}
        @Override public <T> List<T> query(String statement,org.springframework.jdbc.core.RowMapper<T> mapper,Object... args) {
            queries++;sql.add(statement);return super.query(statement,mapper,args);
        }
    }
    @Test void listQueriesStayBoundedAndCandidatesFilterBeforePagination() {
        for(int i=0;i<8;i++)order("100");
        run("orders",null,"create",command(Map.of("save_mode","confirm","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1002","expected_units","25")))));
        var counter=new QueryCounter(db.getDataSource());var read=new ProductionService(counter,json,"demo_fixed");
        read.list(context,"orders","","CONFIRMED","","","","",1,1);int one=counter.queries;
        counter.queries=0;counter.sql.clear();read.list(context,"orders","","CONFIRMED","","","","",1,8);
        assertEquals(one,counter.queries,"List query count must not grow with page rows");
        assertTrue(counter.sql.stream().noneMatch(sql->sql.contains("production_revision")&&(sql.contains("before_value")||sql.contains("after_value")||sql.contains("SELECT *"))),"List must not load detail history");
        var page=read.list(context,"orders","","CONFIRMED","","","1002","",1,1);
        assertEquals(1L,page.get("total"));assertEquals(1,((List<?>)page.get("items")).size());
    }
    @Test void shipmentPeriodKeepsFullCumulativeQuantitySeparate() {
        var a=order("100");run("shipments",null,"create",shipment("40",line(a),"confirm"));
        var later=(tools.jackson.databind.node.ObjectNode)shipment("30",line(a),"confirm");later.put("business_date","2026-10-13");run("shipments",null,"create",later);
        var period=service.summary(context,"","","2026-10-12","2026-10-12","",a.get("system_number").toString());
        assertEquals("40",period.get("actual_units"));assertEquals("70",period.get("cumulative_actual_units"));
        assertEquals("30",period.get("cumulative_difference_units"));
    }
    @Test void shipmentListIncludesScopedAllocationsWithoutGrowingQueryCount() {
        var a=order("100");var b=order("100");
        var body=shipment("40",line(a),"confirm").deepCopy();
        ((tools.jackson.databind.node.ObjectNode)body.path("sources").get(0)).set("allocations",json.valueToTree(List.of(Map.of("order_line_id",line(a),"units","25"),Map.of("order_line_id",line(b),"units","15"))));
        run("shipments",null,"create",body);run("shipments",null,"create",shipment("10",line(a),"confirm"));
        var counter=new QueryCounter(db.getDataSource());var read=new ProductionService(counter,json,"demo_fixed");
        read.list(context,"shipments","","","","","","",1,1);int one=counter.queries;counter.queries=0;
        var page=read.list(context,"shipments","","","","","","",1,20);
        assertEquals(one,counter.queries);var items=(List<Map<String,Object>>)page.get("items");
        var forty=items.stream().filter(item->item.get("actual_units").equals("40")).findFirst().orElseThrow();
        var source=((List<Map<String,Object>>)forty.get("sources")).getFirst();var allocations=(List<Map<String,Object>>)source.get("allocations");
        assertEquals(2,allocations.size());assertEquals("40",source.get("actual_units"));
        assertEquals(Set.of(a.get("system_number"),b.get("system_number")),allocations.stream().map(item->item.get("order_number")).collect(java.util.stream.Collectors.toSet()));
        var other=new ProductionContext(context.site()+2_000_000,context.actor(),context.roles());
        assertEquals(0L,read.list(other,"shipments","","","","","","",1,20).get("total"));
    }
    Map<String,Object> changeOrder(long id,String action,Map<String,Object> payload) {
        var body=new LinkedHashMap<>(payload);body.put("expected_revision",service.get(context,"orders",id).get("revision"));body.putIfAbsent("reason","fictional contract reason");
        return run("orders",id,action,command(body));
    }
    @Test void closeReopenAndHistoricalSupplementRetainEachCommittedStep() {
        var a=order("100");run("shipments",null,"create",shipment("40",line(a),"confirm"));run("shipments",null,"create",shipment("30",line(a),"confirm"));
        var closed=changeOrder(id(a),"close-tracking",Map.of());assertEquals("30",closed.get("closed_units"));assertEquals("0",closed.get("pending_units"));assertEquals("70",closed.get("actual_units"));
        assertEquals("tracking_closed",assertThrows(ProductionError.class,()->run("shipments",null,"create",shipment("10",line(a),"confirm"))).code);
        var opened=changeOrder(id(a),"reopen-tracking",Map.of());assertEquals("0",opened.get("closed_units"));assertEquals("30",opened.get("pending_units"));
        var bad=(tools.jackson.databind.node.ObjectNode)shipment("10",line(a),"confirm");bad.put("business_date","not-date");assertThrows(ProductionError.class,()->run("shipments",null,"create",bad));
        assertEquals("OPEN",service.get(context,"orders",id(a)).get("tracking_state"));assertEquals("70",service.get(context,"orders",id(a)).get("actual_units"));
        var old=(tools.jackson.databind.node.ObjectNode)shipment("10",line(a),"confirm");old.put("business_date","2026-09-29");run("shipments",null,"create",old);
        var stale=command(Map.of("expected_revision",opened.get("revision"),"reason","stale reclose"));assertEquals("revision_conflict",assertThrows(ProductionError.class,()->run("orders",id(a),"close-tracking",stale)).code);
        var result=changeOrder(id(a),"close-tracking",Map.of());assertEquals("80",result.get("actual_units"));assertEquals("20",result.get("closed_units"));
        var events=(List<Map<String,Object>>)result.get("history");assertTrue(events.stream().anyMatch(x->x.get("operation_kind").equals("CLOSE_TRACKING")&&x.get("after_value").toString().contains("30")));
    }
    @Test void demandChangeAndDataCorrectionHaveDifferentHistoryAndStableRows() {
        var a=order("100");String original=line(a);run("shipments",null,"create",shipment("70",original,"confirm"));
        var changed=changeOrder(id(a),"demand-changes",Map.of("effective_date","2026-10-13","lines",List.of(Map.of("sku_id","1001","expected_units","150"),Map.of("sku_id","1002","expected_units","25"))));
        assertEquals(original,line(changed));assertEquals("175",changed.get("expected_units"));assertEquals("70",changed.get("actual_units"));
        assertEquals("DEMAND_CHANGE",((List<Map<String,Object>>)changed.get("history")).getFirst().get("operation_kind"));
        var corrected=changeOrder(id(a),"correct",Map.of("business_date","2026-10-12","lines",List.of(Map.of("sku_id","1001","expected_units","60"),Map.of("sku_id","1002","expected_units","25")),"overage_reason","correct wrongly recorded demand"));
        assertEquals("DATA_CORRECTION",((List<Map<String,Object>>)corrected.get("history")).getFirst().get("operation_kind"));assertEquals("10",corrected.get("overage_units"));
    }
    @Test void allocationCorrectionKeepsSourceAndAllocationIdentityAndChecksBothOrders() {
        var a=order("100");var b=order("100");var sh=run("shipments",null,"create",shipment("40",line(a),"confirm"));
        var source=((List<Map<String,Object>>)sh.get("sources")).getFirst();String sourceId=source.get("id").toString();String allocationId=((List<Map<String,Object>>)source.get("allocations")).getFirst().get("id").toString();
        var sources=List.of(Map.of("id",sourceId,"sku_id","1001","actual_units","40","allocations",List.of(Map.of("order_line_id",line(a),"units","25"),Map.of("order_line_id",line(b),"units","15"))));
        changeOrder(id(b),"close-tracking",Map.of());
        var body=command(Map.of("expected_revision","1","reason","redistribute","sources",sources));assertEquals("tracking_closed",assertThrows(ProductionError.class,()->run("shipments",id(sh),"allocation-corrections",body)).code);
        changeOrder(id(b),"reopen-tracking",Map.of());var result=run("shipments",id(sh),"allocation-corrections",body);
        var next=((List<Map<String,Object>>)result.get("sources")).getFirst();assertEquals(sourceId,next.get("id"));assertEquals("40",next.get("actual_units"));
        assertEquals(allocationId,((List<Map<String,Object>>)next.get("allocations")).getFirst().get("id"));
        assertEquals("25",service.get(context,"orders",id(a)).get("actual_units"));assertEquals("15",service.get(context,"orders",id(b)).get("actual_units"));
        var correction=(tools.jackson.databind.node.ObjectNode)shipment("35",line(a),"confirm");correction.put("expected_revision","2");correction.put("reason","real quantity correction");var corrected=run("shipments",id(sh),"correct",correction);
        assertEquals(sourceId,((List<Map<String,Object>>)corrected.get("sources")).getFirst().get("id"));assertEquals("35",corrected.get("actual_units"));
    }
    @Test void lineLevelPendingAndOverageNeverCancelEachOther() {
        var a=run("orders",null,"create",command(Map.of("save_mode","confirm","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1001","expected_units","100"),Map.of("sku_id","1002","expected_units","100")))));
        var ls=(List<Map<String,Object>>)a.get("lines");run("shipments",null,"create",command(Map.of("save_mode","confirm","business_date","2026-10-12","overage_reason","actual already shipped","sources",List.of(Map.of("sku_id","1001","actual_units","110","allocations",List.of(Map.of("order_line_id",ls.get(0).get("id"),"units","110"))),Map.of("sku_id","1002","actual_units","90","allocations",List.of(Map.of("order_line_id",ls.get(1).get("id"),"units","90")))))));
        var result=service.get(context,"orders",id(a));assertEquals("0",result.get("difference_units"));assertEquals("10",result.get("pending_units"));assertEquals("10",result.get("overage_units"));
        var partial=changeOrder(id(a),"close-tracking",Map.of("line_ids",List.of(ls.get(1).get("id"))));assertEquals("PARTIAL_CLOSED",partial.get("tracking_state"));assertEquals("0",partial.get("pending_units"));
    }
    @Test void closeRacesWithShipmentAndDemandUsingTheAggregateRevision() throws Exception {
        for(String rival:List.of("shipment","demand")) {
            var a=order("100");var start=new CountDownLatch(1);
            try(var pool=Executors.newFixedThreadPool(2)) {
                Future<Boolean> close=pool.submit(()->{start.await();try{run("orders",id(a),"close-tracking",command(Map.of("expected_revision","1","reason","close concurrently")));return true;}catch(ProductionError e){return false;}});
                Future<Boolean> other=pool.submit(()->{start.await();try{if(rival.equals("shipment"))run("shipments",null,"create",shipment("40",line(a),"confirm"));else run("orders",id(a),"demand-changes",command(Map.of("expected_revision","1","effective_date","2026-10-12","reason","legitimate addition","lines",List.of(Map.of("sku_id","1001","expected_units","150")))));return true;}catch(ProductionError e){return false;}});
                start.countDown();assertNotEquals(close.get(15,TimeUnit.SECONDS),other.get(15,TimeUnit.SECONDS),"Only one stale aggregate command may succeed");
            }
        }
    }
    @Test void overageWithoutExplanationRollsBackAndSourceReplacementKeepsEvidence() {
        var a=order("100");var input=(tools.jackson.databind.node.ObjectNode)shipment("110",line(a),"confirm");input.remove("overage_reason");
        assertEquals("overage_reason_required",assertThrows(ProductionError.class,()->run("shipments",null,"create",input)).code);assertEquals("0",service.get(context,"orders",id(a)).get("actual_units"));
        var b=run("orders",null,"create",command(Map.of("save_mode","confirm","business_date","2026-10-12","lines",List.of(Map.of("sku_id","1002","expected_units","100")))));
        var sh=run("shipments",null,"create",shipment("40",line(a),"confirm"));var original=((List<Map<String,Object>>)sh.get("sources")).getFirst();
        var bad=command(Map.of("expected_revision","1","reason","wrong sku","business_date","2026-10-12","sources",List.of(Map.of("id",original.get("id"),"sku_id","1002","actual_units","40","allocations",List.of(Map.of("order_line_id",line(b),"units","40"))))));
        assertEquals("source_identity_replacement_required",assertThrows(ProductionError.class,()->run("shipments",id(sh),"correct",bad)).code);
        var replaced=run("shipments",id(sh),"correct",command(Map.of("expected_revision","1","reason","replace wrongly recorded sku","business_date","2026-10-12","sources",List.of(Map.of("replaces_source_id",original.get("id"),"sku_id","1002","actual_units","40","allocations",List.of(Map.of("order_line_id",line(b),"units","40")))))));
        var next=((List<Map<String,Object>>)replaced.get("sources")).getFirst();assertNotEquals(original.get("id"),next.get("id"));assertEquals(original.get("id"),next.get("replaces_source_id"));
        assertEquals(1L,db.queryForObject("SELECT COUNT(*) FROM production_shipment_source_line WHERE site_id=? AND id=? AND is_active=FALSE",Long.class,context.site(),original.get("id")));
    }

    tools.jackson.databind.node.ObjectNode reliable(JsonNode body,String external) {
        var node=(tools.jackson.databind.node.ObjectNode)body.deepCopy();node.put("source_system","FICTIONAL-FACTORY");node.put("source_event_kind","OUTWARD_DISPATCH");node.put("external_event_id",external);node.put("dispatch_purpose","OUTWARD_ORDER");return node;
    }
    JsonNode sourceFile(Map<String,Object> a,String quantity,String external,String batch) throws Exception {
        try(var book=new org.apache.poi.xssf.usermodel.XSSFWorkbook(new java.io.ByteArrayInputStream(files.template("shipments","v2")));var out=new java.io.ByteArrayOutputStream()) {
            var row=book.getSheetAt(0).createRow(1);var values=List.of("DISPLAY-ONLY","2026-10-12",a.get("system_number").toString(),"DEMO-SKU-BLUE-M",quantity,"different comment","FICTIONAL-FACTORY","OUTWARD_DISPATCH",external,batch,"fictional source","OUTWARD_ORDER");
            for(int i=0;i<values.size();i++)row.createCell(i).setCellValue(values.get(i));book.write(out);
            return command(Map.of("file_base64",Base64.getEncoder().encodeToString(out.toByteArray()),"filename","source-v2.xlsx","mode","create"));
        }
    }
    @Test void outwardDispatchRejectsCompletionInternalReceiptAndPureTransfer() {
        var a=order("100");
        for(String purpose:List.of("PRODUCTION_COMPLETION","INTERNAL_HANDOVER","WAREHOUSE_RECEIPT","LOGISTICS_TRANSFER")) {
            var body=(tools.jackson.databind.node.ObjectNode)shipment("40",line(a),"confirm");body.put("dispatch_purpose",purpose);
            assertEquals("not_order_dispatch",assertThrows(ProductionError.class,()->run("shipments",null,"create",body)).code);assertEquals("0",service.get(context,"orders",id(a)).get("actual_units"));
        }
        var draft=reliable(shipment("40",line(a),"draft"),"draft-outward");var saved=run("shipments",null,"create",draft);assertEquals("0",service.get(context,"orders",id(a)).get("actual_units"));
        run("shipments",id(saved),"confirm",command(Map.of("expected_revision",saved.get("revision"))));assertEquals("40",service.get(context,"orders",id(a)).get("actual_units"));
        assertEquals("LEGACY_UNCLASSIFIED",run("shipments",null,"create",shipment("10",line(a),"draft")).get("dispatch_purpose"));
    }
    @Test void reliableSourceUnifiesManualExcelAndDifferentBatches() throws Exception {
        var a=order("100");var manual=reliable(shipment("40",line(a),"confirm"),"EXT-001");var first=run("shipments",null,"create",manual);
        String orderRevision=service.get(context,"orders",id(a)).get("revision").toString();
        var preview=json.valueToTree(files.preview(context,"shipments",sourceFile(a,"40","EXT-001","")));assertTrue(preview.path("issues").isEmpty());assertTrue(preview.path("source_check").path("content_matches").asBoolean());
        assertTrue(preview.path("order_impact").isEmpty());assertEquals(first.get("id").toString(),preview.path("duplicate_document").path("id").asText());
        var confirm=command(Map.of());var duplicate=json.convertValue(files.confirm(context,preview.path("preview_id").asText(),confirm.path("operation_token").asText(),confirm),Map.class);
        assertEquals(first.get("id"),duplicate.get("id"));assertEquals(orderRevision,service.get(context,"orders",id(a)).get("revision"));assertEquals("40",service.get(context,"orders",id(a)).get("actual_units"));
        var contradictory=reliable(shipment("40",line(a),"confirm"),"ANOTHER-EVENT");contradictory.put("_source_digest",preview.path("digest").asText());assertEquals("file_source_conflict",assertThrows(ProductionError.class,()->run("shipments",null,"create",contradictory)).code);
        var displayOnly=(tools.jackson.databind.node.ObjectNode)manual.deepCopy();displayOnly.put("operation_token",UUID.randomUUID().toString());displayOnly.put("business_number","another display label");displayOnly.put("notes","another comment");assertEquals(first.get("id"),run("shipments",null,"create",displayOnly).get("id"));
        var draftBody=reliable(shipment("40",line(a),"draft"),"EXT-001");var draft=run("shipments",null,"create",draftBody);
        var confirmedDraft=run("shipments",id(draft),"confirm",command(Map.of("expected_revision",draft.get("revision"))));assertEquals(first.get("id"),confirmedDraft.get("id"));assertEquals("DRAFT",service.get(context,"shipments",id(draft)).get("status"));assertEquals("40",service.get(context,"orders",id(a)).get("actual_units"));
        var changed=reliable(shipment("35",line(a),"confirm"),"EXT-001");assertEquals("business_source_conflict",assertThrows(ProductionError.class,()->run("shipments",null,"create",changed)).code);
        var next=reliable(shipment("40",line(a),"confirm"),"EXT-001");next.put("source_batch","BATCH-2");var second=run("shipments",null,"create",next);assertNotEquals(first.get("id"),second.get("id"));assertEquals("80",service.get(context,"orders",id(a)).get("actual_units"));
        var wrong=command(Map.of("expected_revision","1","reason","cannot change event","business_date","2026-10-12","source_system","OTHER","sources",first.get("sources")));
        assertEquals("source_identity_immutable",assertThrows(ProductionError.class,()->run("shipments",id(first),"correct",wrong)).code);
    }
    @Test void reliableSourceConcurrentRequestsCreateOnlyOneFact() throws Exception {
        var a=order("100");var start=new CountDownLatch(1);
        try(var pool=Executors.newFixedThreadPool(2)) {
            var one=pool.submit(()->{start.await();return run("shipments",null,"create",reliable(shipment("40",line(a),"confirm"),"CONCURRENT"));});
            var two=pool.submit(()->{start.await();return run("shipments",null,"create",reliable(shipment("40",line(a),"confirm"),"CONCURRENT"));});
            start.countDown();assertEquals(one.get(15,TimeUnit.SECONDS).get("id"),two.get(15,TimeUnit.SECONDS).get("id"));
        }assertEquals("40",service.get(context,"orders",id(a)).get("actual_units"));assertEquals(1L,db.queryForObject("SELECT COUNT(*) FROM production_shipment WHERE site_id=?",Long.class,context.site()));
    }
    @Test void unknownSourceWarnsButLegitimateEqualQuantityRemainsAllowed() {
        var a=order("100");var first=run("shipments",null,"create",shipment("40",line(a),"confirm"));var next=shipment("40",line(a),"confirm");
        db.update("UPDATE production_shipment SET source_signature=NULL WHERE site_id=? AND id=?",context.site(),id(first)); // represents an unchanged pre-V4 fact
        assertEquals(1,((List<?>)service.checkSource(context,"shipments",next).get("candidates")).size());
        assertEquals("suspected_duplicate_review_required",assertThrows(ProductionError.class,()->run("shipments",null,"create",next)).code);
        ((tools.jackson.databind.node.ObjectNode)next).put("manual_source_note","checked: another outward handover, original manual sheet B");var second=run("shipments",null,"create",next);
        assertNotEquals(first.get("id"),second.get("id"));assertEquals("80",service.get(context,"orders",id(a)).get("actual_units"));
    }
    @Test void staleFileConfirmationRechecksClosureAndFreshSkuAndRollsBack() throws Exception {
        var a=order("100");var preview=json.valueToTree(files.preview(context,"shipments",fileInput("shipments","40","DEMO-SKU-BLUE-M",a.get("system_number").toString(),null,"",false)));
        changeOrder(id(a),"close-tracking",Map.of());var confirm=command(Map.of());assertEquals("revision_conflict",assertThrows(ProductionError.class,()->files.confirm(context,preview.path("preview_id").asText(),confirm.path("operation_token").asText(),confirm)).code);
        assertEquals("0",service.get(context,"orders",id(a)).get("actual_units"));assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM production_shipment WHERE site_id=?",Long.class,context.site()));
        changeOrder(id(a),"reopen-tracking",Map.of());var fresh=json.valueToTree(files.preview(context,"shipments",fileInput("shipments","40","DEMO-SKU-BLUE-M",a.get("system_number").toString(),null,"",false)));
        var deactivated=(tools.jackson.databind.node.ObjectNode)command(Map.of());((tools.jackson.databind.node.ObjectNode)deactivated.path("_catalog").path("1001")).put("status","inactive");
        assertEquals("sku_identity_unavailable",assertThrows(ProductionError.class,()->files.confirm(context,fresh.path("preview_id").asText(),deactivated.path("operation_token").asText(),deactivated)).code);assertEquals("0",service.get(context,"orders",id(a)).get("actual_units"));
    }
    @Test void formalReductionDoesNotEraseShipmentsAndClosedOldTargetCannotBeBypassed() {
        var a=order("100");var b=order("100");var sh=run("shipments",null,"create",shipment("80",line(a),"confirm"));
        var unshipped=service.list(context,"orders","","","","","","",1,20,"UNSHIPPED",false);assertEquals(1L,unshipped.get("total"));assertEquals(b.get("id"),((List<Map<String,Object>>)unshipped.get("items")).getFirst().get("id"));
        var reduced=changeOrder(id(a),"demand-changes",Map.of("effective_date","2026-10-13","lines",List.of(Map.of("sku_id","1001","expected_units","70"))));
        assertEquals("80",reduced.get("actual_units"));assertEquals("-10",reduced.get("difference_units"));assertEquals("10",reduced.get("overage_units"));assertEquals("0",reduced.get("closed_units"));
        var closed=changeOrder(id(a),"close-tracking",Map.of());assertEquals("0",closed.get("closed_units"));
        var source=((List<Map<String,Object>>)sh.get("sources")).getFirst();var shift=command(Map.of("expected_revision","1","reason","new target open but old is closed","sources",List.of(Map.of("id",source.get("id"),"sku_id","1001","actual_units","80","allocations",List.of(Map.of("order_line_id",line(b),"units","80"))))));
        assertEquals("tracking_closed",assertThrows(ProductionError.class,()->run("shipments",id(sh),"allocation-corrections",shift)).code);assertEquals("80",service.get(context,"orders",id(a)).get("actual_units"));assertEquals("0",service.get(context,"orders",id(b)).get("actual_units"));
    }
    @Test void lifecycleReplayOwnerScopeAndSemanticConflictRemainStable() {
        var a=order("100");var close=command(Map.of("expected_revision","1","reason","close once"));var first=run("orders",id(a),"close-tracking",close);assertEquals(first,run("orders",id(a),"close-tracking",close));
        assertEquals(first.get("id").toString(),json.valueToTree(service.commandResult(context,close.path("operation_token").asText())).path("id").asText());
        assertEquals("command_result_unknown",assertThrows(ProductionError.class,()->service.commandResult(new ProductionContext(context.site(),99,Set.of("admin")),close.path("operation_token").asText())).code);
        ((tools.jackson.databind.node.ObjectNode)close).put("reason","changed body");assertEquals("idempotency_content_conflict",assertThrows(ProductionError.class,()->run("orders",id(a),"close-tracking",close)).code);
        var reopen=command(Map.of("expected_revision",first.get("revision"),"reason","reopen once"));var opened=run("orders",id(a),"reopen-tracking",reopen);assertEquals(opened,run("orders",id(a),"reopen-tracking",reopen));
    }
}
