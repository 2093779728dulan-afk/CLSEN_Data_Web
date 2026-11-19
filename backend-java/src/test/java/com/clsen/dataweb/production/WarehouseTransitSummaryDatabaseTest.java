package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
import java.util.*;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import tools.jackson.databind.ObjectMapper;

class WarehouseTransitSummaryDatabaseTest {
    final long site=2_000_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L);
    JdbcTemplate db;
    long leg(long site,long sku,long units,boolean mapped,String status,long received,long settled,String kind){
        db.update("INSERT INTO production_shipment(site_id,system_number,status,warehouse_id,owner_id,destination_id,destination_type) VALUES(?, ?, ?,1,1,2,'WAREHOUSE')",site,"SIM-SUM-"+UUID.randomUUID(),status);
        long shipment=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
        db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,?,'SIM source','SIM',?)",site,shipment,sku,units);
        long source=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
        if(mapped){
            db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,?,?,?,1,1,'SIM','SIM explicit source')",site,shipment,source,UUID.randomUUID().toString(),sku,units);
            long binding=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
            if(received>0){
                db.update("INSERT INTO destination_receipt(site_id,shipment_id,shipment_revision,status,actor_id,actor_name) VALUES(?,?,1,'POSTED',1,'SIM')",site,shipment);
                long receipt=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
                db.update("INSERT INTO destination_receipt_line(site_id,receipt_id,binding_id,sku_id,catalog_version,qualified_units) VALUES(?,?,?,?,'SIM',?)",site,receipt,binding,sku,received);
            }
            if(settled>0)db.update("INSERT INTO destination_receipt_settlement(site_id,binding_id,units,reason,actor_id,actor_name,operation_token) VALUES(?,?,?,'SIM settled',1,'SIM',?)",site,binding,settled,UUID.randomUUID().toString());
        }
        if(kind!=null){
            db.update("INSERT INTO shipment_transport(site_id,shipment_id,shipment_revision,carrier,tracking_number,source_reference,source_snapshot) VALUES(?,?,1,'SIM','SIM','SIM','{}')",site,shipment);
            long transport=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
            db.update("INSERT INTO shipment_transport_event(site_id,transport_id,event_kind,occurred_at,occurred_local,timezone,source_reference) VALUES(?,?,?,'2026-10-28 00:00:00','2026-10-28T00:00','UTC','SIM')",site,transport,kind);
        }
        return shipment;
    }
    @Test void fullSummaryCountsEachSourceOnceBeyondWarehousePageAndKeepsUnknownAndSiteBoundaries() throws Exception {
        String url=System.getenv("FBA_TEST_JDBC_URL");assertNotNull(url);assertTrue(url.startsWith("jdbc:mysql://127.0.0.1:"));assertTrue(url.contains("/clsen_fba_contract?"));
        Flyway.configure().dataSource(url,System.getenv("FBA_TEST_MIGRATION_USER"),System.getenv("FBA_TEST_MIGRATION_PASSWORD")).load().migrate();
        db=new JdbcTemplate(new SingleConnectionDataSource(url,System.getenv("FBA_TEST_RUNTIME_USER"),System.getenv("FBA_TEST_RUNTIME_PASSWORD"),true));
        assertEquals("20",db.queryForObject("SELECT version FROM flyway_schema_history WHERE success=TRUE ORDER BY installed_rank DESC LIMIT 1",String.class));
        for(int i=0;i<25;i++)leg(site,1001,2,true,"CONFIRMED",1,0,"DISPATCHED");
        leg(site,1001,5,true,"CONFIRMED",2,1,"ARRIVED");
        leg(site,1001,9,true,"CONFIRMED",9,0,"SIGNED");
        leg(site,1001,8,true,"CONFIRMED",0,8,"DISPATCHED");
        leg(site,1001,99,true,"VOID",0,0,"DISPATCHED");
        leg(site+1,1001,900,true,"CONFIRMED",0,0,"DISPATCHED");
        var json=new ObjectMapper();var inventory=new InventoryService(db,json,"demo_fixed");var viewer=new ProductionContext(site,1,Set.of("viewer"));
        var first=json.valueToTree(inventory.read(viewer,"transport-summary",Map.of()));
        assertTrue(first.path("full_scope").asBoolean());assertFalse(first.path("stock_effect").asBoolean());
        assertEquals("25",first.path("totals").path("in_transit_units").asText());assertEquals("2",first.path("totals").path("arrival_check_units").asText());
        assertEquals(1,first.path("items").size());assertEquals("1001",first.path("items").get(0).path("sku_id").asText());
        leg(site,1002,7,false,"CONFIRMED",0,0,null);leg(site,1003,4,false,"CONFIRMED",0,0,"IN_TRANSIT");
        var unknown=json.valueToTree(new WarehouseTransitStore(db,json,inventory).summary(viewer,Instant.now()));
        assertTrue(unknown.path("totals").path("in_transit_units").isNull());assertTrue(unknown.path("totals").path("unregistered_units").isNull());assertEquals(2,unknown.path("totals").path("unknown_sources").asInt());assertEquals("2",unknown.path("totals").path("arrival_check_units").asText());
    }
}
