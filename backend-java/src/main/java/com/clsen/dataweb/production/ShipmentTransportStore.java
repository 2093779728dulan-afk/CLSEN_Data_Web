package com.clsen.dataweb.production;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Manual carrier evidence, attached to the existing shipment. Never posts stock. */
final class ShipmentTransportStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final InventoryService inventory;
    ShipmentTransportStore(JdbcTemplate db,ObjectMapper json,InventoryService inventory){this.db=db;this.json=json;this.inventory=inventory;}
    private static ProductionError conflict(String message){return new ProductionError(409,"transport_revision_conflict",message);}
    private static long n(Object value){return Long.parseLong(value.toString());}
    private static long id(JsonNode b,String field){return ProductionService.positive(b.get(field),field);}
    private static String text(JsonNode b,String field,int length){return ProductionService.text(b,field,length).trim();}
    private static String required(JsonNode b,String field,int length){String value=text(b,field,length);if(value.isEmpty())throw new ProductionError(422,"transport_field_required","请填写运输资料的"+field+"。");return value;}
    private Map<String,Object> row(ResultSet r,int ignored)throws SQLException{
        var result=new LinkedHashMap<String,Object>();
        for(int i=1;i<=r.getMetaData().getColumnCount();i++){Object v=r.getObject(i);if(v instanceof Number)v=v.toString();else if(v instanceof Timestamp t)v=t.toInstant().toString();result.put(r.getMetaData().getColumnLabel(i),v);}
        return result;
    }
    private List<Map<String,Object>> rows(String sql,Object...args){return db.query(sql,this::row,args);}
    private Map<String,Object> shipment(long site,long id,boolean lock){
        var found=rows("SELECT id,status,revision,system_number,business_number,warehouse_id,owner_id,destination_id,cartons FROM production_shipment WHERE site_id=? AND id=?"+(lock?" FOR UPDATE":""),site,id);
        if(found.isEmpty())throw new ProductionError(404,"not_found","当前站点没有此出货批次。");return found.getFirst();
    }
    private Map<String,Object> record(long site,long id){
        var found=rows("SELECT * FROM shipment_transport WHERE site_id=? AND id=?",site,id);
        if(found.isEmpty())throw new ProductionError(404,"not_found","当前站点没有此运输记录。");
        var result=found.getFirst();result.put("source_snapshot",json.readTree(result.get("source_snapshot").toString()));return result;
    }
    private Map<String,Object> event(long site,long id){
        var found=rows("SELECT * FROM shipment_transport_event WHERE site_id=? AND id=?",site,id);
        if(found.isEmpty())throw new ProductionError(404,"not_found","当前站点没有此运输节点。");return found.getFirst();
    }
    static Instant time(String local,String timezone){
        try{
            ZoneId zone=ZoneId.of(timezone);
            try{
                var offset=OffsetDateTime.parse(local);
                if(!zone.getRules().getValidOffsets(offset.toLocalDateTime()).contains(offset.getOffset()))throw new DateTimeException("offset mismatch");
                return offset.toInstant();
            }catch(java.time.format.DateTimeParseException noOffset){
                var value=LocalDateTime.parse(local);var offsets=zone.getRules().getValidOffsets(value);
                if(offsets.size()!=1)throw new DateTimeException("ambiguous local time");return value.toInstant(offsets.getFirst());
            }
        }catch(DateTimeException failure){throw new ProductionError(422,"transport_time_invalid","发生/预计时间或时区无效；夏令时重复时请使用明确的UTC偏移时区。");}
    }
    private Map<String,Object> current(ProductionContext c,JsonNode b){
        var header=shipment(c.site(),id(b,"shipment_id"),true);
        if(!"CONFIRMED".equals(header.get("status")))throw conflict("运输登记只关联已确认出货；当前批次状态已变化。");
        if(n(header.get("revision"))!=id(b,"expected_shipment_revision"))throw conflict("出货修订已变化，请重新读取后核对。");
        for(String field:List.of("warehouse_id","owner_id","destination_id"))
            if(!Objects.toString(header.get(field),"").equals(text(b,"expected_"+field,19)))throw new ProductionError(409,"transport_scope_conflict","来源仓、货权或目的仓与当前出货不一致，请重新核对。");
        var sources=rows("SELECT id,sku_id,catalog_version,actual_units FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",c.site(),header.get("id"));
        if(sources.isEmpty())throw conflict("当前出货没有有效商品来源。");
        for(var source:sources){inventory.identity(c.site(),b,n(source.get("sku_id")));source.put("allocations",rows("SELECT id,order_line_id,units FROM production_shipment_allocation WHERE site_id=? AND source_line_id=? ORDER BY id",c.site(),source.get("id")));}
        var snapshot=new LinkedHashMap<String,Object>();snapshot.put("shipment_id",header.get("id"));snapshot.put("shipment_revision",header.get("revision"));snapshot.put("warehouse_id",header.get("warehouse_id"));snapshot.put("owner_id",header.get("owner_id"));snapshot.put("destination_id",header.get("destination_id"));snapshot.put("sources",sources);snapshot.put("cartons",header.get("cartons")==null?List.of():json.readTree(header.get("cartons").toString()));header.put("source_snapshot",snapshot);return header;
    }
    Object state(ProductionContext c,long shipmentId){
        var header=shipment(c.site(),shipmentId,false);var result=new LinkedHashMap<String,Object>();result.put("shipment_id",Long.toString(shipmentId));result.put("shipment_revision",header.get("revision"));result.put("shipment_status",header.get("status"));
        result.put("shipment_units",Long.toString(db.queryForObject("SELECT COALESCE(SUM(actual_units),0) FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE",Long.class,c.site(),shipmentId)));
        result.put("destination_received_units",Long.toString(db.queryForObject("SELECT COALESCE(SUM(l.qualified_units+l.pending_units+l.defective_units),0) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE r.site_id=? AND r.shipment_id=? AND r.status='POSTED'",Long.class,c.site(),shipmentId)));
        long fba=db.queryForObject("SELECT COALESCE(SUM(a.units),0) FROM fba_event_allocation a JOIN destination_shipment_binding b ON b.site_id=a.site_id AND b.id=a.binding_id WHERE b.site_id=? AND b.shipment_id=?",Long.class,c.site(),shipmentId);
        result.put("destination_received_units",Long.toString(Math.addExact(n(result.get("destination_received_units")),fba)));
        for(String field:List.of("warehouse_id","owner_id","destination_id"))result.put(field,header.get(field));
        var found=rows("SELECT id FROM shipment_transport WHERE site_id=? AND shipment_id=?",c.site(),shipmentId);
        result.put("registered",!found.isEmpty());result.put("record",null);result.put("events",List.of());result.put("history",List.of());result.put("latest_event",null);result.put("status","UNREGISTERED");
        if(found.isEmpty())return result;
        long recordId=n(found.getFirst().get("id"));var transport=record(c.site(),recordId);var events=rows("SELECT * FROM shipment_transport_event WHERE site_id=? AND transport_id=? ORDER BY occurred_at DESC,id DESC",c.site(),recordId);
        result.put("record",transport);result.put("events",events);result.put("status",events.isEmpty()?"REGISTERED":events.getFirst().get("event_kind"));result.put("latest_event",events.isEmpty()?null:events.getFirst());
        result.put("source_revision_current",Objects.equals(transport.get("shipment_revision"),header.get("revision")));
        var history=rows("SELECT document_kind,document_id,revision,actor_name,reason,operation_kind,before_value,after_value,created_at FROM production_revision WHERE site_id=? AND ((document_kind='transport' AND document_id=?) OR (document_kind='transport_event' AND document_id IN (SELECT id FROM shipment_transport_event WHERE site_id=? AND transport_id=?))) ORDER BY id DESC",c.site(),recordId,c.site(),recordId);
        for(var item:history)for(String field:List.of("before_value","after_value"))if(item.get(field)!=null)item.put(field,json.readTree(item.get(field).toString()));result.put("history",history);return result;
    }
    Object saveRecord(ProductionContext c,Long recordId,JsonNode b,String token){
        var header=current(c,b);Map<String,Object> before=recordId==null?null:record(c.site(),recordId);
        if(before!=null && n(before.get("shipment_id"))!=id(b,"shipment_id"))throw new ProductionError(409,"transport_scope_conflict","运输记录不能转移到另一出货批次。");
        long expected=InventoryService.number(b,"expected_revision");
        if(before==null){if(expected!=0 || db.queryForObject("SELECT COUNT(*) FROM shipment_transport WHERE site_id=? AND shipment_id=?",Long.class,c.site(),header.get("id"))!=0)throw conflict("该出货已登记运输，请读取当前记录后更正。");}
        else if(expected!=n(before.get("revision")))throw conflict("运输资料已被修改，输入保留，请读取当前修订后核对。");
        String carrier=required(b,"carrier",255),tracking=required(b,"tracking_number",255),source=required(b,"source_reference",2000),reason=before==null?source:required(b,"reason",2000);
        String local=text(b,"arrival_local",64),zone=text(b,"arrival_timezone",80);Instant arrival=local.isEmpty()?null:time(local,zone);
        if(local.isEmpty())zone="";
        if(before==null){db.update("INSERT INTO shipment_transport(site_id,shipment_id,shipment_revision,carrier,tracking_number,estimated_arrival,arrival_local,arrival_timezone,source_reference,source_snapshot) VALUES(?,?,?,?,?,?,?,?,?,?)",c.site(),header.get("id"),header.get("revision"),carrier,tracking,arrival==null?null:Timestamp.from(arrival),local,zone,source,json.writeValueAsString(header.get("source_snapshot")));recordId=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
        else db.update("UPDATE shipment_transport SET shipment_revision=?,carrier=?,tracking_number=?,estimated_arrival=?,arrival_local=?,arrival_timezone=?,source_reference=?,source_snapshot=?,revision=revision+1 WHERE site_id=? AND id=?",header.get("revision"),carrier,tracking,arrival==null?null:Timestamp.from(arrival),local,zone,source,json.writeValueAsString(header.get("source_snapshot")),c.site(),recordId);
        var after=record(c.site(),recordId);inventory.audit(c,"transport",recordId,n(after.get("revision")),token,before==null?"REGISTER":"CORRECT",reason,before,after);return state(c,n(header.get("id")));
    }
    Object saveEvent(ProductionContext c,Long eventId,JsonNode b,String token){
        var header=current(c,b);var transport=record(c.site(),id(b,"transport_id"));
        if(n(transport.get("shipment_id"))!=id(b,"shipment_id"))throw new ProductionError(409,"transport_scope_conflict","运输节点不属于当前出货。");
        if(n(transport.get("revision"))!=id(b,"expected_transport_revision") || n(transport.get("shipment_revision"))!=n(header.get("revision")))throw conflict("运输资料或出货已更正，请先读取/核对当前运输资料。");
        Map<String,Object> before=eventId==null?null:event(c.site(),eventId);
        if(before!=null && n(before.get("transport_id"))!=n(transport.get("id")))throw new ProductionError(409,"transport_scope_conflict","不能更正其他运输记录的节点。");
        if(before!=null && n(before.get("revision"))!=id(b,"expected_revision"))throw conflict("运输节点修订已变化，请读取当前记录后更正。");
        String kind=required(b,"event_kind",24);if(!Set.of("DISPATCHED","IN_TRANSIT","ARRIVED","SIGNED","EXCEPTION").contains(kind))throw new ProductionError(422,"transport_event_invalid","请选择有效运输节点。");
        String local=required(b,"occurred_local",64),zone=required(b,"timezone",80),source=required(b,"source_reference",2000),place=text(b,"location",255),description=text(b,"description",2000);Instant occurred=time(local,zone);
        Long signed=b.hasNonNull("signed_units")&&!text(b,"signed_units",19).isEmpty()?InventoryService.number(b,"signed_units"):null;
        if(!kind.equals("SIGNED") && signed!=null)throw new ProductionError(422,"transport_signed_invalid","累计物流签收件数只用于物流签收节点。");
        String reason=before==null?source:required(b,"reason",2000);
        if(before==null){db.update("INSERT INTO shipment_transport_event(site_id,transport_id,event_kind,occurred_at,occurred_local,timezone,location,description,source_reference,signed_units) VALUES(?,?,?,?,?,?,?,?,?,?)",c.site(),transport.get("id"),kind,Timestamp.from(occurred),local,zone,place,description,source,signed);eventId=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
        else db.update("UPDATE shipment_transport_event SET event_kind=?,occurred_at=?,occurred_local=?,timezone=?,location=?,description=?,source_reference=?,signed_units=?,revision=revision+1 WHERE site_id=? AND id=?",kind,Timestamp.from(occurred),local,zone,place,description,source,signed,c.site(),eventId);
        var after=event(c.site(),eventId);inventory.audit(c,"transport_event",eventId,n(after.get("revision")),token,before==null?"APPEND_NODE":"CORRECT_NODE",reason,before,after);return state(c,n(header.get("id")));
    }
}
