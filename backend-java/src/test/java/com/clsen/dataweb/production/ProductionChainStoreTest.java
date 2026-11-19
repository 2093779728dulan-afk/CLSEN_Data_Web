package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;
import java.util.*;
import org.junit.jupiter.api.Test;

class ProductionChainStoreTest {
    static Map<String,Object> row(Object...pairs){var r=new LinkedHashMap<String,Object>();for(int i=0;i<pairs.length;i+=2)r.put(pairs[i].toString(),pairs[i+1]);return r;}
    static Map<String,Object> order(String id){return row("id",id,"factory_id","1","receipt_warehouse_id","2","receipt_owner_id","1","status","CONFIRMED","lines",List.of(row("id",id+"1","sku_id","5","expected_units","100","produced_units","100","received_units","100","production_direct_units","0")));}
    static Map<String,Object> batch(String id){return row("id",id,"warehouse_id","2","owner_id","1","destination_type","WAREHOUSE","destination_id","3");}
    static Map<String,Object> source(String id,String batch,String units){return row("id",id,"shipment_id",batch,"actual_units",units);}
    static Map<String,Object> allocation(String id,String order,String source,String units){return row("id",id,"order_id",order,"order_line_id",order+"1","source_line_id",source,"units",units);}
    static Map<String,Object> binding(String source,String allocation,String units,String got){return row("source_line_id",source,"allocation_id",allocation,"units",units,"received_units",got);}
    @Test void sameRouteFreightIsVisibleAsContextWithoutInventingOrderAllocations(){
        var order=order("1");order.put("destination_id","3");order.put("destination_type","WAREHOUSE");
        var shipment=batch("9");shipment.put("dispatch_purpose","WAREHOUSE_DISPATCH");
        var source=source("8","9","100");source.put("sku_id","5");
        var group=row("orders",List.of(order),"shipments",List.of());
        assertEquals(List.of(shipment),ProductionChainStore.relatedShipments(group,List.of(shipment),List.of(source),List.of()));
        assertTrue(ProductionChainStore.relatedShipments(group,List.of(shipment),List.of(source),List.of(allocation("a","1","8","100"))).isEmpty());
        shipment.put("owner_id","2");
        assertTrue(ProductionChainStore.relatedShipments(group,List.of(shipment),List.of(source),List.of()).isEmpty());
    }
    @Test void threeOrdersShareOneBatchWithoutTriplingFreightAndStayIndividuallyAttributable(){
        var os=List.of(order("1"),order("2"),order("3"));
        var groups=ProductionChainStore.groups(os,List.of(batch("9")),List.of(source("8","9","300")),List.of(allocation("a","1","8","100"),allocation("b","2","8","100"),allocation("c","3","8","100")),List.of(binding("8","a","100","100"),binding("8","b","100","100"),binding("8","c","100","40")));
        assertEquals(1,groups.size());assertEquals(3,ProductionChainStore.children(groups.getFirst(),"orders").size());assertEquals(1,ProductionChainStore.children(groups.getFirst(),"shipments").size());assertEquals(false,groups.getFirst().get("completed"));
        assertEquals("40",ProductionChainStore.children(os.get(2),"fulfillment_lines").getFirst().get("received_units"));
    }
    @Test void sameRouteCanGroupSeparateBatchesAndUnknownPathsStaySeparate(){
        var os=List.of(order("1"),order("2"));var groups=ProductionChainStore.groups(os,List.of(batch("8"),batch("9")),List.of(source("6","8","100"),source("7","9","100")),List.of(allocation("a","1","6","100"),allocation("b","2","7","100")),List.of(binding("6","a","100","100"),binding("7","b","100","100")));
        assertEquals(1,groups.size());assertEquals(true,groups.getFirst().get("completed"));
        var unknown=List.of(order("3"),order("4"));unknown.forEach(o->o.put("factory_id",null));assertEquals(2,ProductionChainStore.groups(unknown,List.of(),List.of(),List.of(),List.of()).size());
    }
    @Test void partialUnassignedReceiptIsUnknownAndFullSourceIsCertain(){
        var a=allocation("a","1","8","100");var s=source("8","9","300");
        assertNull(ProductionChainStore.allocationReceived(a,s,List.of(binding("8",null,"300","120"))));
        assertEquals("100",ProductionChainStore.allocationReceived(a,s,List.of(binding("8",null,"300","300"))).toString());
        assertNull(ProductionChainStore.allocationReceived(a,s,List.of(binding("8","a","100","100"))));
    }
    @Test void independentFreightCannotJoinOrdersByWarehouseAndDoesNotNeedAnOrderToComplete(){
        var groups=ProductionChainStore.groups(List.of(order("1")),List.of(batch("9")),List.of(source("8","9","100")),List.of(),List.of(binding("8",null,"100","100")));
        assertEquals(2,groups.size());assertEquals(false,groups.getFirst().get("completed"));assertEquals(true,groups.get(1).get("completed"));
    }
    @Test void finishedRoutesRemainVisibleWhenANewBatchUsesTheSameRoute(){
        var groups=ProductionChainStore.groups(List.of(),List.of(batch("8"),batch("9")),List.of(source("6","8","100"),source("7","9","100")),List.of(),List.of(binding("6",null,"100","100"),binding("7",null,"100","20")));
        assertEquals(2,groups.size());assertEquals(1,groups.stream().filter(g->Boolean.TRUE.equals(g.get("completed"))).count());
    }
    @Test void plannedDestinationCanGroupTheSameRouteBeforeEveryOrderHasShipped(){
        var one=order("1");one.put("destination_id","3");one.put("destination_type","WAREHOUSE");
        var groups=ProductionChainStore.groups(List.of(one,order("2")),List.of(batch("9")),List.of(source("8","9","100")),List.of(allocation("a","2","8","100")),List.of(binding("8","a","100","20")));
        assertEquals(1,groups.size());assertEquals(2,ProductionChainStore.children(groups.getFirst(),"orders").size());
        assertEquals("0",ProductionChainStore.children(one,"fulfillment_lines").getFirst().get("shipped_units"));
    }
    @Test void overageOnOneOrderNeverCoversAnotherAndDirectProductionBypassesReceipt(){
        var one=order("1");var two=order("2");var allocations=List.of(allocation("a","1","6","200"),allocation("b","2","7","100"));
        var bindings=List.of(binding("6","a","200","200"),binding("7","b","100","0"));
        var groups=ProductionChainStore.groups(List.of(one,two),List.of(batch("9")),List.of(source("6","9","200"),source("7","9","100")),allocations,bindings);
        assertEquals(false,groups.getFirst().get("completed"));
        var direct=order("3");var line=ProductionChainStore.children(direct,"lines").getFirst();line.put("received_units","0");line.put("production_direct_units","100");
        groups=ProductionChainStore.groups(List.of(direct),List.of(batch("10")),List.of(source("5","10","100")),List.of(allocation("c","3","5","100")),List.of(binding("5","c","100","100")));
        assertEquals(true,groups.getFirst().get("completed"));
        line.put("produced_units",null);assertEquals(false,ProductionChainStore.groups(List.of(direct),List.of(batch("10")),List.of(source("5","10","100")),List.of(allocation("c","3","5","100")),List.of(binding("5","c","100","100"))).getFirst().get("completed"));
    }
    @Test void voidOrdersExitActiveAndAllCountsButRemainDirectlyViewable() {
        var db=mock(JdbcTemplate.class);
        var production=mock(ProductionService.class);
        var inventory=mock(InventoryService.class);
        var active=order("1");var cancelled=order("9");var otherCancelled=order("8");
        cancelled.put("status","VOID");otherCancelled.put("status","VOID");
        var orders=List.of(active,cancelled,otherCancelled);
        var lines=new ArrayList<Map<String,Object>>();
        for(var order:orders) {
            order.put("completion_operation","REOPEN_PRODUCTION");
            var line=ProductionChainStore.children(order,"lines").getFirst();
            line.put("order_id",order.get("id"));line.put("actual_units","0");line.put("closed_units","0");line.put("tracking_state","OPEN");
            lines.add(line);
        }
        when(db.queryForList(anyString(),eq(1L))).thenReturn(List.of());
        when(db.queryForList(contains("FROM production_order o"),eq(1L))).thenReturn(orders);
        when(production.orderLinesFor(eq(1L),anyList())).thenReturn(lines);
        var store=new ProductionChainStore(db,new ObjectMapper(),production,inventory);
        var context=new ProductionContext(1,1,Set.of("admin"),"test.admin");
        var current=store.read(context,Map.of());
        assertEquals("1",current.get("total").toString());
        assertEquals("1",((Map<?,?>)current.get("chain_counts")).get("active").toString());
        assertEquals("1",store.read(context,Map.of("chain_progress","all")).get("total").toString());
        var history=store.read(context,Map.of("trace_kind","order","trace_id","9"));
        assertEquals("1",history.get("total").toString());
        assertEquals("VOID",ProductionChainStore.children(ProductionChainStore.children(history,"items").getFirst(),"orders").getFirst().get("status"));
        assertEquals("1",((Map<?,?>)history.get("chain_counts")).get("active").toString());
    }

}
