package com.clsen.dataweb.production;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Directory metadata only. Inventory scope, opening and balances remain separate facts. */
final class ProductionDirectory {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private static final List<String> PROFILE=List.of("region","address","operator","contact","phone","timezone","seller_account","marketplace","notes","external_code");
    private static final String WAREHOUSES="""
        (SELECT site_id,id,name,type,country,status,revision,profile,1 AS managed FROM production_warehouse
         UNION ALL SELECT s.site_id,s.warehouse_id,
         (CASE WHEN COUNT(DISTINCT s.warehouse_name)=1 THEN MAX(s.warehouse_name) ELSE CONCAT('历史仓库 ',s.warehouse_id,'（名称待核）') END) COLLATE utf8mb4_0900_as_cs,
         'UNCLASSIFIED','','ACTIVE',1,NULL,0 FROM inventory_scope s
         WHERE NOT EXISTS(SELECT 1 FROM production_warehouse w WHERE w.site_id=s.site_id AND w.id=s.warehouse_id)
         GROUP BY s.site_id,s.warehouse_id) directory
        """;
    ProductionDirectory(JdbcTemplate db,ObjectMapper json){this.db=db;this.json=json;}
    private String table(String kind){return switch(kind){case "factories"->"production_factory";case "warehouses"->"production_warehouse";default->throw new ProductionError(404,"not_found","资料入口不存在。");};}
    private Map<String,Object> row(ResultSet r,int index)throws SQLException {
        var value=new LinkedHashMap<String,Object>();
        for(int i=1;i<=r.getMetaData().getColumnCount();i++) {Object v=r.getObject(i);if(v instanceof Number)v=v.toString();else if(v instanceof java.sql.Timestamp t)v=t.toInstant().toString();value.put(r.getMetaData().getColumnLabel(i),v);}
        return value;
    }
    private List<Map<String,Object>> rows(String sql,Object...args){return db.query(sql,this::row,args);}
    private Map<String,Object> entity(ProductionContext c,String kind,long id){
        var values=rows("SELECT * FROM "+(kind.equals("warehouses")?WAREHOUSES:table(kind))+" WHERE site_id=? AND id=?",c.site(),id);
        if(values.isEmpty())throw new ProductionError(404,"directory_not_found","资料不存在或不属于当前站点。");
        var value=values.getFirst();Object profile=value.remove("profile");
        JsonNode info=profile==null?json.createObjectNode():json.readTree(profile.toString());
        for(String key:PROFILE)value.put(key,info.path(key).asText(""));return value;
    }
    Object list(ProductionContext c,String kind,String q,String status,int page,String type,String country){
        table(kind);if(page<1||q.length()>120||country.length()>80)throw new ProductionError(422,"invalid_filter","搜索或分页参数无效。");
        if(!Set.of("","ACTIVE","INACTIVE").contains(status))throw new ProductionError(422,"invalid_status","资料状态无效。");
        var args=new ArrayList<Object>(List.of(c.site(),"%"+q+"%","%"+q+"%"));String where="site_id=? AND (name LIKE ? OR CAST(id AS CHAR) LIKE ?)";
        if(!status.isEmpty()){where+=" AND status=?";args.add(status);}
        if(kind.equals("warehouses")){if(!type.isEmpty()){where+=" AND type=?";args.add(type);}if(!country.isEmpty()){where+=" AND country=?";args.add(country);}}
        String source=kind.equals("warehouses")?WAREHOUSES:table(kind);long total=db.queryForObject("SELECT COUNT(*) FROM "+source+" WHERE "+where,Long.class,args.toArray());
        args.add((long)(page-1)*50);
        var found=rows("SELECT id FROM "+source+" WHERE "+where+" ORDER BY name,id LIMIT 50 OFFSET ?",args.toArray());
        var items=new ArrayList<Object>();for(var item:found)items.add(detail(c,kind,Long.parseLong(item.get("id").toString()),false));
        return Map.of("items",items,"total",total,"page",page,"page_size",50);
    }
    Map<String,Object> detail(ProductionContext c,String kind,long id,boolean history){
        var result=entity(c,kind,id);
        if(kind.equals("factories")){
            result.put("order_count",db.queryForObject("SELECT COUNT(*) FROM production_order WHERE site_id=? AND factory_id=?",Long.class,c.site(),id).toString());
            result.put("open_order_count",db.queryForObject("SELECT COUNT(*) FROM production_order o WHERE site_id=? AND factory_id=? AND status='CONFIRMED' AND EXISTS(SELECT 1 FROM production_order_line l WHERE l.site_id=o.site_id AND l.order_id=o.id AND l.is_active=TRUE AND l.tracking_state='OPEN')",Long.class,c.site(),id).toString());
            result.put("warehouse_ids",rows("SELECT warehouse_id FROM production_factory_warehouse WHERE site_id=? AND factory_id=? ORDER BY warehouse_id",c.site(),id).stream().map(r->r.get("warehouse_id")).toList());
        } else {
            var scopes=rows("SELECT * FROM inventory_scope WHERE site_id=? AND warehouse_id=? ORDER BY owner_id",c.site(),id);result.put("scopes",scopes);
            boolean fbaConnected=result.get("type").equals("FBA")&&db.queryForObject("SELECT COUNT(*) FROM fba_scope WHERE site_id=? AND warehouse_id=?",Long.class,c.site(),id)>0;
            result.put("inventory_state",result.get("type").equals("FBA")?(fbaConnected?"FBA_READY":"NOT_CONNECTED"):result.get("type").equals("LOCATION")?"NOT_APPLICABLE":scopes.isEmpty()?"UNINITIALIZED":"READY");
            result.put("factory_ids",rows("SELECT factory_id FROM production_factory_warehouse WHERE site_id=? AND warehouse_id=? ORDER BY factory_id",c.site(),id).stream().map(r->r.get("factory_id")).toList());
            if(history){result.put("receipt_orders",rows("SELECT id,system_number,business_number,receipt_owner_id FROM production_order WHERE site_id=? AND receipt_warehouse_id=? AND status='CONFIRMED' ORDER BY id DESC LIMIT 50",c.site(),id));}
        }
        if(history){var revisions=rows("SELECT revision,actor_id,actor_name,reason,before_value,after_value,created_at FROM production_directory_revision WHERE site_id=? AND entity_kind=? AND entity_id=? ORDER BY revision DESC LIMIT 100",c.site(),kind,id);for(var r:revisions)for(String key:List.of("before_value","after_value"))if(r.get(key)!=null)r.put(key,json.readTree(r.get(key).toString()));result.put("history",revisions);}
        return result;
    }
    private void materialize(ProductionContext c,long id,Map<String,Object> legacy){
        if(db.queryForObject("SELECT COUNT(*) FROM production_warehouse WHERE site_id=? AND id=?",Long.class,c.site(),id)==0)
            db.update("INSERT INTO production_warehouse(site_id,id,name,type) VALUES(?,?,?,'UNCLASSIFIED')",c.site(),id,legacy.get("name"));
    }
    Object save(ProductionContext c,String kind,Long id,JsonNode input){
        String table=table(kind);Map<String,Object> before=id==null?null:detail(c,kind,id,false);
        if(before!=null&&!Objects.equals(before.get("revision"),input.path("expected_revision").asText()))throw new ProductionError(409,"revision_conflict","资料已变化，请刷新并核对后再保存，输入不会自动覆盖。");
        String name=ProductionService.text(input,"name",120).trim(),status=ProductionService.text(input,"status",16);
        if(name.isEmpty())throw new ProductionError(422,kind.equals("factories")?"factory_name_required":"warehouse_name_required","请填写可区分的完整名称。");
        if(status.isEmpty())status=before==null?"ACTIVE":before.get("status").toString();
        if(!Set.of("ACTIVE","INACTIVE").contains(status))throw new ProductionError(422,"invalid_status","请选择启用或停用。");
        if(db.queryForObject("SELECT COUNT(*) FROM "+table+" WHERE site_id=? AND name=? AND id<>?",Long.class,c.site(),name,id==null?0:id)>0)throw new ProductionError(409,kind.equals("factories")?"factory_exists":"warehouse_exists","同名资料已登记，请选择已有记录或填写可区分全名。");
        var profile=new LinkedHashMap<String,Object>();for(String key:PROFILE)profile.put(key,input.has(key)?ProductionService.text(input,key,key.equals("notes")?2000:key.equals("address")?500:255):before==null?"":before.get(key));
        if(!profile.get("timezone").toString().isBlank())try{java.time.ZoneId.of(profile.get("timezone").toString());}catch(java.time.DateTimeException e){throw new ProductionError(422,"invalid_timezone","请选择有效时区。");}
        String reason=ProductionService.text(input,"reason",2000).trim();if(before!=null&&reason.isEmpty())throw new ProductionError(422,"reason_required","修改或停用资料需填写原因。");
        long revision=before==null?1:Long.parseLong(before.get("revision").toString())+1;
        if(kind.equals("factories")){
            if(id==null){db.update("INSERT INTO production_factory(site_id,name,status,profile) VALUES(?,?,?,?)",c.site(),name,status,json.writeValueAsString(profile));id=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
            else db.update("UPDATE production_factory SET name=?,status=?,profile=?,revision=? WHERE site_id=? AND id=?",name,status,json.writeValueAsString(profile),revision,c.site(),id);
        } else {
            String type=input.has("type")?ProductionService.text(input,"type",24):before==null?"":before.get("type").toString();
            String country=input.has("country")?ProductionService.text(input,"country",80).trim():before==null?"":before.get("country").toString();
            if(!Set.of("FACTORY","OWN","THIRD_PARTY","FBA","LOCATION","UNCLASSIFIED").contains(type)||before==null&&type.equals("UNCLASSIFIED"))throw new ProductionError(422,"invalid_warehouse_type","请选择仓库类型或非库存中转地点。");
            if(country.isEmpty()&&(before==null||!before.get("country").toString().isEmpty()))throw new ProductionError(422,"country_required","请填写国家或地区。");
            if(type.equals("FBA")&&(profile.get("seller_account").toString().isBlank()||profile.get("marketplace").toString().isBlank()))throw new ProductionError(422,"fba_scope_required","FBA档案须明确卖家账号和站点，尚不代表平台库存已接入。");
            if(before!=null&&(!type.equals(before.get("type"))&&!before.get("type").equals("UNCLASSIFIED")||!country.equals(before.get("country"))&&!before.get("country").toString().isEmpty()||!profile.get("seller_account").equals(before.get("seller_account"))||!profile.get("marketplace").equals(before.get("marketplace"))))throw new ProductionError(409,"warehouse_identity_change","类型、国家或账号站点不能通过改名转换归属，请新建明确的仓库档案。");
            if(before!=null&&before.get("type").equals("UNCLASSIFIED")&&Set.of("FBA","LOCATION").contains(type)&&!((List<?>)before.get("scopes")).isEmpty())throw new ProductionError(409,"warehouse_identity_change","已有库存仓不能改成平台仓或非库存地点。");
            if(id==null){db.update("INSERT INTO production_warehouse(site_id,name,type,country,status,profile) VALUES(?,?,?,?,?,?)",c.site(),name,type,country,status,json.writeValueAsString(profile));id=db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
            else {materialize(c,id,before);db.update("UPDATE production_warehouse SET name=?,type=?,country=?,status=?,profile=?,revision=? WHERE site_id=? AND id=?",name,type,country,status,json.writeValueAsString(profile),revision,c.site(),id);}
        }
        String links=kind.equals("factories")?"warehouse_ids":"factory_ids";
        if(input.has(links)){
            JsonNode values=input.path(links);if(!values.isArray()||values.size()>100)throw new ProductionError(422,"invalid_links","关联项最多100项。");
            var ids=new TreeSet<Long>();for(JsonNode value:values){long related=ProductionService.positive(value,"关联资料");if(!ids.add(related))throw new ProductionError(422,"duplicate_link","关联项不能重复。");var relatedValue=entity(c,kind.equals("factories")?"warehouses":"factories",related);if(kind.equals("factories"))materialize(c,related,relatedValue);}
            String column=kind.equals("factories")?"factory_id":"warehouse_id";db.update("DELETE FROM production_factory_warehouse WHERE site_id=? AND "+column+"=?",c.site(),id);
            for(long other:ids)db.update("INSERT INTO production_factory_warehouse(site_id,factory_id,warehouse_id) VALUES(?,?,?)",c.site(),kind.equals("factories")?id:other,kind.equals("factories")?other:id);
        }
        var after=detail(c,kind,id,false);
        db.update("INSERT INTO production_directory_revision(site_id,entity_kind,entity_id,revision,actor_id,actor_name,reason,before_value,after_value) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),kind,id,revision,c.actor(),c.actorName(),before==null?"创建资料":reason,before==null?null:json.writeValueAsString(before),json.writeValueAsString(after));
        return detail(c,kind,id,true);
    }
    static void requireOperational(JdbcTemplate db,long site,long warehouse){
        var found=db.queryForList("SELECT type,status FROM production_warehouse WHERE site_id=? AND id=?",site,warehouse);
        if(!found.isEmpty()&&(!found.getFirst().get("status").equals("ACTIVE")||Set.of("FBA","LOCATION").contains(found.getFirst().get("type"))))throw new ProductionError(409,"warehouse_not_operational","该档案已停用、平台库存未接入或属于非库存地点，不能登记本地库存变动。");
    }
}
