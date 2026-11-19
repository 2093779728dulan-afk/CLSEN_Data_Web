package com.clsen.dataweb.production;

import java.math.BigInteger;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.ObjectMapper;

/** Read-only route groups. Shared paths group presentation; only allocations join freight to orders. */
final class ProductionChainStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final ProductionService production;
    private final InventoryService inventory;
    ProductionChainStore(JdbcTemplate db,ObjectMapper json,ProductionService production,InventoryService inventory){this.db=db;this.json=json;this.production=production;this.inventory=inventory;}
    private List<Map<String,Object>> rows(String sql,Object...args){return db.queryForList(sql,args).stream().map(DestinationReceiptStore::normalized).toList();}
    static String str(Map<String,Object> row,String key){return Objects.toString(row.get(key),"");}
    static BigInteger number(Map<String,Object> row,String key){return new BigInteger(Objects.toString(row.get(key),"0"));}
    static BigInteger sum(List<Map<String,Object>> rows,String key){return rows.stream().map(r->number(r,key)).reduce(BigInteger.ZERO,BigInteger::add);}
    @SuppressWarnings("unchecked") static List<Map<String,Object>> children(Map<String,Object> row,String key){return (List<Map<String,Object>>)row.getOrDefault(key,List.of());}
    private static String root(Map<String,String> parents,String id){String next=parents.get(id);if(!next.equals(id)){next=root(parents,next);parents.put(id,next);}return next;}
    private static void join(Map<String,String> parents,String a,String b){String x=root(parents,a),y=root(parents,b);if(!x.equals(y))parents.put(y,x);}

    /** Partial receipts are attributable only through explicit bindings, never by proportion. */
    static BigInteger allocationReceived(Map<String,Object> allocation,Map<String,Object> source,List<Map<String,Object>> bindings){
        var matching=bindings.stream().filter(b->str(b,"source_line_id").equals(str(source,"id"))).toList();
        if(!sum(matching,"units").equals(number(source,"actual_units")))return null;
        var own=matching.stream().filter(b->!str(allocation,"id").isEmpty()&&str(b,"allocation_id").equals(str(allocation,"id"))).toList();
        if(sum(own,"units").equals(number(allocation,"units")))return sum(own,"received_units");
        BigInteger got=sum(matching,"received_units");
        if(got.signum()==0)return BigInteger.ZERO;
        if(got.compareTo(number(source,"actual_units"))>=0)return number(allocation,"units");
        // A whole source with exactly one full allocation has an unambiguous owner even in old bindings.
        if(number(allocation,"units").equals(number(source,"actual_units")))return got;
        return null;
    }

    /** Same-route freight is visible context until the user explicitly confirms order attribution. */
    static List<Map<String,Object>> relatedShipments(Map<String,Object> group,List<Map<String,Object>> shipments,List<Map<String,Object>> sources,List<Map<String,Object>> allocations){
        var orders=children(group,"orders");
        if(orders.isEmpty()||!children(group,"shipments").isEmpty())return List.of();
        var allocatedSources=new HashSet<String>();allocations.forEach(a->allocatedSources.add(str(a,"source_line_id")));
        return shipments.stream().filter(s->"WAREHOUSE_DISPATCH".equals(str(s,"dispatch_purpose")))
            .filter(s->sources.stream().filter(x->str(x,"shipment_id").equals(str(s,"id"))).noneMatch(x->allocatedSources.contains(str(x,"id"))))
            .filter(s->orders.stream().anyMatch(o->!str(o,"receipt_warehouse_id").isEmpty()
                &&str(o,"receipt_warehouse_id").equals(str(s,"warehouse_id"))
                &&str(o,"receipt_owner_id").equals(str(s,"owner_id"))
                &&!str(o,"destination_id").isEmpty()&&str(o,"destination_id").equals(str(s,"destination_id"))
                &&str(o,"destination_type").equals(str(s,"destination_type"))
                &&sources.stream().anyMatch(x->str(x,"shipment_id").equals(str(s,"id"))
                    &&children(o,"lines").stream().anyMatch(l->str(l,"sku_id").equals(str(x,"sku_id")))))).toList();
    }

    static List<Map<String,Object>> groups(List<Map<String,Object>> orders,List<Map<String,Object>> shipments,List<Map<String,Object>> sources,List<Map<String,Object>> allocations,List<Map<String,Object>> bindings){
        var parents=new LinkedHashMap<String,String>();
        var byOrder=new HashMap<String,Map<String,Object>>();var byShipment=new HashMap<String,Map<String,Object>>();var bySource=new HashMap<String,Map<String,Object>>();
        orders.forEach(o->{String id=str(o,"id");parents.put("o"+id,"o"+id);byOrder.put(id,o);});
        shipments.forEach(s->{String id=str(s,"id");parents.put("s"+id,"s"+id);byShipment.put(id,s);});
        sources.forEach(s->bySource.put(str(s,"id"),s));
        appendFulfillment(orders,sources,allocations,bindings);
        var destinations=new HashMap<String,SortedSet<String>>();
        for(var a:allocations){var source=bySource.get(str(a,"source_line_id"));if(source==null||!byOrder.containsKey(str(a,"order_id")))continue;
            String sid=str(source,"shipment_id");if(!byShipment.containsKey(sid))continue;
            join(parents,"o"+str(a,"order_id"),"s"+sid);
            var batch=byShipment.get(sid);destinations.computeIfAbsent(str(a,"order_id"),k->new TreeSet<>()).add(str(batch,"destination_type")+":"+str(batch,"destination_id"));
        }
        for(var o:orders)if(!destinations.containsKey(str(o,"id"))&&!str(o,"destination_id").isEmpty())destinations.computeIfAbsent(str(o,"id"),k->new TreeSet<>()).add(str(o,"destination_type")+":"+str(o,"destination_id"));
        var completionByRoot=new HashMap<String,Boolean>();
        for(var o:orders)completionByRoot.merge(root(parents,"o"+str(o,"id")),orderCompleted(o),(a,b)->a&&b);
        for(var sh:shipments)completionByRoot.merge(root(parents,"s"+str(sh,"id")),shipmentCompleted(sh,sources,bindings),(a,b)->a&&b);
        var paths=new HashMap<String,String>();
        for(var o:orders){
            if(!str(o,"status").equals("CONFIRMED")||List.of("factory_id","receipt_warehouse_id","receipt_owner_id").stream().anyMatch(k->str(o,k).isEmpty()))continue;
            String path=str(o,"factory_id")+"/"+str(o,"receipt_warehouse_id")+"/"+str(o,"receipt_owner_id")+"/"+destinations.getOrDefault(str(o,"id"),new TreeSet<>())+"/"+completionByRoot.get(root(parents,"o"+str(o,"id")));
            String id="o"+str(o,"id");String previous=paths.putIfAbsent(path,id);if(previous!=null)join(parents,previous,id);
        }
        // Independent stock movements share a route, but never acquire an order from the warehouse name.
        var independentPaths=new HashMap<String,String>();
        for(var s:shipments){String id="s"+str(s,"id");if(!root(parents,id).startsWith("s"))continue;
            if(List.of("warehouse_id","owner_id","destination_id").stream().anyMatch(k->str(s,k).isEmpty()))continue;
            String path=str(s,"warehouse_id")+"/"+str(s,"owner_id")+"/"+str(s,"destination_type")+"/"+str(s,"destination_id")+"/"+shipmentCompleted(s,sources,bindings);String previous=independentPaths.putIfAbsent(path,id);if(previous!=null)join(parents,previous,id);
        }
        var grouped=new LinkedHashMap<String,Map<String,Object>>();
        for(String id:parents.keySet())grouped.computeIfAbsent(root(parents,id),key->{var g=new LinkedHashMap<String,Object>();g.put("orders",new ArrayList<Map<String,Object>>());g.put("shipments",new ArrayList<Map<String,Object>>());return g;});
        orders.forEach(o->children(grouped.get(root(parents,"o"+str(o,"id"))),"orders").add(o));
        shipments.forEach(s->children(grouped.get(root(parents,"s"+str(s,"id"))),"shipments").add(s));
        for(var group:grouped.values()){
            var os=children(group,"orders");var ss=children(group,"shipments");
            group.put("id",!os.isEmpty()?"order-"+os.stream().map(o->new BigInteger(str(o,"id"))).min(BigInteger::compareTo).orElseThrow():"shipment-"+ss.stream().map(s->new BigInteger(str(s,"id"))).min(BigInteger::compareTo).orElseThrow());
            boolean completed=(!os.isEmpty()||!ss.isEmpty())&&os.stream().allMatch(ProductionChainStore::orderCompleted)&&ss.stream().allMatch(sh->shipmentCompleted(sh,sources,bindings));
            group.put("completed",completed);
        }
        return new ArrayList<>(grouped.values());
    }

    private static boolean orderCompleted(Map<String,Object> o){
        return str(o,"status").equals("CONFIRMED")&&!children(o,"lines").isEmpty()
            &&children(o,"lines").stream().allMatch(l->l.get("produced_units")!=null&&number(l,"produced_units").compareTo(number(l,"expected_units"))>=0&&number(l,"received_units").add(number(l,"production_direct_units")).compareTo(number(l,"expected_units"))>=0)
            &&children(o,"fulfillment_lines").stream().allMatch(l->l.get("received_units")!=null&&number(l,"shipped_units").compareTo(number(l,"expected_units"))>=0&&number(l,"received_units").compareTo(number(l,"expected_units"))>=0);
    }

    private static void appendFulfillment(List<Map<String,Object>> orders,List<Map<String,Object>> sources,List<Map<String,Object>> allocations,List<Map<String,Object>> bindings){
        var bySource=new HashMap<String,Map<String,Object>>();sources.forEach(source->bySource.put(str(source,"id"),source));
        for(var o:orders){
            var fulfillment=new ArrayList<Map<String,Object>>();
            for(var line:children(o,"lines")){
                var own=allocations.stream().filter(a->str(a,"order_id").equals(str(o,"id"))&&str(a,"order_line_id").equals(str(line,"id"))).toList();
                BigInteger received=BigInteger.ZERO;
                for(var a:own){var source=bySource.get(str(a,"source_line_id"));BigInteger got=source==null?null:allocationReceived(a,source,bindings);if(got==null){received=null;break;}received=received.add(got);}
                var f=new LinkedHashMap<String,Object>();f.put("id",line.get("id"));f.put("sku_id",line.get("sku_id"));f.put("expected_units",line.get("expected_units"));f.put("shipped_units",sum(own,"units").toString());f.put("received_units",received==null?null:received.toString());fulfillment.add(f);
            }
            o.put("fulfillment_lines",fulfillment);
        }
    }

    /** Enrich the existing order board with the same proven quantities used by the chain. */
    void annotateOrders(ProductionContext context,List<Map<String,Object>> orders){
        if(orders.isEmpty())return;
        var args=new ArrayList<Object>();args.add(context.site());orders.forEach(order->args.add(order.get("id")));
        String orderMarks=String.join(",",Collections.nCopies(orders.size(),"?"));
        var allocations=rows("SELECT a.id,a.source_line_id,a.order_line_id,a.units,l.order_id FROM production_shipment_allocation a JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id WHERE a.site_id=? AND l.order_id IN ("+orderMarks+") AND a.is_active=TRUE AND l.is_active=TRUE AND x.is_active=TRUE AND s.status='CONFIRMED'",args.toArray());
        var sourceIds=allocations.stream().map(a->a.get("source_line_id")).distinct().toList();
        if(sourceIds.isEmpty()){appendFulfillment(orders,List.of(),allocations,List.of());return;}
        var sourceArgs=new ArrayList<Object>();sourceArgs.add(context.site());sourceArgs.addAll(sourceIds);
        String sourceMarks=String.join(",",Collections.nCopies(sourceIds.size(),"?"));
        var sources=rows("SELECT id,actual_units FROM production_shipment_source_line WHERE site_id=? AND id IN ("+sourceMarks+") AND is_active=TRUE",sourceArgs.toArray());
        var bindings=rows("""
            SELECT b.id,b.source_line_id,b.allocation_id,b.units,
              COALESCE((SELECT SUM(l.qualified_units+l.pending_units+l.defective_units) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=b.site_id AND l.binding_id=b.id AND r.status='POSTED'),0)+COALESCE((SELECT SUM(a.units) FROM fba_event_allocation a WHERE a.site_id=b.site_id AND a.binding_id=b.id),0) AS received_units
            FROM destination_shipment_binding b WHERE b.site_id=? AND b.is_active=TRUE AND b.source_line_id IN (
            """+sourceMarks+")",sourceArgs.toArray());
        appendFulfillment(orders,sources,allocations,bindings);
    }

    private static boolean shipmentCompleted(Map<String,Object> s,List<Map<String,Object>> sources,List<Map<String,Object>> bindings){
        var own=sources.stream().filter(x->str(x,"shipment_id").equals(str(s,"id"))).toList();
        return !own.isEmpty()&&own.stream().allMatch(x->{var bs=bindings.stream().filter(b->str(b,"source_line_id").equals(str(x,"id"))).toList();return sum(bs,"units").equals(number(x,"actual_units"))&&sum(bs,"received_units").compareTo(number(x,"actual_units"))>=0;});
    }

    Map<String,Object> read(ProductionContext context,Map<String,String> query){
        int page,size;try{page=Integer.parseInt(query.getOrDefault("page","1"));size=Integer.parseInt(query.getOrDefault("page_size","5"));}catch(NumberFormatException e){throw new ProductionError(422,"invalid_page","分页参数无效。");}
        if(page<1||page>1000000||size<1||size>20)throw new ProductionError(422,"invalid_page","分页参数无效。");
        String state=query.getOrDefault("chain_progress","active"),progress=query.getOrDefault("progress","all");
        if(!Set.of("active","completed","all").contains(state)||!Set.of("active","completed","all").contains(progress))throw new ProductionError(422,"invalid_production_progress","完成状态筛选无效。");
        for(String key:List.of("factory","warehouse_id","trace_id"))if(!query.getOrDefault(key,"").isEmpty()&&!(key.equals("factory")&&query.get(key).equals("unknown")))ProductionService.positive(json.getNodeFactory().textNode(query.get(key)),key);
        String kind=query.getOrDefault("trace_kind",""),target=query.getOrDefault("trace_id","");
        if(!target.isEmpty()&&!Set.of("order","shipment").contains(kind))throw new ProductionError(422,"invalid_trace_target","链路定位无效。");
        var orders=rows("""
            SELECT o.*,f.name AS factory_name,COALESCE((SELECT r.operation_kind FROM production_revision r WHERE r.site_id=o.site_id AND r.document_kind='orders' AND r.document_id=o.id AND r.operation_kind IN ('COMPLETE_PRODUCTION','REOPEN_PRODUCTION') ORDER BY r.revision DESC LIMIT 1),'REOPEN_PRODUCTION') AS completion_operation
            FROM production_order o LEFT JOIN production_factory f ON f.site_id=o.site_id AND f.id=o.factory_id WHERE o.site_id=? ORDER BY o.business_date DESC,o.id DESC
            """,context.site());
        var lines=production.orderLinesFor(context.site(),orders.stream().map(o->o.get("id")).toList());
        for(var order:orders){ProductionService.quantities(order,lines.stream().filter(l->str(l,"order_id").equals(str(order,"id"))).toList());ProductionService.productionCompletion(order,List.of(Map.of("operation_kind",order.remove("completion_operation"))));}
        var shipments=rows("SELECT s.id,s.business_number,s.system_number,s.dispatch_purpose,s.warehouse_id,s.owner_id,s.destination_id,s.destination_type,w.name AS source_name,d.name AS destination_name FROM production_shipment s LEFT JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id LEFT JOIN production_warehouse d ON d.site_id=s.site_id AND d.id=s.destination_id WHERE s.site_id=? AND s.status='CONFIRMED' ORDER BY s.id DESC",context.site());
        var sources=rows("SELECT x.id,x.shipment_id,x.sku_id,x.sku_label,x.actual_units FROM production_shipment_source_line x JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id WHERE x.site_id=? AND x.is_active=TRUE AND s.status='CONFIRMED'",context.site());
        var allocations=rows("SELECT a.id,a.source_line_id,a.order_line_id,a.units,l.order_id FROM production_shipment_allocation a JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id WHERE a.site_id=? AND a.is_active=TRUE AND l.is_active=TRUE AND x.is_active=TRUE AND s.status='CONFIRMED'",context.site());
        var bindings=rows("""
            SELECT b.id,b.source_line_id,b.allocation_id,b.units,
              COALESCE((SELECT SUM(l.qualified_units+l.pending_units+l.defective_units) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=b.site_id AND l.binding_id=b.id AND r.status='POSTED'),0)+COALESCE((SELECT SUM(a.units) FROM fba_event_allocation a WHERE a.site_id=b.site_id AND a.binding_id=b.id),0) AS received_units
            FROM destination_shipment_binding b JOIN production_shipment s ON s.site_id=b.site_id AND s.id=b.shipment_id WHERE b.site_id=? AND b.is_active=TRUE AND s.status='CONFIRMED'
            """,context.site());
        var chainOrders=orders.stream().filter(o->!str(o,"status").equals("VOID")
            ||kind.equals("order")&&str(o,"id").equals(target)).toList();
        var groups=groups(chainOrders,shipments,sources,allocations,bindings);
        for(var group:groups)group.put("related_shipments",relatedShipments(group,shipments,sources,allocations));
        String q=query.getOrDefault("q","").trim().toLowerCase(Locale.ROOT),factory=query.getOrDefault("factory",""),warehouse=query.getOrDefault("warehouse_id","");
        var filtered=groups.stream().filter(g->{var os=children(g,"orders");var ss=children(g,"shipments");
            if(!os.isEmpty()&&ss.isEmpty()&&os.stream().allMatch(o->str(o,"status").equals("VOID")))return false;
            if(!factory.isEmpty()&&os.stream().noneMatch(o->factory.equals("unknown")?str(o,"factory_id").isEmpty():str(o,"factory_id").equals(factory)))return false;
            if(!warehouse.isEmpty()&&os.stream().noneMatch(o->str(o,"receipt_warehouse_id").equals(warehouse))&&ss.stream().noneMatch(s->str(s,"warehouse_id").equals(warehouse)||str(s,"destination_id").equals(warehouse)))return false;
            if(!progress.equals("all")&&!os.isEmpty()&&os.stream().noneMatch(o->progress.equals("completed")?str(o,"production_completion_state").equals("COMPLETED"):!str(o,"production_completion_state").equals("COMPLETED")&&!str(o,"status").equals("VOID")))return false;
            if(q.isEmpty())return true;
            return os.stream().anyMatch(o->(str(o,"business_number")+" "+str(o,"system_number")+" "+str(o,"factory_name")).toLowerCase(Locale.ROOT).contains(q)||children(o,"lines").stream().anyMatch(l->str(l,"sku_label").toLowerCase(Locale.ROOT).contains(q)))||ss.stream().anyMatch(s->(str(s,"business_number")+" "+str(s,"system_number")).toLowerCase(Locale.ROOT).contains(q)||sources.stream().anyMatch(x->str(x,"shipment_id").equals(str(s,"id"))&&str(x,"sku_label").toLowerCase(Locale.ROOT).contains(q)));
        }).toList();
        long completed=filtered.stream().filter(g->Boolean.TRUE.equals(g.get("completed"))).count();
        var selected=target.isEmpty()?filtered.stream().filter(g->state.equals("all")||Boolean.TRUE.equals(g.get("completed"))==state.equals("completed")).toList():groups.stream().filter(g->children(g,kind.equals("order")?"orders":"shipments").stream().anyMatch(r->str(r,"id").equals(target))).toList();
        long total=selected.size();int start=target.isEmpty()?Math.min(selected.size(),(page-1)*size):0;
        var items=selected.subList(start,target.isEmpty()?Math.min(selected.size(),start+size):selected.size());
        for(var group:items)for(String collection:List.of("shipments","related_shipments")){var full=new ArrayList<Map<String,Object>>();for(var s:children(group,collection)){
            var result=json.valueToTree(new WarehouseTransitStore(db,json,inventory).batches(context,Map.of("shipment_id",str(s,"id"),"page_size","1"),Instant.now()));
            if(!result.path("items").isEmpty())full.add(json.convertValue(result.path("items").get(0),new tools.jackson.core.type.TypeReference<Map<String,Object>>(){}));
        }group.put(collection,full);}
        return Map.of("items",items,"total",total,"page",page,"page_size",size,"chain_counts",Map.of("all",filtered.size(),"completed",completed,"active",filtered.size()-completed),"detail_scope","complete_chain_groups","stock_effect",false);
    }
}
