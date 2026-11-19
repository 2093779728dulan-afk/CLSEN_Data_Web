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

@Service
public class ProductionService {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final String authorityMode;
    private final InventoryService inventory;
    private final CatalogAuthority catalogAuthority;
    public ProductionService(JdbcTemplate db,ObjectMapper json,String authorityMode) { this(db,json,authorityMode,"",""); }
    @org.springframework.beans.factory.annotation.Autowired
    public ProductionService(JdbcTemplate db,ObjectMapper json,@Value("${PRODUCTION_AUTHORITY_MODE:disabled}") String authorityMode, @Value("${PRODUCTION_CATALOG_SCHEMA:}") String catalogSchema, @Value("${PRODUCTION_CATALOG_ALLOWED_SKUS:}") String catalogScope) {
        if(authorityMode.equals("qa_catalog")&&!"clsen_orders_qa_sku_20261015".equals(db.queryForObject("SELECT DATABASE()",String.class)))throw new IllegalStateException("QA catalog mode requires the task-owned fictional orders schema");
        this.db=db;this.json=json;this.authorityMode=authorityMode;this.inventory=new InventoryService(db,json,authorityMode,catalogSchema,catalogScope);
        this.catalogAuthority=new CatalogAuthority(db,json,authorityMode,catalogSchema,catalogScope);
    }
    private static LocalDate date(String value) {
        try{return LocalDate.parse(value);}catch(java.time.DateTimeException error){throw new ProductionError(422,"invalid_date","日期格式无效。");}
    }
    static String table(String kind) {
        return switch(kind){case "orders" -> "production_order";case "shipments" -> "production_shipment";default -> throw new ProductionError(404,"not_found","记录不存在。");};
    }
    static long positive(JsonNode value,String field) {
        if(value==null || !value.isTextual() || !value.asText().matches("[1-9][0-9]{0,18}"))
            throw new ProductionError(422,"invalid_integer",field+"必须是正整数。");
        try{return Long.parseLong(value.asText());}catch(NumberFormatException error){throw new ProductionError(422,"integer_out_of_range",field+"超出支持范围。");}
    }
    static String text(JsonNode body,String field,int max) {
        JsonNode value=body.get(field);
        if(value==null || value.isNull())return "";
        if(!value.isTextual() || value.asText().length()>max)throw new ProductionError(422,"invalid_field",field+"内容无效或过长。");
        return value.asText();
    }
    private static Object canonical(JsonNode node) {
        if(node.isObject()) {
            Map<String,Object> result=new TreeMap<>();
            node.properties().forEach(entry->result.put(entry.getKey(),canonical(entry.getValue())));return result;
        }
        if(node.isArray()){List<Object> result=new ArrayList<>();node.forEach(value->result.add(canonical(value)));return result;}
        if(node.isNull())return null;
        if(node.isBoolean())return node.asBoolean();
        if(node.isNumber())return node.asText();
        return node.asText();
    }
    private String fingerprint(String path,JsonNode body) {
        ObjectNode value=(ObjectNode)body.deepCopy();value.remove("_catalog");value.remove("_actor_name");
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest((path+"\n"+json.writeValueAsString(canonical(value))).getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    private Map<String,Object> row(ResultSet result,int index)throws SQLException {
        Map<String,Object> value=new LinkedHashMap<>();
        for(int n=1;n<=result.getMetaData().getColumnCount();n++) {
            Object item=result.getObject(n);String key=result.getMetaData().getColumnLabel(n);
            if(item instanceof Number)item=item.toString();
            else if(item instanceof java.sql.Date date)item=date.toLocalDate().toString();
            else if(item instanceof java.sql.Timestamp time)item=time.toInstant().toString();
            value.put(key,item);
        }return value;
    }
    private String hash(Object value) {
        try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(json.writeValueAsString(value).getBytes(StandardCharsets.UTF_8)));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
    }
    static final Map<String,Integer> SOURCE_FIELDS=Map.of("source_system",120,"source_event_kind",64,"external_event_id",120,"source_batch",120,"manual_source_note",2000);
    private String sourceKey(JsonNode body) {
        String system=text(body,"source_system",120),event=text(body,"source_event_kind",64),external=text(body,"external_event_id",120),batch=text(body,"source_batch",120);
        if(system.isEmpty()&&event.isEmpty()&&external.isEmpty()&&batch.isEmpty())return "";
        if(system.isBlank()||event.isBlank()||external.isBlank())throw new ProductionError(422,"source_key_incomplete","可靠来源需同时填写来源单位/系统、事件类别和外部事件号；没有凭据请保留空白并填写人工来源说明。");
        return hash(List.of(system,event,external,batch));
    }
    private String fulfillmentMode(JsonNode source) {
        String mode=source.hasNonNull("fulfillment_mode")?source.path("fulfillment_mode").asText():"WAREHOUSE_STOCK";
        if(!Set.of("WAREHOUSE_STOCK","PRODUCTION_DIRECT").contains(mode))throw new ProductionError(422,"invalid_fulfillment_mode","出货来源请选择仓库库存出货或生产完成后直接出货。");
        return mode;
    }
    private String contentHash(String kind,JsonNode body,boolean includeAllocation) {
        Map<String,BigInteger> quantities=new TreeMap<>(),allocation=new TreeMap<>(),direct=new TreeMap<>();
        String field=kind.equals("orders")?"lines":"sources",quantity=kind.equals("orders")?"expected_units":"actual_units";
        if(!body.path(field).isArray()||body.path(field).isEmpty()||body.path(field).size()>500)throw new ProductionError(422,"invalid_lines","请填写有效明细（最多500行）。");
        for(JsonNode line:body.path(field)) {
            String sku=Long.toString(positive(line.get("sku_id"),"SKU"));quantities.merge(sku,BigInteger.valueOf(positive(line.get(quantity),"数量")),BigInteger::add);
            if(kind.equals("shipments")){
                if(fulfillmentMode(line).equals("PRODUCTION_DIRECT"))direct.merge(sku,BigInteger.valueOf(positive(line.get(quantity),"数量")),BigInteger::add);
                for(JsonNode a:line.path("allocations"))allocation.merge(sku+":"+positive(a.get("order_line_id"),"订单行"),BigInteger.valueOf(positive(a.get("units"),"分配数量")),BigInteger::add);
            }
        }
        // Presentation number, comments, row order and logical row IDs are not event content.
        var content=new ArrayList<Object>(List.of(text(body,"business_date",10),quantities,includeAllocation?allocation:Map.of()));
        // Keep the legacy warehouse-only signature stable; direct production changes inventory meaning.
        if(!direct.isEmpty())content.add(direct);
        if(kind.equals("orders")&&body.hasNonNull("factory_id"))content.add(List.of("factory",text(body,"factory_id",19)));
        if(!text(body,"destination",255).isEmpty())content.add(List.of("destination",text(body,"destination",255)));
        if(body.hasNonNull("destination_id"))content.add(List.of("destination_object",text(body,"destination_type",16),text(body,"destination_id",19)));
        if(kind.equals("shipments")&&body.hasNonNull("cartons")) {
            JsonNode packing=body.path("cartons").deepCopy();for(JsonNode box:packing)if(box.isObject())((ObjectNode)box).remove("id");
            content.add(canonical(packing));
        }
        return hash(content);
    }
    @Transactional(readOnly=true)
    public Map<String,Object> checkSource(ProductionContext context,String kind,JsonNode input) {
        table(kind);String key=sourceKey(input);String signature=contentHash(kind,input,false);
        var result=new LinkedHashMap<String,Object>();result.put("candidates",List.of());
        if(!key.isEmpty()) {
            var known=rows("SELECT document_id,content_hash FROM production_business_source WHERE site_id=? AND document_kind=? AND source_key=? AND document_id IS NOT NULL",context.site(),kind,key);
            if(!known.isEmpty()){result.put("duplicate_document",document(context,kind,Long.parseLong(known.getFirst().get("document_id").toString()),false));result.put("content_matches",known.getFirst().get("content_hash").equals(contentHash(kind,input,true)));}
        } else {
            // Legacy rows have no stored signature. Compare their active quantities without rewriting provenance.
            var totals=new TreeMap<String,BigInteger>();String quantity=kind.equals("orders")?"expected_units":"actual_units";
            for(JsonNode line:input.path(kind.equals("orders")?"lines":"sources"))totals.merge(line.path("sku_id").asText(),new BigInteger(line.path(quantity).asText()),BigInteger::add);
            String child=kind.equals("orders")?"production_order_line":"production_shipment_source_line",parent=kind.equals("orders")?"order_id":"shipment_id";
            var args=new ArrayList<Object>(List.of(context.site(),date(text(input,"business_date",10)),signature,context.site(),totals.size()));
            String having="COUNT(DISTINCT sku_id)=?";for(var entry:totals.entrySet()){having+=" AND SUM(CASE WHEN sku_id=? THEN "+quantity+" ELSE 0 END)=?";args.add(entry.getKey());args.add(entry.getValue());}
            result.put("candidates",rows("SELECT id,system_number,business_number,business_date,status FROM "+table(kind)+" WHERE site_id=? AND business_date=? AND status='CONFIRMED' AND (source_signature=? OR (source_signature IS NULL AND id IN (SELECT "+parent+" FROM "+child+" WHERE site_id=? AND is_active=TRUE GROUP BY "+parent+" HAVING "+having+"))) ORDER BY id DESC LIMIT 10",args.toArray()));
        }
        return result;
    }
    private void validatePurpose(String kind,JsonNode body,boolean confirmed) {
        if(!kind.equals("shipments"))return;String purpose=text(body,"dispatch_purpose",32);
        if(purpose.isEmpty()||purpose.equals("LEGACY_UNCLASSIFIED"))return; // legacy demo contract, never verified real evidence
        if(!Set.of("OUTWARD_ORDER","PRODUCTION_COMPLETION","INTERNAL_HANDOVER","WAREHOUSE_RECEIPT","LOGISTICS_TRANSFER","WAREHOUSE_DISPATCH").contains(purpose))throw new ProductionError(422,"invalid_dispatch_purpose","发运用途无效。");
        if(purpose.equals("WAREHOUSE_DISPATCH")){
            for(var line:body.path("sources"))if(!fulfillmentMode(line).equals("WAREHOUSE_STOCK"))throw new ProductionError(422,"warehouse_dispatch_source_invalid","仓库出货使用已入库库存，请核对货物来源。");
            if(confirmed){long source=positive(body.get("warehouse_id"),"来源仓");positive(body.get("owner_id"),"货权");if(text(body,"destination_type",16).equals("WAREHOUSE")&&positive(body.get("destination_id"),"目的仓")==source)throw new ProductionError(422,"dispatch_destination_invalid","来源仓与目的仓不能相同；同仓移位请使用库存移位。");}
        }else if(purpose.equals("LOGISTICS_TRANSFER")&&confirmed){
            for(var line:body.path("sources"))if(!line.path("allocations").isEmpty())throw new ProductionError(422,"not_order_dispatch","仓间运输须使用独立出库来源，不能把订单分配再计作仓间发运。");
            long source=positive(body.get("warehouse_id"),"来源仓"),destination=positive(body.get("destination_id"),"目的仓");
            if(source==destination||!text(body,"destination_type",16).equals("WAREHOUSE"))throw new ProductionError(422,"transfer_scope_invalid","仓间发运须选择不同的来源仓和目的仓，货权保持不变。");
            for(var line:body.path("sources"))if(!fulfillmentMode(line).equals("WAREHOUSE_STOCK")||!line.path("allocations").isEmpty()||line.hasNonNull("plan_id"))throw new ProductionError(422,"transfer_source_invalid","仓间发运只使用来源仓成品库存，不分配生产订单或销售安排，不重复累计订单已发。");
        }else if(confirmed&&!purpose.equals("OUTWARD_ORDER"))throw new ProductionError(422,"not_order_dispatch","完工、同址移交及入库不属于订单实际出货，请使用相应独立业务事实。");
    }
    private List<Map<String,Object>> rows(String sql,Object... args){return db.query(sql,this::row,args);}
    private Map<String,Object> document(ProductionContext context,String kind,long id,boolean lock) {
        var values=rows("SELECT * FROM "+table(kind)+" WHERE site_id=? AND id=?"+(lock?" FOR UPDATE":""),context.site(),id);
        if(values.isEmpty())throw new ProductionError(404,"document_not_found","记录不存在或不在当前站点。");return values.getFirst();
    }
    private static String marks(int count){return String.join(",",Collections.nCopies(count,"?"));}
    List<Map<String,Object>> orderLinesFor(long site,List<Object> ids) {
        return orderLinesFor(db,site,ids);
    }
    static List<Map<String,Object>> orderLinesFor(JdbcTemplate db,long site,List<Object> ids) {
        if(ids.isEmpty())return List.of();
        var args=new ArrayList<Object>(List.of(site,site,site));args.addAll(ids);
        return db.queryForList("""
            SELECT l.*,COALESCE(t.actual_units,0) AS actual_units,COALESCE(t.production_direct_units,0) AS production_direct_units,COALESCE(p.received_units,0) AS received_units
            FROM production_order_line l LEFT JOIN (
                SELECT a.order_line_id,SUM(a.units) AS actual_units,SUM(CASE WHEN x.fulfillment_mode='PRODUCTION_DIRECT' THEN a.units ELSE 0 END) AS production_direct_units FROM production_shipment_allocation a
                JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id
                JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id
                WHERE a.site_id=? AND x.is_active=TRUE AND a.is_active=TRUE AND s.status='CONFIRMED' GROUP BY a.order_line_id
            ) t ON t.order_line_id=l.id
            LEFT JOIN (
                SELECT x.order_line_id,SUM(CAST(x.units AS UNSIGNED)) AS received_units
                FROM inventory_document d JOIN JSON_TABLE(d.line_items,'$[*]' COLUMNS(
                    purpose VARCHAR(32) PATH '$.purpose',NESTED PATH '$.production_allocations[*]' COLUMNS(
                        order_line_id BIGINT PATH '$.order_line_id',units VARCHAR(19) PATH '$.units'))) x ON TRUE
                WHERE d.site_id=? AND d.kind='IN' AND d.status='POSTED' AND x.purpose='PRODUCTION_RECEIPT' GROUP BY x.order_line_id
            ) p ON p.order_line_id=l.id
            WHERE l.site_id=? AND l.is_active=TRUE AND l.order_id IN (
            """+marks(ids.size())+") ORDER BY l.id",args.toArray()).stream().map(DestinationReceiptStore::normalized).toList();
    }
    private List<Map<String,Object>> orderLines(long site,long id){return orderLinesFor(site,List.of(id));}
    static void quantities(Map<String,Object> value,List<Map<String,Object>> lines) {
        for(var line:lines)line.put("difference_units",new BigInteger(line.get("expected_units").toString()).subtract(new BigInteger(line.get("actual_units").toString())).toString());
        for(var line:lines)trackingMetrics(line,"actual_units");
        value.put("lines",lines);
        for(String field:List.of("pending_units","overage_units","closed_units"))value.put(field,sum(lines,field).toString());
        long closed=lines.stream().filter(l->"CLOSED".equals(l.get("tracking_state"))).count();
        value.put("tracking_state",closed==0?"OPEN":closed==lines.size()?"CLOSED":"PARTIAL_CLOSED");
        for(String field:List.of("expected_units","actual_units","difference_units","received_units"))value.put(field,sum(lines,field).toString());
    }
    private static void trackingMetrics(Map<String,Object> line,String actualField) {
        BigInteger difference=new BigInteger(line.get("expected_units").toString()).subtract(new BigInteger(line.get(actualField).toString()));
        line.put("pending_units","CLOSED".equals(line.get("tracking_state"))?"0":difference.max(BigInteger.ZERO).toString());
        line.put("overage_units",difference.negate().max(BigInteger.ZERO).toString());
    }
    private static BigInteger sum(List<Map<String,Object>> rows,String field){return rows.stream().map(row->new BigInteger(row.get(field).toString())).reduce(BigInteger.ZERO,BigInteger::add);}
    // Production follow-up is a human decision in the existing revision ledger, separate from shipment tracking.
    static void productionCompletion(Map<String,Object> value,List<Map<String,Object>> decisions) {
        var decision=decisions.stream().filter(item->Objects.equals(item.get("document_id"),value.get("id")) || !item.containsKey("document_id")).findFirst();
        value.put("production_completion_state",decision.map(item->"COMPLETE_PRODUCTION".equals(item.get("operation_kind"))?"COMPLETED":"OPEN").orElse("OPEN"));
        @SuppressWarnings("unchecked") var lines=(List<Map<String,Object>>)value.get("lines");
        boolean ready=Objects.equals(value.get("status"),"CONFIRMED") && lines!=null && !lines.isEmpty() && lines.stream().allMatch(line->
            line.get("produced_units")!=null && line.get("received_units")!=null &&
            new BigInteger(line.get("produced_units").toString()).compareTo(new BigInteger(line.get("expected_units").toString()))>=0 &&
            new BigInteger(line.get("received_units").toString()).compareTo(new BigInteger(line.get("expected_units").toString()))>=0);
        value.put("production_completion_ready",ready);
    }
    private Map<String,Object> detail(ProductionContext context,String kind,long id) {
        Map<String,Object> value=document(context,kind,id,false);
        if(kind.equals("orders")) {
            var factory=rows("SELECT name FROM production_factory WHERE site_id=? AND id=?",context.site(),value.get("factory_id"));
            value.put("factory_name",factory.isEmpty()?null:factory.getFirst().get("name"));
        } else if(value.get("cartons")!=null)value.put("cartons",json.readTree(value.get("cartons").toString()));
        if(kind.equals("orders")) {
            quantities(value,orderLines(context.site(),id));
            var receipts=inventory.productionReceipts(context.site(),id);value.put("receipts",receipts);
            BigInteger received=BigInteger.ZERO;var perLine=new HashMap<String,BigInteger>();
            for(var receipt:receipts)if(receipt.get("status").equals("POSTED")){
                var amount=new BigInteger(receipt.get("units").toString());received=received.add(amount);
                perLine.merge(receipt.get("order_line_id").toString(),amount,BigInteger::add);
            }
            value.put("received_units",received.toString());
            @SuppressWarnings("unchecked") var receiptLines=(List<Map<String,Object>>)value.get("lines");
            for(var line:receiptLines)line.put("received_units",perLine.getOrDefault(line.get("id").toString(),BigInteger.ZERO).toString());
            value.put("shipments",rows("""
                SELECT DISTINCT s.id,s.system_number,s.business_date,s.status,s.revision FROM production_shipment s
                JOIN production_shipment_source_line x ON x.site_id=s.site_id AND x.shipment_id=s.id
                JOIN production_shipment_allocation a ON a.site_id=x.site_id AND a.source_line_id=x.id
                JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id
                WHERE l.site_id=? AND l.order_id=? AND x.is_active=TRUE AND a.is_active=TRUE ORDER BY s.id DESC
                """,context.site(),id));
        } else {
            var sources=rows("SELECT id,sku_id,sku_label,catalog_version,actual_units,replaces_source_id,plan_id,fulfillment_mode FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",context.site(),id);
            for(var source:sources)source.put("allocations",rows("""
                SELECT a.id,a.order_line_id,a.units,l.order_id,o.system_number AS order_number
                FROM production_shipment_allocation a
                JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id
                JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id
                WHERE a.site_id=? AND a.source_line_id=? AND a.is_active=TRUE ORDER BY a.id
                """,context.site(),source.get("id")));
            value.put("sources",sources);value.put("actual_units",sum(sources,"actual_units").toString());
        }
        var history=rows("SELECT revision,actor_id,actor_name,reason,operation_kind,effective_date,before_value,after_value,created_at FROM production_revision WHERE site_id=? AND document_kind=? AND document_id=? ORDER BY revision DESC",context.site(),kind,id);
        if(kind.equals("orders"))productionCompletion(value,history.stream().filter(item->Set.of("COMPLETE_PRODUCTION","REOPEN_PRODUCTION").contains(item.get("operation_kind"))).toList());
        for(var item:history){for(String field:List.of("before_value","after_value"))if(item.get(field)!=null)item.put(field,json.readTree(item.get(field).toString()));}
        value.put("history",history);
        value.put("file_sources",rows("SELECT DISTINCT p.id AS preview_id,p.filename,p.digest,p.created_at FROM production_preview p JOIN production_source s ON s.site_id=p.site_id AND s.document_kind=p.document_kind AND s.digest=p.digest WHERE s.site_id=? AND s.document_kind=? AND s.document_id=? ORDER BY p.created_at",context.site(),kind,id));return value;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> get(ProductionContext context,String kind,long id){return detail(context,kind,id);}

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> chains(ProductionContext context,Map<String,String> query){return new ProductionChainStore(db,json,this,inventory).read(context,query);}

    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> list(ProductionContext context,String kind,String q,String status,String from,String to,String sku,String order,int page,int pageSize) {
        return list(context,kind,q,status,from,to,sku,order,page,pageSize,"",false);
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> list(ProductionContext context,String kind,String q,String status,String from,String to,String sku,String order,int page,int pageSize,String tracking,boolean selectable) {
        return list(context,kind,q,status,from,to,sku,order,page,pageSize,tracking,selectable,"");
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> list(ProductionContext context,String kind,String q,String status,String from,String to,String sku,String order,int page,int pageSize,String tracking,boolean selectable,String factory) {
        return list(context,kind,q,status,from,to,sku,order,page,pageSize,tracking,selectable,factory,"","");
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> list(ProductionContext context,String kind,String q,String status,String from,String to,String sku,String order,int page,int pageSize,String tracking,boolean selectable,String factory,String warehouse,String owner) {
        return list(context,kind,q,status,from,to,sku,order,page,pageSize,tracking,selectable,factory,warehouse,owner,"");
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> list(ProductionContext context,String kind,String q,String status,String from,String to,String sku,String order,int page,int pageSize,String tracking,boolean selectable,String factory,String warehouse,String owner,String progress) {
        if(!progress.isEmpty()&&(!kind.equals("orders")||!Set.of("active","completed","all").contains(progress)))throw new ProductionError(422,"invalid_production_progress","生产完成筛选无效。");
        if(page<1 || pageSize<1 || pageSize>100)throw new ProductionError(422,"invalid_page","分页参数无效。");
        StringBuilder where=new StringBuilder(" WHERE site_id=?");List<Object> args=new ArrayList<>(List.of(context.site()));
        if(kind.equals("shipments"))for(var filter:Map.of("warehouse_id",warehouse,"owner_id",owner).entrySet())if(!filter.getValue().isEmpty()){where.append(" AND "+filter.getKey()+"=?");args.add(positive(json.getNodeFactory().textNode(filter.getValue()),filter.getKey()));}
        if(kind.equals("orders")&&!warehouse.isEmpty()) {
            long warehouseId=positive(json.getNodeFactory().textNode(warehouse),"仓库");
            where.append(" AND (receipt_warehouse_id=? OR id IN (SELECT l.order_id FROM production_order_line l JOIN production_shipment_allocation a ON a.site_id=l.site_id AND a.order_line_id=l.id JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment h ON h.site_id=x.site_id AND h.id=x.shipment_id WHERE l.site_id=? AND l.is_active=TRUE AND a.is_active=TRUE AND x.is_active=TRUE AND h.status='CONFIRMED' AND (h.warehouse_id=? OR h.destination_id=?)))");
            args.add(warehouseId);args.add(context.site());args.add(warehouseId);args.add(warehouseId);
        }
        if(!q.isEmpty()){
            where.append(" AND (system_number LIKE ? OR business_number LIKE ?");args.add("%"+q+"%");args.add("%"+q+"%");
            if(kind.equals("orders")){
                where.append(" OR factory_id IN (SELECT id FROM production_factory WHERE site_id=? AND name LIKE ?) OR id IN (SELECT order_id FROM production_order_line WHERE site_id=? AND is_active=TRUE AND sku_label LIKE ?)");
                args.add(context.site());args.add("%"+q+"%");args.add(context.site());args.add("%"+q+"%");
            }
            if(kind.equals("shipments")){where.append(" OR destination LIKE ?");args.add("%"+q+"%");}
            where.append(")");
        }
        if(kind.equals("orders")&&!factory.isEmpty()) {
            if(factory.equals("unknown"))where.append(" AND factory_id IS NULL");
            else {where.append(" AND factory_id=?");args.add(positive(json.getNodeFactory().textNode(factory),"工厂"));}
        }
        if(!status.isEmpty()){where.append(" AND status=?");args.add(status);}
        if(!from.isEmpty()){where.append(" AND business_date>=?");args.add(date(from));}
        if(!to.isEmpty()){where.append(" AND business_date<=?");args.add(date(to));}
        if(!sku.isEmpty()) {
            long skuId=positive(json.getNodeFactory().textNode(sku),"SKU");
            String child=kind.equals("orders")?"production_order_line":"production_shipment_source_line";
            String parent=kind.equals("orders")?"order_id":"shipment_id";
            where.append(" AND id IN (SELECT "+parent+" FROM "+child+" WHERE site_id=? AND sku_id=? AND is_active=TRUE"+(selectable&&kind.equals("orders")?" AND tracking_state='OPEN'":"")+")");args.add(context.site());args.add(skuId);
        }
        if(!order.isEmpty() && kind.equals("orders")){where.append(" AND system_number=?");args.add(order);}
        if(!order.isEmpty() && kind.equals("shipments")) {
            where.append(" AND id IN (SELECT x.shipment_id FROM production_shipment_source_line x JOIN production_shipment_allocation a ON a.site_id=x.site_id AND a.source_line_id=x.id JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE x.site_id=? AND x.is_active=TRUE AND a.is_active=TRUE AND o.system_number=?)");args.add(context.site());args.add(order);
        }
        if(kind.equals("orders") && !tracking.isEmpty()) {
            if(!Set.of("OPEN","CLOSED","UNSHIPPED","PARTIAL","OVERAGE","WAIT_PRODUCTION","WAIT_RECEIPT","WAIT_SHIPMENT").contains(tracking))throw new ProductionError(422,"invalid_tracking","跟进筛选无效。");
            where.append(" AND status='CONFIRMED'");
            String condition=switch(tracking){
                case "OPEN" -> "l.tracking_state='OPEN'";
                case "CLOSED" -> "l.tracking_state='CLOSED'";
                case "UNSHIPPED" -> "l.tracking_state='OPEN' AND COALESCE(t.units,0)=0";
                case "PARTIAL" -> "l.tracking_state='OPEN' AND COALESCE(t.units,0)>0 AND COALESCE(t.units,0)<l.expected_units";
                case "WAIT_PRODUCTION" -> "l.tracking_state='OPEN' AND (l.produced_units IS NULL OR l.produced_units<l.expected_units)";
                case "WAIT_SHIPMENT" -> "l.tracking_state='OPEN' AND COALESCE(t.units,0)<l.expected_units";
                case "WAIT_RECEIPT" -> "l.tracking_state='OPEN' AND l.expected_units>COALESCE((SELECT SUM(CAST(r.units AS UNSIGNED)) FROM inventory_document d JOIN JSON_TABLE(d.line_items,'$[*]' COLUMNS(purpose VARCHAR(32) PATH '$.purpose',NESTED PATH '$.production_allocations[*]' COLUMNS(order_line_id BIGINT PATH '$.order_line_id',units VARCHAR(19) PATH '$.units'))) r ON TRUE WHERE d.site_id=l.site_id AND d.kind='IN' AND d.status='POSTED' AND r.purpose='PRODUCTION_RECEIPT' AND r.order_line_id=l.id),0)";
                default -> "COALESCE(t.units,0)>l.expected_units";
            };
            where.append(" AND id IN (SELECT l.order_id FROM production_order_line l LEFT JOIN (SELECT a.order_line_id,SUM(a.units) units FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment h ON h.site_id=x.site_id AND h.id=x.shipment_id WHERE a.site_id=? AND a.is_active=TRUE AND x.is_active=TRUE AND h.status='CONFIRMED' GROUP BY a.order_line_id) t ON t.order_line_id=l.id WHERE l.site_id=? AND l.is_active=TRUE AND "+condition+")");args.add(context.site());args.add(context.site());
        }
        Map<String,Object> progressCounts=null;
        if(!progress.isEmpty()) {
            String completed="COALESCE((SELECT r.operation_kind FROM production_revision r WHERE r.site_id=production_order.site_id AND r.document_kind='orders' AND r.document_id=production_order.id AND r.operation_kind IN ('COMPLETE_PRODUCTION','REOPEN_PRODUCTION') ORDER BY r.revision DESC LIMIT 1),'REOPEN_PRODUCTION')='COMPLETE_PRODUCTION'";
            String active="status<>'VOID' AND NOT ("+completed+")";
            String done="status='CONFIRMED' AND ("+completed+")";
            var totals=rows("SELECT COUNT(*) AS all_count,COALESCE(SUM(CASE WHEN "+active+" THEN 1 ELSE 0 END),0) AS active_count,COALESCE(SUM(CASE WHEN "+done+" THEN 1 ELSE 0 END),0) AS completed_count FROM production_order"+where,args.toArray()).getFirst();
            progressCounts=Map.of("all",Long.parseLong(totals.get("all_count").toString()),"active",Long.parseLong(totals.get("active_count").toString()),"completed",Long.parseLong(totals.get("completed_count").toString()));
            if(!progress.equals("all"))where.append(" AND ("+(progress.equals("active")?active:done)+")");
        }
        long count=progressCounts==null?db.queryForObject("SELECT COUNT(*) FROM "+table(kind)+where,Long.class,args.toArray()):((Number)progressCounts.get(progress)).longValue();
        var pageArgs=new ArrayList<>(args);pageArgs.add(pageSize);pageArgs.add((long)(page-1)*pageSize);
        var items=rows("SELECT * FROM "+table(kind)+where+" ORDER BY business_date DESC,id DESC LIMIT ? OFFSET ?",pageArgs.toArray());
        var ids=items.stream().map(item->item.get("id")).toList();
        if(kind.equals("orders")) {
            var all=orderLinesFor(context.site(),ids);
            var factoryIds=items.stream().map(item->item.get("factory_id")).filter(Objects::nonNull).distinct().toList();
            var factoryArgs=new ArrayList<Object>(List.of(context.site()));factoryArgs.addAll(factoryIds);
            var factories=factoryIds.isEmpty()?List.<Map<String,Object>>of():rows("SELECT id,name FROM production_factory WHERE site_id=? AND id IN ("+marks(factoryIds.size())+")",factoryArgs.toArray());
            for(var item:items)item.put("factory_name",factories.stream().filter(f->Objects.equals(f.get("id"),item.get("factory_id"))).map(f->f.get("name")).findFirst().orElse(null));
            for(var item:items)quantities(item,all.stream().filter(line->line.get("order_id").equals(item.get("id"))).toList());
            var decisionArgs=new ArrayList<Object>(List.of(context.site()));decisionArgs.addAll(ids);
            var decisions=ids.isEmpty()?List.<Map<String,Object>>of():rows("SELECT document_id,operation_kind FROM production_revision WHERE site_id=? AND document_kind='orders' AND operation_kind IN ('COMPLETE_PRODUCTION','REOPEN_PRODUCTION') AND document_id IN ("+marks(ids.size())+") ORDER BY revision DESC",decisionArgs.toArray());
            for(var item:items)productionCompletion(item,decisions);
            new ProductionChainStore(db,json,this,inventory).annotateOrders(context,items);
        } else if(!ids.isEmpty()) {
            var childArgs=new ArrayList<Object>(List.of(context.site()));childArgs.addAll(ids);
            var all=rows("SELECT * FROM production_shipment_source_line WHERE site_id=? AND is_active=TRUE AND shipment_id IN ("+marks(ids.size())+") ORDER BY id",childArgs.toArray());
            var allocations=rows("""
                SELECT a.source_line_id,a.order_line_id,a.units,l.order_id,o.system_number AS order_number,o.business_number AS order_business_number
                FROM production_shipment_allocation a
                JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id
                JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id
                JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id
                WHERE x.site_id=? AND x.is_active=TRUE AND a.is_active=TRUE AND x.shipment_id IN (
                """+marks(ids.size())+") ORDER BY a.id",childArgs.toArray());
            for(var source:all)source.put("allocations",allocations.stream().filter(a->a.get("source_line_id").equals(source.get("id"))).toList());
            for(var item:items){var lines=all.stream().filter(line->line.get("shipment_id").equals(item.get("id"))).toList();item.put("actual_units",sum(lines,"actual_units").toString());item.put("sources",lines);}
        }
        var result=new LinkedHashMap<String,Object>(Map.of("items",items,"total",count,"page",page,"page_size",pageSize));
        if(progressCounts!=null)result.put("progress_counts",progressCounts);
        return result;
    }
    @Transactional(readOnly=true,isolation=Isolation.REPEATABLE_READ)
    public Map<String,Object> summary(ProductionContext context,String from,String to,String shipmentFrom,String shipmentTo,String skuFilter,String order) {
        String dates="";List<Object> args=new ArrayList<>(List.of(context.site()));
        if(!from.isEmpty()){dates+=" AND o.business_date>=?";args.add(date(from));}
        if(!to.isEmpty()){dates+=" AND o.business_date<=?";args.add(date(to));}
        if(!skuFilter.isEmpty()){dates+=" AND l.sku_id=?";args.add(positive(json.getNodeFactory().textNode(skuFilter),"SKU"));}
        if(!order.isEmpty()){dates+=" AND o.system_number=?";args.add(order);}
        String period="";List<Object> readArgs=new ArrayList<>();
        if(!shipmentFrom.isEmpty()){period+=" AND s.business_date>=?";readArgs.add(date(shipmentFrom));}
        if(!shipmentTo.isEmpty()){period+=" AND s.business_date<=?";readArgs.add(date(shipmentTo));}
        readArgs.add(context.site());readArgs.addAll(args);
        var lines=rows("""
            SELECT l.*,o.system_number AS order_number,COALESCE(t.full_units,0) AS cumulative_actual_units,
                COALESCE(t.period_units,0) AS actual_units
            FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id
            LEFT JOIN (SELECT a.order_line_id,SUM(a.units) AS full_units,SUM(CASE WHEN 1=1
            """+period+"""
                THEN a.units ELSE 0 END) AS period_units FROM production_shipment_allocation a
                JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id
                JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id
                WHERE a.site_id=? AND x.is_active=TRUE AND a.is_active=TRUE AND s.status='CONFIRMED' GROUP BY a.order_line_id
            ) t ON t.order_line_id=l.id
            WHERE l.site_id=? AND l.is_active=TRUE AND o.status='CONFIRMED'
            """+dates+" ORDER BY o.id,l.id",readArgs.toArray());
        for(var line:lines){
            line.put("difference_units",new BigInteger(line.get("expected_units").toString()).subtract(new BigInteger(line.get("actual_units").toString())).toString());
            trackingMetrics(line,"cumulative_actual_units");
            line.put("cumulative_difference_units",new BigInteger(line.get("expected_units").toString()).subtract(new BigInteger(line.get("cumulative_actual_units").toString())).toString());
        }
        Map<String,Map<String,Object>> skus=new LinkedHashMap<>();
        for(var line:lines) {
            var sku=skus.computeIfAbsent(line.get("sku_id").toString(),key->new LinkedHashMap<>(Map.of("sku_id",key,"sku_label",line.get("sku_label"),"expected_units","0","actual_units","0","difference_units","0","pending_units","0","overage_units","0","closed_units","0")));
            for(String field:List.of("expected_units","actual_units","difference_units","pending_units","overage_units","closed_units"))sku.put(field,new BigInteger(sku.get(field).toString()).add(new BigInteger(line.get(field).toString())).toString());
        }
        var result=new LinkedHashMap<String,Object>(Map.of("items",lines,"skus",skus.values(),"expected_units",sum(lines,"expected_units").toString(),"actual_units",sum(lines,"actual_units").toString(),"difference_units",sum(lines,"difference_units").toString(),"shipment_period_filtered",!shipmentFrom.isEmpty()||!shipmentTo.isEmpty(),"cumulative_actual_units",sum(lines,"cumulative_actual_units").toString(),"cumulative_difference_units",sum(lines,"cumulative_difference_units").toString()));
        for(String field:List.of("pending_units","overage_units","closed_units"))result.put(field,sum(lines,field).toString());
        return result;
    }
    @Transactional(readOnly=true)
    public Object commandResult(ProductionContext context,String token) {
        var found=rows("SELECT result FROM production_command WHERE site_id=? AND actor_id=? AND operation_token=? AND result IS NOT NULL",context.site(),context.actor(),token);
        if(found.isEmpty())throw new ProductionError(404,"command_result_unknown","尚未查询到已提交结果；请保持原操作ID。");return json.readTree(found.getFirst().get("result").toString());
    }
    private JsonNode catalog(long site,JsonNode body,long sku,boolean confirmed) {
        if(confirmed && catalogAuthority.enabled())return catalogAuthority.current(site,body,sku);
        JsonNode value=body.path("_catalog").path(Long.toString(sku));
        if(value.isMissingNode() || (confirmed && !value.path("status").asText().equals("active")))throw new ProductionError(409,"sku_identity_unavailable","SKU不存在、已停用或所属范围发生变化。");
        return value;
    }
    private long insertedId(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    private void requireNoShipment(long site,long line) {
        inventory.requireNoProductionReceipt(site,line);
        long count=db.queryForObject("SELECT COUNT(*) FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_shipment s ON s.site_id=x.site_id AND s.id=x.shipment_id WHERE a.site_id=? AND a.order_line_id=? AND x.is_active=TRUE AND a.is_active=TRUE AND s.status='CONFIRMED'",Long.class,site,line);
        if(count>0)throw new ProductionError(409,"downstream_shipment_exists","存在有效出货引用，请先更正或作废对应出货。");
    }
    private void saveOrder(ProductionContext context,long id,JsonNode body,boolean confirmed,String action) {
        JsonNode lines=body.path("lines");if(!lines.isArray() || lines.isEmpty() || lines.size()>500)throw new ProductionError(422,"order_lines_required","订单需要1到500行SKU明细。");
        var previous=rows("SELECT id,sku_id,tracking_state,expected_units,is_active FROM production_order_line WHERE site_id=? AND order_id=?",context.site(),id);
        Map<Long,Long> existing=new HashMap<>();for(var line:previous)existing.put(Long.parseLong(line.get("sku_id").toString()),Long.parseLong(line.get("id").toString()));
        Set<Long> seen=new HashSet<>();
        for(JsonNode line:lines) {
            long sku=positive(line.get("sku_id"),"SKU"),units=positive(line.get("expected_units"),"预计数量");
            if(!seen.add(sku))throw new ProductionError(422,"duplicate_order_sku","同一订单不能重复录入同一个SKU。");
            JsonNode identity=catalog(context.site(),body,sku,confirmed);
            if(action.equals("correct") && !existing.containsKey(sku))throw new ProductionError(422,"demand_change_required","新增需求SKU请使用正式需求变更，不能与录入更正混用。");
            if(existing.containsKey(sku) && previous.stream().anyMatch(l->l.get("id").toString().equals(existing.get(sku).toString()) && "CLOSED".equals(l.get("tracking_state")) && (!l.get("expected_units").toString().equals(Long.toString(units)) || !Boolean.parseBoolean(l.get("is_active").toString()))))throw new ProductionError(409,"tracking_closed","请先恢复受影响订单行，再修改需求。");
            if(existing.containsKey(sku))db.update("UPDATE production_order_line SET expected_units=?,is_active=TRUE WHERE site_id=? AND id=?",units,context.site(),existing.get(sku));
            else db.update("INSERT INTO production_order_line(site_id,order_id,sku_id,sku_label,catalog_version,expected_units,produced_units) VALUES(?,?,?,?,?,?,0)",context.site(),id,sku,identity.path("label").asText(),identity.path("catalog_version").asText(),units);
        }
        for(var line:existing.entrySet())if(!seen.contains(line.getKey())){requireOpenLine(context.site(),line.getValue());requireNoShipment(context.site(),line.getValue());
            if(db.queryForObject("SELECT COUNT(*) FROM production_order_line WHERE site_id=? AND id=? AND produced_units>0",Long.class,context.site(),line.getValue())>0)throw new ProductionError(409,"production_progress_exists","此规格已有生产进度，请先核对并有原因地更正进度，不能直接移除。");
            db.update("UPDATE production_order_line SET is_active=FALSE WHERE site_id=? AND id=?",context.site(),line.getValue());}
    }
    private void requireOpenLine(long site,long line) {
        var values=rows("SELECT tracking_state FROM production_order_line WHERE site_id=? AND id=? AND is_active=TRUE",site,line);
        if(values.isEmpty())throw new ProductionError(409,"order_link_invalid","关联订单明细不存在。");
        if("CLOSED".equals(values.getFirst().get("tracking_state")))throw new ProductionError(409,"tracking_closed","请先恢复全部受影响订单行，再核对或修改。");
    }
    private void requireOpenShipmentLinks(ProductionContext context,long id) {
        for(var line:rows("SELECT DISTINCT a.order_line_id FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id WHERE x.site_id=? AND x.shipment_id=? AND x.is_active=TRUE AND a.is_active=TRUE",context.site(),id))requireOpenLine(context.site(),Long.parseLong(line.get("order_line_id").toString()));
    }
    private void saveShipment(ProductionContext context,long id,JsonNode body,boolean confirmed) {
        if(confirmed&&Set.of("LOGISTICS_TRANSFER","WAREHOUSE_DISPATCH").contains(text(body,"dispatch_purpose",32))){
            long warehouse=positive(body.get("warehouse_id"),"来源仓"),owner=positive(body.get("owner_id"),"货权");
            ProductionDirectory.requireOperational(db,context.site(),warehouse);
            if(db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",Long.class,context.site(),warehouse,owner)!=1)throw new ProductionError(409,"inventory_not_ready","来源仓及本货权未建立库存账，不能确认仓间出库。");
        }
        JsonNode sources=body.path("sources");if(!sources.isArray() || sources.isEmpty() || sources.size()>500)throw new ProductionError(422,"shipment_sources_required","请填写实际出货来源明细。");
        var previous=rows("SELECT * FROM production_shipment_source_line WHERE site_id=? AND shipment_id=? AND is_active=TRUE ORDER BY id",context.site(),id);
        Set<Long> used=new HashSet<>();
        for(JsonNode source:sources) {
            long sku=positive(source.get("sku_id"),"SKU"),units=positive(source.get("actual_units"),"本次实际数量");JsonNode identity=catalog(context.site(),body,sku,confirmed);
            Long sourceId=source.hasNonNull("id")?positive(source.get("id"),"来源行"):null;
            if(sourceId!=null){long checkId=sourceId;var old=previous.stream().filter(l->l.get("id").toString().equals(Long.toString(checkId))).findFirst().orElseThrow(()->new ProductionError(409,"source_identity_invalid","来源行不属于当前出货修订。"));if(!old.get("sku_id").toString().equals(Long.toString(sku)))throw new ProductionError(409,"source_identity_replacement_required","SKU改变需明确替换来源行，不能复用旧身份。");}
            else if(!source.hasNonNull("replaces_source_id")) {
                var matches=previous.stream().filter(l->l.get("sku_id").toString().equals(Long.toString(sku))&&!used.contains(Long.parseLong(l.get("id").toString()))).toList();
                if(matches.size()>1)throw new ProductionError(409,"source_identity_required","同SKU多来源更正需明确逻辑来源ID。");
                if(matches.size()==1)sourceId=Long.parseLong(matches.getFirst().get("id").toString());
            }
            String mode=source.hasNonNull("fulfillment_mode")?fulfillmentMode(source):"WAREHOUSE_STOCK";
            if(!source.has("fulfillment_mode")&&sourceId!=null)for(var prior:previous)if(prior.get("id").toString().equals(sourceId.toString()))mode=Objects.toString(prior.get("fulfillment_mode"),"WAREHOUSE_STOCK");
            Long planId=null;
            if(source.hasNonNull("plan_id"))planId=positive(source.get("plan_id"),"收发安排");
            else if(!source.has("plan_id")&&sourceId!=null&&mode.equals("WAREHOUSE_STOCK"))for(var prior:previous)if(prior.get("id").toString().equals(sourceId.toString())&&prior.get("plan_id")!=null)planId=Long.parseLong(prior.get("plan_id").toString());
            if(mode.equals("PRODUCTION_DIRECT")&&planId!=null)throw new ProductionError(422,"direct_shipment_plan_forbidden","生产直发不进入仓库，不能关联预计出库安排。");
            if(planId!=null){var plans=rows("SELECT sku_id,direction,loan_id FROM inventory_plan WHERE site_id=? AND id=?",context.site(),planId);if(plans.isEmpty()||!"OUT".equals(plans.getFirst().get("direction"))||plans.getFirst().get("loan_id")!=null||!plans.getFirst().get("sku_id").toString().equals(Long.toString(sku)))throw new ProductionError(409,"plan_scope_invalid","只能关联本站点、同SKU的预计出库安排。库房与货权在确认时再核对。");}
            if(sourceId==null){
                Long replacement=source.hasNonNull("replaces_source_id")?positive(source.get("replaces_source_id"),"被替换来源"):null;
                if(replacement!=null && previous.stream().noneMatch(l->l.get("id").toString().equals(replacement.toString())))throw new ProductionError(409,"source_identity_invalid","替换来源不属于当前出货。");
                db.update("INSERT INTO production_shipment_source_line(site_id,shipment_id,sku_id,sku_label,catalog_version,actual_units,replaces_source_id,plan_id,fulfillment_mode) VALUES(?,?,?,?,?,?,?,?,?)",context.site(),id,sku,identity.path("label").asText(),identity.path("catalog_version").asText(),units,replacement,planId,mode);sourceId=insertedId();
            }else db.update("UPDATE production_shipment_source_line SET actual_units=?,plan_id=?,fulfillment_mode=? WHERE site_id=? AND id=?",units,planId,mode,context.site(),sourceId);
            if(!used.add(sourceId))throw new ProductionError(422,"duplicate_source","不能重复编辑同一逻辑来源。");
            db.update("UPDATE production_shipment_allocation SET is_active=FALSE WHERE site_id=? AND source_line_id=?",context.site(),sourceId);
            BigInteger allocated=BigInteger.ZERO;Set<Long> seen=new HashSet<>();JsonNode allocations=source.path("allocations");
            if(!allocations.isArray() || allocations.size()>500)throw new ProductionError(422,"invalid_allocations","分配明细无效。");
            for(JsonNode allocation:allocations) {
                long line=positive(allocation.get("order_line_id"),"订单明细"),count=positive(allocation.get("units"),"分配数量");if(!seen.add(line))throw new ProductionError(422,"duplicate_allocation","同一来源不能重复分配同一订单明细。");
                var target=rows("SELECT l.sku_id,l.is_active,o.status FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE l.site_id=? AND l.id=?",context.site(),line);
                if(target.isEmpty() || !target.getFirst().get("sku_id").toString().equals(Long.toString(sku)) || !Boolean.parseBoolean(target.getFirst().get("is_active").toString()) || !target.getFirst().get("status").equals("CONFIRMED"))throw new ProductionError(409,"order_link_invalid","必须选择当前站点已确认订单的同一SKU有效明细。");
                if(confirmed)requireOpenLine(context.site(),line);
                allocated=allocated.add(BigInteger.valueOf(count));db.update("INSERT INTO production_shipment_allocation(site_id,source_line_id,order_line_id,units,is_active) VALUES(?,?,?,?,TRUE) ON DUPLICATE KEY UPDATE units=VALUES(units),is_active=TRUE",context.site(),sourceId,line,count);
            }
            if(allocated.compareTo(BigInteger.valueOf(units))>0 || (confirmed&&!Set.of("LOGISTICS_TRANSFER","WAREHOUSE_DISPATCH").contains(text(body,"dispatch_purpose",32))&&!allocated.equals(BigInteger.valueOf(units))))throw new ProductionError(422,"allocation_incomplete","分配合计必须等于来源实际数量；未分配部分可先保存草稿。");
        }
        for(var old:previous)if(!used.contains(Long.parseLong(old.get("id").toString()))){db.update("UPDATE production_shipment_source_line SET is_active=FALSE WHERE site_id=? AND id=?",context.site(),old.get("id"));db.update("UPDATE production_shipment_allocation SET is_active=FALSE WHERE site_id=? AND source_line_id=?",context.site(),old.get("id"));}
    }
    private void tracking(ProductionContext context,long id,JsonNode input,boolean close) {
        var lines=orderLines(context.site(),id);Set<String> wanted=new HashSet<>();
        if(input.has("line_ids")){if(!input.path("line_ids").isArray()||input.path("line_ids").isEmpty())throw new ProductionError(422,"tracking_lines_required","请选择订单行。");for(JsonNode line:input.path("line_ids"))wanted.add(Long.toString(positive(line,"订单行")));if(!lines.stream().map(l->l.get("id").toString()).collect(java.util.stream.Collectors.toSet()).containsAll(wanted))throw new ProductionError(409,"order_link_invalid","选择的行不属于该订单。");}
        int changed=0;for(var line:lines){if(!wanted.isEmpty()&&!wanted.contains(line.get("id").toString()))continue;boolean isClosed="CLOSED".equals(line.get("tracking_state"));if(isClosed==close)continue;
            BigInteger amount=close?new BigInteger(line.get("expected_units").toString()).subtract(new BigInteger(line.get("actual_units").toString())).max(BigInteger.ZERO):BigInteger.ZERO;
            db.update("UPDATE production_order_line SET tracking_state=?,closed_units=?,closed_at="+(close?"CURRENT_TIMESTAMP(6)":"NULL")+" WHERE site_id=? AND id=?",close?"CLOSED":"OPEN",amount.longValueExact(),context.site(),line.get("id"));changed++;
        }if(changed==0)throw new ProductionError(409,"tracking_unchanged","选定行已经处于该跟进状态，请刷新核对。");
        db.update("UPDATE production_order SET revision=revision+1 WHERE site_id=? AND id=?",context.site(),id);
    }
    private void record(ProductionContext context,String kind,long id,String token,String reason,String operation,String effective,Map<String,Object> before,Map<String,Object> after) {
        db.update("INSERT INTO production_revision(site_id,document_kind,document_id,revision,actor_id,actor_name,operation_token,reason,operation_kind,effective_date,before_value,after_value) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",context.site(),kind,id,after.get("revision"),context.actor(),context.actorName(),token,reason,operation,effective.isEmpty()?null:date(effective),before==null?null:json.writeValueAsString(before),json.writeValueAsString(after));
    }
    private Set<Long> shipmentOrders(ProductionContext context,Long id,JsonNode body) {
        Set<Long> orders=new TreeSet<>();
        if(id!=null)for(var row:rows("SELECT DISTINCT l.order_id FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id WHERE x.site_id=? AND x.shipment_id=? AND x.is_active=TRUE AND a.is_active=TRUE",context.site(),id))orders.add(Long.parseLong(row.get("order_id").toString()));
        for(JsonNode source:body.path("sources"))for(JsonNode allocation:source.path("allocations")) {
            long line=positive(allocation.get("order_line_id"),"订单明细");var found=rows("SELECT order_id FROM production_order_line WHERE site_id=? AND id=?",context.site(),line);
            if(found.isEmpty())throw new ProductionError(409,"order_link_invalid","关联订单不存在或不在当前站点。");orders.add(Long.parseLong(found.getFirst().get("order_id").toString()));
        }return orders;
    }
    @Transactional(isolation=Isolation.READ_COMMITTED)
    public Object command(ProductionContext context,String kind,Long id,String action,String key,JsonNode input) {
        context.requireWrite();String table=table(kind);inventory.lockSite(context.site());
        Set<String> allowed=new HashSet<>(Set.of("create","update","delete","confirm","correct","void"));
        allowed.addAll(kind.equals("orders")?Set.of("demand-changes","close-tracking","reopen-tracking","production-progress","complete-production","reopen-production"):Set.of("allocation-corrections"));
        if(!allowed.contains(action))throw new ProductionError(404,"not_found","操作不存在。");
        if(!input.isObject())throw new ProductionError(422,"invalid_command","命令必须是JSON对象。");
        if(action.equals("create") && !Set.of("draft","confirm").contains(text(input,"save_mode",16)))throw new ProductionError(422,"invalid_save_mode","请选择草稿或确认。");
        String token=text(input,"operation_token",36);
        var stored=begin(context,kind+"/"+id+"/"+action,key,input);
        if(stored.get("result")!=null)return json.readTree(stored.get("result").toString());
        JsonNode provenance=action.equals("confirm")?json.valueToTree(detail(context,kind,id)):input;
        boolean binding=action.equals("confirm")||(action.equals("create")&&text(input,"save_mode",16).equals("confirm"));
        if(binding&&!(authorityMode.equals("demo_fixed")||authorityMode.equals("qa_catalog")||catalogAuthority.enabled()))throw new ProductionError(503,"catalog_confirmation_disabled","真实主档确认合同尚未接入；仅允许草稿。");
        validatePurpose(kind,provenance,binding);
        String businessKey="";Long sourceOriginal=null;boolean duplicateReview=false;
        if(binding) {
            businessKey=sourceKey(provenance);
            if(!businessKey.isEmpty()) {
                String content=contentHash(kind,provenance,true);
                db.update("INSERT INTO production_business_source(site_id,document_kind,source_key,content_hash,source_system,source_event_kind,external_event_id,source_batch) VALUES(?,?,?,?,?,?,?,?) ON DUPLICATE KEY UPDATE source_key=source_key",context.site(),kind,businessKey,content,text(provenance,"source_system",120),text(provenance,"source_event_kind",64),text(provenance,"external_event_id",120),text(provenance,"source_batch",120));
                var origin=rows("SELECT document_id,content_hash FROM production_business_source WHERE site_id=? AND document_kind=? AND source_key=? FOR UPDATE",context.site(),kind,businessKey).getFirst();
                if(!origin.get("content_hash").equals(content))throw new ProductionError(409,"business_source_conflict","同一可靠来源已有不同内容，请打开原单据进行更正，不要另建事件。");
                if(origin.get("document_id")!=null)sourceOriginal=Long.parseLong(origin.get("document_id").toString());
                if(id!=null&&sourceOriginal!=null&&!id.equals(sourceOriginal)&&!action.equals("confirm"))throw new ProductionError(409,"source_target_conflict","可靠来源已关联另一张单据。");
            } else {
                var suspects=(List<?>)checkSource(context,kind,provenance).get("candidates");
                String currentId=id==null?null:id.toString();
                duplicateReview=suspects.stream().anyMatch(v->!Objects.equals(((Map<?,?>)v).get("id"),currentId))&&text(provenance,"manual_source_note",2000).isBlank();
            }
        }
        String digest=text(input,"_source_digest",64);
        if(!digest.isEmpty()) {
            db.update("INSERT INTO production_source(site_id,document_kind,digest,document_id) VALUES(?,?,?,NULL) ON DUPLICATE KEY UPDATE digest=digest",context.site(),kind,digest);
            var source=rows("SELECT document_id FROM production_source WHERE site_id=? AND document_kind=? AND digest=? FOR UPDATE",context.site(),kind,digest).getFirst();
            if(source.get("document_id")!=null) {
                long original=Long.parseLong(source.get("document_id").toString());
                if(!businessKey.isEmpty()&&!businessKey.equals(sourceKey(json.valueToTree(document(context,kind,original,false)))))throw new ProductionError(409,"file_source_conflict","完全相同文件已属于另一来源，请核对；不同批次请使用包含真实来源字段的v2模板。");
                if(id!=null && id!=original)throw new ProductionError(409,"source_target_conflict","该来源已关联另一张单据。");
                var prior=detail(context,kind,original);complete(context,token,prior);return prior;
            }
        }
        if(sourceOriginal!=null&&(id==null||!id.equals(sourceOriginal))) {
            var prior=detail(context,kind,sourceOriginal);
            if(!digest.isEmpty())db.update("UPDATE production_source SET document_id=? WHERE site_id=? AND document_kind=? AND digest=?",sourceOriginal,context.site(),kind,digest);
            complete(context,token,prior);return prior;
        }
        if(duplicateReview)throw new ProductionError(409,"suspected_duplicate_review_required","发现同日期/SKU/数量记录，请核对候选并填写人工来源及区别说明后重试；相同数量不等于重复事件。");
        Set<Long> locked=kind.equals("shipments")?shipmentOrders(context,id,input):new TreeSet<>();
        for(long order:locked)document(context,"orders",order,true);
        for(var expected:input.path("_order_revisions").properties()) {
            long order=positive(json.getNodeFactory().textNode(expected.getKey()),"订单");
            if(!locked.contains(order)||!document(context,"orders",order,false).get("revision").toString().equals(expected.getValue().asText()))throw new ProductionError(409,"revision_conflict","关联订单在预览后已变化，请重新预览并核对当前数量和跟进状态。");
        }
        Map<String,Object> before=id==null?null:document(context,kind,id,true);
        if(kind.equals("shipments") && !locked.containsAll(shipmentOrders(context,id,input)))throw new ProductionError(409,"revision_conflict","关联已变化，请刷新后重新更正。");
        if(id!=null && positive(input.get("expected_revision"),"修订号")!=Long.parseLong(before.get("revision").toString()))throw new ProductionError(409,"revision_conflict","记录已被修改，请刷新后核对当前版本。");
        Map<Long,Map<String,Object>> relatedBefore=new LinkedHashMap<>();
        for(long order:locked){var snapshot=detail(context,"orders",order);snapshot.remove("history");relatedBefore.put(order,snapshot);}
        boolean oldConfirmed=before!=null && before.get("status").equals("CONFIRMED");
        boolean stockAttribution=kind.equals("shipments")&&action.equals("allocation-corrections")&&oldConfirmed&&"WAREHOUSE_DISPATCH".equals(before.get("dispatch_purpose"));
        if(kind.equals("shipments") && oldConfirmed&&!stockAttribution){
            long dependent=db.queryForObject("SELECT (SELECT COUNT(*) FROM destination_receipt WHERE site_id=? AND shipment_id=? AND status IN ('DRAFT','POSTED'))+(SELECT COUNT(*) FROM destination_receipt_settlement x JOIN destination_shipment_binding b ON b.site_id=x.site_id AND b.id=x.binding_id WHERE b.site_id=? AND b.shipment_id=? AND x.status='ACTIVE')",Long.class,context.site(),id,context.site(),id);
            long fba=db.queryForObject("SELECT COUNT(*) FROM fba_reference WHERE site_id=? AND shipment_id=?",Long.class,context.site(),id);
            if(dependent>0||fba>0)throw new ProductionError(409,"destination_receipt_dependency","已有目的仓接收草稿、已过账接收、FBA货件或少收结案；请先按下游依赖处理，不能直接更正或作废出货。");
            db.update("UPDATE destination_shipment_binding SET is_active=FALSE WHERE site_id=? AND shipment_id=? AND is_active=TRUE",context.site(),id);
        }
        if(before!=null && before.get("status").equals("VOID"))throw new ProductionError(409,"document_void","已作废记录不能重新编辑。");
        String reason=text(input,"reason",2000);
        if(Set.of("correct","void","demand-changes","close-tracking","reopen-tracking","allocation-corrections").contains(action) && reason.isBlank())throw new ProductionError(422,"reason_required","请填写更正或作废原因。");
        if(Set.of("correct","demand-changes","close-tracking","reopen-tracking","allocation-corrections","production-progress","complete-production","reopen-production").contains(action) && !oldConfirmed)throw new ProductionError(409,"invalid_state","只有已确认记录可以更正或跟进。");
        if(action.equals("update") && oldConfirmed)throw new ProductionError(409,"correction_required","已确认记录请使用更正操作。");
        if(action.equals("confirm") && oldConfirmed)throw new ProductionError(409,"already_confirmed","记录已经确认。");
        Map<String,Object> oldSnapshot=id==null?null:detail(context,kind,id);if(oldSnapshot!=null)oldSnapshot.remove("history");
        if(Set.of("complete-production","reopen-production").contains(action)) {
            boolean completing=action.equals("complete-production");
            boolean completed="COMPLETED".equals(oldSnapshot.get("production_completion_state"));
            if(completing==completed)throw new ProductionError(409,"production_completion_unchanged","完成状态已发生变化，请重新读取后核对。");
            if(completing&&!Boolean.TRUE.equals(oldSnapshot.get("production_completion_ready")))throw new ProductionError(409,"production_completion_not_ready","仍有规格的生产或入库数量未达到下单数量，请先核对实际数量。");
            if(reason.isBlank())reason=completing?"用户确认生产与入库已完成":"用户恢复生产跟进";
            db.update("UPDATE production_order SET revision=revision+1 WHERE site_id=? AND id=?",context.site(),id);
            var result=detail(context,kind,id);result.remove("history");
            result.put("production_completion_state",completing?"COMPLETED":"OPEN");
            record(context,kind,id,token,reason,completing?"COMPLETE_PRODUCTION":"REOPEN_PRODUCTION","",oldSnapshot,result);
            var delivered=detail(context,kind,id);complete(context,token,delivered);return delivered;
        }
        if(action.equals("delete")) {
            if(oldConfirmed)throw new ProductionError(409,"cannot_delete_confirmed","已确认记录不能删除。");
            if(kind.equals("orders")) {
                for(var line:rows("SELECT id FROM production_order_line WHERE site_id=? AND order_id=?",context.site(),id))requireNoShipment(context.site(),Long.parseLong(line.get("id").toString()));
                // A referenced draft is retained rather than cascading away another document.
                long count=db.queryForObject("SELECT COUNT(*) FROM production_shipment_allocation a JOIN production_order_line l ON l.site_id=a.site_id AND l.id=a.order_line_id WHERE l.site_id=? AND l.order_id=?",Long.class,context.site(),id);
                if(count>0)throw new ProductionError(409,"draft_referenced","仍有出货草稿引用，请先修改对应草稿。");
                db.update("DELETE FROM production_order_line WHERE site_id=? AND order_id=?",context.site(),id);
            } else {
                db.update("UPDATE production_shipment_source_line SET replaces_source_id=NULL WHERE site_id=? AND shipment_id=?",context.site(),id);
                db.update("DELETE a FROM production_shipment_allocation a JOIN production_shipment_source_line x ON x.site_id=a.site_id AND x.id=a.source_line_id WHERE x.site_id=? AND x.shipment_id=?",context.site(),id);
                db.update("DELETE FROM production_shipment_source_line WHERE site_id=? AND shipment_id=?",context.site(),id);
            }
            db.update("DELETE FROM "+table+" WHERE site_id=? AND id=?",context.site(),id);
            var result=Map.of("deleted",true,"id",id.toString());complete(context,token,result);return result;
        }
        boolean confirmed=oldConfirmed || action.equals("confirm") || (action.equals("create") && text(input,"save_mode",16).equals("confirm"));
        if(confirmed && !action.equals("void") && !(authorityMode.equals("demo_fixed")||authorityMode.equals("qa_catalog")||catalogAuthority.enabled()))throw new ProductionError(503,"catalog_confirmation_disabled","真实主档确认合同尚未接入；仅允许草稿。");
        String effective=Set.of("demand-changes","production-progress").contains(action)?text(input,"effective_date",10):"";
        if(Set.of("demand-changes","production-progress").contains(action) && effective.isEmpty())throw new ProductionError(422,"effective_date_required","请填写业务生效日期。");
        if(!effective.isEmpty())date(effective);
        if(kind.equals("shipments")&&oldConfirmed)requireOpenShipmentLinks(context,id);
        if(action.equals("production-progress")) {
            saveProgress(context,id,input,reason);
        } else if(action.equals("close-tracking")||action.equals("reopen-tracking")) {
            if(action.equals("close-tracking"))inventory.requireReservationsHandled(context.site(),id);
            tracking(context,id,input,action.equals("close-tracking"));
        } else if(action.equals("void")) {
            if(!oldConfirmed)throw new ProductionError(409,"invalid_state","草稿可删除，作废只适用于已确认记录。");
            if(kind.equals("orders")){inventory.requireReservationsHandled(context.site(),id);for(var line:orderLines(context.site(),id))requireNoShipment(context.site(),Long.parseLong(line.get("id").toString()));}
            db.update("UPDATE "+table+" SET status='VOID',revision=revision+1 WHERE site_id=? AND id=?",context.site(),id);
        } else {
            JsonNode body=input;
            if(action.equals("confirm")||action.equals("demand-changes")||action.equals("allocation-corrections"))body=json.valueToTree(oldSnapshot);
            if(action.equals("demand-changes"))((ObjectNode)body).set("lines",input.path("lines"));
            if(action.equals("allocation-corrections")) {
                for(String field:List.of("warehouse_id","owner_id"))if(input.hasNonNull(field)&&!input.path(field).asText().equals(Objects.toString(oldSnapshot.get(field),"")))throw new ProductionError(422,"allocation_only","归属调整不能改变原出货仓库或货主。");
                if(input.path("sources").size()!=body.path("sources").size())throw new ProductionError(422,"allocation_only","归属调整必须保留全部来源行。");
                for(JsonNode source:input.path("sources")){JsonNode old=null;for(JsonNode prior:body.path("sources"))if(prior.path("id").asText().equals(source.path("id").asText()))old=prior;
                    if(old==null || !old.path("sku_id").asText().equals(source.path("sku_id").asText()) || !old.path("actual_units").asText().equals(source.path("actual_units").asText()) || source.has("plan_id") && !old.path("plan_id").asText().equals(source.path("plan_id").asText()) || source.has("fulfillment_mode") && !fulfillmentMode(old).equals(fulfillmentMode(source)))throw new ProductionError(422,"allocation_only","归属调整不能改变来源身份、SKU、出货来源、计划或实际数量。");}
                ((ObjectNode)body).set("sources",input.path("sources"));
            }
            // The trusted adapter supplies fresh identity data even for an existing draft confirmation.
            if(action.equals("confirm")||action.equals("demand-changes")||action.equals("allocation-corrections"))((ObjectNode)body).set("_catalog",input.path("_catalog"));
            ObjectNode effectiveBody=(ObjectNode)body.deepCopy();
            for(var field:SOURCE_FIELDS.entrySet()) {
                String value=body.has(field.getKey())?text(body,field.getKey(),field.getValue()):before==null?"":Objects.toString(before.get(field.getKey()),"");
                if(oldConfirmed&&!field.getKey().equals("manual_source_note")&&!value.equals(Objects.toString(before.get(field.getKey()),"")))throw new ProductionError(409,"source_identity_immutable","已确认可靠来源身份保留，不能通过一般更正换成另一事件。");
                effectiveBody.put(field.getKey(),value);
            }
            if(kind.equals("shipments"))effectiveBody.put("dispatch_purpose",body.has("dispatch_purpose")?text(body,"dispatch_purpose",32):before==null?"LEGACY_UNCLASSIFIED":before.get("dispatch_purpose").toString());
            body=effectiveBody;sourceKey(body);validatePurpose(kind,body,confirmed);
            if(kind.equals("shipments")&&oldConfirmed&&!Objects.equals(before.get("dispatch_purpose"),text(body,"dispatch_purpose",32))&&(Objects.equals(before.get("dispatch_purpose"),"LOGISTICS_TRANSFER")||text(body,"dispatch_purpose",32).equals("LOGISTICS_TRANSFER")))throw new ProductionError(409,"transfer_purpose_immutable","已确认仓间发运与订单发运不能互相转换，请保留原腿和历史。");
            String date=text(body,"business_date",10);LocalDate parsed=null;
            try{if(!date.isEmpty())parsed=LocalDate.parse(date);}catch(java.time.DateTimeException error){throw new ProductionError(422,"invalid_date","业务日期格式无效。");}
            if(confirmed && parsed==null)throw new ProductionError(422,"date_required","确认前请填写业务日期。");
            String business=text(body,"business_number",120),notes=text(body,"notes",2000),status=confirmed?"CONFIRMED":"DRAFT";
            if(id==null){db.update("INSERT INTO "+table+"(site_id,system_number,business_number,business_date,notes,status) VALUES(?,?,?,?,?,?)",context.site(),(kind.equals("orders")?"PO-":"SH-")+UUID.randomUUID().toString(),business,parsed,notes,status);id=insertedId();}
            else db.update("UPDATE "+table+" SET business_number=?,business_date=?,notes=?,status=?,revision=revision+1 WHERE site_id=? AND id=?",business,parsed,notes,status,context.site(),id);
            if(kind.equals("orders")){if(oldConfirmed&&Set.of("correct","demand-changes").contains(action))inventory.requireReservationsHandled(context.site(),id);saveOrder(context,id,body,confirmed,action);}else saveShipment(context,id,body,confirmed);
            saveWorkbench(context,kind,id,body,before,confirmed);
            for(var field:SOURCE_FIELDS.entrySet())db.update("UPDATE "+table+" SET "+field.getKey()+"=? WHERE site_id=? AND id=?",text(body,field.getKey(),field.getValue()),context.site(),id);
            db.update("UPDATE "+table+" SET source_signature=? WHERE site_id=? AND id=?",contentHash(kind,body,false),context.site(),id);
            if(kind.equals("shipments"))db.update("UPDATE production_shipment SET dispatch_purpose=? WHERE site_id=? AND id=?",text(body,"dispatch_purpose",32),context.site(),id);
        }
        if(!businessKey.isEmpty())db.update("UPDATE production_business_source SET document_id=? WHERE site_id=? AND document_kind=? AND source_key=?",id,context.site(),kind,businessKey);
        Map<String,Object> result=detail(context,kind,id);result.remove("history");
        if(kind.equals("shipments")){
            if(input.hasNonNull("warehouse_id")){
                long warehouse=positive(input.get("warehouse_id"),"仓库"),owner=input.hasNonNull("owner_id")?positive(input.get("owner_id"),"货权"):1;
                db.update("UPDATE production_shipment SET warehouse_id=?,owner_id=? WHERE site_id=? AND id=?",warehouse,owner,context.site(),id);result.put("warehouse_id",Long.toString(warehouse));result.put("owner_id",Long.toString(owner));
            }
            if(stockAttribution){
                // Attribution changes metadata only. Existing receipt allocations retain their stable bindings.
                db.update("UPDATE destination_shipment_binding SET shipment_revision=? WHERE site_id=? AND shipment_id=? AND is_active=TRUE",result.get("revision"),context.site(),id);
                db.update("UPDATE fba_reference SET shipment_revision=? WHERE site_id=? AND shipment_id=?",result.get("revision"),context.site(),id);
                db.update("UPDATE shipment_transport SET shipment_revision=? WHERE site_id=? AND shipment_id=? AND shipment_revision=?",result.get("revision"),context.site(),id,oldSnapshot.get("revision"));
            }else{
                if(confirmed||oldConfirmed)inventory.shipment(context,id,oldConfirmed,oldSnapshot,result,token,reason.isBlank()?"订单实际发货":reason);
                if(confirmed||oldConfirmed)new DestinationReceiptBindingStore(db,json).syncBatch(context,id,Long.parseLong(result.get("revision").toString()),result.get("status").toString());
            }
        }
        String explanation=text(input,"overage_reason",2000);if(explanation.isBlank())explanation=reason;
        if(kind.equals("orders")) {
            BigInteger oldOver=oldSnapshot==null?BigInteger.ZERO:new BigInteger(oldSnapshot.get("overage_units").toString());
            if(new BigInteger(result.get("overage_units").toString()).compareTo(oldOver)>0 && explanation.isBlank())throw new ProductionError(422,"overage_reason_required","预计减少造成超发，请填写原因。");
        } else if(confirmed||oldConfirmed) {
            for(long order:locked){var after=detail(context,"orders",order);after.remove("history");var old=relatedBefore.get(order);
                if(new BigInteger(after.get("overage_units").toString()).compareTo(new BigInteger(old.get("overage_units").toString()))>0 && explanation.isBlank())throw new ProductionError(422,"overage_reason_required","累计超过预计，请填写真实超发说明。");
                db.update("UPDATE production_order SET revision=revision+1 WHERE site_id=? AND id=?",context.site(),order);after.put("revision",document(context,"orders",order,false).get("revision"));record(context,"orders",order,token,explanation,"SHIPMENT_ALLOCATION_CHANGE","",old,after);
            }
        }
        String operation=switch(action){case "create" -> confirmed?"CREATE_CONFIRMED":"CREATE";case "update" -> "UPDATE_DRAFT";case "confirm" -> "CONFIRM";case "void" -> "VOID";case "demand-changes" -> "DEMAND_CHANGE";case "production-progress" -> "PRODUCTION_PROGRESS";case "close-tracking" -> "CLOSE_TRACKING";case "reopen-tracking" -> "REOPEN_TRACKING";case "allocation-corrections" -> "ALLOCATION_CORRECTION";default -> kind.equals("orders")?"DATA_CORRECTION":"SHIPMENT_CORRECTION";};
        if(action.equals("production-progress")) {
            boolean quantityChanged=false;for(JsonNode line:input.path("lines"))if(line.has("produced_units"))quantityChanged=true;
            if(!quantityChanged){operation="PRODUCTION_STATUS";effective="";}
        }
        record(context,kind,id,token,explanation,operation,effective,oldSnapshot,result);
        if(!digest.isEmpty())db.update("UPDATE production_source SET document_id=? WHERE site_id=? AND document_kind=? AND digest=?",id,context.site(),kind,digest);
        var delivered=detail(context,kind,id);complete(context,token,delivered);return delivered;
    }
    @Transactional(readOnly=true)
    public Object factories(ProductionContext context,String q,int page) {
        return directoryList(context,"factories",q,"ACTIVE",page,"","");
    }
    @Transactional(isolation=Isolation.READ_COMMITTED)
    public Object createFactory(ProductionContext context,String key,JsonNode input) {
        return directorySave(context,"factories",null,key,input);
    }
    @Transactional(readOnly=true)
    public Object directoryList(ProductionContext c,String kind,String q,String status,int page,String type,String country){return new ProductionDirectory(db,json).list(c,kind,q,status,page,type,country);}
    @Transactional(readOnly=true)
    public Map<String,Object> directoryDetail(ProductionContext c,String kind,long id){return new ProductionDirectory(db,json).detail(c,kind,id,true);}
    @Transactional(isolation=Isolation.READ_COMMITTED)
    public Object directorySave(ProductionContext c,String kind,Long id,String key,JsonNode input){
        c.requireWrite();inventory.lockSite(c.site());var saved=begin(c,"directory/"+kind+"/"+id,key,input);
        if(saved.get("result")!=null)return json.readTree(saved.get("result").toString());
        Object result=new ProductionDirectory(db,json).save(c,kind,id,input);complete(c,key,result);return result;
    }
    private Map<String,Object> begin(ProductionContext context,String path,String key,JsonNode input) {
        if(!input.isObject())throw new ProductionError(422,"invalid_command","命令必须是JSON对象。");
        String token=text(input,"operation_token",36);
        try{if(UUID.fromString(token).version()!=4||!UUID.fromString(token).toString().equals(token)||!token.equals(key))throw new IllegalArgumentException();}catch(IllegalArgumentException e){throw new ProductionError(422,"idempotency_key_mismatch","操作ID与Idempotency-Key必须一致。");}
        String fingerprint=fingerprint(path,input);
        db.update("INSERT INTO production_command(site_id,actor_id,operation_token,fingerprint) VALUES(?,?,?,?) ON DUPLICATE KEY UPDATE operation_token=operation_token",context.site(),context.actor(),token,fingerprint);
        var stored=rows("SELECT fingerprint,result FROM production_command WHERE site_id=? AND actor_id=? AND operation_token=? FOR UPDATE",context.site(),context.actor(),token).getFirst();
        if(!stored.get("fingerprint").equals(fingerprint))throw new ProductionError(409,"idempotency_content_conflict","同一操作ID不能用于不同内容。");
        return stored;
    }
    private void saveProgress(ProductionContext context,long id,JsonNode input,String reason) {
        JsonNode lines=input.path("lines");if(!lines.isArray()||lines.isEmpty()||lines.size()>500)throw new ProductionError(422,"invalid_lines","请选择需要更新的订单明细。");
        var existing=orderLines(context.site(),id);var seen=new HashSet<Long>();
        for(JsonNode line:lines){
            long lineId=positive(line.get("order_line_id"),"订单明细");if(!seen.add(lineId))throw new ProductionError(422,"duplicate_order_line","同一明细不能重复更新。");
            var target=existing.stream().filter(l->l.get("id").toString().equals(Long.toString(lineId))).findFirst().orElseThrow(()->new ProductionError(409,"order_link_invalid","明细不属于当前订单。"));
            requireOpenLine(context.site(),lineId);
            if(!line.has("produced_units")&&!line.has("production_status"))throw new ProductionError(422,"progress_change_required","请填写生产数量或生产状态。");
            if(line.has("production_status")) {
                if(!line.get("production_status").isTextual())throw new ProductionError(422,"production_status_invalid","生产状态须为64字以内的文字。");
                String label=text(line,"production_status",64).strip();
                db.update("UPDATE production_order_line SET production_status=? WHERE site_id=? AND id=?",label,context.site(),lineId);
            }
            if(!line.has("produced_units"))continue;
            String amount=text(line,"produced_units",19);if(!amount.matches("0|[1-9][0-9]{0,18}"))throw new ProductionError(422,"invalid_integer","累计实际生产数量须为非负整数；未知请不要提交。");
            long produced;try{produced=Long.parseLong(amount);}catch(NumberFormatException e){throw new ProductionError(422,"integer_out_of_range","累计生产数量超出支持范围。");}
            if((target.get("produced_units")!=null&&produced<Long.parseLong(target.get("produced_units").toString())||produced>Long.parseLong(target.get("expected_units").toString()))&&reason.isBlank())throw new ProductionError(422,"reason_required","更正减少或超计划生产需填写原因。");
            db.update("UPDATE production_order_line SET produced_units=? WHERE site_id=? AND id=?",produced,context.site(),lineId);
        }
        db.update("UPDATE production_order SET revision=revision+1 WHERE site_id=? AND id=?",context.site(),id);
    }
    private void saveWorkbench(ProductionContext context,String kind,long id,JsonNode input,Map<String,Object> before,boolean confirmed) {
        String destination=input.has("destination")?text(input,"destination",255).trim():before==null?"":Objects.toString(before.get("destination"),"");
        Object destinationId=before==null?null:before.get("destination_id"),destinationType=before==null?null:before.get("destination_type");
        if(input.has("destination_id")) {
            destinationId=input.hasNonNull("destination_id")?positive(input.get("destination_id"),"收货地点"):null;
            destinationType=destinationId==null?null:text(input,"destination_type",16);
            if(destinationId!=null){
                var place=new ProductionDirectory(db,json).detail(context,"warehouses",Long.parseLong(destinationId.toString()),false);
                String expected=place.get("type").equals("LOCATION")?"LOCATION":"WAREHOUSE";
                if(!expected.equals(destinationType))throw new ProductionError(422,"destination_type_invalid","收货地点类型与档案不一致。");
                boolean same=before!=null&&Objects.equals(before.get("destination_id"),destinationId.toString());
                if(!place.get("status").equals("ACTIVE")&&!same)throw new ProductionError(409,"destination_inactive","该收货地点已停用，不能用于新批次。");
                if(!same)destination=place.get("name").toString();
            }
        }
        db.update("UPDATE "+table(kind)+" SET destination=?,destination_type=?,destination_id=? WHERE site_id=? AND id=?",destination,destinationType,destinationId,context.site(),id);
        if(kind.equals("orders")) {
            Object factory=before==null?null:before.get("factory_id"),warehouse=before==null?null:before.get("receipt_warehouse_id"),owner=before==null?null:before.get("receipt_owner_id");
            if(input.has("factory_id"))factory=input.hasNonNull("factory_id")?positive(input.get("factory_id"),"工厂"):null;
            if(factory!=null&&db.queryForObject("SELECT COUNT(*) FROM production_factory WHERE site_id=? AND id=?",Long.class,context.site(),factory)==0)throw new ProductionError(409,"factory_scope_invalid","工厂不存在或不属于当前站点。");
            if(factory!=null&&db.queryForObject("SELECT COUNT(*) FROM production_factory WHERE site_id=? AND id=? AND status='ACTIVE'",Long.class,context.site(),factory)==0&&(before==null||!Objects.equals(before.get("factory_id"),factory.toString())||confirmed&&!"CONFIRMED".equals(before.get("status"))))throw new ProductionError(409,"factory_inactive","停用工厂不能承接或确认新生产单，历史记录仍保留。");
            if(input.has("receipt_warehouse_id")) {
                warehouse=input.hasNonNull("receipt_warehouse_id")?positive(input.get("receipt_warehouse_id"),"计划入库仓库"):null;
                owner=warehouse==null?null:input.hasNonNull("receipt_owner_id")?positive(input.get("receipt_owner_id"),"货权"):1L;
                if(warehouse!=null){
                    var target=new ProductionDirectory(db,json).detail(context,"warehouses",Long.parseLong(warehouse.toString()),false);
                    boolean established=db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",Long.class,context.site(),warehouse,owner)>0;
                    boolean ordinary=Set.of("FACTORY","OWN","THIRD_PARTY").contains(target.get("type"))||"UNCLASSIFIED".equals(target.get("type"))&&established;
                    if(!"ACTIVE".equals(target.get("status"))||!ordinary||!"1".equals(owner.toString())&&!established)throw new ProductionError(409,"warehouse_scope_invalid","请选择本站点已启用的普通仓库与有效货权。");
                }
            }
            db.update("UPDATE production_order SET factory_id=?,receipt_warehouse_id=?,receipt_owner_id=? WHERE site_id=? AND id=?",factory,warehouse,owner,context.site(),id);
        } else {
            JsonNode cartons=input.has("cartons")?input.get("cartons").deepCopy():before!=null&&before.get("cartons")!=null?json.readTree(before.get("cartons").toString()):null;
            if(cartons!=null&&!cartons.isNull()) {
                validateCartons(input.path("sources"),cartons,confirmed);
                var priorIds=new HashSet<String>();
                if(before!=null&&before.get("cartons")!=null)for(JsonNode box:json.readTree(before.get("cartons").toString()))priorIds.add(box.path("id").asText());
                var seenIds=new HashSet<String>();
                for(JsonNode box:cartons) {
                    String boxId=text(box,"id",36);
                    if(!boxId.isEmpty()&&(!priorIds.contains(boxId)||!seenIds.add(boxId)))throw new ProductionError(409,"carton_identity_invalid","箱身份不属于本单或重复，请刷新原出货记录核对。");
                    if(boxId.isEmpty())((ObjectNode)box).put("id",UUID.randomUUID().toString());
                }
                if(confirmed&&destination.isBlank())throw new ProductionError(422,"destination_required","出货装箱确认前须填写实际目的地。");
                db.update("UPDATE production_shipment SET cartons=? WHERE site_id=? AND id=?",json.writeValueAsString(cartons),context.site(),id);
            } else {
                if(before!=null&&before.get("cartons")!=null&&!json.readTree(before.get("cartons").toString()).isEmpty())throw new ProductionError(422,"packing_required","已有装箱记录不能通过省略内容解除核对；请更正箱内数量。");
                if(input.has("cartons"))db.update("UPDATE production_shipment SET cartons=NULL WHERE site_id=? AND id=?",context.site(),id);
            }
            if(confirmed&&text(input,"dispatch_purpose",32).equals("WAREHOUSE_DISPATCH")&&destination.isBlank())throw new ProductionError(422,"destination_required","确认出货前请填写实际目的地。");
        }
    }
    private void validateCartons(JsonNode sources,JsonNode cartons,boolean confirmed) {
        if(!cartons.isArray()||cartons.size()>500)throw new ProductionError(422,"invalid_cartons","装箱明细最多500箱。");
        Map<String,BigInteger> expected=new TreeMap<>(),packed=new TreeMap<>();Set<String> numbers=new HashSet<>();
        for(JsonNode source:sources)expected.merge(Long.toString(positive(source.get("sku_id"),"SKU")),BigInteger.valueOf(positive(source.get("actual_units"),"出货数量")),BigInteger::add);
        for(JsonNode box:cartons) {
            String number=text(box,"number",80).trim();if(number.isBlank()||!numbers.add(number))throw new ProductionError(422,"duplicate_carton","每箱须填写不重复的箱号。");
            JsonNode items=box.path("items");if(!items.isArray()||items.isEmpty()||items.size()>500)throw new ProductionError(422,"invalid_carton_items","每箱须有1到500条商品数量。");
            Set<String> seen=new HashSet<>();for(JsonNode item:items){String sku=Long.toString(positive(item.get("sku_id"),"SKU"));if(!expected.containsKey(sku)||!seen.add(sku))throw new ProductionError(422,"carton_sku_invalid","箱内商品须属于本次出货，同一箱不能重复同一SKU。");packed.merge(sku,BigInteger.valueOf(positive(item.get("units"),"装箱数量")),BigInteger::add);}
        }
        for(var item:packed.entrySet())if(item.getValue().compareTo(expected.get(item.getKey()))>0)throw new ProductionError(422,"carton_quantity_mismatch","装箱数量不能超过本次出货。");
        if(confirmed&&!packed.equals(expected))throw new ProductionError(422,"carton_quantity_mismatch","确认前每个SKU的装箱合计必须等于本次出货数量。");
    }
    private void complete(ProductionContext context,String token,Object result){db.update("UPDATE production_command SET result=? WHERE site_id=? AND actor_id=? AND operation_token=?",json.writeValueAsString(result),context.site(),context.actor(),token);}
}
