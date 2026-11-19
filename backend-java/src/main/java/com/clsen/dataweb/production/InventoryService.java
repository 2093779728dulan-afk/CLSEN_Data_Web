package com.clsen.dataweb.production;

import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.LocalDate;
import java.util.*;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Stock facts share the shipment transaction; a site row orders all writers. */
@Service
public class InventoryService {
    private final JdbcTemplate db; private final ObjectMapper json; private final String authorityMode;
    private final CatalogAuthority catalogAuthority;
    private final RealOpeningSource realOpening;
    @Value("${PRODUCTION_WRITES_ENABLED:true}")
    private boolean writesEnabled=true;
    @Value("${PRODUCTION_INVENTORY_WRITES_ENABLED:false}")
    private boolean inventoryWritesEnabled;
    @Value("${PRODUCTION_OPENING_ENABLED:false}")
    private boolean openingEnabled;
    @Value("${PRODUCTION_IDENTITY_REBIND_ENABLED:false}")
    private boolean identityRebindingEnabled;
    @Value("${PRODUCTION_FBA_ENABLED:false}")
    private boolean fbaEnabled;
    public InventoryService(JdbcTemplate db,ObjectMapper json,String mode){this(db,json,mode,"","");}
    public InventoryService(JdbcTemplate db,ObjectMapper json,String mode,String catalogSchema,String catalogScope){this(db,json,mode,catalogSchema,catalogScope,"",0,0,"");}
    @org.springframework.beans.factory.annotation.Autowired
    public InventoryService(JdbcTemplate db,ObjectMapper json,@Value("${PRODUCTION_AUTHORITY_MODE:disabled}") String mode, @Value("${PRODUCTION_CATALOG_SCHEMA:}") String catalogSchema, @Value("${PRODUCTION_CATALOG_ALLOWED_SKUS:}") String catalogScope, @Value("${PRODUCTION_OPENING_REVIEW:}") String openingReview, @Value("${PRODUCTION_OPENING_REVIEW_REVISION:0}") long openingRevision, @Value("${PRODUCTION_OPENING_WAREHOUSE_ID:0}") long openingWarehouse, @Value("${PRODUCTION_OPENING_WAREHOUSE_NAME:}") String openingWarehouseName){this.db=db;this.json=json;this.authorityMode=mode;this.catalogAuthority=new CatalogAuthority(db,json,mode,catalogSchema,catalogScope);this.realOpening=new RealOpeningSource(db,json,catalogAuthority,openingReview,openingRevision,openingWarehouse,openingWarehouseName);}
    record Key(long warehouse,long owner,long sku) implements Comparable<Key>{public int compareTo(Key b){int c=Long.compare(warehouse,b.warehouse);if(c==0)c=Long.compare(owner,b.owner);return c==0?Long.compare(sku,b.sku):c;}}
    record Delta(Key key,String quality,long units,String from,String to){}
    static String text(JsonNode b,String k,int max){return ProductionService.text(b,k,max);}
    static long positive(JsonNode b,String k){return ProductionService.positive(b.get(k),k);}
    static long number(JsonNode b,String k){String s=text(b,k,19);if(!s.matches("0|[1-9][0-9]{0,18}"))throw error(422,"invalid_integer","数量必须是非负整数。");try{return Long.parseLong(s);}catch(NumberFormatException e){throw error(422,"integer_out_of_range","数量超出支持范围。");}}
    static long n(Object v){return Long.parseLong(v.toString());}
    static ProductionError error(int status,String code,String message){return new ProductionError(status,code,message);}
    static LocalDate day(String s){try{return LocalDate.parse(s);}catch(RuntimeException e){throw error(422,"invalid_date","请填写有效业务日期。");}}
    static long total(long a,long b){try{return Math.addExact(a,b);}catch(ArithmeticException e){throw error(422,"integer_out_of_range","数量合计超出支持范围。");}}
    static String bucket(String quality){return switch(quality){case "QUALIFIED"->"qualified_units";case "PENDING"->"pending_units";case "DEFECTIVE"->"defective_units";case "UNASSESSED"->"unassessed_units";default->throw error(422,"invalid_quality","请选择合格、待检、次品或明确保留质量未核。");};}
    private Map<String,Object> row(ResultSet r,int ignored)throws SQLException{var value=new LinkedHashMap<String,Object>();for(int i=1;i<=r.getMetaData().getColumnCount();i++){Object v=r.getObject(i);if(v instanceof Number)v=v.toString();else if(v instanceof java.sql.Date d)v=d.toLocalDate().toString();else if(v instanceof java.sql.Timestamp t)v=t.toInstant().toString();value.put(r.getMetaData().getColumnLabel(i),v);}return value;}
    private List<Map<String,Object>> rows(String sql,Object...args){return db.query(sql,this::row,args);}
    private long inserted(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    void lockSite(long site){db.update("INSERT INTO inventory_site_lock(site_id) VALUES(?) ON DUPLICATE KEY UPDATE site_id=site_id",site);rows("SELECT site_id FROM inventory_site_lock WHERE site_id=? FOR UPDATE",site);}
    private String hash(JsonNode body){return hashValue(canonical(body));}
    private String hashValue(Object value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsString(value).getBytes(StandardCharsets.UTF_8)));}catch(java.security.NoSuchAlgorithmException e){throw new IllegalStateException(e);}}
    private Object canonical(JsonNode b){if(b.isObject()){var v=new TreeMap<String,Object>();for(var e:b.properties())if(!Set.of("_catalog","operation_token","_actor_name","_auto_setup").contains(e.getKey()))v.put(e.getKey(),canonical(e.getValue()));return v;}if(b.isArray()){var v=new ArrayList<Object>();b.forEach(x->v.add(canonical(x)));return v;}if(b.isNull())return null;return b.isBoolean()?b.asBoolean():b.asText();}
    private Map<String,Object> scope(long site,Key k){var r=rows("SELECT * FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",site,k.warehouse,k.owner);return r.isEmpty()?null:r.getFirst();}
    private Map<String,Object> balance(long site,Key k){var r=rows("SELECT * FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",site,k.warehouse,k.owner,k.sku);return r.isEmpty()?null:r.getFirst();}
    JsonNode identity(long site,JsonNode b,long sku){if(catalogAuthority.enabled())return catalogAuthority.current(site,b,sku);var item=b.path("_catalog").path(Long.toString(sku));if(!item.path("status").asText().equals("active")||!(authorityMode.equals("demo_fixed")&&item.path("catalog_version").asText().equals("DEMO_LOCAL_ONLY-v1")||authorityMode.equals("qa_catalog")&&item.path("contract_version").asText().equals("2")&&"clsen_orders_qa_sku_20261015".equals(db.queryForObject("SELECT DATABASE()",String.class))))throw error(409,"sku_identity_unavailable","当前只启用独立虚构商品身份；真实身份确认合同尚未接通。");return item;}
    JsonNode displayIdentity(long site,JsonNode input,long sku){return catalogAuthority.enabled()?catalogAuthority.currentForDisplay(site,input,sku):identity(site,input,sku);}
    private long reserved(long site,Key k,String line){String sql="SELECT COALESCE(SUM(units-consumed_units-released_units),0) FROM inventory_reservation WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?";var args=new ArrayList<Object>(List.of(site,k.warehouse,k.owner,k.sku));if(!line.isEmpty()){sql+=" AND order_line_id=?";args.add(line);}return db.queryForObject(sql,Long.class,args.toArray());}
    private long held(long site,Key k){return db.queryForObject("SELECT COALESCE(SUM(units-released_units),0) FROM inventory_hold WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",Long.class,site,k.warehouse,k.owner,k.sku);}
    private Map<String,Object> available(long site,Key k,String orderLine){
        var result=new LinkedHashMap<String,Object>();result.put("warehouse_id",Long.toString(k.warehouse));result.put("owner_id",Long.toString(k.owner));result.put("sku_id",Long.toString(k.sku));
        boolean identityReady=!catalogAuthority.enabled()||catalogAuthority.permits(site,k.sku);result.put("identity_status",identityReady?"mapped":"pending");
        var b=balance(site,k);var s=scope(site,k);if(b==null||s==null){result.put("state","not_ready");result.put("free_available_units",null);result.put("dispatch_allowed_units",null);result.put("on_hand_units",null);result.put("missing","该仓库/货权/SKU尚未登记期初");return result;}
        result.putAll(b);long q=n(b.get("qualified_units")),h=held(site,k),r=reserved(site,k,""),own=0;for(String line:new TreeSet<>(Arrays.asList(orderLine.split(","))))if(!line.isEmpty()){if(!line.matches("[1-9][0-9]{0,18}"))throw error(422,"invalid_scope","订单明细参数无效。");own=total(own,reserved(site,k,line));}long loan=db.queryForObject("SELECT COALESCE(SUM(borrowed_units-returned_units-settled_units),0) FROM inventory_loan WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=? AND is_active=TRUE",Long.class,site,k.warehouse,k.owner,k.sku);
        long occupied=total(h,r),unassessed=n(b.getOrDefault("unassessed_units","0"));boolean shortage=q<occupied;result.put("state",shortage?"shortage":"ready");result.put("held_units",Long.toString(h));result.put("reserved_units",Long.toString(r));result.put("own_reserved_units",Long.toString(own));result.put("shortage_units",Long.toString(Math.max(0,occupied-q)));result.put("free_available_units",shortage?null:Long.toString(q-occupied));result.put("dispatch_allowed_units",shortage?null:Long.toString(total(q-occupied,own)));result.put("on_hand_units",BigInteger.valueOf(q).add(BigInteger.valueOf(n(b.get("pending_units")))).add(BigInteger.valueOf(n(b.get("defective_units")))).add(BigInteger.valueOf(unassessed)).toString());result.put("loan_outstanding_units",Long.toString(loan));result.put("cutoff_on",s.get("cutoff_on"));result.put("source_reference",s.get("source_reference"));
        JsonNode opening=s.get("opening_metadata")==null?json.createObjectNode():json.readTree(s.get("opening_metadata").toString());
        if(!identityReady){result.put("state","not_ready");result.put("free_available_units",null);result.put("dispatch_allowed_units",null);result.put("missing","历史库存已保留，但尚未与当前服务器商品目录建立唯一对应；当前禁止发货或继续过账。");}
        else if(!shortage&&(unassessed>0||opening.path("owner_state").asText().equals("UNASSIGNED")&&!RealOpeningSource.WAREHOUSE_BASIS.equals(opening.path("quantity_basis").asText()))){result.put("state","not_ready");result.put("free_available_units",null);result.put("dispatch_allowed_units",null);result.put("missing","期初数量已登记，货主及货品状态待核，当前可发尚未就绪。");}
        if(!opening.isEmpty())result.put("opening_metadata",opening);return result;
    }
    static Map<String,Object> displayIdentity(String label){
        var result=new LinkedHashMap<String,Object>();
        if(label==null)return result;
        String[] parts=label.split(" · ",3);
        if(parts.length!=3)return result;
        int separator=parts[2].lastIndexOf(" / ");
        if(separator<=0||separator+3>=parts[2].length())return result;
        result.put("style_code",parts[0]);
        result.put("display_sku",parts[1]);
        result.put("standard_color",parts[2].substring(0,separator));
        result.put("standard_size",parts[2].substring(separator+3));
        return result;
    }
    private Map<Long,Map<String,Object>> backupDisplayIdentities(long site){
        if(!"clsen_control_production_backup_b_v1_1_0_20261017".equals(catalogAuthority.schema()))return Map.of();
        var catalog=new HashMap<Long,Map<String,Object>>();
        for(var item:rows("""
            SELECT r.sku_id,sr.style_code,r.internal_display_sku,
                   r.standard_color,r.standard_size
            FROM `clsen_control_production_backup_b_v1_1_0_20261017`.product_catalog_publications p
            JOIN `clsen_control_production_backup_b_v1_1_0_20261017`.product_catalog_sku_members m
              ON m.site_id=p.site_id AND m.catalog_version_id=p.current_catalog_version_id
            JOIN `clsen_control_production_backup_b_v1_1_0_20261017`.product_sku_revisions r
              ON r.site_id=m.site_id AND r.sku_id=m.sku_id AND r.id=m.sku_revision_id
            JOIN `clsen_control_production_backup_b_v1_1_0_20261017`.product_catalog_style_members sm
              ON sm.site_id=p.site_id AND sm.catalog_version_id=p.current_catalog_version_id
             AND sm.style_id=r.style_id
            JOIN `clsen_control_production_backup_b_v1_1_0_20261017`.product_style_revisions sr
              ON sr.site_id=sm.site_id AND sr.style_id=sm.style_id
             AND sr.id=sm.style_revision_id
            WHERE p.site_id=?
            """,site)){
            var identity=new LinkedHashMap<String,Object>();
            identity.put("style_code",item.get("style_code"));
            identity.put("display_sku",item.get("internal_display_sku"));
            identity.put("standard_color",item.get("standard_color"));
            identity.put("standard_size",item.get("standard_size"));
            catalog.put(n(item.get("sku_id")),identity);
        }
        var result=new HashMap<Long,Map<String,Object>>();
        for(var item:rows("SELECT target_sku_id,status,old_identity FROM production_backup_sku_crosswalk")){
            long sku=n(item.get("target_sku_id"));
            var identity="MAPPED".equals(item.get("status"))?catalog.get(sku):displayIdentity(Objects.toString(item.get("old_identity"),null));
            if(identity!=null&&!identity.isEmpty())result.put(sku,identity);
        }
        return result;
    }
    private void enrichDisplayIdentity(Map<String,Object> availability,Map<Long,Map<String,Object>> identities){
        var identity=identities.get(n(availability.get("sku_id")));
        if(identity!=null)availability.putAll(identity);
    }
    private Key key(JsonNode b,long sku){return new Key(b.hasNonNull("warehouse_id")?positive(b,"warehouse_id"):1,b.hasNonNull("owner_id")?positive(b,"owner_id"):1,sku);}
    private Key queryKey(Map<String,String> q){try{return new Key(Long.parseLong(q.getOrDefault("warehouse_id","1")),Long.parseLong(q.getOrDefault("owner_id","1")),Long.parseLong(q.getOrDefault("sku_id","0")));}catch(NumberFormatException e){throw error(422,"invalid_scope","仓库/货权/SKU参数无效。");}}
    private Map<String,Object> entity(long site,String table,long id){var r=rows("SELECT * FROM "+table+" WHERE site_id=? AND id=?",site,id);if(r.isEmpty())throw error(404,"document_not_found","记录不存在或不在当前站点。");return r.getFirst();}
    private Map<String,Object> document(long site,long id){var r=entity(site,"inventory_document",id);r.put("lines",json.readTree(r.remove("line_items").toString()));r.put("production_sources",productionSources(site,r.get("kind").toString(),(JsonNode)r.get("lines"),false));r.put("loan_ids",rows("SELECT id FROM inventory_loan WHERE site_id=? AND document_id=? AND is_active=TRUE",site,id).stream().map(v->v.get("id")).toList());return r;}

    /** Explicit receipt allocations, never inferred from SKU/date or shipment quantities. */
    private List<Map<String,Object>> productionSources(long site,String kind,JsonNode lines,boolean validate){
        var result=new ArrayList<Map<String,Object>>();int index=0;
        for(var line:lines){
            index++;boolean production=line.path("purpose").asText().equals("PRODUCTION_RECEIPT");var allocations=line.path("production_allocations");
            if(!production){if(validate&&line.hasNonNull("production_allocations")&&(!allocations.isArray()||!allocations.isEmpty()))throw error(422,"receipt_purpose_invalid","只有生产实收入库可以分配来源订单。");continue;}
            if(validate&&(!kind.equals("IN")||!allocations.isArray()||allocations.isEmpty()||allocations.size()>500))throw error(422,"receipt_allocations_required","生产实收需填写1至500项来源订单分配，且只用于实际入库。");
            long allocated=0;var seen=new HashSet<Long>();
            for(var allocation:allocations){
                long lineId=positive(allocation,"order_line_id"),amount=positive(allocation,"units");allocated=total(allocated,amount);
                if(validate&&!seen.add(lineId))throw error(422,"duplicate_receipt_allocation","同一收货明细的来源订单行不能重复，请合并分配数量。");
                var matches=rows("SELECT o.id AS order_id,o.system_number AS order_number,o.business_number AS order_business_number,o.revision AS order_revision,o.status AS order_status,l.id AS order_line_id,l.sku_id,l.is_active,l.expected_units FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE l.site_id=? AND l.id=?",site,lineId);
                if(validate&&(matches.isEmpty()||!matches.getFirst().get("order_status").equals("CONFIRMED")||!Boolean.parseBoolean(matches.getFirst().get("is_active").toString())||n(matches.getFirst().get("sku_id"))!=positive(line,"sku_id")))throw error(409,"receipt_source_invalid","来源订单行不存在、不在当前站点、未确认、已移除或商品不同；请重新核对。");
                var source=matches.isEmpty()?new LinkedHashMap<String,Object>():new LinkedHashMap<>(matches.getFirst());
                source.put("order_line_id",Long.toString(lineId));source.put("line_number",Integer.toString(index));source.put("units",Long.toString(amount));result.add(source);
            }
            if(validate&&allocated!=positive(line,"units"))throw error(422,"receipt_allocation_mismatch","来源订单分配合计必须等于该行实际收货件数；不要求等于订单预计量。");
        }return result;
    }
    List<Map<String,Object>> productionReceipts(long site,long order){
        return rows("""
            SELECT d.id AS document_id,d.business_date,d.status,d.revision,d.warehouse_id,d.owner_id,
                   x.line_number,x.sku_id,x.quality,x.order_line_id,x.units
            FROM inventory_document d
            JOIN JSON_TABLE(d.line_items,'$[*]' COLUMNS(
                line_number FOR ORDINALITY,sku_id BIGINT PATH '$.sku_id',quality VARCHAR(16) PATH '$.quality',
                purpose VARCHAR(32) PATH '$.purpose',NESTED PATH '$.production_allocations[*]' COLUMNS(
                    order_line_id BIGINT PATH '$.order_line_id',units VARCHAR(19) PATH '$.units'))) x ON TRUE
            JOIN production_order_line l ON l.site_id=d.site_id AND l.id=x.order_line_id
            WHERE d.site_id=? AND l.order_id=? AND d.kind='IN' AND x.purpose='PRODUCTION_RECEIPT'
                AND d.status IN ('POSTED','REVERSED') ORDER BY d.id DESC,x.line_number,x.order_line_id
            """,site,order);
    }
    void requireNoProductionReceipt(long site,long line){
        long count=db.queryForObject("""
            SELECT COUNT(*) FROM inventory_document d
            JOIN JSON_TABLE(d.line_items,'$[*]' COLUMNS(purpose VARCHAR(32) PATH '$.purpose',
                NESTED PATH '$.production_allocations[*]' COLUMNS(order_line_id BIGINT PATH '$.order_line_id'))) x ON TRUE
            WHERE d.site_id=? AND d.status='POSTED' AND d.kind='IN' AND x.purpose='PRODUCTION_RECEIPT' AND x.order_line_id=?
            """,Long.class,site,line);
        if(count>0)throw error(409,"downstream_receipt_exists","存在有效生产实收入库引用；请先按实际情况更正来源或冲销错误入库，不能移除或作废来源订单。");
    }
    private void revision(Map<String,Object> item,JsonNode b){if(positive(b,"expected_revision")!=n(item.get("revision")))throw error(409,"inventory_revision_conflict","记录已变化；保留输入，读取最新版本后重新预览。");}
    private void touch(long site,Key k){db.update("UPDATE inventory_balance SET revision=revision+1 WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",site,k.warehouse,k.owner,k.sku);}
    private void balanceRevision(long site,Key k,JsonNode b){if(b.hasNonNull("expected_balance_revision")){var item=balance(site,k);if(item==null||n(item.get("revision"))!=positive(b,"expected_balance_revision"))throw error(409,"inventory_revision_conflict","库存已变化，请核对当前可发量后再提交。");}}
    void checkDate(long site,Key k,String date){var s=scope(site,k);if(s==null)throw error(409,"inventory_not_ready","请先完成明确范围和SKU的期初。");if(day(date).isBefore(day(s.get("cutoff_on").toString())))throw error(409,"before_opening_cutoff","截止前的事实可能已包含在期初，不能直接重复过账。");}
    void audit(ProductionContext c,String kind,long id,long rev,String token,String action,String reason,Object before,Object after){db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,actor_name,operation_token,reason,operation_kind,before_value,after_value) VALUES(?,?,?,?,?,?,?,?,?,?,?)",c.site(),kind,id,rev,c.actor(),c.actorName(),token,reason,action,before==null?null:json.writeValueAsString(before),json.writeValueAsString(after));}
    private void event(ProductionContext c,Delta d,String kind,long id,long rev,String token,String reason,String date,Long source){db.update("INSERT INTO inventory_event(site_id,warehouse_id,owner_id,sku_id,quality,delta_units,document_kind,document_id,revision,source_line_id,operation_token,actor_id,actor_name,reason,business_date,location_from,location_to) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",c.site(),d.key.warehouse,d.key.owner,d.key.sku,d.quality,d.units,kind,id,rev,source,token,c.actor(),c.actorName(),reason,day(date),d.from,d.to);}
    void apply(ProductionContext c,List<Delta> deltas,String kind,long id,long rev,String token,String reason,String date,boolean checkFree){
        applyDeltas(c,deltas,kind,id,rev,token,reason,date,checkFree,false);
    }
    void applyFba(ProductionContext c,List<Delta> deltas,String kind,long id,long rev,String token,String reason,String date){
        if(!fbaEnabled)throw error(403,"fba_disabled","FBA库存适配尚未启用。");
        applyDeltas(c,deltas,kind,id,rev,token,reason,date,true,true);
    }
    private void applyDeltas(ProductionContext c,List<Delta> deltas,String kind,long id,long rev,String token,String reason,String date,boolean checkFree,boolean fba){
        var net=new TreeMap<Key,Map<String,Long>>();for(var d:deltas){bucket(d.quality);net.computeIfAbsent(d.key,k->new TreeMap<>()).merge(d.quality,d.units,InventoryService::total);}
        for(var e:net.entrySet()){
            if(fba)FbaInventoryStore.requireScope(db,c.site(),e.getKey().warehouse,e.getKey().owner);
            else ProductionDirectory.requireOperational(db,c.site(),e.getKey().warehouse);
            var b=balance(c.site(),e.getKey());if(b==null)throw error(409,"inventory_not_ready","SKU尚未完成期初，不允许按零库存继续。");
            for(var v:e.getValue().entrySet()){long next=total(n(b.get(bucket(v.getKey()))),v.getValue());if(next<0)throw error(409,"insufficient_available_stock","当前实物不足，或原入库已经被下游消费，不能逆转。");if(checkFree&&v.getKey().equals("QUALIFIED")&&v.getValue()<0)ensureFree(c.site(),e.getKey(),-v.getValue(),0);}
        }
        for(var e:net.entrySet())for(var v:e.getValue().entrySet())db.update("UPDATE inventory_balance SET "+bucket(v.getKey())+"="+bucket(v.getKey())+"+?,revision=revision+1 WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",v.getValue(),c.site(),e.getKey().warehouse,e.getKey().owner,e.getKey().sku);
        for(var d:deltas)event(c,d,kind,id,rev,token,reason,date,null);
    }
    private void ensureFree(long site,Key k,long needed,long own){var a=available(site,k,"");if(a.get("state").equals("not_ready"))throw error(409,"inventory_not_ready","期初或货主、货品状态未就绪；不能确认实际发货。");if(a.get("state").equals("shortage"))throw error(409,"stock_shortage","实物与冻结/预留存在缺口，先处理占用及实际收货。");long free=n(a.get("free_available_units"));if(needed>total(free,own))throw error(409,"insufficient_available_stock","SKU "+k.sku+" 请求"+needed+"件，当前允许"+total(free,own)+"件（自由可发"+free+"，本次预留"+own+"）；预计量不能放行。");}
    @Transactional(readOnly=true)
    public byte[] destinationOriginal(ProductionContext c,String id){return new DestinationReceiptFileStore(db).original(c,id);}
    @Transactional(readOnly=true)
    public byte[] fbaOriginal(ProductionContext c,long id){c.requireWrite();return new FbaInventoryStore(db,json,this).original(c,id);}
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Object read(ProductionContext c,String resource,Map<String,String> q){
        if(resource.equals("overview-sheet-options"))return new InventoryOverviewSheetStore(db,json,this).options(c);
        if(resource.equals("overview-sheet"))return new InventoryOverviewSheetStore(db,json,this).read(c,q);
        if(resource.equals("display-settings"))return new InventoryDisplaySettings(db,json,this).read(c);
        if(resource.equals("transport-summary"))return new WarehouseTransitStore(db,json,this).summary(c,java.time.Instant.now());
        if(resource.equals("transit-batches"))return new WarehouseTransitStore(db,json,this).batches(c,q,java.time.Instant.now());
        if(resource.equals("warehouse-transit"))return new WarehouseTransitStore(db,json,this).read(c,q,java.time.Instant.now());
        if(resource.equals("sku-locations"))return new WarehouseTransitStore(db,json,this).locations(c,q,java.time.Instant.now());
        if(resource.equals("fba-daily-scopes"))return Map.of("items",fbaEnabled?rows("SELECT s.id,s.report_source_scope_id FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND w.status='ACTIVE'",c.site()):List.of());
        if(resource.equals("fba-state")){
            if(!fbaEnabled)return Map.of("enabled",false);
            return new FbaInventoryStore(db,json,this).state(c,ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("warehouse_id","")),"warehouse_id"));
        }
        if(resource.startsWith("fba-batches/"))return new FbaInventoryStore(db,json,this).batch(c,Long.parseLong(resource.substring("fba-batches/".length())));
        if(resource.startsWith("fba-action-scopes/"))return new FbaInventoryStore(db,json,this).actionScopeContext(c,Long.parseLong(resource.substring("fba-action-scopes/".length())));
        if(resource.startsWith("fba-scopes/"))return new FbaInventoryStore(db,json,this).scopeContext(c,Long.parseLong(resource.substring("fba-scopes/".length())));
        if(resource.equals("fba-classifications"))return new FbaInventoryStore(db,json,this).classifications(c,q);
        if(resource.equals("transport-state"))return new ShipmentTransportStore(db,json,this).state(c,ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("shipment_id","")),"shipment_id"));
        if(resource.startsWith("destination-receipts/"))return new DestinationReceiptStore(db,json,this).get(c,Long.parseLong(resource.substring("destination-receipts/".length())));
        if(resource.equals("destination-state"))return new DestinationReceiptStore(db,json,this).state(c,ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("shipment_id","")),"shipment_id"));
        if(resource.equals("destination-receipts")){
            long warehouse=ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("warehouse_id","")),"warehouse_id");
            long owner=ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("owner_id","")),"owner_id");
            return Map.of("items",rows("SELECT r.id,r.shipment_id,r.status,r.revision,r.business_date,r.reason,COALESCE((SELECT SUM(l.qualified_units+l.pending_units+l.defective_units) FROM destination_receipt_line l WHERE l.site_id=r.site_id AND l.receipt_id=r.id),0) AS units FROM destination_receipt r WHERE r.site_id=? AND r.warehouse_id=? AND r.owner_id=? ORDER BY r.id DESC LIMIT 200",c.site(),warehouse,owner),"limit",200);
        }
        if(resource.equals("destination-shipments")){
            long warehouse=ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("warehouse_id","")),"warehouse_id");
            long owner=ProductionService.positive(json.getNodeFactory().textNode(q.getOrDefault("owner_id","")),"owner_id");
            if(scope(c.site(),new Key(warehouse,owner,0))==null)throw error(409,"inventory_not_ready","该目的仓及货权尚未建账，不能登记实际入库。");
            var items=rows("SELECT id,system_number,business_number,business_date,revision,destination_id FROM production_shipment WHERE site_id=? AND destination_id=? AND status='CONFIRMED' ORDER BY id DESC LIMIT 200",c.site(),warehouse);
            return Map.of("items",items,"warehouse_id",Long.toString(warehouse),"owner_id",Long.toString(owner),"limit",200);
        }
        if(resource.equals("availability")&&q.containsKey("sku_id")){
            var item=available(c.site(),queryKey(q),q.getOrDefault("order_line_ids",q.getOrDefault("order_line_id","")));
            enrichDisplayIdentity(item,backupDisplayIdentities(c.site()));return item;
        }
        if(resource.equals("availability")){
            var args=new ArrayList<Object>(List.of(c.site()));String where="site_id=?";
            for(String key:List.of("warehouse_id","owner_id"))if(q.containsKey(key)){where+=" AND "+key+"=?";args.add(ProductionService.positive(json.getNodeFactory().textNode(q.get(key)),key));}
            String projection=q.getOrDefault("projection","full");
            if(!Set.of("full","scopes","summary").contains(projection))throw error(422,"invalid_projection","库存读取方式无效。");
            if(!projection.equals("full")){
                String scopedWhere=where.replace("site_id","s.site_id").replace("warehouse_id","s.warehouse_id").replace("owner_id","s.owner_id");
                var scopes=rows("SELECT s.warehouse_id,s.owner_id,COALESCE(w.name,s.warehouse_name) AS warehouse_name,s.owner_name,w.type AS warehouse_type,w.status AS warehouse_status,s.cutoff_on FROM inventory_scope s LEFT JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE "+scopedWhere+" ORDER BY s.warehouse_id,s.owner_id",args.toArray());
                String balanceWhere=where.replace("site_id","b.site_id").replace("warehouse_id","b.warehouse_id").replace("owner_id","b.owner_id");
                var items=projection.equals("scopes")?List.of():rows("SELECT b.warehouse_id,b.owner_id,CASE WHEN MAX(s.warehouse_id) IS NULL THEN NULL ELSE CAST(SUM(CAST(b.qualified_units AS DECIMAL(65,0))+b.pending_units+b.defective_units+b.unassessed_units) AS CHAR) END AS on_hand_units FROM inventory_balance b LEFT JOIN inventory_scope s ON s.site_id=b.site_id AND s.warehouse_id=b.warehouse_id AND s.owner_id=b.owner_id WHERE "+balanceWhere+" GROUP BY b.warehouse_id,b.owner_id ORDER BY b.warehouse_id,b.owner_id",args.toArray());
                return Map.of("items",items,"scopes",scopes,"projection",projection,"writes_enabled",writesEnabled||inventoryWritesEnabled,"opening_enabled",writesEnabled||openingEnabled,"production_receipts_supported",true);
            }
            var identities=backupDisplayIdentities(c.site());var list=new ArrayList<Object>();for(var b:rows("SELECT warehouse_id,owner_id,sku_id FROM inventory_balance WHERE "+where+" ORDER BY warehouse_id,owner_id,sku_id",args.toArray())){var item=available(c.site(),new Key(n(b.get("warehouse_id")),n(b.get("owner_id")),n(b.get("sku_id"))),"");enrichDisplayIdentity(item,identities);list.add(item);}
            var scopes=rows("SELECT * FROM inventory_scope WHERE "+where+" ORDER BY warehouse_id,owner_id",args.toArray());
            for(var scope:scopes){var names=rows("SELECT name,type,status FROM production_warehouse WHERE site_id=? AND id=?",c.site(),scope.get("warehouse_id"));if(!names.isEmpty()){scope.put("warehouse_name",names.getFirst().get("name"));scope.put("warehouse_type",names.getFirst().get("type"));scope.put("warehouse_status",names.getFirst().get("status"));}}
            return Map.of("items",list,"scopes",scopes,"writes_enabled",writesEnabled||inventoryWritesEnabled,"opening_enabled",writesEnabled||openingEnabled,"production_receipts_supported",true);
        }
        if(resource.startsWith("documents/"))return document(c.site(),Long.parseLong(resource.substring(10)));
        if(resource.equals("history")){
            String filter="site_id=? AND document_kind IN ('stock','opening','reservation','hold','loan','plan','identity','destination','destsettlement')";var args=new ArrayList<Object>(List.of(c.site()));
            for(String name:List.of("actor_id","from","to","action")){String value=q.getOrDefault(name,"");if(!value.isEmpty()){filter+=switch(name){case "actor_id"->" AND actor_id=?";case "from"->" AND created_at>=?";case "to"->" AND created_at<DATE_ADD(?,INTERVAL 1 DAY)";default->" AND operation_kind=?";};args.add(value);}}
            var items=rows("SELECT document_kind,document_id,revision,actor_id,actor_name,operation_kind,reason,before_value,after_value,created_at FROM production_revision WHERE "+filter+" ORDER BY id DESC LIMIT 200",args.toArray());for(var item:items)for(String field:List.of("before_value","after_value"))if(item.get(field)!=null)item.put(field,json.readTree(item.get(field).toString()));return Map.of("items",items,"limit",200,"actors",rows("SELECT actor_id,MAX(actor_name) AS actor_name FROM production_revision WHERE site_id=? AND actor_name<>'' GROUP BY actor_id ORDER BY actor_id",c.site()));
        }
        if(resource.equals("forecast"))return forecast(c,q);
        if(resource.equals("documents")&&q.containsKey("page")) {
            int page,pageSize;
            try{page=Integer.parseInt(q.get("page"));pageSize=Integer.parseInt(q.getOrDefault("page_size","20"));}catch(NumberFormatException e){throw error(422,"invalid_page","分页参数无效。");}
            if(page<1||pageSize<1||pageSize>100)throw error(422,"invalid_page","分页参数无效。");
            String filter="site_id=?";var args=new ArrayList<Object>(List.of(c.site()));
            for(String field:List.of("warehouse_id","owner_id"))if(q.containsKey(field)){filter+=" AND "+field+"=?";args.add(ProductionService.positive(json.getNodeFactory().textNode(q.get(field)),field));}
            if(!q.getOrDefault("kind","").isEmpty()){filter+=" AND kind=?";args.add(q.get("kind"));}
            String state=q.getOrDefault("status","");
            if(!state.isEmpty()){filter+=switch(state){case "complete"->" AND status='POSTED'";case "draft"->" AND status='DRAFT'";case "cancelled"->" AND status IN ('REVERSED','VOID')";default->throw error(422,"invalid_status","记录状态无效。");};}
            for(String field:List.of("from","to"))if(!q.getOrDefault(field,"").isEmpty()){filter+=" AND business_date"+(field.equals("from")?">=":"<=")+"?";args.add(day(q.get(field)));}
            String search=q.getOrDefault("q","").trim();
            if(!search.isEmpty()){filter+=" AND (CAST(id AS CHAR) LIKE ? OR reason LIKE ? OR CAST(line_items AS CHAR) LIKE ?)";for(int i=0;i<3;i++)args.add("%"+search+"%");}
            long count=db.queryForObject("SELECT COUNT(*) FROM inventory_document WHERE "+filter,Long.class,args.toArray());
            args.add(pageSize);args.add((long)(page-1)*pageSize);
            var items=rows("SELECT * FROM inventory_document WHERE "+filter+" ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?",args.toArray());
            for(var item:items){item.put("lines",json.readTree(item.remove("line_items").toString()));item.remove("effects");}
            return Map.of("items",items,"total",count,"page",page,"page_size",pageSize);
        }
        String table=switch(resource){case "documents"->"inventory_document";case "loans"->"inventory_loan";case "plans"->"inventory_plan";case "reservations"->"inventory_reservation";case "holds"->"inventory_hold";default->throw error(404,"not_found","库存入口不存在。");};
        var scopedArgs=new ArrayList<Object>(List.of(c.site()));String scopedWhere="site_id=?";
        for(String field:List.of("warehouse_id","owner_id"))if(q.containsKey(field)){scopedWhere+=" AND "+field+"=?";scopedArgs.add(ProductionService.positive(json.getNodeFactory().textNode(q.get(field)),field));}
        var items=resource.equals("reservations")?rows("SELECT r.*,COALESCE(NULLIF(o.business_number,''),o.system_number) AS order_business_number FROM inventory_reservation r JOIN production_order_line l ON l.site_id=r.site_id AND l.id=r.order_line_id JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE r.site_id=? ORDER BY r.id DESC LIMIT 200",c.site()):rows("SELECT * FROM "+table+" WHERE "+scopedWhere+" ORDER BY id DESC LIMIT 200",scopedArgs.toArray());for(var item:items){if(resource.equals("documents")){item.put("lines",json.readTree(item.remove("line_items").toString()));item.remove("effects");}if(resource.equals("loans")){item.put("outstanding_units",Long.toString(n(item.get("borrowed_units"))-n(item.get("returned_units"))-n(item.get("settled_units"))));item.put("overdue",item.get("due_on")!=null&&day(item.get("due_on").toString()).isBefore(LocalDate.now())&&n(item.get("outstanding_units"))>0);}if(resource.equals("plans"))item.put("remaining_units",Long.toString(n(item.get("units"))-n(item.get("completed_units"))-n(item.get("cancelled_units"))));}return Map.of("items",items,"limit",200);
    }
    private Object forecast(ProductionContext c,Map<String,String> query){
        LocalDate horizon=day(query.getOrDefault("as_of",LocalDate.now().toString()));if(horizon.isBefore(LocalDate.now()))throw error(422,"forecast_date_invalid","预计库存只支持当前或未来日期；过去时点不能用当前余额冒充。");var result=new ArrayList<Object>();var excluded=new ArrayList<Object>();
        for(var b:rows("SELECT * FROM inventory_balance WHERE site_id=? ORDER BY warehouse_id,owner_id,sku_id",c.site())){
            Key k=new Key(n(b.get("warehouse_id")),n(b.get("owner_id")),n(b.get("sku_id")));var a=available(c.site(),k,"");BigInteger projected=new BigInteger(a.get("on_hand_units").toString());var included=new ArrayList<Object>();
            for(var p:rows("SELECT *,units-completed_units-cancelled_units AS remaining_units FROM inventory_plan WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=? AND units>completed_units+cancelled_units",c.site(),k.warehouse,k.owner,k.sku)){
                if(p.get("planned_on")==null||day(p.get("planned_on").toString()).isBefore(LocalDate.now())){excluded.add(p);continue;}if(day(p.get("planned_on").toString()).isAfter(horizon))continue;projected=projected.add(new BigInteger(p.get("remaining_units").toString()).multiply(p.get("direction").equals("IN")?BigInteger.ONE:BigInteger.ONE.negate()));included.add(p);
            }a.put("projected_on_hand_units",projected.toString());a.put("as_of",horizon.toString());a.put("plans",included);result.add(a);
        }return Map.of("items",result,"excluded_pending",excluded,"as_of",horizon.toString());
    }
    @Transactional(isolation=Isolation.READ_COMMITTED)
    public Object command(ProductionContext c,String path,JsonNode input,String key){
        c.requireWrite();if(!input.isObject())throw error(422,"invalid_command","命令必须是对象。");lockSite(c.site());
        if(path.equals("identity-rebindings")&&!c.roles().contains("admin"))throw error(403,"role_forbidden","身份衔接仅允许管理员执行。");
        if(path.startsWith("destination-receipts/") && path.endsWith("/preview")){
            String id=path.substring("destination-receipts/".length(),path.length()-"/preview".length());
            if(!id.matches("[1-9][0-9]{0,18}"))throw error(404,"not_found","接收操作不存在。");
            return new DestinationReceiptStore(db,json,this).get(c,Long.parseLong(id));
        }
        if(path.endsWith("/preview")){if(input.hasNonNull("warehouse_id"))ProductionDirectory.requireOperational(db,c.site(),positive(input,"warehouse_id"));return preview(c,path,input);}
        String token=text(input,"operation_token",36);try{if(!UUID.fromString(token).toString().equals(token)||UUID.fromString(token).version()!=4||!token.equals(key))throw new IllegalArgumentException();}catch(IllegalArgumentException e){throw error(422,"idempotency_key_mismatch","原操作ID与请求头必须一致。");}
        String fingerprint=hashValue(List.of("stock/"+path,canonical(input)));db.update("INSERT INTO production_command(site_id,actor_id,operation_token,fingerprint) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE operation_token=operation_token",c.site(),c.actor(),token,fingerprint);
        var receipt=rows("SELECT fingerprint,result FROM production_command WHERE site_id=? AND actor_id=? AND operation_token=?",c.site(),c.actor(),token).getFirst();if(!receipt.get("fingerprint").equals(fingerprint))throw error(409,"idempotency_content_conflict","同一操作ID不能提交不同内容。");if(receipt.get("result")!=null)return json.readTree(receipt.get("result").toString());
        Object result;
        if(input.hasNonNull("warehouse_id") && !path.startsWith("destination-receipts") && !path.startsWith("fba-"))ProductionDirectory.requireOperational(db,c.site(),positive(input,"warehouse_id"));
        if(path.startsWith("fba-")){
            if(!fbaEnabled)throw error(403,"fba_disabled","FBA库存适配尚未启用，原件和普通库存均未修改。");
            result=new FbaInventoryStore(db,json,this).command(c,path,input,token);
        }
        else if(path.equals("identity-rebindings")){
            if(!identityRebindingEnabled)throw error(403,"identity_rebinding_disabled","本地身份衔接尚未启用，未修改库存。");
            try{result=new InventoryIdentityRebinding(db,json,catalogAuthority).apply(c,input,token);}
            catch(org.springframework.dao.DataAccessException failure){
                if(failure.getMostSpecificCause() instanceof java.sql.SQLException sql)
                    org.slf4j.LoggerFactory.getLogger(InventoryService.class).warn("Identity rebind SQL failure: state={}, code={}, detail={}",sql.getSQLState(),sql.getErrorCode(),sql.getMessage());
                throw failure;
            }
        }
        else if(path.equals("transport-records"))result=new ShipmentTransportStore(db,json,this).saveRecord(c,null,input,token);
        else if(path.equals("transport-events"))result=new ShipmentTransportStore(db,json,this).saveEvent(c,null,input,token);
        else if(path.matches("transport-(records|events)/[1-9][0-9]*/correct")){
            String[] parts=path.split("/");long id=Long.parseLong(parts[1]);var transport=new ShipmentTransportStore(db,json,this);
            result=parts[0].equals("transport-records")?transport.saveRecord(c,id,input,token):transport.saveEvent(c,id,input,token);
        }
        else if(path.equals("destination-bindings"))result=new DestinationReceiptBindingStore(db,json).save(c,input);
        else if(path.equals("destination-uploads"))result=new DestinationReceiptFileStore(db).save(c,input);
        else if(path.equals("destination-receipts"))result=new DestinationReceiptStore(db,json,this).saveDraft(c,null,input,token);
        else if(path.equals("destination-settlements"))result=new DestinationReceiptStore(db,json,this).settle(c,input,token);
        else if(path.startsWith("destination-settlements/") && path.endsWith("/reverse")){
            String id=path.substring("destination-settlements/".length(),path.length()-"/reverse".length());
            if(!id.matches("[1-9][0-9]{0,18}"))throw error(404,"not_found","结案操作不存在。");
            result=new DestinationReceiptStore(db,json,this).reverseSettlement(c,Long.parseLong(id),input,token);
        }
        else if(path.startsWith("destination-receipts/")){
            String[] parts=path.split("/");if(parts.length!=3 || !parts[1].matches("[1-9][0-9]{0,18}"))throw error(404,"not_found","接收操作不存在。");
            long id=Long.parseLong(parts[1]);var store=new DestinationReceiptStore(db,json,this);
            result=switch(parts[2]){case "update"->store.saveDraft(c,id,input,token);case "confirm"->store.confirm(c,id,input,token);case "correct"->store.correct(c,id,input,token);case "reverse"->store.reverse(c,id,input,token);case "abandon"->store.abandon(c,id,input,token);default->throw error(404,"not_found","接收操作不存在。");};
        }
        else if(path.equals("display-settings"))result=new InventoryDisplaySettings(db,json,this).save(c,input,token);
        else if(path.equals("openings/confirm"))result=opening(c,input,token);
        else if(path.equals("documents"))result=createDocument(c,input,token);
        else if(path.startsWith("documents/"))result=changeDocument(c,path,input,token);
        else if(path.startsWith("reservations")||path.startsWith("holds"))result=occupancy(c,path,input,token);
        else if(path.startsWith("loans/"))result=changeLoan(c,path,input,token);
        else if(path.startsWith("plans"))result=plan(c,path,input,token);
        else throw error(404,"not_found","库存操作不存在。");
        db.update("UPDATE production_command SET result=? WHERE site_id=? AND actor_id=? AND operation_token=?",json.writeValueAsString(result),c.site(),c.actor(),token);return result;
    }
    private String reason(JsonNode b){String value=text(b,"reason",2000);if(value.isBlank())throw error(422,"reason_required","请填写来源、依据或更正原因。");return value;}
    private JsonNode validateWarehouseConvention(ProductionContext c,JsonNode b){
        reason(b);var metadata=realOpening.validate(c.site(),b);var k=key(b,0);var current=scope(c.site(),k);
        if(current==null)throw error(409,"opening_missing","该范围尚未登记期初，请先读取来源。");
        var prior=current.get("opening_metadata")==null?json.createObjectNode():json.readTree(current.get("opening_metadata").toString());
        if(RealOpeningSource.WAREHOUSE_BASIS.equals(prior.path("quantity_basis").asText()))throw error(409,"warehouse_convention_applied","该期初已采用正常可发口径，无需重复处理。");
        if(!current.get("source_reference").equals(text(b,"source_reference",255))||!prior.path("quality_state").asText().equals("UNASSESSED")||!prior.path("review_id").equals(metadata.path("review_id"))||!prior.path("review_revision").equals(metadata.path("review_revision")))throw error(409,"warehouse_convention_conflict","期初来源或口径已变化，请读取当前记录，不能覆盖。");
        for(var line:b.path("lines")){
            var balance=balance(c.site(),key(b,positive(line,"sku_id")));
            if(balance==null||n(balance.get("unassessed_units"))!=number(line,"units")||n(balance.get("qualified_units"))!=0||n(balance.get("pending_units"))!=0||n(balance.get("defective_units"))!=0)throw error(409,"warehouse_convention_conflict","已登记数量或货品状态发生变化，请按实际记录处理异常，不能覆盖原库存。");
        }
        return metadata;
    }
    private Object adoptWarehouseConvention(ProductionContext c,JsonNode b,String token,JsonNode metadata){
        var k=key(b,0);var current=scope(c.site(),k);String reason=reason(b),date=current.get("cutoff_on").toString();
        var beforeLines=json.createArrayNode();var afterLines=json.createArrayNode();var deltas=new ArrayList<Delta>();
        for(var line:b.path("lines")){
            long sku=positive(line,"sku_id"),amount=number(line,"units");
            var before=(ObjectNode)line.deepCopy();before.put("quality","UNASSESSED");before.put("purpose","QUALITY");beforeLines.add(before);
            var after=(ObjectNode)line.deepCopy();after.put("quality","QUALIFIED");after.put("purpose","QUALITY");afterLines.add(after);
            var stockKey=key(b,sku);deltas.add(new Delta(stockKey,"UNASSESSED",-amount,"",""));deltas.add(new Delta(stockKey,"QUALIFIED",amount,"",""));
        }
        var beforeValue=Map.of("warehouse_id",Long.toString(k.warehouse),"source_reference",current.get("source_reference"),"cutoff_on",date,"opening_metadata",json.readTree(current.get("opening_metadata").toString()),"lines",beforeLines,"revision","1");
        var saved=(ObjectNode)metadata.deepCopy();saved.put("convention_operation",token);saved.put("convention_revision","2");
        apply(c,deltas,"opening",k.warehouse,2,token,reason,date,false);
        db.update("UPDATE inventory_scope SET opening_metadata=? WHERE site_id=? AND warehouse_id=? AND owner_id=?",json.writeValueAsString(saved),c.site(),k.warehouse,k.owner);
        var result=Map.of("warehouse_id",Long.toString(k.warehouse),"owner_id",Long.toString(k.owner),"source_reference",current.get("source_reference"),"cutoff_on",date,"opening_metadata",saved,"lines",afterLines,"revision","2","quantity_effect","UNCHANGED");
        audit(c,"opening",k.warehouse,2,token,"WAREHOUSE_CONVENTION",reason,beforeValue,result);return result;
    }
    private long openingRevision(long site,long warehouse){return db.queryForObject("SELECT COALESCE(MAX(revision),0) FROM production_revision WHERE site_id=? AND document_kind='opening' AND document_id=?",Long.class,site,warehouse);}
    private JsonNode validateOpeningExtension(ProductionContext c,JsonNode b){
        if(!realOpening.enabled())throw error(403,"real_opening_disabled","补齐需要明确启用的仓库表来源。");
        reason(b);var k=key(b,0);var current=scope(c.site(),k);
        if(current==null)throw error(409,"opening_missing","该仓库尚无期初，请先读取来源。");
        var prior=current.get("opening_metadata")==null?json.createObjectNode():json.readTree(current.get("opening_metadata").toString());var metadata=realOpening.validate(c.site(),b,prior);
        if(positive(b,"expected_opening_revision")!=openingRevision(c.site(),k.warehouse))throw error(409,"opening_revision_conflict","期初登记范围已变化，请重新预览；本次未保存。");
        if(!current.get("cutoff_on").toString().equals(text(b,"cutoff_on",10)) || !current.get("source_reference").equals("REVIEW:"+prior.path("review_id").asText()+":"+prior.path("review_revision").asText()) && !prior.has("extension_operation"))throw error(409,"opening_extension_conflict","补齐必须沿用原盘点日期和仓库来源，不能再次入库。");
        var added=RealOpeningSource.additionalSkuIds(prior,metadata);var expected=new HashSet<Long>();
        for(var cell:prior.path("source_cells"))expected.add(Long.parseLong(cell.path("sku_id").asText()));
        var stored=new HashSet<Long>();for(var row:rows("SELECT sku_id FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=?",c.site(),k.warehouse,k.owner))stored.add(n(row.get("sku_id")));
        if(!expected.equals(stored)||!Collections.disjoint(added,stored))throw error(409,"opening_extension_conflict","现有库存范围与原期初不一致，请核对后再补齐，不能覆盖或重复登记。");
        return metadata;
    }
    private JsonNode validateOpeningSupersession(ProductionContext c,JsonNode b){
        if(!realOpening.enabled())throw error(403,"real_opening_disabled","更正版期初需要明确启用的新核对单来源。");
        reason(b);var k=key(b,0);var current=scope(c.site(),k);
        if(current==null)throw error(409,"opening_missing","该仓库尚无期初，不能接替来源。");
        var prior=current.get("opening_metadata")==null?json.createObjectNode():json.readTree(current.get("opening_metadata").toString());
        if(!prior.path("review_id").asText().equals(text(b,"replaces_review_id",36)) || !prior.path("review_revision").asText().equals(text(b,"replaces_review_revision",19)))throw error(409,"opening_supersession_conflict","更正版未明确引用当前期初来源；请重新读取后再操作。");
        if(positive(b,"expected_opening_revision")!=openingRevision(c.site(),k.warehouse))throw error(409,"opening_revision_conflict","期初登记范围已变化，请重新预览；本次未保存。");
        if(!current.get("cutoff_on").toString().equals(text(b,"cutoff_on",10)))throw error(409,"opening_supersession_conflict","更正版盘点日期与当前期初不一致；本次未修改库存。");
        var metadata=realOpening.validate(c.site(),b);var deltas=RealOpeningSource.supersedingDeltas(prior,metadata);
        var expected=new HashSet<Long>();for(var cell:prior.path("source_cells"))expected.add(Long.parseLong(cell.path("sku_id").asText()));
        var stored=new HashSet<Long>();for(var row:rows("SELECT sku_id FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=?",c.site(),k.warehouse,k.owner))stored.add(n(row.get("sku_id")));
        if(!expected.equals(stored))throw error(409,"opening_supersession_conflict","当前已登记规格与原期初来源不一致；请先核对库存范围。");
        String source=text(b,"source_reference",255);for(var row:rows("SELECT warehouse_id,owner_id FROM inventory_scope WHERE site_id=? AND source_reference=?",c.site(),source))if(n(row.get("warehouse_id"))!=k.warehouse || n(row.get("owner_id"))!=k.owner)throw error(409,"opening_source_used","这份更正版来源已用于其他库存范围，不能重复入账。");
        for(long sku:deltas.keySet())if(!expected.contains(sku) && stored.contains(sku))throw error(409,"opening_supersession_conflict","更正版新增规格已存在库存记录；本次未修改库存。");
        return metadata;
    }
    private Object extendOpening(ProductionContext c,JsonNode b,String token,JsonNode metadata){
        var k=key(b,0);var current=scope(c.site(),k);var prior=json.readTree(current.get("opening_metadata").toString());
        var added=RealOpeningSource.additionalSkuIds(prior,metadata);long next=openingRevision(c.site(),k.warehouse)+1;String why=reason(b),date=current.get("cutoff_on").toString();
        var lines=json.createArrayNode();long addedUnits=0;
        for(var line:b.path("lines"))if(added.contains(positive(line,"sku_id"))){
            long sku=positive(line,"sku_id"),units=number(line,"units");var item=identity(c.site(),b,sku);addedUnits=total(addedUnits,units);
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version,qualified_units) VALUES(?,?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,sku,item.path("label").asText(),item.path("catalog_version").asText(),units);
            event(c,new Delta(new Key(k.warehouse,k.owner,sku),"QUALIFIED",units,"",""),"opening",k.warehouse,next,token,why,date,null);
            var shown=(ObjectNode)line.deepCopy();shown.put("quality","QUALIFIED");shown.put("purpose","OPENING");lines.add(shown);
        }
        var saved=(ObjectNode)metadata.deepCopy();saved.put("extension_operation",token);saved.put("opening_revision",Long.toString(next));
        db.update("UPDATE inventory_scope SET opening_metadata=? WHERE site_id=? AND warehouse_id=? AND owner_id=?",json.writeValueAsString(saved),c.site(),k.warehouse,k.owner);
        var result=new LinkedHashMap<String,Object>(Map.of("warehouse_id",Long.toString(k.warehouse),"owner_id",Long.toString(k.owner),"source_reference",current.get("source_reference"),"cutoff_on",date,"revision",Long.toString(next),"opening_metadata",saved,"lines",lines,"added_units",Long.toString(addedUnits),"existing_stock_preserved",true));
        audit(c,"opening",k.warehouse,next,token,"OPENING_EXTEND",why,Map.of("opening_metadata",prior,"revision",Long.toString(next-1)),result);return result;
    }
    private Object supersedeOpening(ProductionContext c,JsonNode b,String token,JsonNode metadata){
        var k=key(b,0);var current=scope(c.site(),k);var prior=json.readTree(current.get("opening_metadata").toString());
        var deltas=new TreeMap<>(RealOpeningSource.supersedingDeltas(prior,metadata));long next=openingRevision(c.site(),k.warehouse)+1;String why=reason(b),date=current.get("cutoff_on").toString();
        var previousCells=new HashMap<Long,JsonNode>();for(var cell:prior.path("source_cells"))previousCells.put(Long.parseLong(cell.path("sku_id").asText()),cell);
        var currentCells=new HashMap<Long,JsonNode>();for(var cell:metadata.path("source_cells"))currentCells.put(Long.parseLong(cell.path("sku_id").asText()),cell);
        var inputLines=new HashMap<Long,JsonNode>();for(var line:b.path("lines"))inputLines.put(positive(line,"sku_id"),line);
        for(long sku:deltas.keySet())if(!previousCells.containsKey(sku)){
            var item=identity(c.site(),b,sku);db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,sku,item.path("label").asText(),item.path("catalog_version").asText());
        }
        var changes=new ArrayList<Delta>();var lines=json.createArrayNode();long net=0;int added=0,changed=0;
        for(var entry:deltas.entrySet()){
            long sku=entry.getKey(),delta=entry.getValue();net=total(net,delta);if(previousCells.containsKey(sku))changed++;else added++;
            changes.add(new Delta(new Key(k.warehouse,k.owner,sku),"QUALIFIED",delta,"",""));
            var shown=(ObjectNode)inputLines.get(sku).deepCopy();shown.put("quality","QUALIFIED");shown.put("purpose","OPENING_CORRECTION");shown.put("previous_units",previousCells.containsKey(sku)?previousCells.get(sku).path("units").asText():"0");shown.put("units",currentCells.get(sku).path("units").asText());shown.put("delta_units",Long.toString(delta));lines.add(shown);
        }
        apply(c,changes,"opening",k.warehouse,next,token,why,date,true);
        var saved=(ObjectNode)metadata.deepCopy();saved.put("supersedes_review_id",prior.path("review_id").asText());saved.put("supersedes_review_revision",prior.path("review_revision").asText());saved.put("superseded_source_reference",current.get("source_reference").toString());saved.put("supersession_operation",token);saved.put("opening_revision",Long.toString(next));
        String source=text(b,"source_reference",255);db.update("UPDATE inventory_scope SET source_reference=?,opening_metadata=? WHERE site_id=? AND warehouse_id=? AND owner_id=?",source,json.writeValueAsString(saved),c.site(),k.warehouse,k.owner);
        var result=new LinkedHashMap<String,Object>();result.put("warehouse_id",Long.toString(k.warehouse));result.put("owner_id",Long.toString(k.owner));result.put("source_reference",source);result.put("cutoff_on",date);result.put("revision",Long.toString(next));result.put("opening_metadata",saved);result.put("lines",lines);result.put("net_quantity_effect",Long.toString(net));result.put("changed_existing_skus",Integer.toString(changed));result.put("added_skus",Integer.toString(added));result.put("prior_opening_preserved",true);
        audit(c,"opening",k.warehouse,next,token,"OPENING_SUPERSEDE",why,Map.of("source_reference",current.get("source_reference"),"opening_metadata",prior,"revision",Long.toString(next-1)),result);return result;
    }
    private JsonNode validateOpening(ProductionContext c,JsonNode b){
        int actions=(b.path("extend_opening").asBoolean()?1:0)+(b.path("apply_warehouse_convention").asBoolean()?1:0)+(b.path("supersede_opening").asBoolean()?1:0);
        if(actions>1)throw error(422,"invalid_opening_action","补齐期初、口径调整与更正版接替只能选择一项。");
        if(b.path("supersede_opening").asBoolean())return validateOpeningSupersession(c,b);
        if(b.path("extend_opening").asBoolean())return validateOpeningExtension(c,b);
        if(b.path("apply_warehouse_convention").asBoolean())return validateWarehouseConvention(c,b);
        if(realOpening.enabled()){reason(b);var metadata=realOpening.validate(c.site(),b);if(scope(c.site(),key(b,0))!=null)throw error(409,"opening_exists","该仓库已有期初，不能重复启用。");if(!rows("SELECT warehouse_id FROM inventory_scope WHERE site_id=? AND source_reference=?",c.site(),text(b,"source_reference",255)).isEmpty())throw error(409,"opening_source_used","这份来源已经登记过期初，不能在其他仓库重复入账。");return metadata;}
        if(catalogAuthority.realCatalog())throw error(403,"real_opening_disabled","真实期初尚未启用，请保留资料核对结果。");
        Key k=key(b,0);if(k.owner!=1)throw error(422,"owner_scope_not_enabled","首批仅启用已明确公司自有货权的虚构范围。");if(scope(c.site(),k)!=null)throw error(409,"opening_exists","该范围已有期初，不能重复启用。");String source=text(b,"source_reference",255);if(!source.startsWith("FICTIONAL"))throw error(403,"real_opening_disabled","本轮仅允许标识明确的虚构期初。");day(text(b,"cutoff_on",10));reason(b);if(!b.path("lines").isArray()||b.path("lines").isEmpty()||b.path("lines").size()>500)throw error(422,"invalid_lines","期初需1至500行明确SKU和数量。");var seen=new HashSet<String>();for(var line:b.path("lines")){long sku=positive(line,"sku_id");identity(c.site(),b,sku);String quality=text(line,"quality",16);bucket(quality);number(line,"units");if(!seen.add(sku+":"+quality))throw error(422,"duplicate_opening","同SKU/质量的期初不能重复。");}return null;
    }
    private Object opening(ProductionContext c,JsonNode b,String token){var metadata=validateOpening(c,b);
        if(b.path("supersede_opening").asBoolean())return supersedeOpening(c,b,token,metadata);
        if(b.path("extend_opening").asBoolean())return extendOpening(c,b,token,metadata);
        if(b.path("apply_warehouse_convention").asBoolean())return adoptWarehouseConvention(c,b,token,metadata);
        Key scopeKey=key(b,0);if(scope(c.site(),scopeKey)!=null)throw error(409,"opening_exists","该范围已有期初；新增货物走入库或盘点调整，不能再次开仓。");
        String source=text(b,"source_reference",255),cutoff=text(b,"cutoff_on",10),reason=reason(b);if(metadata==null&&!source.startsWith("FICTIONAL"))throw error(403,"real_opening_disabled","本轮仅允许明确标识的虚构期初。");day(cutoff);if(!b.path("lines").isArray()||b.path("lines").isEmpty()||b.path("lines").size()>500)throw error(422,"invalid_lines","期初需1至500行明确SKU和数量。");
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token,opening_metadata) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),scopeKey.warehouse,scopeKey.owner,metadata==null?(text(b,"warehouse_name",120).isEmpty()?"虚构仓库"+scopeKey.warehouse:text(b,"warehouse_name",120)):metadata.path("warehouse_name").asText(),metadata==null?"公司自有（虚构）":"货主未登记（当前不区分）",day(cutoff),source,token,metadata==null?null:json.writeValueAsString(metadata));
        var seen=new HashSet<String>();for(JsonNode line:b.path("lines")){long sku=positive(line,"sku_id"),amount=number(line,"units");var identity=identity(c.site(),b,sku);String quality=metadata==null?text(line,"quality",16):"QUALIFIED";String column=bucket(quality);if(!seen.add(sku+":"+quality))throw error(422,"duplicate_opening","同SKU/质量的期初不能重复。");
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,?,?,?,?,?) ON DUPLICATE KEY UPDATE sku_id=sku_id",c.site(),scopeKey.warehouse,scopeKey.owner,sku,identity.path("label").asText(),identity.path("catalog_version").asText());db.update("UPDATE inventory_balance SET "+column+"=? WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",amount,c.site(),scopeKey.warehouse,scopeKey.owner,sku);event(c,new Delta(new Key(scopeKey.warehouse,scopeKey.owner,sku),quality,amount,"",""),"opening",scopeKey.warehouse,1,token,reason,cutoff,null);
        }var result=new LinkedHashMap<String,Object>(Map.of("warehouse_id",Long.toString(scopeKey.warehouse),"owner_id",Long.toString(scopeKey.owner),"source_reference",source,"cutoff_on",cutoff,"revision","1"));if(metadata!=null){result.put("opening_metadata",metadata);var historyLines=json.createArrayNode();for(var sourceLine:b.path("lines")){var historyLine=(tools.jackson.databind.node.ObjectNode)sourceLine.deepCopy();historyLine.put("quality","QUALIFIED");historyLine.put("purpose","OPENING");historyLines.add(historyLine);}result.put("lines",historyLines);}audit(c,"opening",scopeKey.warehouse,1,token,"OPENING",reason,null,result);return result;
    }
    private Object createDocument(ProductionContext c,JsonNode b,String token){
        productionSources(c.site(),text(b,"kind",8),b.path("lines"),true);
        String kind=text(b,"kind",8);if(!Set.of("IN","OUT","MOVE","ADJUST").contains(kind))throw error(422,"invalid_movement_kind","请选择四类变动之一。");String date=text(b,"business_date",10),why=reason(b);day(date);var lines=b.path("lines");if(!lines.isArray()||lines.isEmpty()||lines.size()>500)throw error(422,"invalid_lines","变动需要1至500行。");for(var line:lines)identity(c.site(),b,positive(line,"sku_id"));Key k=key(b,0);
        String system=text(b,"source_system",120),external=text(b,"external_event_id",120);String source=null;if(!system.isEmpty()||!external.isEmpty()){if(system.isBlank()||external.isBlank())throw error(422,"source_key_incomplete","来源系统和外部事件号需同时填写。");source=hashValue(List.of(system,external,kind));}
        String fingerprint=hashValue(List.of(kind,k.warehouse,k.owner,date,canonical(lines)));if(source!=null){var known=rows("SELECT id,source_fingerprint FROM inventory_document WHERE site_id=? AND source_key=?",c.site(),source);if(!known.isEmpty()){if(!known.getFirst().get("source_fingerprint").equals(fingerprint))throw error(409,"business_source_conflict","同一外部事件存在不同内容，请更正原单。");return document(c.site(),n(known.getFirst().get("id")));}}
        db.update("INSERT INTO inventory_document(site_id,warehouse_id,owner_id,kind,business_date,reason,line_items,source_key,source_fingerprint,actor_id,actor_name) VALUES(?,?,?,?,?,?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,kind,day(date),why,json.writeValueAsString(lines),source,fingerprint,c.actor(),c.actorName());long id=inserted();var result=document(c.site(),id);audit(c,"stock",id,1,token,"CREATE_DRAFT",why,null,result);return result;
    }
    Object postFbaCount(ProductionContext c, JsonNode body, String token) {
        var created = json.valueToTree(createDocument(c, body, token));
        long id = created.path("id").asLong();
        var doc = document(c.site(), id);
        var change = changes(c, doc, body);
        // A recorded count may expose a reservation shortage; it is not a dispatch.
        applyDeltas(c, change.deltas, "stock", id, 2, token,
            doc.get("reason").toString(), doc.get("business_date").toString(), false, true);
        saveEffects(c, doc, change, id);
        var result = document(c.site(), id);
        audit(c, "stock", id, 2, token, "POST", doc.get("reason").toString(), created, result);
        return result;
    }
    private record Changes(List<Delta> deltas,List<Map<String,Object>> loans,List<Map<String,Object>> returns,List<Map<String,Object>> plans,Map<Key,JsonNode> firstReceipts){}
    private Map<String,Object> zeroReceiptBalance(){
        return Map.of("qualified_units","0","pending_units","0","defective_units","0","unassessed_units","0","on_hand_units","0","free_available_units","0","held_units","0","reserved_units","0");
    }
    private void initializeFirstReceipts(ProductionContext c,Map<String,Object> doc,Changes change,long revision,String token){
        for(var entry:change.firstReceipts.entrySet()){
            Key k=entry.getKey();var identity=entry.getValue();
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,k.sku,identity.path("label").asText(),identity.path("catalog_version").asText());
            event(c,new Delta(k,"QUALIFIED",0,"",""),"stock",n(doc.get("id")),revision,token,doc.get("kind").equals("ADJUST")?"新规格按实盘首次建账，盘点前数量未知":"新规格首次入库，原库存默认为0",doc.get("business_date").toString(),null);
        }
    }
    private Changes changes(ProductionContext c,Map<String,Object> doc,JsonNode b){
        productionSources(c.site(),doc.get("kind").toString(),json.valueToTree(doc.get("lines")),true);
        var deltas=new ArrayList<Delta>();var loans=new ArrayList<Map<String,Object>>();var returns=new ArrayList<Map<String,Object>>();var plans=new ArrayList<Map<String,Object>>();var firstReceipts=new TreeMap<Key,JsonNode>();JsonNode lines=json.valueToTree(doc.get("lines"));int index=0;
        for(var line:lines){long sku=positive(line,"sku_id");var identity=identity(c.site(),b,sku);Key k=new Key(n(doc.get("warehouse_id")),n(doc.get("owner_id")),sku);checkDate(c.site(),k,doc.get("business_date").toString());balanceRevision(c.site(),k,line);String quality=text(line,"quality",16),purpose=text(line,"purpose",32);bucket(quality);text(line,"counterparty",255);long amount=doc.get("kind").equals("ADJUST")?number(line,"units"):positive(line,"units");var bal=balance(c.site(),k);
            if(bal==null){
                boolean firstCount=doc.get("kind").equals("ADJUST")&&purpose.equals("COUNT");
                if(!firstCount&&(!doc.get("kind").equals("IN")||!Set.of("RECEIPT","PRODUCTION_RECEIPT","OTHER").contains(purpose)))throw error(409,"inventory_not_ready","该SKU期初尚未就绪。");
                ProductionDirectory.requireOperational(db,c.site(),k.warehouse);
                if(!firstReceipts.containsKey(k)&&!rows("SELECT id FROM inventory_event WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=? LIMIT 1",c.site(),k.warehouse,k.owner,k.sku).isEmpty())throw error(409,"inventory_not_ready","该规格已有库存历史但余额缺失，请核对库存记录后再入库。");
                firstReceipts.put(k,identity);bal=zeroReceiptBalance();
            }
            if(doc.get("_prior_inverse") instanceof List<?> undo){bal=new LinkedHashMap<>(bal);for(Object item:undo){Delta d=(Delta)item;if(d.key.equals(k))bal.put(bucket(d.quality),Long.toString(total(n(bal.get(bucket(d.quality))),d.units)));}}
            switch(doc.get("kind").toString()){
                case "IN"->{if(!Set.of("RECEIPT","PRODUCTION_RECEIPT","RETURN","OTHER","SALES_RETURN").contains(purpose))throw error(422,"invalid_purpose","入库用途无效。");deltas.add(new Delta(k,quality,amount,"",text(line,"location_to",120)));if(purpose.equals("RETURN")){long loan=positive(line,"loan_id");var l=entity(c.site(),"inventory_loan",loan);if(!Boolean.parseBoolean(l.get("is_active").toString())||n(l.get("sku_id"))!=sku||n(l.get("warehouse_id"))!=k.warehouse||n(l.get("owner_id"))!=k.owner)throw error(409,"loan_scope_invalid","归还必须关联同SKU/仓库/货权的有效借出。");long outstanding=n(l.get("borrowed_units"))-n(l.get("returned_units"))-n(l.get("settled_units"))+credit(doc,"returns",loan);long earlier=returns.stream().filter(v->n(v.get("id"))==loan).mapToLong(v->n(v.get("units"))).reduce(0,InventoryService::total);if(total(earlier,amount)>outstanding)throw error(422,"return_exceeds_outstanding","归还总量超过原借出未还量。");returns.add(Map.of("id",loan,"units",amount));}}
                case "OUT"->{if(!Set.of("BORROW","CONSUME","TAKE","GIFT","SCRAP","RETURN_SUPPLIER").contains(purpose))throw error(422,"invalid_purpose","订单发货请从实际出货页登记，不能另建一笔销售出库。");if(!quality.equals("QUALIFIED")&&!Set.of("SCRAP","RETURN_SUPPLIER").contains(purpose))throw error(422,"quality_not_dispatchable","待检和次品只允许对应报废/退供用途。");deltas.add(new Delta(k,quality,-amount,text(line,"location_from",120),""));if(purpose.equals("BORROW")){String borrower=text(line,"borrower",255);if(borrower.isBlank())throw error(422,"borrower_required","借出需记录实际借用人/对象。");String due=text(line,"due_on",10);if(!due.isEmpty())day(due);var loan=new LinkedHashMap<String,Object>(Map.of("index",index,"sku",sku,"units",amount,"borrower",borrower,"purpose",text(line,"borrow_purpose",255)));loan.put("due_on",due.isEmpty()?null:due);loans.add(loan);}}
                case "MOVE"->{if(amount>n(bal.get(bucket(quality))))throw error(409,"insufficient_available_stock","内部变更量超过来源状态的实际在库。");String target=text(line,"target_quality",16);bucket(target);String from=text(line,"location_from",120),to=text(line,"location_to",120);if(line.hasNonNull("target_warehouse_id")&&positive(line,"target_warehouse_id")!=k.warehouse)throw error(422,"cross_warehouse_transfer_not_enabled","跨仓运输需分别发出/到达，本期仅同仓质量/库位变更。");if(target.equals(quality)&&(from.isBlank()||to.isBlank()||from.equals(to)))throw error(422,"location_change_required","同质量变更需明确不同的来源和目标库位。");deltas.add(new Delta(k,quality,-amount,from,to));deltas.add(new Delta(k,target,amount,from,to));}
                case "ADJUST"->{if(!purpose.equals("COUNT")||text(line,"evidence",2000).isBlank()||text(line,"counted_on",10).isEmpty())throw error(422,"stocktake_evidence_required","盘点调整需实盘截止、实盘数量与证据。");LocalDate counted=day(text(line,"counted_on",10));var latest=rows("SELECT MAX(business_date) AS latest_on FROM inventory_event WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",c.site(),k.warehouse,k.owner,k.sku).getFirst().get("latest_on");if(!counted.equals(day(doc.get("business_date").toString()))||latest!=null&&counted.isBefore(day(latest.toString())))throw error(409,"stocktake_cutoff_stale","旧盘点不能覆盖之后的收发事实；请核对同一实际截止日期的当前实盘或补录原事件。");long adjustment=amount-n(bal.get(bucket(quality)));if(doc.get("_prior_lines")!=null){for(var previous:json.valueToTree(doc.get("_prior_lines")))if(previous.path("sku_id").asText().equals(Long.toString(sku))&&previous.path("quality").asText().equals(quality)){long oldInverse=0;for(Object item:(List<?>)doc.get("_prior_inverse")){Delta d=(Delta)item;if(d.key.equals(k)&&d.quality.equals(quality))oldInverse=total(oldInverse,d.units);}adjustment=-oldInverse+amount-number(previous,"units");}}deltas.add(new Delta(k,quality,adjustment,"",""));}
            }
            if(line.hasNonNull("plan_id")){long id=positive(line,"plan_id");var p=entity(c.site(),"inventory_plan",id);String direction=doc.get("kind").equals("IN")?"IN":doc.get("kind").equals("OUT")?"OUT":"";if(!p.get("direction").equals(direction)||n(p.get("sku_id"))!=sku||n(p.get("warehouse_id"))!=k.warehouse||n(p.get("owner_id"))!=k.owner||p.get("loan_id")!=null)throw error(409,"plan_scope_invalid","计划必须对应同方向、仓库/货权/SKU；借还安排由原借出自动结算。");long earlier=plans.stream().filter(v->n(v.get("id"))==id).mapToLong(v->n(v.get("units"))).reduce(0,InventoryService::total);if(total(earlier,amount)>n(p.get("units"))-n(p.get("completed_units"))-n(p.get("cancelled_units"))+credit(doc,"plans",id))throw error(422,"plan_completion_exceeded","实际完成量超过计划剩余数。");plans.add(Map.of("id",id,"units",amount));}index++;
        }return new Changes(deltas,loans,returns,plans,firstReceipts);
    }
    private long historicalSku(long sku){
        if(sku<900_000_000_000L)return sku;
        String database=db.queryForObject("SELECT DATABASE()",String.class);
        if(!Set.of("clsen_orders_b_v1_1_0_test","clsen_orders_production_backup_b_v1_1_0_20261017").contains(database))return sku;
        var mapped=rows("SELECT target_sku_id FROM production_backup_sku_crosswalk WHERE old_sku_id=? AND status='MAPPED'",sku-900_000_000_000L);
        return mapped.size()==1?n(mapped.getFirst().get("target_sku_id")):sku;
    }
    private List<Delta> inverse(ProductionContext c,long id){
        var combined=new TreeMap<Key,Map<String,Long>>();
        for(var e:rows("SELECT warehouse_id,owner_id,sku_id,quality,SUM(delta_units) AS delta_units FROM inventory_event WHERE site_id=? AND document_kind='stock' AND document_id=? GROUP BY warehouse_id,owner_id,sku_id,quality",c.site(),id))
            combined.computeIfAbsent(new Key(n(e.get("warehouse_id")),n(e.get("owner_id")),historicalSku(n(e.get("sku_id")))),k->new TreeMap<>()).merge(e.get("quality").toString(),-n(e.get("delta_units")),InventoryService::total);
        var result=new ArrayList<Delta>();for(var entry:combined.entrySet())for(var quality:entry.getValue().entrySet())result.add(new Delta(entry.getKey(),quality.getKey(),quality.getValue(),"",""));return result;
    }
    private void correctionDependencies(ProductionContext c,long id){for(var loan:rows("SELECT * FROM inventory_loan WHERE site_id=? AND document_id=? AND is_active=TRUE",c.site(),id))if(n(loan.get("returned_units"))+n(loan.get("settled_units"))>0)throw error(409,"downstream_loan_exists","已有归还或结清，先核对下游；不能抹去借还事实。");}
    private Map<String,Object> correctionCandidate(Map<String,Object> doc,JsonNode input,List<Delta> inverse){if(!input.path("lines").isArray()||input.path("lines").isEmpty()||input.path("lines").size()>500)throw error(422,"invalid_lines","更正需明确完整明细。");var value=new LinkedHashMap<>(doc);value.put("lines",input.path("lines"));value.put("business_date",input.hasNonNull("business_date")?day(text(input,"business_date",10)).toString():doc.get("business_date"));value.put("reason",reason(input));value.put("_prior_inverse",inverse);value.put("_prior_lines",doc.get("lines"));value.put("_reverse_effects",doc.get("effects")==null?json.createObjectNode():json.readTree(doc.get("effects").toString()));return value;}
    private long credit(Map<String,Object> doc,String relation,long id){long total=0;JsonNode effects=doc.get("_reverse_effects")==null?json.createObjectNode():(JsonNode)doc.get("_reverse_effects");for(var e:effects.path(relation))if(e.path("id").asLong()==id)total=total(total,e.path("units").asLong());return total;}
    private Object preview(ProductionContext c,String path,JsonNode input){
        if(path.equals("openings/preview")){var metadata=validateOpening(c,input);var previewLines=input.path("lines").deepCopy();if(metadata!=null)for(var line:previewLines)((ObjectNode)line).put("quality","QUALIFIED");var result=new LinkedHashMap<String,Object>(Map.of("source_reference",text(input,"source_reference",255),"lines",previewLines,"posting_enabled",authorityMode.equals("demo_fixed")||authorityMode.equals("qa_catalog")||catalogAuthority.enabled()));if(metadata!=null)result.put("opening_metadata",metadata);return result;}
        String[] parts=path.split("/");if(parts.length!=3||!parts[0].equals("documents"))throw error(404,"not_found","预览不存在。");var doc=document(c.site(),Long.parseLong(parts[1]));revision(doc,input);List<Delta> reversed=List.of();if(doc.get("status").equals("POSTED")&&input.path("mode").asText().equals("correct")){correctionDependencies(c,n(doc.get("id")));reversed=inverse(c,n(doc.get("id")));doc=correctionCandidate(doc,input,reversed);}else if(!doc.get("status").equals("DRAFT"))throw error(409,"invalid_state","已过账请预览更正。");var change=changes(c,doc,input);var net=new ArrayList<Delta>(reversed);net.addAll(change.deltas);validateDeltas(c,net,!permitsObservedLoss(doc),change.firstReceipts.keySet());
        var summed=new TreeMap<Key,Map<String,Long>>();for(var d:net)summed.computeIfAbsent(d.key,k->new TreeMap<>()).merge(d.quality,d.units,InventoryService::total);var shown=new ArrayList<Map<String,String>>();for(var entry:summed.entrySet())for(var quality:entry.getValue().entrySet())shown.add(Map.of("sku_id",Long.toString(entry.getKey().sku),"quality",quality.getKey(),"delta_units",Long.toString(quality.getValue())));
        var impacts=new ArrayList<Map<String,Object>>();
        for(var entry:summed.entrySet()) {
            Key k=entry.getKey();var before=change.firstReceipts.containsKey(k)?zeroReceiptBalance():available(c.site(),k,"");
            BigInteger delta=BigInteger.ZERO;for(long amount:entry.getValue().values())delta=delta.add(BigInteger.valueOf(amount));
            long qualified=total(n(before.get("qualified_units")),entry.getValue().getOrDefault("QUALIFIED",0L));
            long occupied=total(n(before.get("held_units")),n(before.get("reserved_units")));
            var impact=new LinkedHashMap<String,Object>();impact.put("warehouse_id",Long.toString(k.warehouse));impact.put("sku_id",Long.toString(k.sku));
            impact.put("on_hand_before",before.get("on_hand_units"));impact.put("on_hand_after",new BigInteger(before.get("on_hand_units").toString()).add(delta).toString());
            impact.put("free_before",before.get("free_available_units"));impact.put("free_after",qualified<occupied?null:Long.toString(qualified-occupied));impacts.add(impact);
        }
        return Map.of("id",doc.get("id"),"expected_revision",doc.get("revision"),"changes",shown,"impacts",impacts,"production_sources",productionSources(c.site(),doc.get("kind").toString(),json.valueToTree(doc.get("lines")),false),"preview_hash",previewHash(c,doc,change));
    }
    private String previewHash(ProductionContext c,Map<String,Object> doc,Changes change){
        var versions=new TreeMap<Key,Object>();for(var d:change.deltas)versions.put(d.key,available(c.site(),d.key,""));if(doc.get("_prior_inverse") instanceof List<?> inverse)for(var item:inverse){Delta d=(Delta)item;versions.put(d.key,available(c.site(),d.key,""));}
        var loans=new TreeSet<Long>();var plans=new TreeSet<Long>();for(var loan:rows("SELECT id FROM inventory_loan WHERE site_id=? AND document_id=? AND is_active=TRUE",c.site(),doc.get("id")))loans.add(n(loan.get("id")));for(var r:change.returns)loans.add(n(r.get("id")));for(var p:change.plans)plans.add(n(p.get("id")));
        JsonNode old=doc.get("_reverse_effects")==null?json.createObjectNode():(JsonNode)doc.get("_reverse_effects");for(var r:old.path("returns"))loans.add(r.path("id").asLong());for(var p:old.path("plans"))plans.add(p.path("id").asLong());
        var relations=new TreeMap<String,Object>();for(long id:loans){relations.put("loan:"+id,entity(c.site(),"inventory_loan",id));relations.put("loan-plan:"+id,rows("SELECT * FROM inventory_plan WHERE site_id=? AND loan_id=?",c.site(),id));}for(long id:plans)relations.put("plan:"+id,entity(c.site(),"inventory_plan",id));
        return hashValue(List.of(doc,change.deltas.toString(),versions.values(),relations,productionSources(c.site(),doc.get("kind").toString(),json.valueToTree(doc.get("lines")),false)));
    }
    private boolean permitsObservedLoss(Map<String,Object> doc){if(doc.get("kind").equals("ADJUST"))return true;if(!doc.get("kind").equals("MOVE"))return false;for(var line:json.valueToTree(doc.get("lines")))if(!line.path("purpose").asText().equals("DAMAGE")||line.path("evidence").asText().isBlank())return false;return true;}
    private void validateDeltas(ProductionContext c,List<Delta> deltas,boolean checkFree,Set<Key> firstReceipts){var net=new TreeMap<Key,Map<String,Long>>();for(var d:deltas)net.computeIfAbsent(d.key,k->new TreeMap<>()).merge(d.quality,d.units,InventoryService::total);for(var e:net.entrySet()){var b=firstReceipts.contains(e.getKey())?zeroReceiptBalance():balance(c.site(),e.getKey());for(var v:e.getValue().entrySet()){if(total(n(b.get(bucket(v.getKey()))),v.getValue())<0)throw error(409,"insufficient_available_stock","当前实物不足。");if(checkFree&&v.getKey().equals("QUALIFIED")&&v.getValue()<0)ensureFree(c.site(),e.getKey(),-v.getValue(),0);}}}
    private Object changeDocument(ProductionContext c,String path,JsonNode input,String token){
        String[] parts=path.split("/");if(parts.length!=3)throw error(404,"not_found","库存操作不存在。");long id=Long.parseLong(parts[1]);String action=parts[2];var doc=document(c.site(),id);revision(doc,input);var before=new LinkedHashMap<>(doc);long next=n(doc.get("revision"))+1;
        if(action.equals("update")){if(!doc.get("status").equals("DRAFT"))throw error(409,"correction_required","已过账请使用更正。");if(!input.path("lines").isArray()||input.path("lines").isEmpty()||input.path("lines").size()>500)throw error(422,"invalid_lines","需填写有效明细。");productionSources(c.site(),doc.get("kind").toString(),input.path("lines"),true);db.update("UPDATE inventory_document SET line_items=?,business_date=?,reason=?,revision=revision+1 WHERE site_id=? AND id=?",json.writeValueAsString(input.path("lines")),day(text(input,"business_date",10)),reason(input),c.site(),id);}
        else if(action.equals("confirm")){
            if(!doc.get("status").equals("DRAFT"))throw error(409,"invalid_state","只有草稿可以确认过账。");var change=changes(c,doc,input);if(input.hasNonNull("preview_hash")&&!text(input,"preview_hash",64).equals(previewHash(c,doc,change)))throw error(409,"inventory_revision_conflict","库存或占用在预览后已变化，请重新预览。");initializeFirstReceipts(c,doc,change,next,token);apply(c,change.deltas,"stock",id,next,token,doc.get("reason").toString(),doc.get("business_date").toString(),!permitsObservedLoss(doc));
            saveEffects(c,doc,change,id);
        } else if(action.equals("reverse")||action.equals("correct")){
            if(!doc.get("status").equals("POSTED"))throw error(409,"invalid_state","只有已过账单据可更正或冲销。");String why=reason(input);
            correctionDependencies(c,id);var reversed=inverse(c,id);Map<String,Object> candidate=null;Changes replacement=null;
            if(action.equals("correct")){candidate=correctionCandidate(doc,input,reversed);replacement=changes(c,candidate,input);if(input.hasNonNull("preview_hash")&&!text(input,"preview_hash",64).equals(previewHash(c,candidate,replacement)))throw error(409,"inventory_revision_conflict","库存/关联在更正预览后已变化，请重新预览。");}
            for(var loan:rows("SELECT id FROM inventory_loan WHERE site_id=? AND document_id=? AND is_active=TRUE",c.site(),id)){db.update("UPDATE inventory_plan SET cancelled_units=units-completed_units,revision=revision+1 WHERE site_id=? AND loan_id=?",c.site(),loan.get("id"));db.update("UPDATE inventory_loan SET is_active=FALSE,revision=revision+1 WHERE site_id=? AND id=?",c.site(),loan.get("id"));}
            var effects=doc.get("effects")==null?json.createObjectNode():json.readTree(doc.get("effects").toString());for(var r:effects.path("returns")){var l=entity(c.site(),"inventory_loan",r.path("id").asLong());if(n(l.get("returned_units"))<r.path("units").asLong())throw error(409,"downstream_loan_exists","归还关系已变更，不能逆转。");db.update("UPDATE inventory_loan SET returned_units=returned_units-?,revision=revision+1 WHERE site_id=? AND id=?",r.path("units").asLong(),c.site(),r.path("id").asLong());db.update("UPDATE inventory_plan SET completed_units=completed_units-?,revision=revision+1 WHERE site_id=? AND loan_id=?",r.path("units").asLong(),c.site(),r.path("id").asLong());}
            for(var p:effects.path("plans"))db.update("UPDATE inventory_plan SET completed_units=completed_units-?,revision=revision+1 WHERE site_id=? AND id=?",p.path("units").asLong(),c.site(),p.path("id").asLong());
            if(action.equals("correct")){
                initializeFirstReceipts(c,candidate,replacement,next,token);var combined=new ArrayList<Delta>(reversed);combined.addAll(replacement.deltas);apply(c,combined,"stock",id,next,token,why,candidate.get("business_date").toString(),!permitsObservedLoss(candidate));
                db.update("UPDATE inventory_document SET line_items=?,reason=?,business_date=? WHERE site_id=? AND id=?",json.writeValueAsString(input.path("lines")),why,day(candidate.get("business_date").toString()),c.site(),id);saveEffects(c,candidate,replacement,id);
            }else{apply(c,reversed,"stock",id,next,token,why,doc.get("business_date").toString(),true);db.update("UPDATE inventory_document SET status='REVERSED',reason=?,revision=revision+1 WHERE site_id=? AND id=?",why,c.site(),id);}

        } else throw error(404,"not_found","库存操作不存在。");
        var result=document(c.site(),id);audit(c,"stock",id,next,token,action.toUpperCase(Locale.ROOT),action.equals("confirm")?doc.get("reason").toString():reason(input),before,result);return result;
    }

    private void saveEffects(ProductionContext c,Map<String,Object> doc,Changes change,long id){
            for(var loan:change.loans){db.update("INSERT INTO inventory_loan(site_id,document_id,line_index,warehouse_id,owner_id,sku_id,borrower,purpose,due_on,borrowed_units) VALUES(?,?,?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE sku_id=VALUES(sku_id),borrower=VALUES(borrower),purpose=VALUES(purpose),due_on=VALUES(due_on),borrowed_units=VALUES(borrowed_units),is_active=TRUE,revision=revision+1",c.site(),id,loan.get("index"),doc.get("warehouse_id"),doc.get("owner_id"),loan.get("sku"),loan.get("borrower"),loan.get("purpose"),loan.get("due_on"),loan.get("units"));long loanId=db.queryForObject("SELECT id FROM inventory_loan WHERE site_id=? AND document_id=? AND line_index=?",Long.class,c.site(),id,loan.get("index"));db.update("INSERT INTO inventory_plan(site_id,warehouse_id,owner_id,sku_id,direction,planned_on,units,source_reference,loan_id) VALUES(?,?,?,?,'IN',?,?,?,?) ON DUPLICATE KEY UPDATE sku_id=VALUES(sku_id),planned_on=VALUES(planned_on),units=VALUES(units),cancelled_units=0,revision=revision+1",c.site(),doc.get("warehouse_id"),doc.get("owner_id"),loan.get("sku"),loan.get("due_on"),loan.get("units"),"借出"+loanId,loanId);}
            for(var r:change.returns){db.update("UPDATE inventory_loan SET returned_units=returned_units+?,revision=revision+1 WHERE site_id=? AND id=?",r.get("units"),c.site(),r.get("id"));db.update("UPDATE inventory_plan SET completed_units=completed_units+?,revision=revision+1 WHERE site_id=? AND loan_id=?",r.get("units"),c.site(),r.get("id"));}
            for(var p:change.plans)db.update("UPDATE inventory_plan SET completed_units=completed_units+?,revision=revision+1 WHERE site_id=? AND id=?",p.get("units"),c.site(),p.get("id"));
            db.update("UPDATE inventory_document SET status='POSTED',effects=?,revision=revision+1 WHERE site_id=? AND id=?",json.writeValueAsString(Map.of("returns",change.returns,"plans",change.plans)),c.site(),id);
    }
    private Object occupancy(ProductionContext c,String path,JsonNode b,String token){
        boolean reserve=path.startsWith("reservations");String table=reserve?"inventory_reservation":"inventory_hold",kind=reserve?"reservation":"hold";String[] parts=path.split("/");String why=reason(b);
        if(parts.length==1){long sku=positive(b,"sku_id"),units=positive(b,"units");identity(c.site(),b,sku);Key k=key(b,sku);balanceRevision(c.site(),k,b);ensureFree(c.site(),k,units,0);
            if(reserve){long line=positive(b,"order_line_id");requireOrderLine(c.site(),line,sku);db.update("INSERT INTO inventory_reservation(site_id,warehouse_id,owner_id,sku_id,order_line_id,units,reason) VALUES(?,?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,k.sku,line,units,why);}else db.update("INSERT INTO inventory_hold(site_id,warehouse_id,owner_id,sku_id,units,reason) VALUES(?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,k.sku,units,why);
            long id=inserted();touch(c.site(),k);var after=entity(c.site(),table,id);audit(c,kind,id,1,token,reserve?"RESERVE":"FREEZE",why,null,after);return after;
        }if(parts.length!=3||!parts[2].equals("release"))throw error(404,"not_found","占用操作不存在。");long id=Long.parseLong(parts[1]);var before=entity(c.site(),table,id);revision(before,b);long remaining=n(before.get("units"))-n(before.get("released_units"))-(reserve?n(before.get("consumed_units")):0);long amount=b.hasNonNull("units")?positive(b,"units"):remaining;if(amount<=0||amount>remaining)throw error(422,"release_exceeds_remaining","释放量超过剩余占用。");db.update("UPDATE "+table+" SET released_units=released_units+?,revision=revision+1 WHERE site_id=? AND id=?",amount,c.site(),id);touch(c.site(),new Key(n(before.get("warehouse_id")),n(before.get("owner_id")),n(before.get("sku_id"))));var after=entity(c.site(),table,id);audit(c,kind,id,n(after.get("revision")),token,reserve?"RELEASE":"UNFREEZE",why,before,after);return after;
    }
    private void requireOrderLine(long site,long line,long sku){var r=rows("SELECT l.*,o.status FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE l.site_id=? AND l.id=?",site,line);if(r.isEmpty()||n(r.getFirst().get("sku_id"))!=sku||!Boolean.parseBoolean(r.getFirst().get("is_active").toString())||!r.getFirst().get("status").equals("CONFIRMED")||r.getFirst().get("tracking_state").equals("CLOSED"))throw error(409,"order_link_invalid","预留须关联本站点已确认、同SKU且正在跟进的订单行。");}
    private Object changeLoan(ProductionContext c,String path,JsonNode b,String token){String[] p=path.split("/");if(p.length!=3||!Set.of("settle","reschedule").contains(p[2]))throw error(404,"not_found","借还操作不存在。");long id=Long.parseLong(p[1]);var before=entity(c.site(),"inventory_loan",id);revision(before,b);if(!Boolean.parseBoolean(before.get("is_active").toString()))throw error(409,"invalid_state","原借出已冲销。");String why=reason(b);if(p[2].equals("settle")){long amount=positive(b,"units"),outstanding=n(before.get("borrowed_units"))-n(before.get("returned_units"))-n(before.get("settled_units"));if(amount>outstanding)throw error(422,"return_exceeds_outstanding","结清不能超过未还量。");db.update("UPDATE inventory_loan SET settled_units=settled_units+?,revision=revision+1 WHERE site_id=? AND id=?",amount,c.site(),id);db.update("UPDATE inventory_plan SET cancelled_units=cancelled_units+?,revision=revision+1 WHERE site_id=? AND loan_id=?",amount,c.site(),id);}else{String due=text(b,"due_on",10);if(!due.isEmpty())day(due);db.update("UPDATE inventory_loan SET due_on=?,revision=revision+1 WHERE site_id=? AND id=?",due.isEmpty()?null:due,c.site(),id);db.update("UPDATE inventory_plan SET planned_on=?,revision=revision+1 WHERE site_id=? AND loan_id=?",due.isEmpty()?null:due,c.site(),id);}var after=entity(c.site(),"inventory_loan",id);audit(c,"loan",id,n(after.get("revision")),token,p[2].toUpperCase(Locale.ROOT),why,before,after);return after;}
    private Object plan(ProductionContext c,String path,JsonNode b,String token){String why=reason(b);if(path.equals("plans")){long sku=positive(b,"sku_id");identity(c.site(),b,sku);Key k=key(b,sku);if(balance(c.site(),k)==null)throw error(409,"inventory_not_ready","计划范围尚未完成期初。");String direction=text(b,"direction",3),on=text(b,"planned_on",10),source=text(b,"source_reference",255);if(!Set.of("IN","OUT").contains(direction)||source.isBlank())throw error(422,"plan_source_required","安排需要收发方向及来源依据。");if(!on.isEmpty())day(on);db.update("INSERT INTO inventory_plan(site_id,warehouse_id,owner_id,sku_id,direction,planned_on,units,source_reference) VALUES(?,?,?,?,?,?,?,?)",c.site(),k.warehouse,k.owner,sku,direction,on.isEmpty()?null:on,positive(b,"units"),source);long id=inserted();var after=entity(c.site(),"inventory_plan",id);audit(c,"plan",id,1,token,"PLAN",why,null,after);return after;}
        String[] p=path.split("/");if(p.length!=3||!Set.of("cancel","update").contains(p[2]))throw error(404,"not_found","安排操作不存在。");long id=Long.parseLong(p[1]);var before=entity(c.site(),"inventory_plan",id);revision(before,b);if(before.get("loan_id")!=null)throw error(409,"loan_plan_managed","借还安排从借出记录更改日期或结清，不能重复取消。");if(p[2].equals("cancel")){long remaining=n(before.get("units"))-n(before.get("completed_units"))-n(before.get("cancelled_units"));long amount=b.hasNonNull("units")?positive(b,"units"):remaining;if(amount<=0||amount>remaining)throw error(422,"plan_cancel_exceeded","取消量超过剩余安排。");db.update("UPDATE inventory_plan SET cancelled_units=cancelled_units+?,revision=revision+1 WHERE site_id=? AND id=?",amount,c.site(),id);}else{String on=text(b,"planned_on",10);if(!on.isEmpty())day(on);long units=positive(b,"units");if(units<n(before.get("completed_units"))+n(before.get("cancelled_units")))throw error(422,"plan_completion_exceeded","不能减少已完成或已取消事实。");db.update("UPDATE inventory_plan SET units=?,planned_on=?,revision=revision+1 WHERE site_id=? AND id=?",units,on.isEmpty()?null:on,c.site(),id);}var after=entity(c.site(),"inventory_plan",id);audit(c,"plan",id,n(after.get("revision")),token,p[2].toUpperCase(Locale.ROOT),why,before,after);return after;
    }
    /** Called only inside ProductionService.command's transaction and site lock. */
    private boolean warehouseSource(JsonNode source){return !source.hasNonNull("fulfillment_mode")||source.path("fulfillment_mode").asText().equals("WAREHOUSE_STOCK");}
    void shipment(ProductionContext c,long id,boolean oldConfirmed,Map<String,Object> old,Map<String,Object> now,String token,String reason){
        var scopeRows=rows("SELECT * FROM inventory_scope WHERE site_id=? ORDER BY warehouse_id,owner_id",c.site());boolean tracked=Boolean.parseBoolean(now.get("stock_tracked").toString());JsonNode sources=json.valueToTree(now.get("sources"));JsonNode oldSources=oldConfirmed?json.valueToTree(old.get("sources")):json.createArrayNode();boolean active=now.get("status").equals("CONFIRMED");boolean hasWarehouse=active&&java.util.stream.StreamSupport.stream(sources.spliterator(),false).anyMatch(this::warehouseSource);boolean oldDirect=java.util.stream.StreamSupport.stream(oldSources.spliterator(),false).anyMatch(source->!warehouseSource(source));var previous=rows("SELECT * FROM inventory_shipment_position WHERE site_id=? AND shipment_id=?",c.site(),id);
        if(!tracked&&oldConfirmed&&!oldDirect)return;
        if(previous.isEmpty()&&!hasWarehouse)return;
        if(scopeRows.isEmpty()&&!tracked)return;
        if(!tracked&&hasWarehouse){var s=scopeRows.getFirst();db.update("UPDATE production_shipment SET stock_tracked=TRUE,warehouse_id=?,owner_id=? WHERE site_id=? AND id=?",now.get("warehouse_id")==null?s.get("warehouse_id"):now.get("warehouse_id"),now.get("owner_id")==null?s.get("owner_id"):now.get("owner_id"),c.site(),id);now.put("stock_tracked",true);if(now.get("warehouse_id")==null)now.put("warehouse_id",s.get("warehouse_id"));if(now.get("owner_id")==null)now.put("owner_id",s.get("owner_id"));}
        long warehouse=n(now.get("warehouse_id")),owner=n(now.get("owner_id"));var net=new TreeMap<Key,Long>();var own=new TreeMap<Key,Long>();var limits=new HashMap<String,Long>();var consume=new LinkedHashMap<Long,Long>();
        for(var p:previous)net.merge(new Key(n(p.get("warehouse_id")),n(p.get("owner_id")),n(p.get("sku_id"))),-n(p.get("units")),InventoryService::total);
        if(active)for(var source:sources){if(!warehouseSource(source))continue;Key k=new Key(warehouse,owner,positive(source,"sku_id"));checkDate(c.site(),k,now.get("business_date").toString());net.merge(k,positive(source,"actual_units"),InventoryService::total);for(var a:source.path("allocations")){String line=a.path("order_line_id").asText();long amount=positive(a,"units");long remaining=limits.computeIfAbsent(line,x->reserved(c.site(),k,x));long take=Math.min(remaining,amount);limits.put(line,remaining-take);own.merge(k,take,InventoryService::total);if(take>0)consume.merge(Long.parseLong(line),take,InventoryService::total);}}
        var restoreRemaining=new TreeMap<Key,Long>();for(var e:net.entrySet())if(e.getValue()<0)restoreRemaining.put(e.getKey(),-e.getValue());
        var currentLines=new HashMap<Key,Set<Long>>();if(active)for(var source:sources){if(!warehouseSource(source))continue;Key k=new Key(warehouse,owner,positive(source,"sku_id"));for(var a:source.path("allocations"))currentLines.computeIfAbsent(k,x->new HashSet<>()).add(positive(a,"order_line_id"));}
        for(var r:rows("SELECT r.*,m.consumed_units AS shipment_consumed FROM inventory_shipment_reservation m JOIN inventory_reservation r ON r.site_id=m.site_id AND r.id=m.reservation_id WHERE m.site_id=? AND m.shipment_id=? AND m.consumed_units>0 ORDER BY r.id",c.site(),id)){
            Key k=new Key(n(r.get("warehouse_id")),n(r.get("owner_id")),n(r.get("sku_id")));boolean removed=active&&!currentLines.getOrDefault(k,Set.of()).contains(n(r.get("order_line_id")));long amount=removed?n(r.get("shipment_consumed")):Math.min(restoreRemaining.getOrDefault(k,0L),n(r.get("shipment_consumed")));if(amount==0)continue;
            db.update("UPDATE inventory_reservation SET consumed_units=consumed_units-?,released_units=released_units+?,revision=revision+1 WHERE site_id=? AND id=?",amount,removed?amount:0,c.site(),r.get("id"));
            db.update("UPDATE inventory_shipment_reservation SET consumed_units=consumed_units-? WHERE site_id=? AND shipment_id=? AND reservation_id=?",amount,c.site(),id,r.get("id"));restoreRemaining.put(k,Math.max(0,restoreRemaining.getOrDefault(k,0L)-amount));
            var after=entity(c.site(),"inventory_reservation",n(r.get("id")));audit(c,"reservation",n(r.get("id")),n(after.get("revision")),token,removed?"RELEASE_CONSUMPTION":"RESTORE_CONSUMPTION",reason,r,after);
        }
        for(var e:net.entrySet())if(e.getValue()>0)ensureFree(c.site(),e.getKey(),e.getValue(),own.getOrDefault(e.getKey(),0L));
        // Corrections consume only extra reservations, never consume them again for unchanged quantity.
        for(var e:net.entrySet()){long positive=Math.max(0,e.getValue());long remaining=Math.min(positive,own.getOrDefault(e.getKey(),0L));if(remaining>0)for(var line:consume.entrySet()){for(var r:rows("SELECT * FROM inventory_reservation WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=? AND order_line_id=? AND units>consumed_units+released_units ORDER BY id",c.site(),e.getKey().warehouse,e.getKey().owner,e.getKey().sku,line.getKey())){long amount=Math.min(remaining,Math.min(line.getValue(),n(r.get("units"))-n(r.get("consumed_units"))-n(r.get("released_units"))));if(amount<=0)continue;db.update("UPDATE inventory_reservation SET consumed_units=consumed_units+?,revision=revision+1 WHERE site_id=? AND id=?",amount,c.site(),r.get("id"));db.update("INSERT INTO inventory_shipment_reservation(site_id,shipment_id,reservation_id,consumed_units) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE consumed_units=consumed_units+VALUES(consumed_units)",c.site(),id,r.get("id"),amount);var after=entity(c.site(),"inventory_reservation",n(r.get("id")));audit(c,"reservation",n(r.get("id")),n(after.get("revision")),token,"CONSUME_RESERVATION",reason,r,after);remaining-=amount;line.setValue(line.getValue()-amount);}}}
        var deltas=new ArrayList<Delta>();for(var e:net.entrySet())if(e.getValue()!=0)deltas.add(new Delta(e.getKey(),"QUALIFIED",-e.getValue(),"",""));apply(c,deltas,"shipments",id,n(now.get("revision")),token,reason,now.get("business_date").toString(),false);
        settleShipmentPlans(c,oldSources,active?sources:json.createArrayNode(),warehouse,owner,token,reason);
        db.update("UPDATE inventory_shipment_position SET units=0 WHERE site_id=? AND shipment_id=?",c.site(),id);if(active)for(var source:sources)if(warehouseSource(source))db.update("INSERT INTO inventory_shipment_position(site_id,shipment_id,source_line_id,warehouse_id,owner_id,sku_id,units) VALUES(?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE warehouse_id=VALUES(warehouse_id),owner_id=VALUES(owner_id),sku_id=VALUES(sku_id),units=VALUES(units)",c.site(),id,positive(source,"id"),warehouse,owner,positive(source,"sku_id"),positive(source,"actual_units"));
    }
    private void settleShipmentPlans(ProductionContext c,JsonNode previous,JsonNode current,long warehouse,long owner,String token,String reason){
        var oldUnits=new TreeMap<Long,Long>();var newUnits=new TreeMap<Long,Long>();
        for(var source:previous)if(warehouseSource(source)&&source.hasNonNull("plan_id"))oldUnits.merge(positive(source,"plan_id"),positive(source,"actual_units"),InventoryService::total);
        for(var source:current)if(warehouseSource(source)&&source.hasNonNull("plan_id")){
            long planId=positive(source,"plan_id"),sku=positive(source,"sku_id");var plan=entity(c.site(),"inventory_plan",planId);
            if(!"OUT".equals(plan.get("direction"))||plan.get("loan_id")!=null||n(plan.get("warehouse_id"))!=warehouse||n(plan.get("owner_id"))!=owner||n(plan.get("sku_id"))!=sku)throw error(409,"plan_scope_invalid","销售发货安排必须对应同方向、仓库/货权及SKU。");
            newUnits.merge(planId,positive(source,"actual_units"),InventoryService::total);
        }
        var ids=new TreeSet<Long>();ids.addAll(oldUnits.keySet());ids.addAll(newUnits.keySet());
        for(long planId:ids){long delta=total(newUnits.getOrDefault(planId,0L),-oldUnits.getOrDefault(planId,0L));if(delta==0)continue;var before=entity(c.site(),"inventory_plan",planId);long completed=total(n(before.get("completed_units")),delta);
            if(completed<0||completed>n(before.get("units"))-n(before.get("cancelled_units")))throw error(422,"plan_completion_exceeded","实际出货超过计划剩余量，或更正与原完成事实不一致。");
            db.update("UPDATE inventory_plan SET completed_units=?,revision=revision+1 WHERE site_id=? AND id=?",completed,c.site(),planId);var after=entity(c.site(),"inventory_plan",planId);audit(c,"plan",planId,n(after.get("revision")),token,delta>0?"COMPLETE_SHIPMENT":"RESTORE_SHIPMENT",reason,before,after);
        }
    }
    void requireReservationsHandled(long site,long order){long remaining=db.queryForObject("SELECT COALESCE(SUM(r.units-r.consumed_units-r.released_units),0) FROM inventory_reservation r JOIN production_order_line l ON l.site_id=r.site_id AND l.id=r.order_line_id WHERE r.site_id=? AND l.order_id=?",Long.class,site,order);if(remaining>0)throw error(409,"reservation_release_required","订单仍有库存预留，请先明确释放或更正占用，再关闭/作废/减少需求。");}
}
