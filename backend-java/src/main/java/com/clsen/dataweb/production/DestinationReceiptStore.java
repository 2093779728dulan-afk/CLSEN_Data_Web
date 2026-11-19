package com.clsen.dataweb.production;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Destination receipt persistence, called only inside the site-locked inventory transaction. */
final class DestinationReceiptStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final InventoryService inventory;
    DestinationReceiptStore(JdbcTemplate db,ObjectMapper json,InventoryService inventory){this.db=db;this.json=json;this.inventory=inventory;}
    private static long id(JsonNode node,String field){return ProductionService.positive(node.get(field),field);}
    private static long n(Object value){return Long.parseLong(value.toString());}
    private static ProductionError conflict(String message){return new ProductionError(409,"destination_receipt_conflict",message);}
    static Map<String,Object> normalized(Map<String,Object> row){
        var result=new LinkedHashMap<String,Object>();
        row.forEach((key,value)->{
            Object normalized=value;
            if(value instanceof java.sql.Date date)normalized=date.toLocalDate().toString();
            else if(value instanceof java.sql.Timestamp time)normalized=time.toInstant().toString();
            else if(value instanceof Number)normalized=value.toString();
            result.put(key,normalized);
        });
        return result;
    }

    private Map<String,Object> receipt(long site,long id,boolean lock){
        var rows=db.queryForList("SELECT * FROM destination_receipt WHERE site_id=? AND id=?"+(lock?" FOR UPDATE":""),site,id);
        if(rows.isEmpty())throw conflict("接收记录不存在或不属于当前站点。");
        var result=normalized(rows.getFirst());
        result.put("lines",db.queryForList("SELECT * FROM destination_receipt_line WHERE site_id=? AND receipt_id=? ORDER BY id",site,id).stream().map(DestinationReceiptStore::normalized).toList());
        return result;
    }

    Object get(ProductionContext c,long id){
        var result=receipt(c.site(),id,false);
        result.put("bindings",db.queryForList("SELECT b.*,s.sku_label,l.catalog_version FROM destination_receipt_line l JOIN destination_shipment_binding b ON b.site_id=l.site_id AND b.id=l.binding_id JOIN production_shipment_source_line s ON s.site_id=b.site_id AND s.id=b.source_line_id WHERE l.site_id=? AND l.receipt_id=? ORDER BY l.id",c.site(),id).stream().map(DestinationReceiptStore::normalized).toList());
        result.put("history",db.queryForList("SELECT revision,actor_id,actor_name,reason,operation_kind,created_at FROM production_revision WHERE site_id=? AND document_kind='destination' AND document_id=? ORDER BY revision DESC",c.site(),id).stream().map(DestinationReceiptStore::normalized).toList());
        return result;
    }

    Object state(ProductionContext c,long shipment){
        var headers=db.queryForList("SELECT id,status,revision,destination_id,destination_type FROM production_shipment WHERE site_id=? AND id=?",c.site(),shipment);
        if(headers.isEmpty())throw conflict("来源出货不存在或不属于当前站点。");
        var bindings=db.queryForList("SELECT b.*,s.sku_label,s.catalog_version,COALESCE((SELECT SUM(l.qualified_units+l.pending_units+l.defective_units) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=b.site_id AND l.binding_id=b.id AND r.status='POSTED'),0) AS received_units,COALESCE((SELECT SUM(x.units) FROM destination_receipt_settlement x WHERE x.site_id=b.site_id AND x.binding_id=b.id AND x.status='ACTIVE'),0) AS settled_units FROM destination_shipment_binding b JOIN production_shipment_source_line s ON s.site_id=b.site_id AND s.id=b.source_line_id WHERE b.site_id=? AND b.shipment_id=? AND b.is_active=TRUE ORDER BY b.id",c.site(),shipment);
        var receipts=db.queryForList("SELECT id,status,revision,warehouse_id,owner_id,business_date,reason,replaces_receipt_id FROM destination_receipt WHERE site_id=? AND shipment_id=? ORDER BY id DESC",c.site(),shipment);
        // FBA official receipts share these explicit carton/order allocations.
        // This is a projection of the same stock fact, never a second receipt write.
        for(var binding:bindings){long fba=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM fba_event_allocation WHERE site_id=? AND binding_id=?",Long.class,c.site(),binding.get("id"));binding.put("received_units",Math.addExact(n(binding.get("received_units")),fba));}
        var settlements=db.queryForList("SELECT x.* FROM destination_receipt_settlement x JOIN destination_shipment_binding b ON b.site_id=x.site_id AND b.id=x.binding_id WHERE b.site_id=? AND b.shipment_id=? ORDER BY x.id DESC",c.site(),shipment);
        return Map.of("shipment",normalized(headers.getFirst()),"bindings",bindings.stream().map(DestinationReceiptStore::normalized).toList(),"receipts",receipts.stream().map(DestinationReceiptStore::normalized).toList(),"settlements",settlements.stream().map(DestinationReceiptStore::normalized).toList());
    }

    Object saveDraft(ProductionContext c,Long receiptId,JsonNode input,String token){
        long shipment=id(input,"shipment_id"), sourceRevision=id(input,"expected_shipment_revision");
        var headers=db.queryForList("SELECT status,revision FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipment);
        if(headers.isEmpty() || !"CONFIRMED".equals(headers.getFirst().get("status")) || n(headers.getFirst().get("revision"))!=sourceRevision)
            throw conflict("来源出货状态或修订已变化，请保留输入并重新核对。");
        String date=ProductionService.text(input,"business_date",10),reason=ProductionService.text(input,"reason",2000);
        if(!date.isEmpty())InventoryService.day(date);
        Long warehouse=input.hasNonNull("warehouse_id")?id(input,"warehouse_id"):null;
        Long owner=input.hasNonNull("owner_id")?id(input,"owner_id"):null;
        if((warehouse==null)!=(owner==null))throw new ProductionError(422,"scope_incomplete","仓库和货权应同时选择。");
        if(warehouse!=null && db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",Long.class,c.site(),warehouse,owner)==0)
            throw conflict("目的仓及货权未建账或不属于当前站点，请重新选择。");
        JsonNode lines=input.path("lines");if(!lines.isArray()||lines.size()>5000)throw new ProductionError(422,"invalid_lines","接收明细应为不超过5000行的列表。");
        var before=receiptId==null?null:receipt(c.site(),receiptId,true);
        if(before!=null && (!"DRAFT".equals(before.get("status")) || n(before.get("revision"))!=id(input,"expected_revision") || n(before.get("shipment_id"))!=shipment))
            throw conflict("草稿状态、来源或修订已变化，请重新读取。");
        String upload=input.hasNonNull("upload_id")?ProductionService.text(input,"upload_id",36):before==null?"":Objects.toString(before.get("upload_id"),"");
        if(!upload.isEmpty() && db.queryForObject("SELECT COUNT(*) FROM destination_receipt_upload WHERE site_id=? AND shipment_id=? AND id=?",Long.class,c.site(),shipment,upload)!=1)
            throw conflict("导入原件不属于当前出货或站点，请重新上传核对。");
        if(receiptId==null){
            db.update("INSERT INTO destination_receipt(site_id,shipment_id,shipment_revision,warehouse_id,owner_id,business_date,reason,upload_id,actor_id,actor_name) VALUES(?,?,?,?,?,?,?,?,?,?)",c.site(),shipment,sourceRevision,warehouse,owner,date.isEmpty()?null:InventoryService.day(date),reason,upload.isEmpty()?null:upload,c.actor(),c.actorName());
            receiptId=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
        }else{
            db.update("UPDATE destination_receipt SET shipment_revision=?,warehouse_id=?,owner_id=?,business_date=?,reason=?,upload_id=?,revision=revision+1 WHERE site_id=? AND id=?",sourceRevision,warehouse,owner,date.isEmpty()?null:InventoryService.day(date),reason,upload.isEmpty()?null:upload,c.site(),receiptId);
            db.update("DELETE FROM destination_receipt_line WHERE site_id=? AND receipt_id=?",c.site(),receiptId);
        }
        var seen=new HashSet<Long>();
        for(var line:lines){
            long binding=id(line,"binding_id"),sku=id(line,"sku_id");if(!seen.add(binding))throw new ProductionError(422,"duplicate_binding","同一箱来源不能在草稿中重复。");
            var found=db.queryForList("SELECT sku_id FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND id=? AND is_active=TRUE",c.site(),shipment,binding);
            if(found.isEmpty() || n(found.getFirst().get("sku_id"))!=sku)throw conflict("箱来源或SKU不属于当前出货，请重新核对。");
            long qualified=InventoryService.number(line,"qualified_units"),pending=InventoryService.number(line,"pending_units"),defective=InventoryService.number(line,"defective_units");
            DestinationReceiptQuantities.received(qualified,pending,defective);
            String catalogVersion=ProductionService.text(line,"catalog_version",64);
            db.update("INSERT INTO destination_receipt_line(site_id,receipt_id,binding_id,sku_id,catalog_version,qualified_units,pending_units,defective_units) VALUES(?,?,?,?,?,?,?,?)",c.site(),receiptId,binding,sku,catalogVersion,qualified,pending,defective);
        }
        var after=receipt(c.site(),receiptId,false);inventory.audit(c,"destination",receiptId,n(after.get("revision")),token,before==null?"CREATE_DRAFT":"UPDATE_DRAFT",reason,before,after);return after;
    }

    Object confirm(ProductionContext c,long receiptId,JsonNode input,String token){
        var before=receipt(c.site(),receiptId,true);
        if(!"DRAFT".equals(before.get("status")) || n(before.get("revision"))!=id(input,"expected_revision"))throw conflict("草稿状态或修订已变化，请重新读取。");
        if(before.get("warehouse_id")==null || before.get("owner_id")==null || before.get("business_date")==null || before.get("reason").toString().isBlank())
            throw new ProductionError(422,"receipt_incomplete","确认前请填写目的仓、货权、日期和依据。");
        long shipment=n(before.get("shipment_id")),warehouse=n(before.get("warehouse_id")),owner=n(before.get("owner_id"));
        var headers=db.queryForList("SELECT status,revision,destination_id FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipment);
        if(headers.isEmpty() || !"CONFIRMED".equals(headers.getFirst().get("status")) || n(headers.getFirst().get("revision"))!=n(before.get("shipment_revision")) || headers.getFirst().get("destination_id")==null || n(headers.getFirst().get("destination_id"))!=warehouse)
            throw conflict("原出货状态、修订或目的仓不匹配；文字地点不能自动变成入库仓。");
        var warehouses=db.queryForList("SELECT type,status FROM production_warehouse WHERE site_id=? AND id=?",c.site(),warehouse);
        if(warehouses.isEmpty() || !"ACTIVE".equals(warehouses.getFirst().get("status")) || "FBA".equals(warehouses.getFirst().get("type")))
            throw conflict("目的仓未启用或为尚未接入的FBA资料。");
        @SuppressWarnings("unchecked") var lines=(List<Map<String,Object>>)before.get("lines");
        if(lines.isEmpty())throw new ProductionError(422,"receipt_lines_required","请填写本次实收明细。");
        var deltas=new ArrayList<InventoryService.Delta>();long total=0;
        for(var line:lines){
            long binding=n(line.get("binding_id")),sku=n(line.get("sku_id"));
            var rows=db.queryForList("SELECT * FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND id=? AND is_active=TRUE FOR UPDATE",c.site(),shipment,binding);
            if(rows.isEmpty() || n(rows.getFirst().get("sku_id"))!=sku || n(rows.getFirst().get("shipment_revision"))!=n(before.get("shipment_revision")))throw conflict("箱来源、SKU或来源修订已变化，请重新核对。");
            long received=db.queryForObject("SELECT COALESCE(SUM(l.qualified_units+l.pending_units+l.defective_units),0) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=? AND l.binding_id=? AND r.status='POSTED'",Long.class,c.site(),binding);
            long settled=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM destination_receipt_settlement WHERE site_id=? AND binding_id=? AND status='ACTIVE'",Long.class,c.site(),binding);
            long amount=DestinationReceiptQuantities.received(n(line.get("qualified_units")),n(line.get("pending_units")),n(line.get("defective_units")));
            long remaining=DestinationReceiptQuantities.remaining(n(rows.getFirst().get("units")),received,settled);
            if(amount>remaining)throw new ProductionError(422,"receipt_exceeds_remaining","本次实收超过来源余量，请保留差异并核对。");
            var current=inventory.identity(c.site(),input,sku);
            if(!current.path("catalog_version").asText().equals(line.get("catalog_version")))throw conflict("商品目录版本已变化，请重新核对。");
            var key=new InventoryService.Key(warehouse,owner,sku); inventory.checkDate(c.site(),key,before.get("business_date").toString());
            if(n(line.get("qualified_units"))>0)deltas.add(new InventoryService.Delta(key,"QUALIFIED",n(line.get("qualified_units")),"",""));
            if(n(line.get("pending_units"))>0)deltas.add(new InventoryService.Delta(key,"PENDING",n(line.get("pending_units")),"",""));
            if(n(line.get("defective_units"))>0)deltas.add(new InventoryService.Delta(key,"DEFECTIVE",n(line.get("defective_units")),"",""));
            total=InventoryService.total(total,amount);
        }
        if(total==0)throw new ProductionError(422,"receipt_quantity_required","请填写本次实际收下的数量。");
        long revision=n(before.get("revision"))+1;
        inventory.apply(c,deltas,"destination",receiptId,revision,token,before.get("reason").toString(),before.get("business_date").toString(),false);
        db.update("UPDATE destination_receipt SET status='POSTED',revision=? WHERE site_id=? AND id=?",revision,c.site(),receiptId);
        var after=receipt(c.site(),receiptId,false);inventory.audit(c,"destination",receiptId,revision,token,"CONFIRM",before.get("reason").toString(),before,after);return after;
    }

    Object reverse(ProductionContext c,long receiptId,JsonNode input,String token){
        var before=receipt(c.site(),receiptId,true);
        if(!"POSTED".equals(before.get("status")) || n(before.get("revision"))!=id(input,"expected_revision"))throw conflict("接收状态或修订已变化，请重新读取。");
        String reason=ProductionService.text(input,"reason",2000);
        if(reason.isBlank())throw new ProductionError(422,"reason_required","请填写撤销依据。");
        long warehouse=n(before.get("warehouse_id")),owner=n(before.get("owner_id"));
        @SuppressWarnings("unchecked") var lines=(List<Map<String,Object>>)before.get("lines");
        var deltas=new ArrayList<InventoryService.Delta>();
        for(var line:lines){
            long sku=n(line.get("sku_id"));inventory.identity(c.site(),input,sku);
            var key=new InventoryService.Key(warehouse,owner,sku);
            if(n(line.get("qualified_units"))>0)deltas.add(new InventoryService.Delta(key,"QUALIFIED",-n(line.get("qualified_units")),"",""));
            if(n(line.get("pending_units"))>0)deltas.add(new InventoryService.Delta(key,"PENDING",-n(line.get("pending_units")),"",""));
            if(n(line.get("defective_units"))>0)deltas.add(new InventoryService.Delta(key,"DEFECTIVE",-n(line.get("defective_units")),"",""));
        }
        long revision=n(before.get("revision"))+1;
        inventory.apply(c,deltas,"destination",receiptId,revision,token,reason,before.get("business_date").toString(),true);
        db.update("UPDATE destination_receipt SET status='REVERSED',revision=? WHERE site_id=? AND id=?",revision,c.site(),receiptId);
        var after=receipt(c.site(),receiptId,false);inventory.audit(c,"destination",receiptId,revision,token,"REVERSE",reason,before,after);return after;
    }

    Object abandon(ProductionContext c,long receiptId,JsonNode input,String token){
        var before=receipt(c.site(),receiptId,true);
        if(!"DRAFT".equals(before.get("status")) || n(before.get("revision"))!=id(input,"expected_revision"))throw conflict("草稿状态或修订已变化，请重新读取。");
        String reason=ProductionService.text(input,"reason",2000);
        if(reason.isBlank())throw new ProductionError(422,"reason_required","请填写放弃草稿的原因。");
        long revision=n(before.get("revision"))+1;
        db.update("UPDATE destination_receipt SET status='REVERSED',revision=? WHERE site_id=? AND id=?",revision,c.site(),receiptId);
        var after=receipt(c.site(),receiptId,false);inventory.audit(c,"destination",receiptId,revision,token,"ABANDON_DRAFT",reason,before,after);return after;
    }

    Object correct(ProductionContext c,long receiptId,JsonNode input,String token){
        var original=receipt(c.site(),receiptId,true);
        if(!"POSTED".equals(original.get("status")) || n(original.get("revision"))!=id(input,"expected_revision"))throw conflict("接收状态或修订已变化，请重新读取。");
        if(n(original.get("shipment_id"))!=id(input,"shipment_id") || n(original.get("warehouse_id"))!=id(input,"warehouse_id") || n(original.get("owner_id"))!=id(input,"owner_id"))
            throw conflict("更正不能改换来源出货、目的仓或货权；请先按下游依赖处理原记录。");
        var correction=(tools.jackson.databind.node.ObjectNode)input.deepCopy();
        if(!correction.has("upload_id") && original.get("upload_id")!=null)correction.put("upload_id",original.get("upload_id").toString());
        reverse(c,receiptId,correction,token);
        var replacement=saveDraft(c,null,correction,token);
        @SuppressWarnings("unchecked") var values=(Map<String,Object>)replacement;
        long nextId=n(values.get("id"));
        db.update("UPDATE destination_receipt SET replaces_receipt_id=? WHERE site_id=? AND id=?",receiptId,c.site(),nextId);
        var confirmation=(tools.jackson.databind.node.ObjectNode)correction.deepCopy();
        confirmation.put("expected_revision",values.get("revision").toString());
        return confirm(c,nextId,confirmation,token);
    }

    Object settle(ProductionContext c,JsonNode input,String token){
        long binding=id(input,"binding_id"),quantity=id(input,"units");
        String reason=ProductionService.text(input,"reason",2000);
        if(reason.isBlank())throw new ProductionError(422,"reason_required","少收结案需要明确的依据和原因。");
        var rows=db.queryForList("SELECT b.*,s.status AS shipment_status,s.revision AS current_revision FROM destination_shipment_binding b JOIN production_shipment s ON s.site_id=b.site_id AND s.id=b.shipment_id WHERE b.site_id=? AND b.id=? AND b.is_active=TRUE FOR UPDATE",c.site(),binding);
        if(rows.isEmpty() || !"CONFIRMED".equals(rows.getFirst().get("shipment_status")) || n(rows.getFirst().get("shipment_revision"))!=n(rows.getFirst().get("current_revision")) || n(rows.getFirst().get("current_revision"))!=id(input,"expected_shipment_revision"))throw conflict("箱来源或出货修订已变化，请重新核对。");
        long received=db.queryForObject("SELECT COALESCE(SUM(l.qualified_units+l.pending_units+l.defective_units),0) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=? AND l.binding_id=? AND r.status='POSTED'",Long.class,c.site(),binding);
        long settled=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM destination_receipt_settlement WHERE site_id=? AND binding_id=? AND status='ACTIVE'",Long.class,c.site(),binding);
        long remaining=DestinationReceiptQuantities.remaining(n(rows.getFirst().get("units")),received,settled);
        if(quantity>remaining)throw new ProductionError(422,"settlement_exceeds_remaining","结案数量超过尚未接收和结案的来源余量。");
        db.update("INSERT INTO destination_receipt_settlement(site_id,binding_id,units,reason,actor_id,actor_name,operation_token) VALUES(?,?,?,?,?,?,?)",c.site(),binding,quantity,reason,c.actor(),c.actorName(),token);
        long id=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);
        var after=normalized(db.queryForMap("SELECT * FROM destination_receipt_settlement WHERE site_id=? AND id=?",c.site(),id));
        inventory.audit(c,"destsettlement",id,1,token,"SETTLE",reason,null,after);
        return after;
    }

    Object reverseSettlement(ProductionContext c,long settlementId,JsonNode input,String token){
        var rows=db.queryForList("SELECT * FROM destination_receipt_settlement WHERE site_id=? AND id=? FOR UPDATE",c.site(),settlementId);
        if(rows.isEmpty())throw conflict("少收结案记录不存在或不属于当前站点。");
        var before=normalized(rows.getFirst());
        if(!"ACTIVE".equals(before.get("status")) || n(before.get("revision"))!=id(input,"expected_revision"))throw conflict("结案状态或修订已变化，请重新读取。");
        String reason=ProductionService.text(input,"reason",2000);
        if(reason.isBlank())throw new ProductionError(422,"reason_required","请填写撤销结案的依据。");
        long revision=n(before.get("revision"))+1;
        db.update("UPDATE destination_receipt_settlement SET status='REVERSED',revision=? WHERE site_id=? AND id=?",revision,c.site(),settlementId);
        var after=normalized(db.queryForMap("SELECT * FROM destination_receipt_settlement WHERE site_id=? AND id=?",c.site(),settlementId));
        inventory.audit(c,"destsettlement",settlementId,revision,token,"REVERSE",reason,before,after);return after;
    }
}
