package com.clsen.dataweb.production;

import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import static com.clsen.dataweb.production.DestinationReceiptBindings.*;

/** Operates inside the inventory command's site-locked transaction. */
final class DestinationReceiptBindingStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    DestinationReceiptBindingStore(JdbcTemplate db,ObjectMapper json){this.db=db;this.json=json;}
    private static long id(JsonNode node,String field){return ProductionService.positive(node.get(field),field);}
    private static long number(Object value){return Long.parseLong(value.toString());}
    private static ProductionError conflict(String message){return new ProductionError(409,"shipment_binding_conflict",message);}

    /** A batch has exact source lines but no physical cartons. Empty carton_id means not applicable. */
    void syncBatch(ProductionContext c,long shipment,long revision,String status) {
        var header=db.queryForMap("SELECT dispatch_purpose,cartons FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipment);
        if(!"WAREHOUSE_DISPATCH".equals(header.get("dispatch_purpose")) || header.get("cartons")!=null)return;
        db.update("UPDATE destination_shipment_binding SET is_active=FALSE WHERE site_id=? AND shipment_id=? AND is_active=TRUE",c.site(),shipment);
        if(!"CONFIRMED".equals(status))return;
        for(var source:db.queryForList("SELECT id,sku_id,actual_units FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",c.site(),shipment))
            db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,allocation_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,NULL,'',?,?,?,?,?,?)",c.site(),shipment,source.get("id"),source.get("sku_id"),source.get("actual_units"),revision,c.actor(),c.actorName(),"按已确认本批货物明细建立来源关联，无箱明细。");
    }

    Object save(ProductionContext c,JsonNode input) {
        long shipment=id(input,"shipment_id"), revision=id(input,"expected_shipment_revision");
        String reason=ProductionService.text(input,"reason",2000);
        if(reason.isBlank())throw new ProductionError(422,"reason_required","请填写箱与来源对应的核对依据。");
        var matches=db.queryForList("SELECT status,revision,cartons FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipment);
        if(matches.isEmpty())throw conflict("出货不存在或不属于当前站点。");
        var header=matches.getFirst();
        if(!"CONFIRMED".equals(header.get("status")) || number(header.get("revision"))!=revision)
            throw conflict("来源出货状态或修订已变化，请重新读取核对。");
        if(header.get("cartons")==null)throw conflict("原出货没有可核对的装箱信息，不能猜配箱来源。");
        var sources=new ArrayList<Source>(); var allocations=new ArrayList<Allocation>(); var cartons=new ArrayList<CartonItem>();
        for(var row:db.queryForList("SELECT id,sku_id,actual_units FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",c.site(),shipment))
            sources.add(new Source(number(row.get("id")),number(row.get("sku_id")),number(row.get("actual_units"))));
        for(var row:db.queryForList("SELECT a.id,a.source_line_id,a.units FROM production_shipment_allocation a JOIN production_shipment_source_line s ON s.site_id=a.site_id AND s.id=a.source_line_id WHERE a.site_id=? AND s.shipment_id=? AND s.is_active=TRUE AND a.is_active=TRUE ORDER BY a.id",c.site(),shipment))
            allocations.add(new Allocation(number(row.get("id")),number(row.get("source_line_id")),number(row.get("units"))));
        JsonNode boxes=json.readTree(header.get("cartons").toString());
        if(!boxes.isArray())throw conflict("原装箱资料无效，请先核对原出货。");
        for(var box:boxes){
            String carton=ProductionService.text(box,"id",36);
            if(carton.isBlank())throw conflict("历史箱缺少稳定身份，不能自动配对；请先核对原出货。");
            for(var item:box.path("items"))cartons.add(new CartonItem(carton,id(item,"sku_id"),id(item,"units")));
        }
        JsonNode lines=input.path("bindings");
        if(!lines.isArray()||lines.size()>5000)throw new ProductionError(422,"shipment_binding_invalid","请填写不超过5000条箱来源对应。");
        var bindings=new ArrayList<Binding>();
        for(var line:lines){
            Long allocation=line.hasNonNull("allocation_id")?id(line,"allocation_id"):null;
            bindings.add(new Binding(ProductionService.text(line,"carton_id",36),id(line,"source_line_id"),allocation,id(line,"sku_id"),id(line,"units")));
        }
        DestinationReceiptBindings.validate(sources,allocations,cartons,bindings);
        long used=db.queryForObject("SELECT COUNT(*) FROM destination_shipment_binding b WHERE b.site_id=? AND b.shipment_id=? AND b.is_active=TRUE AND (EXISTS(SELECT 1 FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=b.site_id AND l.binding_id=b.id AND r.status='POSTED') OR EXISTS(SELECT 1 FROM destination_receipt_settlement x WHERE x.site_id=b.site_id AND x.binding_id=b.id AND x.status='ACTIVE'))",Long.class,c.site(),shipment);
        long fba=db.queryForObject("SELECT COUNT(*) FROM fba_reference WHERE site_id=? AND shipment_id=?",Long.class,c.site(),shipment);
        if(used>0||fba>0)throw conflict("已有接收、FBA货件或差异结案引用，请先按下游依赖处理，不能重配来源。");
        long drafts=db.queryForObject("SELECT COUNT(*) FROM destination_receipt WHERE site_id=? AND shipment_id=? AND status='DRAFT'",Long.class,c.site(),shipment);
        if(drafts>0)throw conflict("已有接收草稿引用，请先处理草稿，不能重配来源。");
        db.update("UPDATE destination_shipment_binding SET is_active=FALSE WHERE site_id=? AND shipment_id=? AND is_active=TRUE",c.site(),shipment);
        for(var line:bindings)db.update("INSERT INTO destination_shipment_binding(site_id,shipment_id,source_line_id,allocation_id,carton_id,sku_id,units,shipment_revision,actor_id,actor_name,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?)",c.site(),shipment,line.source(),line.allocation(),line.carton(),line.sku(),line.units(),revision,c.actor(),c.actorName(),reason);
        return Map.of("shipment_id",Long.toString(shipment),"shipment_revision",Long.toString(revision),"bindings",db.queryForList("SELECT id,source_line_id,allocation_id,carton_id,sku_id,units FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",c.site(),shipment).stream().map(DestinationReceiptStore::normalized).toList());
    }
}
