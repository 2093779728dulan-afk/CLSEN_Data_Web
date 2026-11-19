package com.clsen.dataweb.production;

import java.time.LocalDate;
import java.time.ZoneId;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Explicit local-backup maintenance inside InventoryService's site transaction. */
final class InventoryIdentityRebinding {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final CatalogAuthority authority;
    InventoryIdentityRebinding(JdbcTemplate db,ObjectMapper json,CatalogAuthority authority){this.db=db;this.json=json;this.authority=authority;}
    static JsonNode rewriteSkuReferences(JsonNode original,Map<Long,Long> mapping){
        if(original==null||original.isNull())return original;
        JsonNode result=original.deepCopy();
        if(result.isObject()){
            var object=(ObjectNode)result;
            for(var entry:new ArrayList<>(object.properties())){
                var value=entry.getValue();
                if(entry.getKey().equals("sku_id")&&value.asText().matches("[1-9][0-9]{0,18}")){
                    Long target=mapping.get(Long.parseLong(value.asText()));
                    if(target!=null){if(value.isNumber())object.put(entry.getKey(),target.longValue());else object.put(entry.getKey(),target.toString());}
                }else object.set(entry.getKey(),rewriteSkuReferences(value,mapping));
            }
        }else if(result.isArray()){
            var array=(tools.jackson.databind.node.ArrayNode)result;
            for(int i=0;i<array.size();i++)array.set(i,rewriteSkuReferences(array.get(i),mapping));
        }
        return result;
    }
    // Deliberately bounded to ASCII evidence; do not invent a Java Unicode/casefold contract.
    static boolean sameIdentity(String oldStyle,String oldColor,String oldSize,String style,String color,String size,boolean confirmedColor){
        if(!List.of(oldStyle,oldColor,oldSize,style,color,size).stream().allMatch(s->s.chars().allMatch(c->c<128)))return false;
        if(!oldStyle.equals(style)||!oldSize.equalsIgnoreCase(size))return false;
        if(oldColor.equalsIgnoreCase(color))return true;
        return confirmedColor&&(style.equals("1126")&&oldColor.equalsIgnoreCase("GREY")&&color.equals("Gray")
            ||style.equals("2121")&&oldColor.equalsIgnoreCase("LT GREY")&&color.equals("Light Gray"));
    }
    private static ProductionError conflict(String message){return new ProductionError(409,"identity_rebind_conflict",message);}
    private static long num(Object value){return Long.parseLong(value.toString());}
    private static long id(JsonNode value){String s=value.asText();if(!s.matches("[1-9][0-9]{0,18}"))throw conflict("身份、范围或修订必须为正整数。");return Long.parseLong(s);}
    private List<Map<String,Object>> rows(String sql,Object... args){
        return db.query(sql,(r,i)->{var m=new LinkedHashMap<String,Object>();for(int k=1;k<=r.getMetaData().getColumnCount();k++){Object v=r.getObject(k);if(v instanceof Number||v instanceof java.sql.Date||v instanceof java.sql.Timestamp)v=v.toString();m.put(r.getMetaData().getColumnLabel(k),v);}return m;},args);
    }
    private long count(String sql,Object...args){return db.queryForObject(sql,Long.class,args);}
    private static String marks(int size){return String.join(",",Collections.nCopies(size,"?"));}
    private Object[] args(long site,Collection<Long> ids){var a=new ArrayList<Object>();a.add(site);a.addAll(ids);return a.toArray();}
    private static long sum(List<Map<String,Object>> values){long result=0;for(var r:values)for(String f:List.of("qualified_units","pending_units","defective_units","unassessed_units"))result=Math.addExact(result,num(r.get(f)));return result;}
    private Set<Long> expectedIds(JsonNode b,String name){var result=new HashSet<Long>();if(!b.path(name).isArray())throw conflict("请重新读取关联单据范围。");for(var v:b.path(name))if(!result.add(id(v)))throw conflict("关联行重复。");return result;}
    private void audit(ProductionContext c,String kind,long document,long revision,String token,String reason,Object before,Object after){
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,actor_name,operation_token,reason,operation_kind,effective_date,before_value,after_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            c.site(),kind,document,revision,c.actor(),c.actorName(),token,reason,"IDENTITY_REBIND",LocalDate.now(ZoneId.of("Asia/Shanghai")),json.writeValueAsString(before),json.writeValueAsString(after));
    }
    Object apply(ProductionContext c,JsonNode b,String token){
        String database=db.queryForObject("SELECT DATABASE()",String.class);
        boolean fixture="clsen_orders_b_v1_1_0_test".equals(database)&&!authority.enabled();
        if(!fixture&&(!"clsen_orders_production_backup_b_v1_1_0_20261017".equals(database)||!authority.realCatalog()))throw new ProductionError(403,"identity_rebind_scope_forbidden","只允许已明确配对的本地备份身份衔接。");
        long warehouse=id(b.path("warehouse_id")),owner=id(b.path("owner_id"));
        String reason=b.path("reason").asText();
        if(reason.length()<10||reason.length()>1800)throw conflict("请填写身份衔接来源和原因。");
        var lines=b.path("mappings");if(!lines.isArray()||lines.isEmpty()||lines.size()>250)throw conflict("请提供本次明确的身份对应清单。");
        if(!b.path("identity_key_version").asText().equals("catalog_identity_key_v1"))throw conflict("身份核对版本不一致。");
        var scope=rows("SELECT * FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=? FOR UPDATE",c.site(),warehouse,owner);
        if(scope.size()!=1)throw conflict("库存范围不存在。");
        var beforeBalances=rows("SELECT * FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=? ORDER BY sku_id FOR UPDATE",c.site(),warehouse,owner);
        long totalBefore=sum(beforeBalances);
        long identityRevision=count("SELECT COALESCE(MAX(revision),0)+1 FROM production_revision WHERE site_id=? AND document_kind='identity' AND document_id=?",c.site(),warehouse);
        if(!Long.toString(totalBefore).equals(b.path("expected_total_units").asText()))throw conflict("库存总量已变化。");
        var mapping=new LinkedHashMap<Long,Long>();var targets=new HashSet<Long>();
        var identities=new HashMap<Long,JsonNode>();var crosswalks=new ArrayList<Map<String,Object>>();
        var balances=new HashMap<Long,Map<String,Object>>();for(var r:beforeBalances)balances.put(num(r.get("sku_id")),r);
        for(var line:lines){
            long old=id(line.path("old_sku_id")),target=id(line.path("target_sku_id"));
            if(old==target||mapping.putIfAbsent(old,target)!=null||!targets.add(target)||balances.containsKey(target))throw conflict("身份重复或目标库存已存在。");
            var prior=balances.get(old);if(prior==null||!prior.get("revision").equals(line.path("expected_revision").asText()))throw conflict("库存修订已变化。");
            if(num(prior.get("pending_units"))+num(prior.get("defective_units"))+num(prior.get("unassessed_units"))!=0||!prior.get("qualified_units").equals(line.path("expected_units").asText()))throw conflict("本次只允许已核对数量的正常货品身份衔接。");
            if(count("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND sku_id=? AND NOT(warehouse_id=? AND owner_id=?)",c.site(),old,warehouse,owner)>0)throw conflict("旧身份还有其他库存范围，不能局部替换。");
            var cross=rows("SELECT * FROM production_backup_sku_crosswalk WHERE target_sku_id=? AND status='PENDING' FOR UPDATE",old);
            if(cross.size()!=1||old!=900_000_000_000L+num(cross.getFirst().get("old_sku_id")))throw conflict("旧身份不是本地备份待识别记录。");
            JsonNode identity;
            if(fixture){identity=b.path("_catalog").path(Long.toString(target));if(!identity.path("status").asText().equals("active")||!identity.path("catalog_version").asText().equals("DEMO_LOCAL_ONLY-v1"))throw conflict("测试商品身份无效。");}
            else identity=authority.current(c.site(),b,target);
            if(!identity.path("catalog_version").asText().equals(b.path("expected_catalog_version").asText()))throw conflict("目录已变化，请重新核对。");
            var oldIdentity=InventoryService.displayIdentity(cross.getFirst().get("old_identity").toString());
            var newIdentity=InventoryService.displayIdentity(identity.path("label").asText());
            if(oldIdentity.isEmpty()||newIdentity.isEmpty()||!sameIdentity(oldIdentity.get("style_code").toString(),oldIdentity.get("standard_color").toString(),oldIdentity.get("standard_size").toString(),
                newIdentity.get("style_code").toString(),newIdentity.get("standard_color").toString(),newIdentity.get("standard_size").toString(),line.path("source_color_confirmed").asBoolean(false)))throw conflict("款色尺码或颜色确认不一致。");
            if(line.path("evidence").asText().isBlank())throw conflict("每个身份对应必须保留来源依据。");
            identities.put(target,identity);crosswalks.add(cross.getFirst());
        }
        var allIds=new HashSet<>(mapping.keySet());allIds.addAll(targets);
        for(String table:List.of("inventory_hold","inventory_reservation","inventory_loan","inventory_plan"))
            if(count("SELECT COUNT(*) FROM "+table+" WHERE site_id=? AND sku_id IN ("+marks(allIds.size())+")",args(c.site(),allIds))>0)throw conflict("存在占用、借还或计划引用，需另行核对，不能覆盖。");
        var orderLines=rows("SELECT * FROM production_order_line WHERE site_id=? AND is_active=TRUE AND sku_id IN ("+marks(mapping.size())+") ORDER BY id FOR UPDATE",args(c.site(),mapping.keySet()));
        var shipmentLines=rows("SELECT * FROM production_shipment_source_line WHERE site_id=? AND is_active=TRUE AND sku_id IN ("+marks(mapping.size())+") ORDER BY id FOR UPDATE",args(c.site(),mapping.keySet()));
        if(!expectedIds(b,"expected_order_line_ids").equals(orderLines.stream().map(r->num(r.get("id"))).collect(java.util.stream.Collectors.toSet()))
            ||!expectedIds(b,"expected_shipment_source_ids").equals(shipmentLines.stream().map(r->num(r.get("id"))).collect(java.util.stream.Collectors.toSet())))throw conflict("关联单据行范围已变化。");
        var parents=new LinkedHashMap<String,Map<Long,Map<String,Object>>>();
        for(String kind:List.of("orders","shipments")){
            String table=kind.equals("orders")?"production_order":"production_shipment",field=kind.equals("orders")?"order_id":"shipment_id";
            var selected=new TreeMap<Long,Map<String,Object>>();
            for(var line:kind.equals("orders")?orderLines:shipmentLines){long document=num(line.get(field));if(!selected.containsKey(document)){
                var parent=rows("SELECT * FROM "+table+" WHERE site_id=? AND id=? FOR UPDATE",c.site(),document).getFirst();
                if(!Objects.equals(parent.get("revision"),b.path("expected_"+kind+"_revisions").path(Long.toString(document)).asText()))throw conflict("关联单据修订已变化。");selected.put(document,parent);
            }}parents.put(kind,selected);
        }
        var positions=rows("SELECT * FROM inventory_shipment_position WHERE site_id=? AND sku_id IN ("+marks(mapping.size())+") FOR UPDATE",args(c.site(),mapping.keySet()));
        if(positions.stream().anyMatch(r->num(r.get("warehouse_id"))!=warehouse||num(r.get("owner_id"))!=owner))throw conflict("出货占位属于其他库存范围。");
        var documents=rows("SELECT * FROM inventory_document WHERE site_id=? AND warehouse_id=? AND owner_id=? ORDER BY id FOR UPDATE",c.site(),warehouse,owner);
        var changedDocuments=new ArrayList<Object>();
        for(var document:documents){
            JsonNode beforeLines=json.readTree(document.get("line_items").toString());
            JsonNode beforeEffects=document.get("effects")==null?json.nullNode():json.readTree(document.get("effects").toString());
            var afterLines=rewriteSkuReferences(beforeLines,mapping);var afterEffects=rewriteSkuReferences(beforeEffects,mapping);
            if(beforeLines.equals(afterLines)&&beforeEffects.equals(afterEffects))continue;
            long documentId=num(document.get("id")),revision=num(document.get("revision"));
            if(!Long.toString(revision).equals(b.path("expected_stock_revisions").path(Long.toString(documentId)).asText()))throw conflict("库存单据修订已变化。");
            var before=new LinkedHashMap<>(document);before.put("line_items",beforeLines);before.put("effects",beforeEffects);
            db.update("UPDATE inventory_document SET line_items=?,effects=?,revision=revision+1 WHERE site_id=? AND id=?",json.writeValueAsString(afterLines),afterEffects.isNull()?null:json.writeValueAsString(afterEffects),c.site(),documentId);
            var after=new LinkedHashMap<>(before);after.put("line_items",afterLines);after.put("effects",afterEffects);after.put("revision",Long.toString(revision+1));
            audit(c,"stock",documentId,revision+1,token,reason,before,after);changedDocuments.add(Map.of("before",before,"after",after));
        }
        for(var entry:mapping.entrySet()){
            long old=entry.getKey(),target=entry.getValue(),amount=num(balances.get(old).get("qualified_units"));var identity=identities.get(target);
            db.update("UPDATE inventory_balance SET sku_id=?,sku_label=?,catalog_version=?,revision=revision+1 WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",target,identity.path("label").asText(),identity.path("catalog_version").asText(),c.site(),warehouse,owner,old);
            db.update("UPDATE production_backup_sku_crosswalk SET target_sku_id=?,status='MAPPED',match_rule='EXPLICIT_IDENTITY_REBIND',target_identity=? WHERE target_sku_id=?",target,identity.path("label").asText(),old);
            db.update("UPDATE inventory_shipment_position SET sku_id=? WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",target,c.site(),warehouse,owner,old);
            for(String table:List.of("production_order_line","production_shipment_source_line"))db.update("UPDATE "+table+" SET sku_id=?,sku_label=?,catalog_version=? WHERE site_id=? AND sku_id=? AND is_active=TRUE",target,identity.path("label").asText(),identity.path("catalog_version").asText(),c.site(),old);
            if(amount>0)for(boolean outgoing:List.of(true,false))db.update("INSERT INTO inventory_event(site_id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,operation_token,actor_id,actor_name,reason,business_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                c.site(),warehouse,owner,outgoing?old:target,"QUALIFIED",outgoing?-amount:amount,"identity",warehouse,identityRevision,token,c.actor(),c.actorName(),reason,LocalDate.now(ZoneId.of("Asia/Shanghai")));
        }
        for(var kind:parents.entrySet())for(var parent:kind.getValue().entrySet()){
            String table=kind.getKey().equals("orders")?"production_order":"production_shipment";long revision=num(parent.getValue().get("revision"));
            db.update("UPDATE "+table+" SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),parent.getKey());
            String lineTable=kind.getKey().equals("orders")?"production_order_line":"production_shipment_source_line",parentField=kind.getKey().equals("orders")?"order_id":"shipment_id";
            var priorLines=(kind.getKey().equals("orders")?orderLines:shipmentLines).stream().filter(r->num(r.get(parentField))==parent.getKey()).toList();
            var before=Map.of("document",parent.getValue(),"identity_lines",priorLines);
            var after=Map.of("document",rows("SELECT * FROM "+table+" WHERE site_id=? AND id=?",c.site(),parent.getKey()).getFirst(),"identity_lines",rows("SELECT * FROM "+lineTable+" WHERE site_id=? AND "+parentField+"=? AND is_active=TRUE ORDER BY id",c.site(),parent.getKey()));
            audit(c,kind.getKey(),parent.getKey(),revision+1,token,reason,before,after);
        }
        var afterBalances=rows("SELECT * FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=? ORDER BY sku_id",c.site(),warehouse,owner);
        if(sum(afterBalances)!=totalBefore||afterBalances.size()!=beforeBalances.size())throw conflict("衔接数量不守恒，全部回滚。");
        var afterById=new HashMap<Long,Map<String,Object>>();for(var r:afterBalances)afterById.put(num(r.get("sku_id")),r);
        for(var before:beforeBalances){var after=afterById.get(mapping.getOrDefault(num(before.get("sku_id")),num(before.get("sku_id"))));if(after==null)throw conflict("库存身份缺失，全部回滚。");for(String quality:List.of("qualified_units","pending_units","defective_units","unassessed_units"))if(!before.get(quality).equals(after.get(quality)))throw conflict("单规格货品数量发生变化，全部回滚。");}
        var result=new LinkedHashMap<String,Object>();result.put("converted_records",mapping.size());result.put("converted_units",mapping.keySet().stream().mapToLong(k->num(balances.get(k).get("qualified_units"))).sum());
        result.put("order_line_count",orderLines.size());result.put("shipment_source_count",shipmentLines.size());result.put("stock_document_count",changedDocuments.size());
        result.put("physical_net_change","0");result.put("inventory_total_units",Long.toString(totalBefore));result.put("catalog_version",b.path("expected_catalog_version").asText());result.put("operation_token",token);
        result.put("identity_revision",identityRevision);
        audit(c,"identity",warehouse,identityRevision,token,reason,Map.of("balances",beforeBalances,"crosswalks",crosswalks,"shipment_positions",positions),Map.of("result",result,"balances",afterBalances,"mappings",b.path("mappings"),"source_reference",b.path("source_reference")));
        return result;
    }
}
