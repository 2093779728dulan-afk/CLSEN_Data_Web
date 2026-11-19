package com.clsen.dataweb.production;

import java.io.*;
import java.math.BigInteger;
import java.security.MessageDigest;
import java.time.LocalDate;
import java.util.*;
import org.apache.poi.ss.usermodel.*;
import org.apache.poi.xssf.usermodel.XSSFWorkbook;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/** Explicit v1/v2 templates. Preview has no business write; confirm uses the manual command core. */
@Service
public class ProductionFiles {
    private final JdbcTemplate db; private final ProductionService service; private final ObjectMapper json;
    private static final List<String> ORDER_HEADERS=List.of("业务订单号（可选）","下单日期","SKU","预计数量","备注");
    private static final List<String> SHIP_HEADERS=List.of("业务出货单号（可选）","实际出货日期","对应系统订单号","SKU","本次实际出货数量","备注");
    public ProductionFiles(JdbcTemplate db,ProductionService service,ObjectMapper json){this.db=db;this.service=service;this.json=json;}
    private static String name(String kind){ProductionService.table(kind);return kind.equals("orders")?"预计订单_v1":"实际出货_v1";}
    private static List<String> headers(String kind){return kind.equals("orders")?ORDER_HEADERS:SHIP_HEADERS;}
    private static final List<String> PROVENANCE_FIELDS=List.of("source_system","source_event_kind","external_event_id","source_batch","manual_source_note");
    private static List<String> headers(String kind,String version){var heads=new ArrayList<>(headers(kind));if(version.equals("v3"))heads.set(2,"商品规格ID");if(!version.equals("v1")){heads.addAll(List.of("来源单位/系统","来源事件类别","外部事件号","来源批次（可选）","人工来源说明"));if(kind.equals("shipments"))heads.add("发运用途");}return heads;}
    private static String cell(Row row,int index) {
        Cell c=row.getCell(index);if(c==null || c.getCellType()==CellType.BLANK)return "";
        if(c.getCellType()==CellType.FORMULA)throw new ProductionError(422,"formula_forbidden","标准模板不允许公式，请粘贴明确的值。");
        if(c.getCellType()==CellType.NUMERIC) {
            if(DateUtil.isCellDateFormatted(c))return c.getLocalDateTimeCellValue().toLocalDate().toString();
            double n=c.getNumericCellValue();
            if(n!=Math.rint(n) || Math.abs(n)>9007199254740991d)throw new ProductionError(422,"unsafe_excel_number","数量必须为整数；超出Excel安全精度时请使用文本单元格。");
            return String.format(java.util.Locale.ROOT,"%.0f",n);
        }
        if(c.getCellType()!=CellType.STRING)throw new ProductionError(422,"invalid_cell","请使用文字、日期或整数单元格。");
        return c.getStringCellValue().trim();
    }
    @Transactional(isolation=org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public Object preview(ProductionContext context,String kind,JsonNode input) {
        context.requireWrite();name(kind);
        byte[] bytes;
        try{bytes=Base64.getDecoder().decode(ProductionService.text(input,"file_base64",2800000));}catch(IllegalArgumentException e){throw new ProductionError(422,"invalid_file","文件编码无效。");}
        if(bytes.length==0 || bytes.length>2_000_000)throw new ProductionError(413,"file_too_large","请选择不超过2MB的标准XLSX文件。");
        String filename=ProductionService.text(input,"filename",255),mode=ProductionService.text(input,"mode",16);
        if(!Set.of("create","correct").contains(mode))throw new ProductionError(422,"invalid_mode","请选择新增或更正。");
        Long target=mode.equals("correct")?ProductionService.positive(input.get("target_id"),"目标单据"):null;
        boolean workbench=input.path("workbench_order").asBoolean(false);
        if(workbench&&(!kind.equals("orders")||target!=null))throw new ProductionError(422,"invalid_mode","新版表格下单仅用于新增订单草稿。");
        Map<String,Object> before=target==null?null:service.get(context,kind,target);
        if(before!=null && !before.get("status").equals("CONFIRMED"))throw new ProductionError(409,"invalid_state","文件更正只能选择已确认单据。");
        String reason=ProductionService.text(input,"reason",2000);
        List<Map<String,Object>> issues=new ArrayList<>();List<Map<String,Object>> parsed=new ArrayList<>();
        String business=null,date=null,version="v1"; List<String> notes=new ArrayList<>();Map<String,String> provenance=new LinkedHashMap<>();
        try(XSSFWorkbook book=new XSSFWorkbook(new ByteArrayInputStream(bytes))) {
            if(book.getNumberOfSheets()==1&&book.getSheetName(0).equals(name(kind).replace("v1","v2")))version="v2";
            if(book.getNumberOfSheets()==1&&book.getSheetName(0).equals(name(kind).replace("v1","v3"))&&kind.equals("orders")&&workbench)version="v3";
            if(book.getNumberOfSheets()!=1 || !book.getSheetName(0).equals(name(kind).replace("v1",version)) || !book.getExternalLinksTable().isEmpty())throw new ProductionError(422,"invalid_template","请选择当前入口支持的标准数据页，不能包含外部链接；规格ID模板仅用于新版下单。");
            Sheet sheet=book.getSheetAt(0);Row head=sheet.getRow(0);List<String> h=headers(kind,version);
            if(head==null || head.getLastCellNum()!=h.size())throw new ProductionError(422,"invalid_header","模板表头列数不一致。");
            for(int i=0;i<h.size();i++)if(!cell(head,i).equals(h.get(i)) && !(i==0 && cell(head,i).equals(h.get(i).replace("（可选）",""))))throw new ProductionError(422,"invalid_header","请保持对应版本模板的标准表头。");
            if(sheet.getLastRowNum()>500)throw new ProductionError(422,"too_many_rows","一份文件最多500条数据行。");
            for(int r=1;r<=sheet.getLastRowNum();r++) {
                Row row=sheet.getRow(r);if(row==null)continue;
                try {
                    List<String> v=new ArrayList<>();for(int col=0;col<h.size();col++)v.add(cell(row,col));
                    if(v.stream().allMatch(String::isEmpty))continue;
                    if(row.getLastCellNum()>h.size())throw new ProductionError(422,"extra_columns","存在额外数据列。");
                    String bn=v.get(0),dt=v.get(1);LocalDate.parse(dt);if(bn.length()>120)throw new ProductionError(422,"invalid_number","业务单号最多120个字符。");
                    if(business==null){business=bn;date=dt;}else if(!business.equals(bn) || !date.equals(dt))throw new ProductionError(422,"mixed_documents","一份文件只能包含同一业务号和日期的单据。");
                    int skuCol=kind.equals("orders")?2:3;String code=v.get(skuCol);JsonNode identity=input.path(version.equals("v3")?"_catalog":"_resolved_codes").get(code);
                    if(identity==null || !identity.path("status").asText().equals("active"))throw new ProductionError(422,"unknown_sku",version.equals("v3")?"商品规格ID不属于本站可用商品，请核对填写参考："+code:"编码未唯一关联到可用商品；待补码请改用商品选择："+code);
                    String qty=v.get(skuCol+1);ProductionService.positive(json.getNodeFactory().textNode(qty),"数量");
                    var item=new LinkedHashMap<String,Object>();item.put("sku_id",identity.path("sku_id").asText());item.put("sku_label",identity.path("label").asText());
                    if(kind.equals("orders"))item.put("expected_units",qty);
                    else {
                        String number=v.get(2);
                        var matches=db.queryForList("SELECT l.id FROM production_order o JOIN production_order_line l ON l.site_id=o.site_id AND l.order_id=o.id WHERE o.site_id=? AND o.system_number=? AND o.status='CONFIRMED' AND l.sku_id=? AND l.is_active=TRUE",context.site(),number,identity.path("sku_id").asText());
                        if(matches.size()!=1)throw new ProductionError(422,"unknown_order","系统订单号不存在或没有对应已确认SKU："+number);
                        item.put("order_line_id",matches.getFirst().get("id").toString());item.put("units",qty);item.put("order_number",number);
                    }
                    if(!version.equals("v1")) {
                        var current=new LinkedHashMap<String,String>();int offset=headers(kind).size();
                        var fields=new ArrayList<>(PROVENANCE_FIELDS);if(kind.equals("shipments"))fields.add("dispatch_purpose");
                        for(int n=0;n<fields.size();n++){Cell c=row.getCell(offset+n);String value=c==null||c.getCellType()==CellType.BLANK?"":c.getCellType()==CellType.STRING?c.getStringCellValue():null;if(value==null)throw new ProductionError(422,"invalid_source_field","来源字段必须使用原始文本，不能使用公式或数字。");current.put(fields.get(n),value);}
                        if(provenance.isEmpty())provenance.putAll(current);else if(!provenance.equals(current))throw new ProductionError(422,"mixed_sources","同一文件各行必须使用相同单据来源及发运用途。");
                    }
                    parsed.add(item);String note=v.get(skuCol+2);if(!note.isBlank())notes.add(note);
                } catch(ProductionError e){issues.add(Map.of("row",r+1,"message",e.getMessage()));}
                catch(java.time.DateTimeException e){issues.add(Map.of("row",r+1,"message","日期格式应为YYYY-MM-DD。"));}
            }
        }catch(ProductionError e){throw e;}catch(IOException|RuntimeException e){throw new ProductionError(422,"invalid_xlsx","文件不能按标准XLSX读取。");}
        JsonNode original=input.path("_order_source");
        if(!original.isMissingNode()) {
            if(!workbench||!kind.equals("orders")||target!=null)throw new ProductionError(422,"invalid_mode","四字段下单表仅用于新版订单草稿预览。");
            var sourceRows=original.path("rows");
            for(var issue:issues) {
                int index=Integer.parseInt(issue.get("row").toString())-2;
                if(index>=0&&index<sourceRows.size()) {
                    // Replace canonical row numbers with physical locations in the unchanged original.
                    int physical=sourceRows.get(index).path("source_row").asInt();
                    int at=issues.indexOf(issue);issues.set(at,Map.of("row",physical,"sheet",original.path("sheet").asText(),"message",issue.get("message")));
                }
            }
            for(JsonNode issue:original.path("issues"))issues.add(json.convertValue(issue,Map.class));
            try{bytes=Base64.getDecoder().decode(ProductionService.text(input,"_original_file_base64",2800000));}catch(IllegalArgumentException e){throw new ProductionError(422,"invalid_file","原始下单表编码无效。");}
            if(bytes.length==0||bytes.length>2_000_000)throw new ProductionError(413,"file_too_large","原始下单表必须为不超过2MB的非空文件。");
            version="order-table-v4";
        }
        if(parsed.isEmpty())issues.add(Map.of("row",0,"message","没有可导入的数据行。"));
        Map<String,Object> command=new LinkedHashMap<>();command.put("business_number",business==null?"":business);command.put("business_date",date==null?"":date);command.put("notes",String.join("；",notes));
        command.putAll(provenance);
        if(!original.isMissingNode())command.put("_source_table",original);
        String manual=ProductionService.text(input,"manual_source_note",2000);if(!manual.isBlank())command.put("manual_source_note",manual);
        command.put("overage_reason",ProductionService.text(input,"overage_reason",2000));
        if(kind.equals("orders")) {
            Set<String> seen=new HashSet<>();for(var l:parsed)if(!seen.add(l.get("sku_id").toString()))issues.add(Map.of("row",0,"message","同一订单存在重复SKU，请先合并明确数量。"));
            command.put("lines",parsed.stream().map(l->Map.of("sku_id",l.get("sku_id"),"expected_units",l.get("expected_units"))).toList());
        } else {
            Map<String,Map<String,Object>> sources=new LinkedHashMap<>();Set<String> seen=new HashSet<>();
            for(var l:parsed) {
                String sku=l.get("sku_id").toString();if(!seen.add(sku+":"+l.get("order_line_id")))issues.add(Map.of("row",0,"message","存在重复订单明细分配，请先核对。"));
                var source=sources.computeIfAbsent(sku,k->new LinkedHashMap<>(Map.of("sku_id",k,"actual_units","0","allocations",new ArrayList<Map<String,Object>>())));
                source.put("actual_units",new BigInteger(source.get("actual_units").toString()).add(new BigInteger(l.get("units").toString())).toString());
                @SuppressWarnings("unchecked") var allocations=(List<Map<String,Object>>)source.get("allocations");allocations.add(Map.of("order_line_id",l.get("order_line_id"),"units",l.get("units")));
            }
            command.put("sources",new ArrayList<>(sources.values()));
            Map<String,String> revisions=new TreeMap<>();for(var l:parsed){var order=db.queryForMap("SELECT o.id,o.revision FROM production_order o JOIN production_order_line l ON l.site_id=o.site_id AND l.order_id=o.id WHERE l.site_id=? AND l.id=?",context.site(),l.get("order_line_id"));revisions.put(order.get("id").toString(),order.get("revision").toString());}command.put("_order_revisions",revisions);
        }
        if(String.join("；",notes).length()>2000)issues.add(Map.of("row",0,"message","整单备注最多2000个字符。"));
        if(target==null)command.put("save_mode","confirm");else {command.put("expected_revision",before.get("revision"));command.put("reason",reason);if(reason.isBlank())issues.add(Map.of("row",0,"message","更正必须填写原因。"));}
        if(workbench) {
            long factory=ProductionService.positive(input.get("factory_id"),"生产工厂"),warehouse=ProductionService.positive(input.get("receipt_warehouse_id"),"计划入库仓库"),owner=ProductionService.positive(input.get("receipt_owner_id"),"货权");
            if(db.queryForObject("SELECT COUNT(*) FROM production_factory WHERE site_id=? AND id=? AND status='ACTIVE'",Long.class,context.site(),factory)==0)throw new ProductionError(409,"factory_scope_invalid","请选择本站已启用的生产工厂。");
            if(db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",Long.class,context.site(),warehouse,owner)==0)throw new ProductionError(409,"warehouse_scope_invalid","计划入库仓库/货权尚未登记。");
            command.put("save_mode","draft");command.put("factory_id",Long.toString(factory));command.put("receipt_warehouse_id",Long.toString(warehouse));command.put("receipt_owner_id",Long.toString(owner));
            String destination=ProductionService.text(input,"destination",255),type=ProductionService.text(input,"destination_type",16);
            if(input.hasNonNull("destination_id")&&!input.path("destination_id").asText().isBlank()) {
                long destinationId=ProductionService.positive(input.get("destination_id"),"计划收货地点");var place=new ProductionDirectory(db,json).detail(context,"warehouses",destinationId,false);
                if(!place.get("status").equals("ACTIVE"))throw new ProductionError(409,"destination_inactive","该收货地点已停用。");
                String expected=place.get("type").equals("LOCATION")?"LOCATION":"WAREHOUSE";
                if(!expected.equals(type))throw new ProductionError(422,"destination_type_invalid","收货地点类型与档案不一致。");
                command.put("destination_id",Long.toString(destinationId));command.put("destination_type",type);destination=place.get("name").toString();
            }
            command.put("destination",destination);
        }
        String digest;try{digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}catch(java.security.NoSuchAlgorithmException e){throw new IllegalStateException(e);}
        if(kind.equals("shipments"))for(JsonNode source:json.valueToTree(command).path("sources")) {
            if(new BigInteger(source.path("actual_units").asText()).compareTo(BigInteger.valueOf(Long.MAX_VALUE))>0)issues.add(Map.of("row",0,"message","同SKU来源数量超出支持范围。"));
        }
        Map<String,Object> sourceCheck=Map.of("candidates",List.of());
        if(issues.isEmpty())try{sourceCheck=service.checkSource(context,kind,json.valueToTree(command));}catch(ProductionError e){issues.add(Map.of("row",0,"message",e.getMessage()));}
        String id=UUID.randomUUID().toString();command.put("_source_digest",digest);
        db.update("INSERT INTO production_preview(id,site_id,actor_id,document_kind,filename,digest,file_data,command_value,issues,target_id,target_revision) VALUES(?,?,?,?,?,?,?,?,?,?,?)",id,context.site(),context.actor(),kind,filename,digest,bytes,json.writeValueAsString(command),json.writeValueAsString(issues),target,before==null?null:before.get("revision"));
        var result=new LinkedHashMap<String,Object>();result.put("preview_id",id);result.put("filename",filename);result.put("digest",digest);result.put("rows",parsed);result.put("issues",issues);result.put("command",command);result.put("before",before);result.put("template_version",version);result.put("source_check",sourceCheck);
        if(!original.isMissingNode())result.put("source_table",original);
        result.put("changes",changes(context,kind,before,command,input.path("_catalog")));
        if(kind.equals("orders")) {
            BigInteger expected=BigInteger.ZERO;for(var l:parsed)expected=expected.add(new BigInteger(l.get("expected_units").toString()));
            String actual=before==null?"0":before.get("actual_units").toString();
            result.put("quantity_preview",Map.of("expected_units",expected.toString(),"actual_units",actual,"difference_units",expected.subtract(new BigInteger(actual)).toString()));
        } else {
            BigInteger actual=BigInteger.ZERO;for(var l:parsed)actual=actual.add(new BigInteger(l.get("units").toString()));
            result.put("quantity_preview",Map.of("actual_units",actual.toString()));
            result.put("order_impact",orderImpact(context,before,command));

        }
        var duplicate=db.queryForList("SELECT document_id FROM production_source WHERE site_id=? AND document_kind=? AND digest=? AND document_id IS NOT NULL",context.site(),kind,digest);
        if(!duplicate.isEmpty()) {
            var existing=service.get(context,kind,Long.parseLong(duplicate.getFirst().get("document_id").toString()));result.put("duplicate_document",existing);result.put("changes",List.of());result.put("order_impact",List.of());
            if(target!=null && !target.toString().equals(existing.get("id").toString()))throw new ProductionError(409,"source_target_conflict","该文件来源已关联另一张单据。");
        }
        if(sourceCheck.containsKey("duplicate_document")&&Boolean.TRUE.equals(sourceCheck.get("content_matches"))) {
            @SuppressWarnings("unchecked") var known=(Map<String,Object>)sourceCheck.get("duplicate_document");
            result.put("duplicate_document",service.get(context,kind,Long.parseLong(known.get("id").toString())));result.put("changes",List.of());result.put("order_impact",List.of());
        }
        return result;
    }
    private List<Map<String,String>> changes(ProductionContext context,String kind,Map<String,Object> before,Map<String,Object> command,JsonNode catalog) {
        List<Map<String,String>> result=new ArrayList<>();
        JsonNode old=json.valueToTree(before==null?Map.of():before),next=json.valueToTree(command);
        for(String field:List.of("business_number","business_date","notes"))if(!old.path(field).asText("").equals(next.path(field).asText("")))result.add(Map.of("field",switch(field){case "business_number"->"业务单号";case "business_date"->"业务日期";default->"备注";},"before",old.path(field).asText(""),"after",next.path(field).asText(""),"change",before==null?"新增":"更改"));
        Map<String,String> prior=new LinkedHashMap<>(),updated=new LinkedHashMap<>();
        for(var pair:List.of(Map.entry(prior,old),Map.entry(updated,next))) {
            if(kind.equals("orders"))for(JsonNode line:pair.getValue().path("lines"))pair.getKey().put(catalog.path(line.path("sku_id").asText()).path("label").asText()+" 预计数量",line.path("expected_units").asText());
            else for(JsonNode source:pair.getValue().path("sources"))for(JsonNode a:source.path("allocations")) {
                String number=db.queryForObject("SELECT o.system_number FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE l.site_id=? AND l.id=?",String.class,context.site(),a.path("order_line_id").asText());
                String key=catalog.path(source.path("sku_id").asText()).path("label").asText()+" / "+number+" 分配数量";
                pair.getKey().put(key,new BigInteger(pair.getKey().getOrDefault(key,"0")).add(new BigInteger(a.path("units").asText())).toString());
            }
        }
        var keys=new LinkedHashSet<>(prior.keySet());keys.addAll(updated.keySet());
        for(String key:keys)if(!Objects.equals(prior.get(key),updated.get(key)))result.add(Map.of("field",key,"before",prior.getOrDefault(key,"—"),"after",updated.getOrDefault(key,"—"),"change",!prior.containsKey(key)?"新增":!updated.containsKey(key)?"删除":"更改"));
        return result;
    }
    private static Map<String,BigInteger> allocations(JsonNode node) {
        Map<String,BigInteger> result=new LinkedHashMap<>();
        for(JsonNode source:node.path("sources"))for(JsonNode a:source.path("allocations"))result.merge(a.path("order_line_id").asText(),new BigInteger(a.path("units").asText()),BigInteger::add);
        return result;
    }
    private List<Map<String,String>> orderImpact(ProductionContext context,Map<String,Object> before,Map<String,Object> command) {
        var prior=allocations(json.valueToTree(before==null?Map.of():before));var next=allocations(json.valueToTree(command));
        Set<String> keys=new LinkedHashSet<>(prior.keySet());keys.addAll(next.keySet());List<Map<String,String>> result=new ArrayList<>();
        for(String line:keys) {
            var match=db.queryForMap("SELECT l.order_id,l.sku_label,l.expected_units,o.system_number FROM production_order_line l JOIN production_order o ON o.site_id=l.site_id AND o.id=l.order_id WHERE l.site_id=? AND l.id=?",context.site(),line);
            var order=service.get(context,"orders",Long.parseLong(match.get("order_id").toString()));
            JsonNode current=json.valueToTree(order);String actual="0";for(JsonNode l:current.path("lines"))if(l.path("id").asText().equals(line))actual=l.path("actual_units").asText();
            BigInteger after=new BigInteger(actual).subtract(prior.getOrDefault(line,BigInteger.ZERO)).add(next.getOrDefault(line,BigInteger.ZERO));
            result.add(Map.of("order_number",match.get("system_number").toString(),"sku_label",match.get("sku_label").toString(),"before_actual",actual,"after_actual",after.toString(),"after_difference",new BigInteger(match.get("expected_units").toString()).subtract(after).toString()));
        }return result;
    }
    @Transactional
    public Object confirm(ProductionContext context,String id,String key,JsonNode input) {
        context.requireWrite();
        var matches=db.queryForList("SELECT * FROM production_preview WHERE site_id=? AND actor_id=? AND id=? FOR UPDATE",context.site(),context.actor(),id);
        if(matches.isEmpty())throw new ProductionError(404,"preview_not_found","预览不存在或不属于当前账号。");var preview=matches.getFirst();
        if(!json.readTree(preview.get("issues").toString()).isEmpty())throw new ProductionError(422,"preview_has_issues","请先处理预览问题并重新上传。");
        ObjectNode body=(ObjectNode)json.readTree(preview.get("command_value").toString());body.put("operation_token",ProductionService.text(input,"operation_token",36));body.set("_catalog",input.path("_catalog"));
        Long target=preview.get("target_id")==null?null:Long.valueOf(preview.get("target_id").toString());
        return service.command(context,preview.get("document_kind").toString(),target,target==null?"create":"correct",key,body);
    }
    public byte[] template(String kind) {return workbook(name(kind),headers(kind),List.of());}
    public byte[] template(String kind,String version) {if(!Set.of("v1","v2","v3").contains(version)||version.equals("v3")&&!kind.equals("orders"))throw new ProductionError(422,"invalid_template_version","模板版本无效。");return workbook(name(kind).replace("v1",version),headers(kind,version),List.of());}
    @Transactional(readOnly=true,isolation=org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public byte[] export(ProductionContext context,String kind,String from,String to,String shipmentFrom,String shipmentTo,String q,String status,String sku,String order) {
        return export(context,kind,from,to,shipmentFrom,shipmentTo,q,status,sku,order,"");
    }
    @Transactional(readOnly=true,isolation=org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public byte[] export(ProductionContext context,String kind,String from,String to,String shipmentFrom,String shipmentTo,String q,String status,String sku,String order,String tracking) {
        return export(context,kind,from,to,shipmentFrom,shipmentTo,q,status,sku,order,tracking,"","");
    }
    @Transactional(readOnly=true,isolation=org.springframework.transaction.annotation.Isolation.REPEATABLE_READ)
    public byte[] export(ProductionContext context,String kind,String from,String to,String shipmentFrom,String shipmentTo,String q,String status,String sku,String order,String tracking,String factory,String progress) {
        String filters="from="+from+",to="+to+",shipment_from="+shipmentFrom+",shipment_to="+shipmentTo+",q="+q+",status="+status+",sku="+sku+",order="+order+",tracking="+tracking+",factory="+factory+",progress="+progress;
        String generated=java.time.Instant.now().toString();
        if(kind.equals("summary")) {
            var summary=service.summary(context,from,to,shipmentFrom,shipmentTo,sku,order);
            @SuppressWarnings("unchecked") var items=(List<Map<String,Object>>)summary.get("items");
            return workbook("数量汇总",List.of("系统订单号","SKU","预计数量","有效出货数量","差额","出货口径","全部累计出货","当前关闭量","当前待跟进","行级超发","查询条件","生成时间UTC"),items.stream().map(l->List.of(l.get("order_number").toString(),l.get("sku_label").toString(),l.get("expected_units").toString(),l.get("actual_units").toString(),l.get("difference_units").toString(),Boolean.TRUE.equals(summary.get("shipment_period_filtered"))?"所选出货期间":"全部有效累计",l.get("cumulative_actual_units").toString(),l.get("closed_units").toString(),l.get("pending_units").toString(),l.get("overage_units").toString(),filters,generated)).toList());
        }
        List<List<String>> all=new ArrayList<>();int page=1;
        while(true) {
            var result=service.list(context,kind,q,status,from,to,sku,order,page++,100,tracking,false,factory,"","",progress);
            @SuppressWarnings("unchecked") var items=(List<Map<String,Object>>)result.get("items");
            for(var d:items)all.add(List.of(d.get("system_number").toString(),d.get("business_number").toString(),Objects.toString(d.get("business_date"),""),d.get("status").toString(),d.get("revision").toString(),Objects.toString(d.get("expected_units"),""),d.get("actual_units").toString(),Objects.toString(d.get("difference_units"),""),Objects.toString(d.get("closed_units"),""),Objects.toString(d.get("pending_units"),""),Objects.toString(d.get("overage_units"),""),filters,generated));
            if(items.size()<100)break;
        }
        if(kind.equals("shipments")){
            var purposes=new HashMap<String,String>();for(var row:db.queryForList("SELECT system_number,dispatch_purpose FROM production_shipment WHERE site_id=?",context.site()))purposes.put(row.get("system_number").toString(),row.get("dispatch_purpose").toString());
            all=all.stream().map(row->{var out=new ArrayList<>(row);out.add(purposes.get(row.getFirst()));return (List<String>)out;}).toList();
        }
        var heads=new ArrayList<>(List.of("系统单号","业务单号","业务日期","状态","修订","预计数量","实际数量","差额","当前关闭量","当前待跟进","行级超发","查询条件","生成时间UTC"));if(kind.equals("shipments"))heads.add("发运用途（仓间不累计订单）");
        return workbook(kind.equals("orders")?"预计订单导出":"实际出货导出",heads,all);
    }
    private static byte[] workbook(String name,List<String> heads,List<List<String>> rows) {
        try(XSSFWorkbook book=new XSSFWorkbook();ByteArrayOutputStream output=new ByteArrayOutputStream()) {
            Sheet sheet=book.createSheet(name);Row header=sheet.createRow(0);for(int i=0;i<heads.size();i++){header.createCell(i,CellType.STRING).setCellValue(heads.get(i));sheet.setColumnWidth(i,Math.min(60,Math.max(18,heads.get(i).length()*3))*256);}
            int n=1;for(var values:rows){Row row=sheet.createRow(n++);for(int i=0;i<values.size();i++)row.createCell(i,CellType.STRING).setCellValue(values.get(i));}
            sheet.createFreezePane(0,1);book.write(output);return output.toByteArray();
        }catch(IOException e){throw new IllegalStateException(e);}
    }
}
