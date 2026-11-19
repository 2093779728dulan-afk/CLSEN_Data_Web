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

class FbaInventoryDatabaseTest {
    static JdbcTemplate db; static TransactionTemplate tx; static ObjectMapper json; static InventoryService inventory;
    static final long SITE=4_000_000L+Math.abs(UUID.randomUUID().getMostSignificantBits()%1_000_000_000L);
    static final ProductionContext actor=new ProductionContext(SITE,1,Set.of("data_manager"),"SIMULATED FBA contract");
    static long shipment,source,allocation,binding,scope;
    static final Map<String,Object> CATALOG=Map.of("1001",Map.of("sku_id","1001","style_id","2001","code","TEST-SKU","label","TEST-SKU","status","active","catalog_version","DEMO_LOCAL_ONLY-v1"));
    @BeforeAll static void setup()throws Exception{
        String url=System.getenv("FBA_TEST_JDBC_URL");if(url==null||!url.startsWith("jdbc:mysql://127.0.0.1:")||!(url.contains("/clsen_fba_contract?")||url.contains("/clsen_fba_contract_visibility_20261111?")))throw new IllegalStateException("Explicit task FBA schema required");
        Flyway.configure().dataSource(url,System.getenv("FBA_TEST_MIGRATION_USER"),System.getenv("FBA_TEST_MIGRATION_PASSWORD")).load().migrate();
        var ds=new DriverManagerDataSource(url,System.getenv("FBA_TEST_RUNTIME_USER"),System.getenv("FBA_TEST_RUNTIME_PASSWORD"));db=new JdbcTemplate(ds);tx=new TransactionTemplate(new DataSourceTransactionManager(ds));json=new ObjectMapper();inventory=new InventoryService(db,json,"demo_fixed");
        var flag=InventoryService.class.getDeclaredField("fbaEnabled");flag.setAccessible(true);flag.setBoolean(inventory,true);
        tx.executeWithoutResult(t->{
            db.update("INSERT INTO production_warehouse(site_id,id,name,type,country,profile) VALUES(?,2,'SIMULATED FBA','FBA','US',?)",SITE,"{\"seller_account\":\"SIM-ACCOUNT\",\"marketplace\":\"amazon_us\"}");
            db.update("INSERT INTO production_order(site_id,system_number,status) VALUES(?,'FBA-test-order','CONFIRMED')",SITE);long order=last();
            db.update("INSERT INTO production_order_line(site_id,order_id,sku_id,sku_label,catalog_version,expected_units) VALUES(?,?,1001,'TEST-SKU','DEMO_LOCAL_ONLY-v1',100)",SITE,order);long line=last();
            db.update("INSERT INTO production_shipment(site_id,system_number,status,destination_id,destination_type,owner_id,cartons) VALUES(?,'FBA-test-shipment','CONFIRMED',2,'FBA',1,?)",SITE,"[{\"id\":\"test-carton\",\"items\":[{\"sku_id\":\"1001\",\"units\":\"100\"}]}]");shipment=last();
            db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units) VALUES(?,?,1001,'TEST-SKU','DEMO_LOCAL_ONLY-v1',100)",SITE,shipment);source=last();
            db.update("INSERT INTO production_shipment_allocation(site_id,source_line_id,order_line_id,units) VALUES(?,?,?,100)",SITE,source,line);allocation=last();
            db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,allocation_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,?,'test-carton',1001,100,1,1,'test','SIMULATED explicit binding')",SITE,shipment,source,allocation);binding=last();
        });
    }
    static long last(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    static JsonNode body(Map<String,?> fields){var value=json.valueToTree(fields);var result=(tools.jackson.databind.node.ObjectNode)value;result.put("operation_token",UUID.randomUUID().toString());result.set("_catalog",json.valueToTree(CATALOG));if(Set.of("FULFILLMENT","RETURN").contains(result.path("kind").asText()))for(var line:result.path("lines")){var item=(tools.jackson.databind.node.ObjectNode)line;if(!item.has("source_event_ref"))item.put("source_event_ref",result.path("event_key").asText()+"-"+item.path("sku_id").asText());if(!item.has("customer_order_ref"))item.put("customer_order_ref","SIM-ORDER-"+item.path("sku_id").asText());}return result;}
    static JsonNode command(String path,JsonNode b){return json.valueToTree(tx.execute(s->inventory.command(actor,path,b,b.path("operation_token").asText())));}
    static JsonNode call(String path,Map<String,?> b){return command(path,body(b));}
    static long events(){return db.queryForObject("SELECT COUNT(*) FROM inventory_event WHERE site_id=?",Long.class,SITE);}
    static long balance(String bucket){return db.queryForObject("SELECT "+bucket+" FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1001",Long.class,SITE);}
    static Map<String,Object> row(int number,String units,String stamp){return Map.of("source_row",number,"raw",Map.of("MSKU","TEST-SKU","FNSKU","TEST-FN","ASIN","TEST-AS","Store","","Country","US","Reference ID","TEST-FBA-REF","Event Type","Receipts","Disposition","SELLABLE","Date and Time",stamp),"quantity",units,"occurred_at",stamp,"business_date",stamp.substring(0,10),"seller_match",Base64.getEncoder().encodeToString("TEST-SKU".getBytes()),"fingerprint",Integer.toHexString(Objects.hash(units,stamp)),"same_file_candidates",List.of());}
    static Map<String,Object> decision(int row,String units,String key,String correction){var d=new LinkedHashMap<String,Object>();d.put("source_row",String.valueOf(row));d.put("decision","NEW");d.put("event_key",key);d.put("correction_of",correction);d.put("reason","SIMULATED independently checked source occurrence "+key);d.put("allocations",List.of(Map.of("binding_id",String.valueOf(binding),"units",units)));return d;}
    static JsonNode upload(String raw,List<Map<String,Object>> rows){return call("fba-uploads",Map.of("scope_id",String.valueOf(scope),"filename","SIMULATED.csv","file_base64",Base64.getEncoder().encodeToString(raw.getBytes()),"_parsed",Map.of("rows",rows,"issues",List.of())));}
    static JsonNode save(long batch,long revision,List<Map<String,Object>> decisions){return call("fba-batch-save",Map.of("batch_id",String.valueOf(batch),"expected_revision",String.valueOf(revision),"decisions",decisions,"reason","SIMULATED explicit decision evidence"));}
    static JsonNode confirm(long batch,long revision,List<String> rows){return call("fba-batch-confirm",Map.of("batch_id",String.valueOf(batch),"expected_revision",String.valueOf(revision),"source_rows",rows,"reason","SIMULATED check and confirm selected physical receipts"));}
    @Test void receiptFulfillmentReturnTransactionsAndAmbiguousOverlap()throws Exception{
        var init=body(Map.ofEntries(Map.entry("warehouse_id","2"),Map.entry("owner_id","1"),Map.entry("owner_name","SIMULATED owner"),Map.entry("seller_account","SIM-ACCOUNT"),Map.entry("marketplace","amazon_us"),Map.entry("report_source_scope_id","1"),Map.entry("store_evidence","SIMULATED source"),Map.entry("cutoff_on","2026-09-30"),Map.entry("reason","SIMULATED explicitly complete zero opening"),Map.entry("explicit_zero_opening",true),Map.entry("simulated",true),Map.entry("_fba_scope",Map.of("id","1","seller_account","SIM-ACCOUNT","marketplace","amazon_us")),Map.entry("_fba_identities",Map.of("1001",Map.of("seller_sku","TEST-SKU","match",Base64.getEncoder().encodeToString("TEST-SKU".getBytes())))),Map.entry("identities",List.of(Map.of("sku_id","1001","seller_sku","TEST-SKU","fnsku","TEST-FN","asin","TEST-AS","reason","SIMULATED explicitly checked mapping")))));
        var initialized=command("fba-scopes",init);scope=initialized.path("scopes").get(0).path("id").asLong();assertEquals(0,events());assertEquals(0,balance("qualified_units"));
        var tracked=call("fba-tracking",Map.of("scope_id",String.valueOf(scope),"expected_revision","1","sku_ids",List.of("1001"),"store_name","SIM store","reason","SIMULATED correct Store and select one SKU without posting"));assertEquals(0,events());assertEquals("SIM store",tracked.path("scopes").get(0).path("store_evidence").asText());
        call("fba-references",Map.of("scope_id",String.valueOf(scope),"reference_id","TEST-FBA-REF","shipment_id",String.valueOf(shipment),"expected_shipment_revision","1","reason","SIMULATED explicit platform reference and carton evidence"));
        var rows=List.of(row(2,"10","2026-10-25T10:00:00-07:00"),row(3,"8","2026-10-26T10:00:00-07:00"),row(4,"-1","2026-10-26T11:00:00-07:00"),row(5,"1","2026-10-26T11:01:00-07:00"));
        var batch=upload("SIMULATED-original",rows);long batchId=batch.path("id").asLong();assertEquals(batchId,upload("SIMULATED-original",rows).path("id").asLong());assertArrayEquals("SIMULATED-original".getBytes(),tx.execute(s->inventory.fbaOriginal(actor,batchId)));
        var decisions=List.of(decision(2,"10","receive-10",""),decision(3,"9","receive-8",""),decision(4,"-1","correction-minus","receive-10"),decision(5,"1","correction-plus","correction-minus"));
        save(batchId,1,decisions);assertThrows(ProductionError.class,()->confirm(batchId,2,List.of("2","3")));assertEquals(0,events());assertEquals(0,balance("qualified_units"));
        decisions=List.of(decision(2,"10","receive-10",""),decision(3,"8","receive-8",""),decision(4,"-1","correction-minus","receive-10"),decision(5,"1","correction-plus","correction-minus"));save(batchId,2,decisions);
        var firstBody=body(Map.of("batch_id",String.valueOf(batchId),"expected_revision","3","source_rows",List.of("2"),"reason","SIMULATED first partial receipt"));var first=command("fba-batch-confirm",firstBody);assertEquals("PARTIAL",first.path("status").asText());assertEquals(10,balance("qualified_units"));assertEquals(first,command("fba-batch-confirm",firstBody));assertEquals(1,events());
        assertEquals("fba_store_locked",assertThrows(ProductionError.class,()->call("fba-tracking",Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope)),"sku_ids",List.of("1001"),"store_name","OTHER","reason","SIMULATED reject store change after receipts"))).code);
        assertEquals("fba_revision_conflict",assertThrows(ProductionError.class,()->confirm(batchId,3,List.of("3"))).code);
        confirm(batchId,4,List.of("3"));assertEquals(18,balance("qualified_units"));confirm(batchId,5,List.of("4","5"));assertEquals(18,balance("qualified_units"));assertEquals(4,events());
        var dest=json.valueToTree(tx.execute(s->inventory.read(actor,"destination-state",Map.of("shipment_id",String.valueOf(shipment)))));assertEquals("18",dest.path("bindings").get(0).path("received_units").asText());
        var overlap=upload("SIMULATED-reordered",List.of(rows.get(1),rows.get(0)));long overlapId=overlap.path("id").asLong();assertFalse(overlap.path("rows").get(0).path("existing_candidates").isEmpty());
        save(overlapId,1,List.of(decision(3,"8","not-independent",""),decision(2,"10","also-not-independent","")));assertEquals("fba_duplicate_decision_required",assertThrows(ProductionError.class,()->confirm(overlapId,2,List.of("3"))).code);assertEquals(4,events());
        long original=overlap.path("rows").get(0).path("existing_candidates").get(0).path("id").asLong(),original2=overlap.path("rows").get(1).path("existing_candidates").get(0).path("id").asLong();
        save(overlapId,2,List.of(Map.of("source_row","3","decision","SAME","existing_event_id",String.valueOf(original),"reason","SIMULATED explicit exact-row replay evidence"),Map.of("source_row","2","decision","SAME","existing_event_id",String.valueOf(original2),"reason","SIMULATED explicit exact-row replay evidence")));confirm(overlapId,3,List.of("2","3"));assertEquals(4,events());assertEquals(18,balance("qualified_units"));
        var viewer=new ProductionContext(SITE,2,Set.of("viewer"),"SIMULATED viewer");var blocked=body(Map.of("scope_id",String.valueOf(scope)));assertEquals("role_forbidden",assertThrows(ProductionError.class,()->tx.execute(s->inventory.command(viewer,"fba-tracking",blocked,blocked.path("operation_token").asText()))).code);
        var invalid=body(Map.of("scope_id",String.valueOf(scope),"kind","FULFILLMENT","event_key","too-many","occurred_at","2026-10-27T10:00:00-07:00","reason","SIMULATED actual fulfillment evidence","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","units","19"))));assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->command("fba-actions",invalid)).code);assertEquals(0L,db.queryForObject("SELECT COUNT(*) FROM fba_action WHERE site_id=?",Long.class,SITE));
        var fulfillment=body(Map.of("scope_id",String.valueOf(scope),"kind","FULFILLMENT","event_key","physical-3","occurred_at","2026-10-27T10:00:00-07:00","reason","SIMULATED actual fulfillment, distinct from business report","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","units","3"))));var after=command("fba-actions",fulfillment);assertEquals(after,command("fba-actions",fulfillment));assertEquals(15,balance("qualified_units"));var samePhysical=(tools.jackson.databind.node.ObjectNode)fulfillment.deepCopy();samePhysical.put("operation_token",UUID.randomUUID().toString());samePhysical.put("event_key","different-batch-same-physical-source");assertEquals("fba_source_event_exists",assertThrows(ProductionError.class,()->command("fba-actions",samePhysical)).code);assertEquals(15,balance("qualified_units"));long fulfillmentId=after.path("actions").get(0).path("id").asLong();
        var ret=call("fba-actions",Map.of("scope_id",String.valueOf(scope),"kind","RETURN","event_key","physical-return-1","fulfillment_id",String.valueOf(fulfillmentId),"occurred_at","2026-10-28T10:00:00-07:00","reason","SIMULATED physical damaged return, not a refund","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","units","1","quality","DEFECTIVE"))));long returnId=ret.path("actions").get(0).path("id").asLong();assertEquals(15,balance("qualified_units"));assertEquals(1,balance("defective_units"));
        assertEquals("fba_downstream_dependency",assertThrows(ProductionError.class,()->call("fba-action-reverse",Map.of("action_id",String.valueOf(fulfillmentId),"expected_revision","1","reason","SIMULATED cannot reverse consumed fulfillment"))).code);
        long eventCount=events();call("fba-actions",Map.of("scope_id",String.valueOf(scope),"kind","OBSERVATION","event_key","snapshot-only","occurred_at","2026-10-28T11:00:00-07:00","reason","SIMULATED observation is not a stock event","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","sellable","12","reserved","3","unsellable","1","held","0"))));assertEquals(eventCount,events());assertEquals(15,balance("qualified_units"));
        call("fba-action-reverse",Map.of("action_id",String.valueOf(returnId),"expected_revision","1","reason","SIMULATED undo physical return before fulfillment"));call("fba-action-reverse",Map.of("action_id",String.valueOf(fulfillmentId),"expected_revision","1","reason","SIMULATED restore before concurrent test"));assertEquals(18,balance("qualified_units"));assertEquals(0,balance("defective_units"));
        var gate=new CountDownLatch(1);try(var pool=Executors.newFixedThreadPool(2)){
            var futures=new ArrayList<Future<Boolean>>();for(int i=0;i<2;i++){final int index=i;futures.add(pool.submit(()->{gate.await();try{call("fba-actions",Map.of("scope_id",String.valueOf(scope),"kind","FULFILLMENT","event_key","concurrent-"+index,"occurred_at","2026-10-28T12:00:00-07:00","reason","SIMULATED concurrent actual fulfillment","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","units","10"))));return true;}catch(ProductionError e){assertEquals("insufficient_available_stock",e.code);return false;}}));}gate.countDown();assertNotEquals(futures.get(0).get(20,TimeUnit.SECONDS),futures.get(1).get(20,TimeUnit.SECONDS));
        }assertEquals(8,balance("qualified_units"));
        long beforeTracking=events();call("fba-tracking",Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope)),"sku_ids",List.of(),"reason","SIMULATED disable tracking, retain balance and history"));call("fba-tracking",Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope)),"sku_ids",List.of("1001"),"reason","SIMULATED restart tracking without reopening"));assertEquals(beforeTracking,events());assertEquals(8,balance("qualified_units"));
        assertThrows(ProductionError.class,()->call("documents",Map.of("warehouse_id","2","owner_id","1","kind","IN","business_date","2026-10-28","reason","SIMULATED ordinary FBA bypass forbidden","lines",List.of(Map.of("sku_id","1001","quality","QUALIFIED","units","1","purpose","RECEIVE")))));
        // A receipt correction is blocked by active later fulfillment, and allowed
        // again after those facts are explicitly reversed; old audit events stay.
        var negative=upload("SIMULATED-later-correction",List.of(row(2,"-1","2026-10-26T13:00:00-07:00")));long negativeId=negative.path("id").asLong();save(negativeId,1,List.of(decision(2,"-1","later-minus","receive-10")));
        long countBefore=events();assertEquals("fba_downstream_dependency",assertThrows(ProductionError.class,()->confirm(negativeId,2,List.of("2"))).code);assertEquals(countBefore,events());
        long activeFulfillment=db.queryForObject("SELECT id FROM fba_action WHERE site_id=? AND scope_id=? AND kind='FULFILLMENT' AND status='POSTED'",Long.class,SITE,scope);
        call("fba-action-reverse",Map.of("action_id",String.valueOf(activeFulfillment),"expected_revision","1","reason","SIMULATED resolve later fulfillment dependency before correction"));assertEquals(18,balance("qualified_units"));
        confirm(negativeId,2,List.of("2"));assertEquals(17,balance("qualified_units"));
        var restore=upload("SIMULATED-correction-restore",List.of(row(2,"1","2026-10-26T13:01:00-07:00")));long restoreId=restore.path("id").asLong();save(restoreId,1,List.of(decision(2,"1","later-plus","later-minus")));confirm(restoreId,2,List.of("2"));assertEquals(18,balance("qualified_units"));
        // Identical legitimate occurrences remain separate when explicitly proven.
        var a=new LinkedHashMap<String,Object>(row(2,"1","2026-10-28T13:00:00-07:00"));a.put("same_file_candidates",List.of(3));var d=new LinkedHashMap<String,Object>(row(3,"1","2026-10-28T13:00:00-07:00"));d.put("same_file_candidates",List.of(2));
        var legitimate=upload("SIMULATED-legitimate-identical-occurrences",List.of(a,d));long legitimateId=legitimate.path("id").asLong();var firstLegitimate=decision(2,"1","independent-one","");var secondLegitimate=decision(3,"1","independent-two","");save(legitimateId,1,List.of(firstLegitimate,secondLegitimate));assertEquals("fba_duplicate_decision_required",assertThrows(ProductionError.class,()->confirm(legitimateId,2,List.of("2","3"))).code);
        firstLegitimate.put("independent_occurrence",true);secondLegitimate.put("independent_occurrence",true);save(legitimateId,2,List.of(firstLegitimate,secondLegitimate));confirm(legitimateId,3,List.of("2","3"));assertEquals(20,balance("qualified_units"));
        var unmatched=new LinkedHashMap<String,Object>(row(2,"1","2026-10-28T14:00:00-07:00"));var badRaw=json.valueToTree(unmatched.get("raw"));((tools.jackson.databind.node.ObjectNode)badRaw).put("FNSKU","UNMATCHED");unmatched.put("raw",badRaw);
        var unmatchedBatch=upload("SIMULATED-unmatched-kept",List.of(unmatched));long unmatchedId=unmatchedBatch.path("id").asLong();save(unmatchedId,1,List.of(decision(2,"1","unmatched-keep","")));assertEquals("fba_identity_unmatched",assertThrows(ProductionError.class,()->confirm(unmatchedId,2,List.of("2"))).code);assertEquals(20,balance("qualified_units"));assertEquals(1,json.valueToTree(tx.execute(s->inventory.read(actor,"fba-batches/"+unmatchedId,Map.of()))).path("rows").size());
        // A directory refresh must be explicit, validate every original identity, and retain all posted facts.
        long scopeRevision=db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope);
        db.update("UPDATE fba_scope SET catalog_version='PREVIOUS' WHERE site_id=? AND id=?",SITE,scope);
        var refreshFields=new LinkedHashMap<String,Object>(Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(scopeRevision),"sku_ids",List.of("1001"),"reason","SIMULATED reconfirm unchanged identity after catalog refresh"));
        assertEquals("fba_catalog_conflict",assertThrows(ProductionError.class,()->call("fba-tracking",refreshFields)).code);
        refreshFields.put("reconfirm_catalog",true);
        assertEquals("fba_identity_conflict",assertThrows(ProductionError.class,()->call("fba-tracking",refreshFields)).code);
        refreshFields.put("_fba_identities",Map.of("1001",Map.of("seller_sku","TEST-SKU")));
        db.update("UPDATE fba_identity SET style_id=9999 WHERE site_id=? AND scope_id=?",SITE,scope);
        assertEquals("fba_identity_conflict",assertThrows(ProductionError.class,()->call("fba-tracking",refreshFields)).code);
        db.update("UPDATE fba_identity SET style_id=2001 WHERE site_id=? AND scope_id=?",SITE,scope);
        long beforeRefresh=events();var refreshed=call("fba-tracking",refreshFields);
        assertEquals("DEMO_LOCAL_ONLY-v1",refreshed.path("scopes").get(0).path("catalog_version").asText());assertEquals(beforeRefresh,events());assertEquals(20,balance("qualified_units"));
        // Compatible automatic refresh is metadata-only and preserves disabled tracking.
        db.update("UPDATE fba_scope SET catalog_version='PREVIOUS-AUTO' WHERE site_id=? AND id=?",SITE,scope);
        db.update("UPDATE fba_identity SET tracked=FALSE WHERE site_id=? AND scope_id=?",SITE,scope);
        var automaticRefresh=body(Map.of("scope_id",String.valueOf(scope),"_report_source_scope_id","1","_trusted_report_returns",List.of(),"_report_set_complete",true,"report_version_ids",List.of(),"reason","SIMULATED metadata-only refresh"));
        ((tools.jackson.databind.node.ObjectNode)automaticRefresh).set("_auto_setup",json.valueToTree(Map.of("scope_id",String.valueOf(scope),"identities",List.of(),"catalog_version","DEMO_LOCAL_ONLY-v1","reconfirm_catalog",true,"sku_ids",List.of(),"reason","SIMULATED verified compatible identity refresh","_fba_identities",Map.of("1001",Map.of("seller_sku","TEST-SKU")))));
        var automaticResult=command("fba-report-sync",automaticRefresh);
        assertEquals("DEMO_LOCAL_ONLY-v1",automaticResult.path("scopes").get(0).path("catalog_version").asText());
        assertEquals(beforeRefresh,events());
        assertFalse(automaticResult.path("identities").get(0).path("tracked").asBoolean());
        assertEquals(automaticResult,command("fba-report-sync",automaticRefresh));
        db.update("UPDATE fba_identity SET tracked=TRUE WHERE site_id=? AND scope_id=?",SITE,scope);
        // A second account with the same MSKU/ASIN/FNSKU never inherits events.
        db.update("INSERT INTO production_warehouse(site_id,id,name,type,country,profile) VALUES(?,3,'SIMULATED other account','FBA','US',?)",SITE,"{\"seller_account\":\"SIM-OTHER\",\"marketplace\":\"amazon_us\"}");var otherInit=(tools.jackson.databind.node.ObjectNode)init.deepCopy();otherInit.put("operation_token",UUID.randomUUID().toString());otherInit.put("warehouse_id","3");otherInit.put("seller_account","SIM-OTHER");otherInit.put("report_source_scope_id","2");otherInit.set("_fba_scope",json.valueToTree(Map.of("id","2","seller_account","SIM-OTHER","marketplace","amazon_us")));long otherScope=command("fba-scopes",otherInit).path("scopes").get(0).path("id").asLong();
        var otherBatch=call("fba-uploads",Map.of("scope_id",String.valueOf(otherScope),"filename","other.csv","file_base64",Base64.getEncoder().encodeToString("SIMULATED other account".getBytes()),"_parsed",Map.of("rows",List.of(rows.get(0)),"issues",List.of())));long otherBatchId=otherBatch.path("id").asLong();assertTrue(otherBatch.path("rows").get(0).path("existing_candidates").isEmpty());
        long originalEvent=db.queryForObject("SELECT id FROM fba_receipt_event WHERE site_id=? AND scope_id=? AND event_key=?",Long.class,SITE,scope,"receive-10".getBytes());save(otherBatchId,1,List.of(Map.of("source_row","2","decision","SAME","existing_event_id",String.valueOf(originalEvent),"reason","SIMULATED intentionally incorrect cross-account event")));assertEquals("fba_duplicate_conflict",assertThrows(ProductionError.class,()->confirm(otherBatchId,2,List.of("2"))).code);

        // Published physical returns are idempotent across uploads and revisions.
        var firstReturn=new LinkedHashMap<String,Object>(Map.of("sku_id","1001","units","1","quality","QUALIFIED","customer_order_ref","REPORT-ORDER","source_event_ref","report-return:LPN1","occurred_at","2026-11-04T03:00:00-08:00","report_version_id","101"));
        var secondReturn=new LinkedHashMap<String,Object>(firstReturn);secondReturn.put("source_event_ref","report-return:LPN2");secondReturn.put("quality","DEFECTIVE");
        var daily=new LinkedHashMap<String,Object>();daily.put("scope_id",String.valueOf(scope));daily.put("_report_source_scope_id","1");daily.put("_trusted_report_returns",List.of(firstReturn,secondReturn));daily.put("_report_set_complete",true);daily.put("report_version_ids",List.of("101"));daily.put("reason","SIMULATED published actual return evidence");
        call("fba-report-sync",daily);assertEquals(21,balance("qualified_units"));assertEquals(1,balance("defective_units"));
        long dailyEvents=events();call("fba-report-sync",daily);assertEquals(dailyEvents,events());
        long qualityRevision=db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope);
        var quality=body(Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(qualityRevision),"from_quality","QUALIFIED","target_quality","DEFECTIVE","business_date","2026-11-04","reason","SIMULATED batch status adjustment","lines",List.of(Map.of("sku_id","1001","units","1"))));
        var qualityResult=command("fba-quality",quality);assertEquals(qualityResult,command("fba-quality",quality));assertEquals(20,balance("qualified_units"));assertEquals(2,balance("defective_units"));
        dailyEvents=events();call("fba-report-sync",daily);assertEquals(dailyEvents,events());assertEquals(2,balance("defective_units"));
        firstReturn.put("units","2");daily.put("report_version_ids",List.of("102"));call("fba-report-sync",daily);assertEquals(21,balance("qualified_units"));assertEquals(2,balance("defective_units"));
        daily.put("_trusted_report_returns",List.of(secondReturn));daily.put("_report_set_complete",false);dailyEvents=events();call("fba-report-sync",daily);assertEquals(dailyEvents,events());
        daily.put("_report_set_complete",true);call("fba-report-sync",daily);assertEquals(19,balance("qualified_units"));assertEquals(2,balance("defective_units"));
        // Published business sales deduct once, revisions/withdrawal restore the
        // correct delta, and manual same-day fulfillment never double-deducts.
        var sale=new LinkedHashMap<String,Object>(Map.of("sku_id","1001","report_units","5","business_date","2026-11-04","occurred_at","2026-11-04T23:59:59-08:00","report_version_ids",List.of("201")));
        daily.put("_trusted_report_sales",List.of(sale));call("fba-report-sync",daily);assertEquals(14,balance("qualified_units"));
        long salesEvents=events();call("fba-report-sync",daily);assertEquals(salesEvents,events());
        long reportAction=db.queryForObject("SELECT id FROM fba_action WHERE site_id=? AND scope_id=? AND status='POSTED' AND JSON_EXTRACT(payload,'$.report_sales_key') IS NOT NULL",Long.class,SITE,scope);
        assertEquals("fba_report_managed",assertThrows(ProductionError.class,()->call("fba-action-reverse",Map.of("action_id",String.valueOf(reportAction),"expected_revision","1","reason","SIM forbidden direct report undo"))).code);
        sale.put("report_units","7");sale.put("report_version_ids",List.of("202"));call("fba-report-sync",daily);assertEquals(12,balance("qualified_units"));
        sale.put("report_version_ids",List.of("203"));salesEvents=events();call("fba-report-sync",daily);assertEquals(salesEvents,events());
        var manualSales=call("fba-actions",Map.of("scope_id",String.valueOf(scope),"kind","FULFILLMENT","event_key","manual-over-report","occurred_at","2026-11-04T12:00:00-08:00","reason","SIM real fulfillment covers report sales","physical_fact_confirmed",true,"lines",List.of(Map.of("sku_id","1001","units","7"))));assertEquals(12,balance("qualified_units"));
        long manualId=manualSales.path("actions").valueStream().filter(record->record.path("event_key").asText().equals("manual-over-report")).findFirst().orElseThrow().path("id").asLong();
        call("fba-action-reverse",Map.of("action_id",String.valueOf(manualId),"expected_revision","1","reason","SIM undo manual leaves report deduction"));assertEquals(12,balance("qualified_units"));
        sale.put("report_units","3");call("fba-report-sync",daily);assertEquals(16,balance("qualified_units"));
        sale.put("report_units","100");salesEvents=events();assertEquals("insufficient_available_stock",assertThrows(ProductionError.class,()->call("fba-report-sync",daily)).code);assertEquals(salesEvents,events());assertEquals(16,balance("qualified_units"));
        daily.put("_trusted_report_sales",List.of());daily.put("_report_set_complete",false);call("fba-report-sync",daily);assertEquals(16,balance("qualified_units"));
        daily.put("_report_set_complete",true);call("fba-report-sync",daily);assertEquals(19,balance("qualified_units"));
        var invalidScope=new LinkedHashMap<String,Object>(daily);invalidScope.put("_report_source_scope_id","2");assertEquals("fba_report_reference_invalid",assertThrows(ProductionError.class,()->call("fba-report-sync",invalidScope)).code);
        qualityRevision=db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope);
        var over=body(Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(qualityRevision),"from_quality","QUALIFIED","target_quality","DEFECTIVE","business_date","2026-11-04","reason","SIMULATED cannot convert excess stock","lines",List.of(Map.of("sku_id","1001","units","100"))));
        dailyEvents=events();assertThrows(ProductionError.class,()->command("fba-quality",over));assertEquals(dailyEvents,events());
        var damagedReceipt=new LinkedHashMap<String,Object>(row(2,"1","2026-11-05T03:00:00-08:00"));damagedReceipt.put("quality","DEFECTIVE");
        var damagedRaw=(tools.jackson.databind.node.ObjectNode)json.valueToTree(damagedReceipt.get("raw"));damagedRaw.put("Disposition","CUSTOMER_DAMAGED");damagedReceipt.put("raw",damagedRaw);
        long damagedBatch=upload("SIMULATED explicit damaged receipt",List.of(damagedReceipt)).path("id").asLong();
        save(damagedBatch,1,List.of(decision(2,"1","damaged-receipt","")));confirm(damagedBatch,2,List.of("2"));
        assertEquals(19,balance("qualified_units"));assertEquals(3,balance("defective_units"));
        var inventoryState=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-state",Map.of("warehouse_id","2"))));
        assertEquals(2,inventoryState.path("quality_events").size());assertEquals("DEFECTIVE",inventoryState.path("events").get(inventoryState.path("events").size()-1).path("quality").asText());
        long wrongQualityBatch=upload("SIMULATED invalid correction quality",List.of(row(2,"-1","2026-11-05T04:00:00-08:00"))).path("id").asLong();
        save(wrongQualityBatch,1,List.of(decision(2,"-1","wrong-quality-correction","damaged-receipt")));
        dailyEvents=events();assertEquals("fba_correction_conflict",assertThrows(ProductionError.class,()->confirm(wrongQualityBatch,2,List.of("2"))).code);assertEquals(dailyEvents,events());
        // Order attribution is metadata only, including an already-received FBA shipment.
        db.update("INSERT INTO production_warehouse(site_id,id,name,type,country,profile) VALUES(?,1,'SIMULATED source','OWN','CN','{}')",SITE);
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token) VALUES(?,1,1,'SIMULATED source','SIM owner','2026-09-30','SIM-source-opening',?)",SITE,UUID.randomUUID().toString());
        db.update("UPDATE production_shipment SET dispatch_purpose='WAREHOUSE_DISPATCH',warehouse_id=1,owner_id=1,business_date='2026-10-24',destination_type='WAREHOUSE',destination='SIMULATED FBA',cartons=? WHERE site_id=? AND id=?","[{\"id\":\"test-carton\",\"number\":\"SIM-CARTON\",\"items\":[{\"sku_id\":\"1001\",\"units\":\"100\"}]}]",SITE,shipment);
        var production=new ProductionService(db,json,"demo_fixed");
        var beforeAttribution=json.valueToTree(production.get(actor,"shipments",shipment));
        var attribution=body(Map.of("expected_revision","1","reason","SIMULATED confirm existing order attribution","sources",beforeAttribution.path("sources")));
        long beforeAttributionEvents=events();
        tx.execute(t->production.command(actor,"shipments",shipment,"allocation-corrections",attribution.path("operation_token").asText(),attribution));
        assertEquals(beforeAttributionEvents,events());
        assertEquals(2,db.queryForObject("SELECT shipment_revision FROM fba_reference WHERE site_id=? AND shipment_id=?",Long.class,SITE,shipment));
        var refreshedBatch=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-batches/"+batchId,Map.of())));
        assertFalse(refreshedBatch.path("rows").get(0).path("bindings").isEmpty());
        // Counts adjust the existing normal bucket; receipts and sales stay unchanged.
        long baseline = balance("qualified_units"), receiptEvents = db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=?",Long.class,SITE);
        String countDate = java.time.LocalDate.now(java.time.ZoneId.of("America/Los_Angeles")).toString();
        long countScopeRevision=db.queryForObject("SELECT revision FROM fba_scope WHERE site_id=? AND id=?",Long.class,SITE,scope);
        long stockRevision=db.queryForObject("SELECT revision FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1001",Long.class,SITE);
        var countBody=body(Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(countScopeRevision),"business_date",countDate,"reason","SIMULATED count verification: normal goods only", "lines",List.of(Map.of("sku_id","1001","units",String.valueOf(baseline+5),"balance_revision",String.valueOf(stockRevision)))));
        var counted=command("fba-stocktake",countBody);
        assertEquals(baseline+5,balance("qualified_units")); assertEquals(receiptEvents,db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=?",Long.class,SITE));
        assertEquals(counted,command("fba-stocktake",countBody)); assertEquals(baseline+5,balance("qualified_units"));
        long documents=db.queryForObject("SELECT COUNT(*) FROM inventory_document WHERE site_id=?",Long.class,SITE);
        assertEquals("inventory_revision_conflict",assertThrows(ProductionError.class,()->call("fba-stocktake",Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(countScopeRevision),"business_date",countDate,"reason","SIMULATED stale count must retain its input", "lines",List.of(Map.of("sku_id","1001","units","0","balance_revision",String.valueOf(stockRevision)))))).code);
        assertEquals(documents,db.queryForObject("SELECT COUNT(*) FROM inventory_document WHERE site_id=?",Long.class,SITE));
        assertEquals(baseline+5,balance("qualified_units"));
        long newRevision=db.queryForObject("SELECT revision FROM inventory_balance WHERE site_id=? AND warehouse_id=2 AND owner_id=1 AND sku_id=1001",Long.class,SITE);
        call("fba-stocktake",Map.of("scope_id",String.valueOf(scope),"expected_revision",String.valueOf(countScopeRevision),"business_date",countDate,"reason","SIMULATED recount restores original normal quantity", "lines",List.of(Map.of("sku_id","1001","units",String.valueOf(baseline),"balance_revision",String.valueOf(newRevision)))));
        assertEquals(baseline,balance("qualified_units")); assertEquals(receiptEvents,db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=?",Long.class,SITE));
        var stocktakes=json.valueToTree(tx.execute(t->inventory.read(actor,"fba-state",Map.of("warehouse_id","2")))).path("stocktakes");
        assertEquals(2,stocktakes.size());
        assertEquals(0,stocktakes.get(0).path("units").asLong()+stocktakes.get(1).path("units").asLong());





    }
}

