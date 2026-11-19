package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;

/** Uses the existing owned warehouse fixture and the real production/inventory transaction. */
class WarehouseDispatchDatabaseTest extends WarehouseTransitDatabaseTest {
    @Test void warehouseDispatchIsIndependentRevisionedAndStockBounded() throws Exception {
        var orderBody=body(map("save_mode","confirm","business_date","2026-10-30","manual_source_note","SIMULATED production demand independent of dispatch","lines",List.of(map("sku_id","1001","expected_units","50"))));
        var order=json.valueToTree(tx.execute(t->production.command(ACTOR,"orders",null,"create",orderBody.path("operation_token").asText(),orderBody)));
        var fields=transfer(4);fields.put("dispatch_purpose","WAREHOUSE_DISPATCH");fields.put("save_mode","draft");
        var input=body(fields);var draft=json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",null,"create",input.path("operation_token").asText(),input)));
        assertEquals(20,balance(source));assertEquals("DRAFT",draft.path("status").asText());
        var confirm=body(map("expected_revision",draft.path("revision").asText()));
        long shipment=draft.path("id").asLong();
        var saved=json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",shipment,"confirm",confirm.path("operation_token").asText(),confirm)));
        assertEquals(saved,json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",shipment,"confirm",confirm.path("operation_token").asText(),confirm))));
        assertEquals(16,balance(source));assertEquals(0,balance(destination));
        assertEquals(0,saved.path("sources").get(0).path("allocations").size());
        var unchanged=json.valueToTree(production.get(ACTOR,"orders",order.path("id").asLong()));
        assertEquals("0",unchanged.path("actual_units").asText());assertEquals("0",unchanged.path("received_units").asText());assertEquals("0",unchanged.path("lines").get(0).path("produced_units").asText());
        var wrong=transfer(1);wrong.put("dispatch_purpose","WAREHOUSE_DISPATCH");wrong.put("owner_id","99");assertEquals("inventory_not_ready",assertThrows(ProductionError.class,()->shipment(wrong)).code);
        var direct=transfer(1);direct.put("dispatch_purpose","WAREHOUSE_DISPATCH");direct.put("sources",List.of(map("sku_id","1001","actual_units","1","fulfillment_mode","PRODUCTION_DIRECT","allocations",List.of())));assertEquals("warehouse_dispatch_source_invalid",assertThrows(ProductionError.class,()->shipment(direct)).code);
        var linked=transfer(1);linked.put("dispatch_purpose","WAREHOUSE_DISPATCH");linked.put("sources",List.of(map("sku_id","1001","actual_units","1","allocations",List.of(map("order_line_id",order.path("lines").get(0).path("id").asText(),"units","1")))));linked.put("save_mode","draft");var linkedDraft=shipment(linked);assertEquals(1,linkedDraft.path("sources").get(0).path("allocations").size());assertEquals(16,balance(source));
        var same=transfer(1);same.put("dispatch_purpose","WAREHOUSE_DISPATCH");same.put("destination_id",Long.toString(source));assertEquals("dispatch_destination_invalid",assertThrows(ProductionError.class,()->shipment(same)).code);
        try(var pool=Executors.newFixedThreadPool(2)){
            var gate=new CountDownLatch(1);var tasks=new ArrayList<Future<Boolean>>();
            for(int i=0;i<2;i++)tasks.add(pool.submit(()->{gate.await();var command=transfer(10);command.put("dispatch_purpose","WAREHOUSE_DISPATCH");try{shipment(command);return true;}catch(ProductionError e){assertEquals("insufficient_available_stock",e.code);return false;}}));
            gate.countDown();assertNotEquals(tasks.get(0).get(20,TimeUnit.SECONDS),tasks.get(1).get(20,TimeUnit.SECONDS));
        }
        assertEquals(6,balance(source));assertEquals(0,balance(destination));
        var viewer=new ProductionContext(SITE,2,Set.of("viewer"));var attempt=body(fields);assertEquals(403,assertThrows(ProductionError.class,()->tx.execute(t->production.command(viewer,"shipments",null,"create",attempt.path("operation_token").asText(),attempt))).status);
        var stale=body(map("expected_revision","1","reason","SIM stale revision"));assertEquals("revision_conflict",assertThrows(ProductionError.class,()->tx.execute(t->production.command(ACTOR,"shipments",shipment,"void",stale.path("operation_token").asText(),stale))).code);
        var cancel=body(map("expected_revision",saved.path("revision").asText(),"reason","SIM void independent dispatch"));tx.execute(t->production.command(ACTOR,"shipments",shipment,"void",cancel.path("operation_token").asText(),cancel));assertEquals(10,balance(source));
        assertEquals("0",json.valueToTree(production.get(ACTOR,"orders",order.path("id").asLong())).path("actual_units").asText());
        var scopes=json.valueToTree(inventory.read(ACTOR,"availability",Map.of("warehouse_id",Long.toString(source))));assertEquals("OWN",scopes.path("scopes").get(0).path("warehouse_type").asText());
    }

    @Test void batchGoodsReceivesPartiallyWithoutCartonsAndReplaysOnce() {
        var fields=transfer(4);fields.remove("cartons");fields.put("dispatch_purpose","WAREHOUSE_DISPATCH");fields.put("save_mode","draft");
        var input=body(fields);var draft=json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",null,"create",input.path("operation_token").asText(),input)));
        long shipment=draft.path("id").asLong();assertTrue(draft.path("cartons").isNull());assertEquals(20,balance(source));
        var confirm=body(map("expected_revision",draft.path("revision").asText()));
        var saved=json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",shipment,"confirm",confirm.path("operation_token").asText(),confirm)));
        assertEquals(saved,json.valueToTree(tx.execute(t->production.command(ACTOR,"shipments",shipment,"confirm",confirm.path("operation_token").asText(),confirm))));
        assertEquals(16,balance(source));assertEquals(0,balance(destination));
        var state=json.valueToTree(inventory.read(ACTOR,"destination-state",Map.of("shipment_id",Long.toString(shipment))));
        assertEquals(1,state.path("bindings").size());var binding=state.path("bindings").get(0);assertEquals("",binding.path("carton_id").asText());assertEquals(saved.path("sources").get(0).path("id").asText(),binding.path("source_line_id").asText());assertEquals("4",binding.path("units").asText());
        var receipt=command("destination-receipts",body(map("shipment_id",Long.toString(shipment),"expected_shipment_revision",saved.path("revision").asText(),"warehouse_id",Long.toString(destination),"owner_id","1","business_date","2026-10-29","reason","SIM batch partial arrival without boxes","lines",List.of(map("binding_id",binding.path("id").asText(),"sku_id","1001","catalog_version","DEMO_LOCAL_ONLY-v1","qualified_units","2","pending_units","0","defective_units","0")))));
        var post=body(map("expected_revision",receipt.path("revision").asText()));String path="destination-receipts/"+receipt.path("id").asText()+"/confirm";var posted=command(path,post);assertEquals(posted,command(path,post));assertEquals(2,balance(destination));
        state=json.valueToTree(inventory.read(ACTOR,"destination-state",Map.of("shipment_id",Long.toString(shipment))));assertEquals("2",state.path("bindings").get(0).path("received_units").asText());
        var blocked=body(map("expected_revision",saved.path("revision").asText(),"reason","SIM cannot cancel received goods"));assertEquals("destination_receipt_dependency",assertThrows(ProductionError.class,()->tx.execute(t->production.command(ACTOR,"shipments",shipment,"void",blocked.path("operation_token").asText(),blocked))).code);
        command("destination-receipts/"+receipt.path("id").asText()+"/reverse",body(map("expected_revision",posted.path("revision").asText(),"reason","SIM restore test receipt")));assertEquals(0,balance(destination));
        var undo=body(map("expected_revision",saved.path("revision").asText(),"reason","SIM restore test dispatch"));tx.execute(t->production.command(ACTOR,"shipments",shipment,"void",undo.path("operation_token").asText(),undo));assertEquals(20,balance(source));
        assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND is_active=TRUE",Long.class,SITE,shipment));
    }
}
