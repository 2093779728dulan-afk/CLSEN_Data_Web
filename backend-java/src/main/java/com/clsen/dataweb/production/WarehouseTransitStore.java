package com.clsen.dataweb.production;

import java.time.Instant;
import java.time.Duration;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

/** Warehouse view of the existing shipment, transport and receipt facts. No writes. */
final class WarehouseTransitStore {
    private final JdbcTemplate db; private final ObjectMapper json; private final InventoryService inventory;
    WarehouseTransitStore(JdbcTemplate db,ObjectMapper json,InventoryService inventory){this.db=db;this.json=json;this.inventory=inventory;}
    private long n(Object value){return Long.parseLong(value.toString());}
    /** Selected destination and owner, one row per source. Receipts never multiply sources. */
    Object sheetSources(ProductionContext c, Map<String,Object> scope, java.time.LocalDate asOf) {
        return rows("""
            WITH receipts AS (
              SELECT l.binding_id,SUM(l.qualified_units+l.pending_units+l.defective_units) units
              FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id
              WHERE l.site_id=? AND r.status='POSTED' AND r.business_date<=? GROUP BY l.binding_id
            ), fba AS (
              SELECT a.binding_id,SUM(a.units) units FROM fba_event_allocation a
              JOIN fba_receipt_event e ON e.site_id=a.site_id AND e.id=a.event_id
              WHERE a.site_id=? AND e.business_date<=? GROUP BY a.binding_id
            ), settlements AS (
              SELECT binding_id,SUM(units) units FROM destination_receipt_settlement
              WHERE site_id=? AND status='ACTIVE' GROUP BY binding_id
            ), bound AS (
              SELECT b.source_line_id,SUM(b.units) mapped,SUM(COALESCE(r.units,0)+COALESCE(f.units,0)) received,
                SUM(COALESCE(x.units,0)) settled
              FROM destination_shipment_binding b LEFT JOIN receipts r ON r.binding_id=b.id
              LEFT JOIN fba f ON f.binding_id=b.id LEFT JOIN settlements x ON x.binding_id=b.id
              WHERE b.site_id=? AND b.is_active=TRUE GROUP BY b.source_line_id
            )
            SELECT s.id shipment_id,s.business_number,s.business_date,s.revision,x.id source_line_id,x.sku_id,x.actual_units,
              COALESCE(b.mapped,0) mapped,COALESCE(b.received,0) received_units,COALESCE(b.settled,0) settled_units,
              (SELECT COUNT(*) FROM destination_receipt_settlement z JOIN destination_shipment_binding zb
                ON zb.site_id=z.site_id AND zb.id=z.binding_id WHERE z.site_id=s.site_id
                AND zb.source_line_id=x.id AND z.status='ACTIVE') settlement_history,
              COALESCE((SELECT e.event_kind FROM shipment_transport t JOIN shipment_transport_event e
                ON e.site_id=t.site_id AND e.transport_id=t.id WHERE t.site_id=s.site_id AND t.shipment_id=s.id
                AND LEFT(e.occurred_local,10)<=? ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'UNREGISTERED') transport_status
            FROM production_shipment s JOIN production_shipment_source_line x
              ON x.site_id=s.site_id AND x.shipment_id=s.id AND x.is_active=TRUE
            LEFT JOIN bound b ON b.source_line_id=x.id
            WHERE s.site_id=? AND s.status='CONFIRMED' AND s.destination_id=? AND s.owner_id=? AND s.business_date<=?
            ORDER BY s.id,x.id
            """, c.site(), asOf, c.site(), asOf, c.site(), c.site(), asOf,
                c.site(), scope.get("warehouse_id"), scope.get("owner_id"), asOf);
    }
    private List<Map<String,Object>> rows(String sql,Object...args){return db.queryForList(sql,args).stream().map(DestinationReceiptStore::normalized).toList();}
    /** Full site summary, once per stable shipment source. Directional warehouse pages are not summed. */
    Object summary(ProductionContext c,Instant asOf){
        var sources=rows("""
            WITH receipts AS (
              SELECT l.binding_id,SUM(l.qualified_units+l.pending_units+l.defective_units) units
              FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id
              WHERE l.site_id=? AND r.status='POSTED' GROUP BY l.binding_id
            ), fba AS (
              SELECT binding_id,SUM(units) units FROM fba_event_allocation WHERE site_id=? GROUP BY binding_id
            ), settlements AS (
              SELECT binding_id,SUM(units) units FROM destination_receipt_settlement WHERE site_id=? AND status='ACTIVE' GROUP BY binding_id
            ), bound AS (
              SELECT b.shipment_id,b.source_line_id,SUM(b.units) mapped,
                SUM(COALESCE(r.units,0)+COALESCE(f.units,0)) received,SUM(COALESCE(x.units,0)) settled
              FROM destination_shipment_binding b LEFT JOIN receipts r ON r.binding_id=b.id LEFT JOIN fba f ON f.binding_id=b.id
              LEFT JOIN settlements x ON x.binding_id=b.id WHERE b.site_id=? AND b.is_active=TRUE GROUP BY b.shipment_id,b.source_line_id
            )
            SELECT s.id shipment_id,x.id source_id,x.sku_id,x.actual_units,COALESCE(b.mapped,0) mapped,
              COALESCE(b.received,0) received,COALESCE(b.settled,0) settled,
              COALESCE((SELECT e.event_kind FROM shipment_transport t JOIN shipment_transport_event e ON e.site_id=t.site_id AND e.transport_id=t.id
                WHERE t.site_id=s.site_id AND t.shipment_id=s.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'UNREGISTERED') transport_status
            FROM production_shipment s JOIN production_shipment_source_line x ON x.site_id=s.site_id AND x.shipment_id=s.id AND x.is_active=TRUE
            LEFT JOIN bound b ON b.shipment_id=s.id AND b.source_line_id=x.id
            WHERE s.site_id=? AND s.status='CONFIRMED' ORDER BY s.id,x.id
            """,c.site(),c.site(),c.site(),c.site(),c.site());
        var items=new LinkedHashMap<String,Map<String,Object>>();
        for(var source:sources){
            boolean known=n(source.get("mapped"))==n(source.get("actual_units"));
            Long remaining=known?Math.subtractExact(n(source.get("actual_units")),n(source.get("received"))):null;
            String status=source.get("transport_status").toString();String stage=classify(remaining,n(source.get("settled")),status,status.equals("DISPATCHED"));
            if(stage.equals("RECEIVED")||stage.equals("SETTLED"))continue;
            long unsettled=known?Math.subtractExact(remaining,n(source.get("settled"))):0;
            if(known&&unsettled==0)continue;
            String key=switch(stage){case "IN_TRANSIT"->"in_transit_units";case "ARRIVAL_CHECK"->"arrival_check_units";case "EXCEPTION"->"exception_units";default->"unregistered_units";};
            String sku=source.get("sku_id").toString();var item=items.computeIfAbsent(sku,ignored->summaryRow(sku));
            if(!known){item.put(key,null);item.put("unknown_sources",n(item.get("unknown_sources"))+1);}
            else if(item.get(key)!=null)item.put(key,Long.toString(Math.addExact(n(item.get(key)),unsettled)));
        }
        var totals=summaryRow("");
        for(var item:items.values())for(String key:List.of("in_transit_units","arrival_check_units","exception_units","unregistered_units")){
            if(item.get(key)==null)totals.put(key,null);else if(totals.get(key)!=null)totals.put(key,Long.toString(Math.addExact(n(totals.get(key)),n(item.get(key)))));
        }
        totals.put("unknown_sources",items.values().stream().mapToLong(item->n(item.get("unknown_sources"))).sum());
        return Map.of("items",new ArrayList<>(items.values()),"totals",totals,"as_of",asOf.toString(),"full_scope",true,"scope","all confirmed site shipment sources; settled differences excluded","stock_effect",false);
    }
    private Map<String,Object> summaryRow(String sku){
        var item=new LinkedHashMap<String,Object>();item.put("sku_id",sku);
        for(String key:List.of("in_transit_units","arrival_check_units","exception_units","unregistered_units"))item.put(key,"0");item.put("unknown_sources",0L);return item;
    }
    Object read(ProductionContext c,Map<String,String> query,Instant asOf){return batchPage(c,query,asOf,false);}
    Object batches(ProductionContext c,Map<String,String> query,Instant asOf){return batchPage(c,query,asOf,true);}
    private Object batchPage(ProductionContext c,Map<String,String> query,Instant asOf,boolean all){
        long warehouse=all?0:ProductionService.positive(json.getNodeFactory().textNode(query.getOrDefault("warehouse_id","")),"仓库");String owner=query.getOrDefault("owner_id","");
        if(!owner.isEmpty())ProductionService.positive(json.getNodeFactory().textNode(owner),"货权");
        if(!all&&db.queryForObject("SELECT COUNT(*) FROM production_warehouse WHERE site_id=? AND id=?",Long.class,c.site(),warehouse)!=1)throw new ProductionError(404,"warehouse_not_found","当前站点没有此仓库。");
        String direction=all?"all":query.getOrDefault("direction","incoming");if(!all&&!Set.of("incoming","outgoing").contains(direction))throw new ProductionError(422,"transit_direction_invalid","请选择待运入或已发出。");
        int page,pageSize;try{page=Integer.parseInt(query.getOrDefault("page","1"));pageSize=Integer.parseInt(query.getOrDefault("page_size","20"));}catch(NumberFormatException ex){throw new ProductionError(422,"invalid_page","页码无效。");}
        if(page<1||page>1000000||pageSize<1||pageSize>100)throw new ProductionError(422,"invalid_page","页码或每页条数无效。");
        String where="s.site_id=? AND s.status='CONFIRMED'";var args=new ArrayList<Object>(List.of(c.site()));
        if(!all){where+=" AND s."+(direction.equals("incoming")?"destination_id":"warehouse_id")+"=?";args.add(warehouse);}
        String warehouseFilter=query.getOrDefault("warehouse_id","");
        if(all&&!warehouseFilter.isEmpty()){ProductionService.positive(json.getNodeFactory().textNode(warehouseFilter),"仓库");where+=" AND (s.warehouse_id=? OR s.destination_id=?)";args.add(warehouseFilter);args.add(warehouseFilter);}
        String shipmentFilter=query.getOrDefault("shipment_id","");if(all&&!shipmentFilter.isEmpty()){ProductionService.positive(json.getNodeFactory().textNode(shipmentFilter),"运输批次");where+=" AND s.id=?";args.add(shipmentFilter);}
        String orderFilter=query.getOrDefault("order_id","");
        if(all&&!orderFilter.isEmpty()){ProductionService.positive(json.getNodeFactory().textNode(orderFilter),"订单");where+=" AND EXISTS(SELECT 1 FROM production_shipment_source_line x JOIN production_shipment_allocation a ON a.site_id=x.site_id AND a.source_line_id=x.id JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id WHERE x.site_id=s.site_id AND x.shipment_id=s.id AND x.is_active=TRUE AND a.is_active=TRUE AND l.is_active=TRUE AND l.order_id=?)";args.add(orderFilter);}
        if(!owner.isEmpty()){where+=" AND s.owner_id=?";args.add(owner);}
        String exactSku=query.getOrDefault("sku_id","");if(!exactSku.isEmpty()){ProductionService.positive(json.getNodeFactory().textNode(exactSku),"SKU");where+=" AND EXISTS(SELECT 1 FROM production_shipment_source_line x WHERE x.site_id=s.site_id AND x.shipment_id=s.id AND x.is_active=TRUE AND x.sku_id=?)";args.add(exactSku);}
        String search=query.getOrDefault("q","").trim();if(!search.isEmpty()){where+=" AND (s.business_number LIKE ? OR s.system_number LIKE ? OR EXISTS(SELECT 1 FROM production_shipment_source_line x WHERE x.site_id=s.site_id AND x.shipment_id=s.id AND x.is_active=TRUE AND (x.sku_label LIKE ? OR CAST(x.sku_id AS CHAR)=?)))";args.add("%"+search+"%");args.add("%"+search+"%");args.add("%"+search+"%");args.add(search);}
        String node=query.getOrDefault("node","");if(!node.isEmpty()){
            if(!Set.of("UNREGISTERED","IN_TRANSIT","ARRIVED","SIGNED","EXCEPTION").contains(node))throw new ProductionError(422,"transport_event_invalid","物流节点筛选无效。");
            where+=" AND COALESCE((SELECT e.event_kind FROM shipment_transport t JOIN shipment_transport_event e ON e.site_id=t.site_id AND e.transport_id=t.id WHERE t.site_id=s.site_id AND t.shipment_id=s.id ORDER BY e.occurred_at DESC,e.id DESC LIMIT 1),'UNREGISTERED') "+(node.equals("IN_TRANSIT")?"IN ('DISPATCHED','IN_TRANSIT')":"=?");if(!node.equals("IN_TRANSIT"))args.add(node);
        }
        long total=db.queryForObject("SELECT COUNT(*) FROM production_shipment s WHERE "+where,Long.class,args.toArray());args.add(pageSize);args.add((page-1)*pageSize);
        var shipments=rows("SELECT s.id,s.system_number,s.business_number,s.business_date,s.revision,s.owner_id,s.warehouse_id,s.destination_id,s.destination_type,s.dispatch_purpose,s.cartons,w.name AS source_name,d.name AS destination_name,d.type AS destination_kind FROM production_shipment s LEFT JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id LEFT JOIN production_warehouse d ON d.site_id=s.site_id AND d.id=s.destination_id WHERE "+where+" ORDER BY s.id DESC LIMIT ? OFFSET ?",args.toArray());
        var items=new ArrayList<Map<String,Object>>();
        for(var shipment:shipments){
            long id=n(shipment.get("id"));var transport=(Map<String,Object>)new ShipmentTransportStore(db,json,inventory).state(c,id);
            var destination=(Map<String,Object>)new DestinationReceiptStore(db,json,inventory).state(c,id);
            var bindings=(List<Map<String,Object>>)destination.get("bindings");
            var sources=(all||exactSku.isEmpty())?rows("SELECT id,sku_id,sku_label,actual_units,fulfillment_mode FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",c.site(),id):rows("SELECT id,sku_id,sku_label,actual_units,fulfillment_mode FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE AND sku_id=? ORDER BY id",c.site(),id,exactSku);
            long shipped=0,received=0,settled=0;boolean complete=true;
            for(var source:sources){long sourceId=n(source.get("id")),units=n(source.get("actual_units"));shipped=Math.addExact(shipped,units);
                var matching=bindings.stream().filter(b->n(b.get("source_line_id"))==sourceId).toList();long mapped=0,got=0,closed=0;
                for(var b:matching){mapped=Math.addExact(mapped,n(b.get("units")));got=Math.addExact(got,n(b.get("received_units")));closed=Math.addExact(closed,n(b.get("settled_units")));}
                boolean known=mapped==units;complete&=known;received=Math.addExact(received,got);settled=Math.addExact(settled,closed);
                source.put("received_units",known?Long.toString(got):null);source.put("unreceived_units",known?Long.toString(Math.subtractExact(units,got)):null);source.put("settled_units",known?Long.toString(closed):null);source.put("bindings",matching);
                source.put("allocations",rows("SELECT a.id,a.order_line_id,a.units,o.id AS order_id,o.business_number AS order_number FROM production_shipment_allocation a JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE a.site_id=? AND a.source_line_id=? AND a.is_active=TRUE",c.site(),sourceId));
            }
            var events=(List<Map<String,Object>>)transport.get("events");
            var departed=events.stream().filter(e->"DISPATCHED".equals(e.get("event_kind"))).min(Comparator.comparing(e->Instant.parse(e.get("occurred_at").toString()))).orElse(null);
            var arrived=events.stream().filter(e->"ARRIVED".equals(e.get("event_kind"))).min(Comparator.comparing(e->Instant.parse(e.get("occurred_at").toString()))).orElse(null);
            Long remaining=complete?Math.subtractExact(shipped,received):null;String status=transport.get("status").toString();
            String stage=classify(remaining,complete?settled:0,status,departed!=null);
            var record=(Map<String,Object>)transport.get("record");Instant eta=record!=null&&record.get("estimated_arrival")!=null?Instant.parse(record.get("estimated_arrival").toString()):null;
            shipment.put("sources",sources);shipment.put("bindings",bindings);shipment.put("cartons",shipment.get("cartons")==null?json.createArrayNode():json.readTree(shipment.get("cartons").toString()));
            shipment.put("planned_dispatch_dates",rows("SELECT DISTINCT p.planned_on FROM production_shipment_source_line x JOIN inventory_plan p ON p.site_id=x.site_id AND p.id=x.plan_id WHERE x.site_id=? AND x.shipment_id=? AND x.is_active=TRUE AND p.direction='OUT' AND p.planned_on IS NOT NULL ORDER BY p.planned_on",c.site(),id).stream().map(p->p.get("planned_on")).toList());
            shipment.put("shipped_units",Long.toString(shipped));shipment.put("received_units",complete?Long.toString(received):null);shipment.put("unreceived_units",remaining==null?null:remaining.toString());shipment.put("settled_units",complete?Long.toString(settled):null);
            shipment.put("stage",stage);shipment.put("transport",transport);shipment.put("departed",departed);shipment.put("arrived",arrived);shipment.put("eta_overdue",eta!=null&&asOf.isAfter(eta)&&!Set.of("RECEIVED","ARRIVAL_CHECK").contains(stage));
            shipment.put("duration_hours",departed!=null&&arrived!=null&&!Instant.parse(arrived.get("occurred_at").toString()).isBefore(Instant.parse(departed.get("occurred_at").toString()))?Long.toString(Duration.between(Instant.parse(departed.get("occurred_at").toString()),Instant.parse(arrived.get("occurred_at").toString())).toHours()):null);
            var receiptDates=new ArrayList<Object>(((List<Map<String,Object>>)destination.get("receipts")).stream().filter(r->"POSTED".equals(r.get("status"))).map(r->r.get("business_date")).toList());
            receiptDates.addAll(db.queryForList("SELECT DISTINCT e.business_date FROM fba_receipt_event e JOIN fba_event_allocation a ON a.site_id=e.site_id AND a.event_id=e.id JOIN destination_shipment_binding b ON b.site_id=a.site_id AND b.id=a.binding_id WHERE b.site_id=? AND b.shipment_id=? ORDER BY e.business_date",c.site(),id).stream().map(r->Objects.toString(r.get("business_date"))).toList());shipment.put("receipt_dates",receiptDates);items.add(shipment);
        }
        var result=new LinkedHashMap<String,Object>(Map.of("warehouse_id",all?"":Long.toString(warehouse),"owner_id",owner,"direction",direction,"items",items,"total",total,"page",page,"page_size",pageSize,"as_of",asOf.toString(),"stock_effect",false));
        if(all){result.put("scope","all_confirmed_site_shipments");result.put("detail_scope","whole_batch");result.put("filter_sku_id",exactSku);}
        return result;
    }
    static String classify(Long remaining,long settled,String transport,boolean departed){
        if(transport.equals("EXCEPTION"))return "EXCEPTION";
        if(remaining!=null&&remaining==0)return "RECEIVED";
        if(Set.of("ARRIVED","SIGNED").contains(transport))return "ARRIVAL_CHECK";
        if(remaining!=null&&remaining>0&&remaining==settled)return "SETTLED";
        if(transport.equals("IN_TRANSIT")||departed&&transport.equals("DISPATCHED"))return "IN_TRANSIT";
        return "UNREGISTERED";
    }
    Object locations(ProductionContext c,Map<String,String> query,Instant asOf){
        String sku=Long.toString(ProductionService.positive(json.getNodeFactory().textNode(query.getOrDefault("sku_id","")),"SKU"));int page;
        try{page=Integer.parseInt(query.getOrDefault("page","1"));}catch(NumberFormatException ex){throw new ProductionError(422,"invalid_page","页码无效。");}
        if(page<1||page>1000000)throw new ProductionError(422,"invalid_page","页码无效。");
        String join=" FROM production_warehouse w LEFT JOIN inventory_scope s ON s.site_id=w.site_id AND s.warehouse_id=w.id WHERE w.site_id=?";
        long total=db.queryForObject("SELECT COUNT(*)"+join,Long.class,c.site());
        var places=rows("SELECT w.id AS warehouse_id,w.name AS warehouse_name,w.type,w.status,s.owner_id,s.owner_name,s.cutoff_on"+join+" ORDER BY w.id,s.owner_id LIMIT 20 OFFSET ?",c.site(),(page-1)*20);
        for(var place:places){String warehouse=place.get("warehouse_id").toString(),owner=Objects.toString(place.get("owner_id"),"");
            place.put("balance",owner.isEmpty()?null:inventory.read(c,"availability",Map.of("warehouse_id",warehouse,"owner_id",owner,"sku_id",sku)));
            for(String direction:List.of("incoming","outgoing"))place.put(direction,read(c,Map.of("warehouse_id",warehouse,"owner_id",owner,"direction",direction,"sku_id",sku,"page_size","20"),asOf));
        }
        return Map.of("sku_id",sku,"items",places,"page",page,"page_size",20,"total",total,"as_of",asOf.toString(),"stock_effect",false);
    }
}
