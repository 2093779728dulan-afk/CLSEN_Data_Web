package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.time.Instant;
import java.util.*;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

class WarehouseTransitBatchTest {
    final ObjectMapper json=new ObjectMapper();
    final ProductionContext actor=new ProductionContext(91,1,Set.of("viewer"));
    static Map<String,Object> row(Object...pairs){var result=new LinkedHashMap<String,Object>();for(int i=0;i<pairs.length;i+=2)result.put(pairs[i].toString(),pairs[i+1]);return result;}
    @Test void wholeBatchSkuFilterKeepsAllSourcesAndLegacyWarehouseReadKeepsItsScope(){
        var db=mock(JdbcTemplate.class);var queries=new ArrayList<String>();var args=new ArrayList<List<Object>>();
        var sources=List.of(row("id","1","sku_id","11","sku_label","Black-L","actual_units","2"),row("id","2","sku_id","12","sku_label","Black-M","actual_units","3"));
        when(db.queryForObject(anyString(),eq(Long.class),any(Object[].class))).thenReturn(1L);
        when(db.queryForList(anyString(),any(Object[].class))).thenAnswer(call->{
            String sql=call.getArgument(0);queries.add(sql);args.add(Arrays.asList(call.getArguments()).subList(1,call.getArguments().length));
            if(sql.startsWith("SELECT s.id"))return List.of(row("id","77","cartons","[]"));
            if(sql.startsWith("SELECT id,sku_id"))return sql.contains("AND sku_id=?")?List.of(new LinkedHashMap<>(sources.get(0))):sources.stream().map(LinkedHashMap::new).toList();
            return List.of();
        });
        try(var transport=mockConstruction(ShipmentTransportStore.class,(mock,context)->when(mock.state(any(),eq(77L))).thenReturn(row("status","IN_TRANSIT","events",List.of(),"record",null)));
            var receipts=mockConstruction(DestinationReceiptStore.class,(mock,context)->when(mock.state(any(),eq(77L))).thenReturn(row("bindings",List.of(row("source_line_id","1","units","2","received_units","1","settled_units","0"),row("source_line_id","2","units","3","received_units","1","settled_units","0")),"receipts",List.of())))){
            var store=new WarehouseTransitStore(db,json,mock(InventoryService.class));
            var page=json.valueToTree(store.batches(actor,Map.of("sku_id","11","shipment_id","77","page","2","page_size","5"),Instant.now()));
            assertEquals("whole_batch",page.path("detail_scope").asText());var item=page.path("items").get(0);
            assertEquals(2,item.path("sources").size());assertEquals("5",item.path("shipped_units").asText());assertEquals("2",item.path("received_units").asText());assertEquals("3",item.path("unreceived_units").asText());
            String sql=queries.get(0);assertTrue(sql.contains("s.site_id=? AND s.status='CONFIRMED'"));assertTrue(sql.contains("s.id=?"));assertTrue(sql.contains("EXISTS(SELECT 1"));assertFalse(sql.contains("AND s.destination_id=?"));
            assertEquals(List.of(91L,"77","11",5,5),args.get(0));assertFalse(queries.stream().anyMatch(q->q.startsWith("SELECT id,sku_id")&&q.contains("AND sku_id=?")));
            queries.clear();args.clear();var legacy=json.valueToTree(store.read(actor,Map.of("warehouse_id","2","sku_id","11"),Instant.now()));
            assertEquals(1,legacy.path("items").get(0).path("sources").size());assertEquals("2",legacy.path("items").get(0).path("shipped_units").asText());assertFalse(legacy.has("detail_scope"));assertTrue(queries.get(0).contains("AND s.destination_id=?"));
            assertTrue(queries.stream().anyMatch(q->q.startsWith("SELECT id,sku_id")&&q.contains("AND sku_id=?")));
        }
        assertTrue(mockingDetails(db).getInvocations().stream().noneMatch(i->i.getMethod().getName().equals("update")));
    }
    @Test void validatesBatchIdsAndPagingBeforeReading(){
        var store=new WarehouseTransitStore(mock(JdbcTemplate.class),json,mock(InventoryService.class));
        assertThrows(ProductionError.class,()->store.batches(actor,Map.of("shipment_id","0"),Instant.now()));
        assertThrows(ProductionError.class,()->store.batches(actor,Map.of("page_size","101"),Instant.now()));
        assertThrows(ProductionError.class,()->store.batches(actor,Map.of("node","FORGED"),Instant.now()));
    }
}
