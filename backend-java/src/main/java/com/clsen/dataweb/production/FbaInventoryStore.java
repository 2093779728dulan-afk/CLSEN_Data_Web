package com.clsen.dataweb.production;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Timestamp;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** Account-scoped FBA facts. Called only within InventoryService's locked transaction. */
final class FbaInventoryStore {
    private final JdbcTemplate db;
    private final ObjectMapper json;
    private final InventoryService inventory;
    FbaInventoryStore(JdbcTemplate db,ObjectMapper json,InventoryService inventory){this.db=db;this.json=json;this.inventory=inventory;}
    private static long id(JsonNode b,String field){return InventoryService.positive(b,field);}
    private static long n(Object v){return InventoryService.n(v);}
    private static ProductionError fail(String code,String message){return new ProductionError(409,code,message);}
    private static String text(JsonNode b,String field,int max){return InventoryService.text(b,field,max);}
    private static String required(JsonNode b,String field,int max){String value=text(b,field,max);if(value.isBlank())throw new ProductionError(422,"fba_field_required","请填写"+field+"及明确核对依据。");return value;}
    private static byte[] bytes(String value){return value.getBytes(StandardCharsets.UTF_8);}
    private static String fingerprint(String value){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes(value)));}catch(java.security.NoSuchAlgorithmException ex){throw new IllegalStateException(ex);}}
    private List<Map<String,Object>> rows(String sql,Object...args){return db.queryForList(sql,args).stream().map(DestinationReceiptStore::normalized).toList();}
    private long last(){return db.queryForObject("SELECT LAST_INSERT_ID()",Long.class);}
    private JsonNode node(Object value){return value instanceof JsonNode v?v:json.readTree(value.toString());}
    private String encode(Object value){return json.writeValueAsString(value);}
    private Map<String,Object> one(String sql,Object...args){var found=rows(sql,args);if(found.size()!=1)throw fail("fba_scope_conflict","记录不存在、范围不一致或来源尚未核实。");return found.getFirst();}
    static void requireScope(JdbcTemplate db,long site,long warehouse,long owner){
        if(db.queryForObject("SELECT COUNT(*) FROM fba_scope s JOIN production_warehouse w ON w.site_id=s.site_id AND w.id=s.warehouse_id WHERE s.site_id=? AND s.warehouse_id=? AND s.owner_id=? AND w.type='FBA' AND w.status='ACTIVE'",Long.class,site,warehouse,owner)!=1)
            throw fail("fba_scope_conflict","FBA逻辑仓、账号、货权未明确或已停用。");
    }
    private Map<String,Object> scope(ProductionContext c,long scope){var value=one("SELECT * FROM fba_scope WHERE site_id=? AND id=?",c.site(),scope);var opening=one("SELECT opening_metadata FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",c.site(),value.get("warehouse_id"),value.get("owner_id"));if(opening.get("opening_metadata")!=null)value.put("opening_metadata",node(opening.get("opening_metadata")));return value;}
    Object scopeContext(ProductionContext c,long id){return scope(c,id);}
    Object actionScopeContext(ProductionContext c, long id) {
        var action = one("SELECT scope_id FROM fba_action WHERE site_id=? AND id=?", c.site(), id);
        return scope(c, n(action.get("scope_id")));
    }
    private String receiptQuality(JsonNode row) {
        return switch(row.path("raw").path("Disposition").asText().trim().toUpperCase(Locale.ROOT)) {
            case "", "SELLABLE" -> "QUALIFIED";
            case "PENDING" -> "PENDING";
            case "CUSTOMER_DAMAGED","DEFECTIVE","CARRIER_DAMAGED","WAREHOUSE_DAMAGED","DISTRIBUTOR_DAMAGED","EXPIRED","UNSELLABLE" -> "DEFECTIVE";
            default -> "";
        };
    }
    private String ledgerKind(JsonNode row) {
        String type=row.path("raw").path("Event Type").asText();
        return switch(type) {
            case "Receipts","CustomerReturns" -> row.path("quantity").asText().matches("-[1-9][0-9]{0,8}") ? "CORRECTION" : type.equals("Receipts") ? "RECEIPT" : "CUSTOMER_RETURN";
            case "Adjustments","WhseTransfers","VendorReturns","Shipments" -> "ADJUSTMENT";
            default -> "UNKNOWN";
        };
    }
    private Map<String,String> snapshotCutoffs(ProductionContext c,Map<String,Object> scope) {
        var result=new HashMap<String,String>();
        for(var row:rows("""
            SELECT l.sku_id,l.quality,MAX(d.business_date) AS snapshot_on
            FROM inventory_document d JOIN JSON_TABLE(d.line_items,'$[*]' COLUMNS(
                sku_id BIGINT PATH '$.sku_id',quality VARCHAR(16) PATH '$.quality',purpose VARCHAR(32) PATH '$.purpose'
            )) l ON TRUE
            WHERE d.site_id=? AND d.warehouse_id=? AND d.owner_id=? AND d.status='POSTED'
            AND d.kind='ADJUST' AND l.purpose='COUNT'
            GROUP BY l.sku_id,l.quality
            """,c.site(),scope.get("warehouse_id"),scope.get("owner_id")))
            result.put(row.get("sku_id")+":"+row.get("quality"),row.get("snapshot_on").toString());
        if(!Boolean.parseBoolean(scope.get("simulated").toString()))for(var identity:rows("SELECT sku_id FROM fba_identity WHERE site_id=? AND scope_id=?",c.site(),scope.get("id")))result.merge(identity.get("sku_id")+":QUALIFIED",scope.get("cutoff_on").toString(),(a,b)->a.compareTo(b)>=0?a:b);
        return result;
    }
    private void checkFactDate(ProductionContext c,Map<String,Object> scope,long sku,String quality,String date) {
        inventory.checkDate(c.site(),new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),date);
        String snapshot=snapshotCutoffs(c,scope).get(sku+":"+quality);
        if(snapshot!=null&&LocalDate.parse(date).compareTo(LocalDate.parse(snapshot))<=0)
            throw fail("fba_snapshot_covered","该日期的此规格库存状态已包含在盘点快照中，原行保留核对，不能再次累计。");
    }
    private void revision(Map<String,Object> record,JsonNode b){if(n(record.get("revision"))!=id(b,"expected_revision"))throw fail("fba_revision_conflict","记录已变化，输入保留；读取最新修订后核对。");}
    private JsonNode currentIdentity(ProductionContext c,Map<String,Object> scope,JsonNode b,long sku){
        requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
        var current=inventory.identity(c.site(),b,sku);
        if(!scope.get("catalog_version").equals(current.path("catalog_version").asText()))throw fail("fba_catalog_conflict","本范围的已确认目录与当前目录不一致，请先核对商品映射，不能沿用过期身份过账。");
        return current;
    }
    private void connectApprovedProducts(ProductionContext c,Map<String,Object> scope,JsonNode body,String token) {
        if(!body.path("_auto_setup").isObject())return;
        var setup=(tools.jackson.databind.node.ObjectNode)body.deepCopy();
        setup.setAll((tools.jackson.databind.node.ObjectNode)body.path("_auto_setup"));
        if(id(setup,"scope_id")!=n(scope.get("id")))throw fail("fba_scope_conflict","自动带入商品的仓库范围不一致。");
        setup.put("expected_revision",scope.get("revision").toString());
        long sku=setup.path("identities").isEmpty()
            ? n(one("SELECT sku_id FROM fba_identity WHERE site_id=? AND scope_id=? ORDER BY sku_id LIMIT 1",c.site(),scope.get("id")).get("sku_id"))
            : id(setup.path("identities").get(0),"sku_id");
        var current=inventory.identity(c.site(),body,sku);
        if(!setup.path("catalog_version").asText().equals(current.path("catalog_version").asText())||(body.hasNonNull("catalog_version")&&!body.path("catalog_version").asText().equals(current.path("catalog_version").asText())))throw fail("fba_catalog_conflict","商品资料已更新，请刷新本批商品后继续。");
        if(!scope.get("catalog_version").equals(current.path("catalog_version").asText())) {
            tracking(c,setup,UUID.nameUUIDFromBytes(bytes(token+":catalog")).toString());
            scope.clear();scope.putAll(scope(c,id(setup,"scope_id")));
            setup.put("expected_revision",scope.get("revision").toString());
        }
        if(!setup.path("identities").isEmpty()) {
            extendIdentities(c,setup,token);
            scope.clear();scope.putAll(scope(c,id(setup,"scope_id")));
        }
    }
    private static OffsetDateTime time(String raw){
        try{var value=OffsetDateTime.parse(raw);if(!ZoneId.of("America/Los_Angeles").getRules().getValidOffsets(value.toLocalDateTime()).contains(value.getOffset()))throw new DateTimeException("offset");return value;}
        catch(DateTimeException ex){throw new ProductionError(422,"fba_time_invalid","发生时间须保留洛杉矶有效UTC偏移。");}
    }
    Object command(ProductionContext c,String path,JsonNode b,String token){
        if(b.path("_auto_setup").isObject()) {
            var scope=scope(c,id(b.path("_auto_setup"),"scope_id"));
            if (path.equals("fba-action-reverse")) {
                var action = one("SELECT scope_id FROM fba_action WHERE site_id=? AND id=?", c.site(), id(b,"action_id"));
                if (n(action.get("scope_id")) != n(scope.get("id")))
                    throw fail("fba_scope_conflict", "撤销记录与商品核对范围不一致。");
            }
            if (Set.of("fba-batch-confirm", "fba-unified-confirm").contains(path)) {
                var batch = one("SELECT scope_id FROM fba_receipt_batch WHERE site_id=? AND id=?", c.site(), id(b,"batch_id"));
                if (n(batch.get("scope_id")) != n(scope.get("id")))
                    throw fail("fba_scope_conflict", "接收记录与商品核对范围不一致。");
            }
            boolean scopeRevision=Set.of("fba-extend-identities","fba-quality","fba-classification-correct","fba-stocktake").contains(path);
            if(scopeRevision)revision(scope,b);
            connectApprovedProducts(c,scope,b,token);
            var prepared=(tools.jackson.databind.node.ObjectNode)b.deepCopy();
            prepared.remove("_auto_setup");
            if(scopeRevision)prepared.put("expected_revision",scope.get("revision").toString());
            b=prepared;
            if(path.equals("fba-extend-identities"))return state(c,n(scope.get("warehouse_id")));
        }
        return switch(path){
            case "fba-scopes"->initialize(c,b,token);
            case "fba-extend-identities" -> extendIdentities(c,b,token);
            case "fba-tracking"->tracking(c,b,token);
            case "fba-references"->reference(c,b,token);
            case "fba-uploads"->upload(c,b,token);
            case "fba-unified-save"->saveUnified(c,b,token);
            case "fba-unified-confirm"->confirmUnified(c,b,token);
            case "fba-batch-save"->save(c,b,token);
            case "fba-batch-confirm"->confirm(c,b,token);
            case "fba-batch-abandon"->abandon(c,b,token);
            case "fba-actions"->manualAction(c,b,token,false);
            case "fba-action-reverse"->manualAction(c,b,token,true);
            case "fba-report-sync"->syncReports(c,b,token);
            case "fba-quality"->quality(c,b,token);
            case "fba-classification-correct"->correctClassification(c,b,token);
            case "fba-stocktake" -> stocktake(c,b,token);
            default->throw new ProductionError(404,"not_found","FBA操作不存在。");
        };
    }
    private Object initialize(ProductionContext c,JsonNode b,String token){
        long warehouse=id(b,"warehouse_id"),owner=id(b,"owner_id");
        var directory=one("SELECT name,type,status,profile FROM production_warehouse WHERE site_id=? AND id=?",c.site(),warehouse);
        var profile=node(directory.get("profile"));
        String seller=required(b,"seller_account",255),market=required(b,"marketplace",32),basis=required(b,"reason",2000),cutoff=required(b,"cutoff_on",10);
        LocalDate date=InventoryService.day(cutoff);
        if(!"FBA".equals(directory.get("type"))||!"ACTIVE".equals(directory.get("status"))||!seller.equals(profile.path("seller_account").asText())||!market.equals(profile.path("marketplace").asText())||!Set.of("US","amazon_us").contains(market))throw fail("fba_scope_conflict","请核对已启用FBA资料的卖家账号和US站点。");
        var approved=b.path("_fba_scope");
        if(!approved.path("seller_account").asText().equals(seller)||approved.path("id").asLong()!=id(b,"report_source_scope_id")||!approved.path("marketplace").asText().equals("amazon_us"))throw fail("fba_scope_conflict","报表账号范围未由服务端核实。");
        boolean real=b.path("opening_mode").asText().equals("snapshot");
        var snapshot=b.path("_real_snapshot");
        if(real && date.isAfter(LocalDate.now(ZoneId.of("America/Los_Angeles"))))throw fail("invalid_business_date","快照日期不能晚于店铺当前日期。");
        if(real && (!snapshot.path("source_kind").asText().equals("REAL_SOURCE") || !snapshot.path("source_id").asText().matches("[a-f0-9]{64}") || !snapshot.path("site_id").asText().equals(Long.toString(c.site())) || !snapshot.path("snapshot_on").asText().equals(cutoff) || snapshot.path("report_source_scope_id").asLong()!=id(b,"report_source_scope_id") || !snapshot.path("missing_skus_zero_confirmed").asBoolean() || b.path("simulated").asBoolean()))throw fail("fba_opening_required","真实期初必须核对原始库存快照及完整店铺范围。");
        if(!real && (!b.path("explicit_zero_opening").asBoolean()||!b.path("simulated").asBoolean()))throw fail("fba_opening_required","当前仅启用明确模拟零期初；跟踪选择或未开卖不能证明真实期初为零。");
        if(real && db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND JSON_UNQUOTE(JSON_EXTRACT(opening_metadata,'$.snapshot.source_id'))=?",Long.class,c.site(),snapshot.path("source_id").asText())>0)throw fail("fba_snapshot_used","此库存快照已建立期初，不能在其他仓库重复入账。");
        if(db.queryForObject("SELECT COUNT(*) FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",Long.class,c.site(),warehouse,owner)>0)throw fail("fba_opening_exists","已有范围或期初，不能重建或覆盖余额。");
        if(!b.path("identities").isArray()||b.path("identities").isEmpty())throw fail("fba_identity_required","请逐规格确认账号内MSKU、ASIN、FNSKU和稳定商品身份。");
        String version="";
        for(var line:b.path("identities")){var identity=inventory.identity(c.site(),b,id(line,"sku_id"));if(version.isEmpty())version=identity.path("catalog_version").asText();if(!version.equals(identity.path("catalog_version").asText()))throw fail("fba_catalog_conflict","商品目录版本不一致。");}
        String ownerName=required(b,"owner_name",120);
        if(b.path("identity_mode").asText().equals("catalog")&&!version.equals(b.path("catalog_version").asText()))throw fail("fba_catalog_conflict","商品资料已更新，请刷新后重新确认期初。");
        db.update("INSERT INTO inventory_scope(site_id,warehouse_id,owner_id,warehouse_name,owner_name,cutoff_on,source_reference,opening_token,opening_metadata) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),warehouse,owner,directory.get("name"),ownerName,date,(real?"REAL-FBA-SNAPSHOT-":"SIMULATED-FBA-")+token,token,encode(real?Map.of("simulated",false,"quantity_basis","FBA_REAL_SNAPSHOT","snapshot",snapshot,"evidence",basis):Map.of("simulated",true,"explicit_zero_opening",true,"quantity_basis","FBA_CONFIRMED_EVENTS","evidence",basis)));
        db.update("INSERT INTO fba_scope(site_id,warehouse_id,owner_id,seller_account,marketplace,report_source_scope_id,store_evidence,catalog_version,cutoff_on,opening_basis,simulated) VALUES(?,?,?,?,?,?,?,?,?,?,?)",c.site(),warehouse,owner,seller,market,id(b,"report_source_scope_id"),required(b,"store_evidence",255),version,date,basis,!real);
        long scope=last();var seen=new HashSet<Long>();
        for(var line:b.path("identities")){
            long sku=id(line,"sku_id");if(!seen.add(sku))throw fail("fba_identity_conflict","同一范围不能重复确认规格。");
            var identity=inventory.identity(c.site(),b,sku);String raw=required(line,"seller_sku",255),fnsku=required(line,"fnsku",255),asin=required(line,"asin",255);
            var trusted=b.path("_fba_identities").path(Long.toString(sku));
            if(!trusted.path("seller_sku").asText().equals(raw))throw fail("fba_identity_conflict","MSKU尚未通过当前账号的已批准商品映射。");
            byte[] match;try{match=Base64.getDecoder().decode(trusted.path("match").asText());}catch(IllegalArgumentException ex){throw fail("fba_identity_conflict","商品规范化版本无效。");}
            db.update("INSERT INTO fba_identity(site_id,scope_id,sku_id,seller_sku,seller_sku_raw,fnsku,asin,style_id,catalog_version,evidence,tracked) VALUES(?,?,?,?,?,?,?,?,?,?,TRUE)",c.site(),scope,sku,match,raw,bytes(fnsku),bytes(asin),identity.path("style_id").asLong(),version,required(line,"reason",2000));
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,?,?,?,?,?)",c.site(),warehouse,owner,sku,identity.path("label").asText(),version);
        }
        if(real){
            var counts=new HashMap<Long,Long>();
            if(!snapshot.path("rows").isArray()||snapshot.path("rows").isEmpty())throw fail("fba_opening_required","库存快照不能为空。");
            for(var row:snapshot.path("rows")){long sku=id(row,"sku_id");if(!seen.contains(sku)||counts.put(sku,InventoryService.number(row,"units"))!=null)throw fail("fba_identity_conflict","快照规格重复或不属于本店铺。");}
            for(long sku:seen)inventory.recordFbaOpening(c,new InventoryService.Key(warehouse,owner,sku),counts.getOrDefault(sku,0L),token,basis,cutoff);
        }
        inventory.audit(c,"fba_scope",scope,1,token,real?"REAL_SNAPSHOT_OPENING":"EXPLICIT_ZERO_OPENING",basis,null,Map.of("warehouse_id",warehouse,"owner_id",owner,"skus",seen.size(),"simulated",!real));return state(c,warehouse);
    }
    private Object extendIdentities(ProductionContext c,JsonNode b,String token) {
        var scope=scope(c,id(b,"scope_id"));
        revision(scope,b);
        requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
        if(!b.path("explicit_zero_opening").asBoolean())
            throw fail("fba_opening_required","请确认新接入规格在原截止日库存为零，不能覆盖已有余额。");
        var approved=b.path("_fba_scope");
        if(approved.path("id").asLong()!=n(scope.get("report_source_scope_id"))||!approved.path("seller_account").asText().equals(scope.get("seller_account"))||!required(b,"store_evidence",255).equals(scope.get("store_evidence")))
            throw fail("fba_scope_conflict","新接入规格须属于当前FBA的店铺与账号范围。");
        if(!b.path("identities_confirmed").asBoolean()||!b.path("identities").isArray()||b.path("identities").isEmpty())
            throw fail("fba_identity_required","请核对已有商品及其平台资料后确认接入。");
        String reason=required(b,"reason",2000);
        var seen=new HashSet<Long>();
        for(var line:b.path("identities")) {
            long sku=id(line,"sku_id");
            if(!seen.add(sku))throw fail("fba_identity_conflict","同一规格不能重复接入。");
            var identity=currentIdentity(c,scope,b,sku);
            String raw=required(line,"seller_sku",255),fnsku=required(line,"fnsku",255),asin=required(line,"asin",255);
            var trusted=b.path("_fba_identities").path(Long.toString(sku));
            if(!trusted.path("seller_sku").asText().equals(raw))throw fail("fba_identity_conflict","平台资料尚未与当前主档规格核对一致。");
            byte[] match;
            try{match=Base64.getDecoder().decode(trusted.path("match").asText());}catch(IllegalArgumentException ex){throw fail("fba_identity_conflict","商品规范化版本无效。");}
            if(db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND (sku_id=? OR seller_sku=? OR fnsku=?)",Long.class,c.site(),scope.get("id"),sku,match,bytes(fnsku))>0)
                throw fail("fba_identity_exists","所选规格或平台编码已在本仓登记，请使用现有记录核对。");
            if(db.queryForObject("SELECT COUNT(*) FROM inventory_balance WHERE site_id=? AND warehouse_id=? AND owner_id=? AND sku_id=?",Long.class,c.site(),scope.get("warehouse_id"),scope.get("owner_id"),sku)>0)
                throw fail("fba_opening_exists","该规格已有库存基线，请先核对原账簿，不能覆盖。");
            db.update("INSERT INTO fba_identity(site_id,scope_id,sku_id,seller_sku,seller_sku_raw,fnsku,asin,style_id,catalog_version,evidence,tracked) VALUES(?,?,?,?,?,?,?,?,?,?,TRUE)",c.site(),scope.get("id"),sku,match,raw,bytes(fnsku),bytes(asin),identity.path("style_id").asLong(),scope.get("catalog_version"),required(line,"reason",2000));
            db.update("INSERT INTO inventory_balance(site_id,warehouse_id,owner_id,sku_id,sku_label,catalog_version) VALUES(?,?,?,?,?,?)",c.site(),scope.get("warehouse_id"),scope.get("owner_id"),sku,identity.path("label").asText(),scope.get("catalog_version"));
        }
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
        inventory.audit(c,"fba_scope",n(scope.get("id")),n(scope.get("revision"))+1,token,"CONNECT_EXISTING_SKUS",reason,null,Map.of("sku_ids",seen,"zero_cutoff",scope.get("cutoff_on").toString()));
        return state(c,n(scope.get("warehouse_id")));
    }
    private Object tracking(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));revision(scope,b);String reason=required(b,"reason",2000);var selected=new HashSet<Long>();
        String previousVersion=scope.get("catalog_version").toString();
        if(b.path("reconfirm_catalog").asBoolean()){
            requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
            String version="";
            for(var line:rows("SELECT * FROM fba_identity WHERE site_id=? AND scope_id=?",c.site(),scope.get("id"))){
                long sku=n(line.get("sku_id"));var current=inventory.identity(c.site(),b,sku);var trusted=b.path("_fba_identities").path(Long.toString(sku));
                if(!trusted.path("seller_sku").asText().equals(line.get("seller_sku_raw"))||current.path("style_id").asLong()!=n(line.get("style_id")))throw fail("fba_identity_conflict","当前目录的FBA商品归属或款式与原确认身份不一致，不能切换目录。");
                String currentVersion=current.path("catalog_version").asText();if(version.isEmpty())version=currentVersion;if(!version.equals(currentVersion))throw fail("fba_catalog_conflict","本次商品目录版本不一致。");
            }
            if(version.isEmpty())throw fail("fba_identity_required","原FBA范围尚无可核对身份。");
            db.update("UPDATE fba_scope SET catalog_version=? WHERE site_id=? AND id=?",version,c.site(),scope.get("id"));
            db.update("UPDATE fba_identity SET catalog_version=? WHERE site_id=? AND scope_id=?",version,c.site(),scope.get("id"));
            scope.put("catalog_version",version);
        }
        for(var item:b.path("sku_ids")){long sku=ProductionService.positive(item,"sku_id");currentIdentity(c,scope,b,sku);if(db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?",Long.class,c.site(),scope.get("id"),sku)!=1)throw fail("fba_scope_conflict","跟踪规格不在该账号范围。");selected.add(sku);}
        String store=b.has("store_name")?required(b,"store_name",255):scope.get("store_evidence").toString();
        if(!store.equals(scope.get("store_evidence"))){
            if(db.queryForObject("SELECT (SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=? AND scope_id=?)+(SELECT COUNT(*) FROM fba_action WHERE site_id=? AND scope_id=?)",Long.class,c.site(),scope.get("id"),c.site(),scope.get("id"))>0)throw fail("fba_store_locked","已有接收或实物记录，不能更改报告店铺名；请核对原始账号与来源。");
            db.update("UPDATE fba_scope SET store_evidence=? WHERE site_id=? AND id=?",store,c.site(),scope.get("id"));
        }
        db.update("UPDATE fba_identity SET tracked=FALSE WHERE site_id=? AND scope_id=?",c.site(),scope.get("id"));for(long sku:selected)db.update("UPDATE fba_identity SET tracked=TRUE WHERE site_id=? AND scope_id=? AND sku_id=?",c.site(),scope.get("id"),sku);
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));inventory.audit(c,"fba_scope",n(scope.get("id")),n(scope.get("revision"))+1,token,"TRACKING",reason,Map.of("store_name",scope.get("store_evidence"),"catalog_version",previousVersion),Map.of("sku_ids",selected,"store_name",store,"catalog_version",scope.get("catalog_version")));return state(c,n(scope.get("warehouse_id")));
    }
    private Object reference(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));String evidence=required(b,"reason",2000),reference=required(b,"reference_id",255);long shipment=id(b,"shipment_id");
        var source=one("SELECT status,revision,destination_id,owner_id FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipment);
        if(!"CONFIRMED".equals(source.get("status"))||n(source.get("revision"))!=id(b,"expected_shipment_revision")||n(source.get("destination_id"))!=n(scope.get("warehouse_id"))||n(source.get("owner_id"))!=n(scope.get("owner_id")))throw fail("fba_source_conflict","出货状态、修订、目的FBA范围或货权不一致，不能按名称猜配。");
        if(db.queryForObject("SELECT COUNT(*) FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND is_active=TRUE",Long.class,c.site(),shipment)==0)throw fail("fba_binding_required","请先核对本批出货的商品来源。");
        long link=b.hasNonNull("reference_link_id")?id(b,"reference_link_id"):0;
        if(db.queryForObject("SELECT COUNT(*) FROM fba_reference WHERE site_id=? AND scope_id=? AND reference_key=? AND id<>?",Long.class,c.site(),scope.get("id"),bytes(reference),link)>0)throw fail("fba_reference_exists","该FBA货件号已关联出货，请核对原记录。");
        if(link>0){
            var before=one("SELECT id,shipment_id,CAST(reference_key AS CHAR CHARACTER SET utf8mb4) AS reference_number FROM fba_reference WHERE site_id=? AND scope_id=? AND id=? FOR UPDATE",c.site(),scope.get("id"),link);
            if(n(before.get("shipment_id"))!=shipment||!before.get("reference_number").equals(required(b,"expected_reference_number",255)))throw fail("fba_source_conflict","货件关联已变化，请重新核对。");
            if(db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=? AND reference_id=?",Long.class,c.site(),link)>0)throw fail("fba_reference_in_use","此货件已有接收记录，不能直接更改货件号。");
            db.update("UPDATE fba_reference SET reference_key=?,shipment_revision=?,evidence=? WHERE site_id=? AND id=?",bytes(reference),source.get("revision"),evidence,c.site(),link);
            long next=db.queryForObject("SELECT COALESCE(MAX(revision),0)+1 FROM production_revision WHERE site_id=? AND document_kind='fba_reference' AND document_id=?",Long.class,c.site(),link);
            inventory.audit(c,"fba_reference",link,next,token,"CORRECT",evidence,before,Map.of("reference_id",reference,"shipment_id",shipment));
            return state(c,n(scope.get("warehouse_id")));
        }
        db.update("INSERT INTO fba_reference(site_id,scope_id,reference_key,shipment_id,shipment_revision,evidence) VALUES(?,?,?,?,?,?)",c.site(),scope.get("id"),bytes(reference),shipment,source.get("revision"),evidence);
        long id=last();inventory.audit(c,"fba_reference",id,1,token,"LINK",evidence,null,Map.of("reference_id",reference,"shipment_id",shipment));return state(c,n(scope.get("warehouse_id")));
    }
    private Object upload(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));String name=required(b,"filename",255);if(name.contains("/")||name.contains("\\")||name.contains("\n")||name.contains("\r"))throw fail("fba_file_invalid","文件名无效。");
        byte[] raw;String digest;
        try{raw=Base64.getDecoder().decode(text(b,"file_base64",2_800_000));digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(raw));}catch(java.security.NoSuchAlgorithmException ex){throw new IllegalStateException(ex);}catch(IllegalArgumentException ex){throw fail("fba_file_invalid","原件编码无效。");}
        if(raw.length==0||raw.length>2_000_000||!b.path("_parsed").path("rows").isArray())throw fail("fba_file_invalid","原件或专用解析结果无效。");
        var prior=rows("SELECT id FROM fba_receipt_batch WHERE site_id=? AND scope_id=? AND digest=?",c.site(),scope.get("id"),digest);if(!prior.isEmpty()){var result=batch(c,n(prior.getFirst().get("id")));result.put("exact_file_duplicate",true);return result;}
        connectApprovedProducts(c,scope,b,token);
        var parsed=b.path("_parsed");db.update("INSERT INTO fba_receipt_batch(site_id,scope_id,filename,digest,original_data,source_rows,source_issues,decisions,actor_id) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),scope.get("id"),name,digest,raw,encode(parsed.path("rows")),encode(parsed.path("issues")),"[]",c.actor());long id=last();inventory.audit(c,"fba_batch",id,1,token,"UPLOAD","保留FBA接收原件；尚未入账",null,Map.of("filename",name,"digest",digest));return batch(c,id);
    }
    byte[] original(ProductionContext c,long id){var result=db.queryForList("SELECT original_data FROM fba_receipt_batch WHERE site_id=? AND id=?",c.site(),id);if(result.isEmpty())throw fail("fba_batch_missing","原件不存在或不在当前范围。");return (byte[])result.getFirst().get("original_data");}
    Map<String,Object> batch(ProductionContext c,long id){
        var result=one("SELECT id,scope_id,filename,digest,source_rows,source_issues,decisions,status,revision,source_kind,shipment_id,draft_payload FROM fba_receipt_batch WHERE site_id=? AND id=?",c.site(),id);var scope=scope(c,n(result.get("scope_id")));result.put("rows",node(result.remove("source_rows")));result.put("issues",node(result.remove("source_issues")));result.put("decisions",node(result.get("decisions")));
        if(result.get("draft_payload")!=null)result.put("draft_payload",node(result.get("draft_payload")));
        if("MANUAL".equals(result.get("source_kind"))){
            var reports=new ArrayList<Object>();var reportIds=new HashSet<Long>();
            for(var line:node(result.get("draft_payload")).path("lines"))if(line.hasNonNull("batch_id")&&reportIds.add(id(line,"batch_id"))){
                var report=one("SELECT scope_id,source_kind FROM fba_receipt_batch WHERE site_id=? AND id=?",c.site(),id(line,"batch_id"));
                if(n(report.get("scope_id"))!=n(scope.get("id"))||!"REPORT".equals(report.get("source_kind")))throw fail("fba_source_conflict","草稿原报告范围不一致。");
                reports.add(batch(c,id(line,"batch_id")));
            }
            result.put("source_reports",reports);
        }
        result.put("resolved",rows("SELECT source_row,event_id,decision,evidence,confirmed_units,linked_units FROM fba_receipt_resolution WHERE site_id=? AND batch_id=? ORDER BY source_row",c.site(),id));
        var enriched=new ArrayList<Object>();
        var snapshots=snapshotCutoffs(c,scope);
        for(var row:(JsonNode)result.get("rows")){
            var item=new LinkedHashMap<String,Object>();item.put("source_row",row.path("source_row").asInt());item.put("raw",row.path("raw"));item.put("fingerprint",row.path("fingerprint").asText());item.put("quantity",row.path("quantity").asText());item.put("occurred_at",row.path("occurred_at").asText());item.put("business_date",row.path("business_date").asText());item.put("same_file_candidates",row.path("same_file_candidates"));item.put("seller_match",row.path("seller_match").asText());
            var found=identityRows(c,n(scope.get("id")),row);item.put("identity",found.isEmpty()?null:found.getFirst());
            boolean correction=false;
            for(var decision:(JsonNode)result.get("decisions"))
                if(decision.path("source_row").asInt()==row.path("source_row").asInt()&&!decision.path("correction_of").asText().isBlank())correction=true;
            item.put("ledger_kind",correction?"CORRECTION":ledgerKind(row));
            String snapshot=found.isEmpty()?null:snapshots.get(found.getFirst().get("sku_id")+":"+receiptQuality(row));
            String sourceDate=row.path("business_date").asText();
            boolean covered=snapshot!=null&&!sourceDate.isBlank()&&sourceDate.compareTo(snapshot)<=0;
            item.put("snapshot_on",snapshot);
            item.put("posting_block",covered?"SNAPSHOT_COVERED":!row.path("raw").path("Event Type").asText().equals("Receipts")?"REVIEW_REQUIRED":"");

            item.put("existing_candidates",rows("SELECT DISTINCT e.id,CAST(e.event_key AS CHAR CHARACTER SET utf8mb4) AS event_key,COALESCE(r.confirmed_units,e.units) AS units,e.batch_id,e.source_row FROM fba_receipt_event e LEFT JOIN fba_receipt_resolution r ON r.site_id=e.site_id AND r.event_id=e.id AND r.source_fingerprint=? WHERE e.site_id=? AND e.scope_id=? AND (e.fingerprint=? OR r.event_id IS NOT NULL) ORDER BY e.id",row.path("fingerprint").asText(),c.site(),scope.get("id"),row.path("fingerprint").asText()));
            item.put("bindings",found.isEmpty()?List.of():rows("SELECT b.id,b.source_line_id,b.allocation_id,b.carton_id,b.sku_id,b.units,r.shipment_id,r.id AS reference_link_id,CAST(r.reference_key AS CHAR CHARACTER SET utf8mb4) AS reference_id,COALESCE((SELECT SUM(a.units) FROM fba_event_allocation a WHERE a.site_id=b.site_id AND a.binding_id=b.id),0) AS received_units FROM fba_reference r JOIN production_shipment s ON s.site_id=r.site_id AND s.id=r.shipment_id AND s.status='CONFIRMED' AND s.revision=r.shipment_revision JOIN destination_shipment_binding b ON b.site_id=r.site_id AND b.shipment_id=r.shipment_id AND b.is_active=TRUE WHERE r.site_id=? AND r.scope_id=? AND r.reference_key=? AND b.sku_id=? ORDER BY b.id",c.site(),scope.get("id"),bytes(row.path("raw").path("Reference ID").asText()),found.getFirst().get("sku_id")));
            item.put("receipt_candidates",found.isEmpty()?List.of():receiptCandidates(c,n(scope.get("id")),n(found.getFirst().get("sku_id")),row.path("raw").path("Reference ID").asText(),receiptQuality(row)));
            enriched.add(item);
        }
        result.put("rows",enriched);result.put("history",rows("SELECT revision,operation_kind,reason,actor_name,created_at FROM production_revision WHERE site_id=? AND document_kind='fba_batch' AND document_id=? ORDER BY id",c.site(),id));return result;
    }
    private List<Map<String,Object>> identityRows(ProductionContext c,long scope,JsonNode row){
        byte[] match;try{match=Base64.getDecoder().decode(row.path("seller_match").asText());}catch(IllegalArgumentException ex){return List.of();}
        return rows("SELECT sku_id,style_id,seller_sku_raw AS seller_sku,tracked,catalog_version FROM fba_identity WHERE site_id=? AND scope_id=? AND seller_sku=? AND fnsku=? AND asin=?",c.site(),scope,match,bytes(row.path("raw").path("FNSKU").asText()),bytes(row.path("raw").path("ASIN").asText()));
    }
    private Map<String,Object> receiptShipment(ProductionContext c,Map<String,Object> scope,long shipmentId) {
        var shipment=one("SELECT * FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),shipmentId);
        if(!"CONFIRMED".equals(shipment.get("status"))||n(shipment.get("destination_id"))!=n(scope.get("warehouse_id"))||n(shipment.get("owner_id"))!=n(scope.get("owner_id"))) throw fail("fba_source_conflict","请选择当前FBA仓库与货主的已确认出货。来源发生变化，请重新核对。");
        requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
        return shipment;
    }
    private Map<String,Object> receiptReference(ProductionContext c,Map<String,Object> scope,long shipment,JsonNode payload){
        if(payload.path("reference_link_id").asText().isBlank())throw fail("fba_reference_required","请先填写或选择FBA货件号。");
        var reference=one("SELECT r.*,CAST(r.reference_key AS CHAR CHARACTER SET utf8mb4) AS reference_number FROM fba_reference r JOIN production_shipment s ON s.site_id=r.site_id AND s.id=r.shipment_id AND s.status='CONFIRMED' AND s.revision=r.shipment_revision WHERE r.site_id=? AND r.scope_id=? AND r.id=? AND r.shipment_id=?",c.site(),scope.get("id"),id(payload,"reference_link_id"),shipment);
        if(!payload.path("reference_number").asText().equals(reference.get("reference_number")))throw fail("fba_source_conflict","FBA货件号已变化，请重新保存核对。");
        return reference;
    }
    private Object saveUnified(ProductionContext c,JsonNode b,String token) {
        var scope=scope(c,id(b,"scope_id"));
        long shipmentId=id(b,"shipment_id");
        var shipment=receiptShipment(c,scope,shipmentId);
        if(n(shipment.get("revision"))!=id(b,"expected_shipment_revision"))throw fail("fba_source_conflict","出货修订已变化，请重新核对本批来源。");
        connectApprovedProducts(c,scope,b,token);
        var payload=b.path("draft_payload").deepCopy();
        if(!payload.isObject())throw fail("fba_row_coverage","请保存完整接收表。");
        ((tools.jackson.databind.node.ObjectNode)payload).put("shipment_revision",shipment.get("revision").toString());
        if(!payload.path("reference_link_id").asText().isBlank()){
            var reference=one("SELECT id,CAST(reference_key AS CHAR CHARACTER SET utf8mb4) AS reference_number FROM fba_reference WHERE site_id=? AND scope_id=? AND shipment_id=? AND id=? AND shipment_revision=?",c.site(),scope.get("id"),shipmentId,id(payload,"reference_link_id"),shipment.get("revision"));
            if(!payload.path("reference_number").asText().isBlank()&&!payload.path("reference_number").asText().equals(reference.get("reference_number")))throw fail("fba_source_conflict","FBA货件号已更正，请重新读取后核对。");
            ((tools.jackson.databind.node.ObjectNode)payload).put("reference_number",reference.get("reference_number").toString());
        }
        if(!payload.path("lines").isArray()||payload.path("lines").size()>1000)throw fail("fba_row_coverage","接收表最多保存1000行。");
        var seen=new HashSet<Long>();
        for(var line:payload.path("lines")) {
            long lineId=id(line,"line_id");
            if(lineId>Integer.MAX_VALUE||!seen.add(lineId))throw fail("fba_row_coverage","接收表行引用重复或无效。");
            long sku=id(line,"sku_id");
            currentIdentity(c,scope,b,sku);
            if(db.queryForObject("SELECT COUNT(*) FROM destination_shipment_binding WHERE site_id=? AND shipment_id=? AND sku_id=? AND is_active=TRUE",Long.class,c.site(),shipmentId,sku)==0)throw fail("fba_source_conflict","接收商品不属于本批已核实出货。");
            if(line.hasNonNull("batch_id")) {
                var report=one("SELECT scope_id,source_kind,source_rows FROM fba_receipt_batch WHERE site_id=? AND id=?",c.site(),id(line,"batch_id"));
                if(n(report.get("scope_id"))!=n(scope.get("id"))||!"REPORT".equals(report.get("source_kind")))throw fail("fba_source_conflict","报告不属于当前账号范围。");
                if(!node(report.get("source_rows")).isArray())throw fail("fba_row_coverage","原报告行无效。");
                var original=originalRow(report,line);
                var identities=identityRows(c,n(scope.get("id")),original);
                if(identities.size()!=1||n(identities.getFirst().get("sku_id"))!=sku)throw fail("fba_identity_conflict","导入商品与原始报告身份不一致。");
            }
        }
        long draftId;
        if(b.hasNonNull("batch_id")) {
            draftId=id(b,"batch_id");
            var before=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),draftId);
            revision(before,b);
            if(!"MANUAL".equals(before.get("source_kind"))||!"DRAFT".equals(before.get("status"))||n(before.get("scope_id"))!=n(scope.get("id"))||n(before.get("shipment_id"))!=shipmentId)throw fail("fba_batch_read_only","统一接收草稿范围已变化或已确认。");
            db.update("UPDATE fba_receipt_batch SET draft_payload=?,revision=revision+1 WHERE site_id=? AND id=?",encode(payload),c.site(),draftId);
            inventory.audit(c,"fba_batch",draftId,n(before.get("revision"))+1,token,"SAVE","保存统一接收草稿",node(before.get("draft_payload")),payload);
        }
        else {
            String digest=UUID.randomUUID().toString().replace("-","")+UUID.randomUUID().toString().replace("-","");
            db.update("INSERT INTO fba_receipt_batch(site_id,scope_id,filename,digest,original_data,source_rows,source_issues,decisions,actor_id,source_kind,shipment_id,draft_payload) VALUES(?,?,?,?,?,'[]','[]','[]',?,'MANUAL',?,?)",c.site(),scope.get("id"),"出货"+shipmentId+"接收核对.json",digest,bytes(encode(payload)),c.actor(),shipmentId,encode(payload));
            draftId=last();
            inventory.audit(c,"fba_batch",draftId,1,token,"SAVE","保存统一接收草稿",null,payload);
        }
        return batch(c,draftId);
    }
    private JsonNode originalRow(Map<String,Object> report,JsonNode line) {
        for(var original:node(report.get("source_rows")))if(original.path("source_row").asLong()==id(line,"source_row"))return original;
        throw fail("fba_row_coverage","原报告行不存在。");
    }
    private Object confirmUnified(ProductionContext c,JsonNode b,String token) {
        long draftId=id(b,"batch_id");
        var draft=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),draftId);
        revision(draft,b);
        if(!"MANUAL".equals(draft.get("source_kind"))||!"DRAFT".equals(draft.get("status")))throw fail("fba_batch_read_only","本次接收已确认，请查看记录。");
        var scope=scope(c,n(draft.get("scope_id")));
        connectApprovedProducts(c,scope,b,token);
        long shipmentId=n(draft.get("shipment_id"));
        var payload=node(draft.get("draft_payload"));
        String reason=required(payload,"reason",2000);
        var shipment=receiptShipment(c,scope,shipmentId);
        if(n(shipment.get("revision"))!=id(payload,"shipment_revision"))throw fail("fba_source_conflict","出货修订已变化，请重新载入来源并保存核对。");
        var chosenReference=receiptReference(c,scope,shipmentId,payload);
        var seen=new HashSet<String>();
        int count=0;
        long added=0,linked=0;
        for(var line:payload.path("lines")) {
            if(line.hasNonNull("batch_id")&&(!line.path("selected").asBoolean()||Set.of("","0").contains(line.path("quantity").asText())))required(line,"adjustment_reason",2000);
            if(!line.path("selected").asBoolean()||line.path("quantity").asText().isBlank()||line.path("quantity").asText().equals("0"))continue;
            long units=receiptUnits(line,"quantity");
            count++;
            if(line.hasNonNull("batch_id")) {
                long reportId=id(line,"batch_id");
                String key=reportId+":"+id(line,"source_row");
                if(!seen.add(key))throw fail("fba_row_coverage","同一报告行不能重复接收。");
                var report=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),reportId);
                if(n(report.get("scope_id"))!=n(scope.get("id"))||!"REPORT".equals(report.get("source_kind")))throw fail("fba_source_conflict","接收报告范围不一致。");
                var original=originalRow(report,line);
                var identities=identityRows(c,n(scope.get("id")),original);
                if(identities.size()!=1||n(identities.getFirst().get("sku_id"))!=id(line,"sku_id"))throw fail("fba_identity_conflict","原报告商品与本次核对不一致。");
                if(!original.path("raw").path("Reference ID").asText().equals(chosenReference.get("reference_number")))throw fail("fba_source_conflict","报告原行对应其他FBA货件，本次不能确认。");
                var decision=json.createObjectNode();
                decision.put("source_row",original.path("source_row").asText());
                decision.put("decision",line.path("decision").asText("NEW"));
                decision.put("quantity",Long.toString(units));
                decision.put("reason",line.path("reason").asText(reason));
                decision.put("event_key","unified-"+draftId+"-"+id(line,"line_id"));
                decision.set("allocations",line.path("allocations"));
                decision.set("receipt_links",line.path("receipt_links"));
                if(line.hasNonNull("existing_event_id"))decision.set("existing_event_id",line.path("existing_event_id"));
                decision.put("independent_occurrence",line.path("independent_occurrence").asBoolean());
                if(!original.path("quantity").asText().equals(Long.toString(units)))required(line,"adjustment_reason",2000);
                decision.put("adjustment_reason",line.path("adjustment_reason").asText());
                var decisions=json.createArrayNode();
                boolean replaced=false;
                for(var prior:node(report.get("decisions"))) {
                    if(prior.path("source_row").asLong()==original.path("source_row").asLong()) {
                        decisions.add(decision);
                        replaced=true;
                    }
                    else decisions.add(prior);
                }
                if(!replaced)decisions.add(decision);
                db.update("UPDATE fba_receipt_batch SET decisions=? WHERE site_id=? AND id=?",encode(decisions),c.site(),reportId);
                var command=(tools.jackson.databind.node.ObjectNode)b.deepCopy();
                command.put("batch_id",Long.toString(reportId));
                command.put("expected_revision",report.get("revision").toString());
                command.put("reason",reason);
                command.putArray("source_rows").add(original.path("source_row").asText());
                confirm(c,command,token);
                var resolution=one("SELECT confirmed_units,linked_units,decision FROM fba_receipt_resolution WHERE site_id=? AND batch_id=? AND source_row=?",c.site(),reportId,original.path("source_row").asInt());
                if("SAME".equals(resolution.get("decision")))linked+=units;
                else {
                    linked+=n(resolution.get("linked_units"));
                    added+=units-n(resolution.get("linked_units"));
                }
            }
            else {
                postManual(c,scope,b,payload,line,draftId,shipmentId,token);
                added+=units;
            }
        }
        if(count==0)throw fail("fba_rows_required","请勾选实际到货商品并填写本次接收数量。");
        db.update("UPDATE fba_receipt_batch SET status='POSTED',revision=revision+1 WHERE site_id=? AND id=?",c.site(),draftId);
        inventory.audit(c,"fba_batch",draftId,n(draft.get("revision"))+1,token,"CONFIRM",reason,null,Map.of("added_units",added,"linked_units",linked,"lines",count));
        var result=batch(c,draftId);
        result.put("added_units",Long.toString(added));
        result.put("linked_units",Long.toString(linked));
        return result;
    }
    private long receiptUnits(JsonNode line,String field) {
        String value=line.path(field).asText();
        if(!value.matches("[1-9][0-9]{0,8}"))throw fail("fba_quantity_invalid","本次接收须为正整数，最多9位。请检查对应商品数量。");
        return Long.parseLong(value);
    }
    private void postManual(ProductionContext c,Map<String,Object> scope,JsonNode body,JsonNode payload,JsonNode line,long batch,long shipment,String token) {
        long sku=id(line,"sku_id"),units=receiptUnits(line,"quantity");
        currentIdentity(c,scope,body,sku);
        if(db.queryForObject("SELECT COUNT(*) FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=? AND tracked=TRUE",Long.class,c.site(),scope.get("id"),sku)!=1)throw fail("fba_not_tracked","当前规格身份未就绪或未纳入跟踪，请先核对。");
        String date=required(payload,"business_date",10);
        InventoryService.day(date);
        String reason=required(payload,"reason",2000),occurred=text(payload,"occurred_at",64);
        OffsetDateTime stamp=occurred.isEmpty()?null:time(occurred);
        if(stamp!=null&&!stamp.toLocalDate().toString().equals(date))throw fail("fba_time_invalid","实际时刻与接收日期不一致。");
        checkFactDate(c,scope,sku,"QUALIFIED",date);
        long sum=0;
        var seen=new HashSet<Long>();
        for(var allocation:line.path("allocations")) {
            long binding=id(allocation,"binding_id"),amount=receiptUnits(allocation,"units");
            if(!seen.add(binding))throw fail("fba_allocation_invalid","来源分配重复。");
            var source=one("SELECT units FROM destination_shipment_binding WHERE site_id=? AND id=? AND shipment_id=? AND sku_id=? AND is_active=TRUE",c.site(),binding,shipment,sku);
            long received=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM fba_event_allocation WHERE site_id=? AND binding_id=?",Long.class,c.site(),binding);
            long ordinary=db.queryForObject("SELECT COALESCE(SUM(l.qualified_units+l.pending_units+l.defective_units),0) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=? AND l.binding_id=? AND r.status='POSTED'",Long.class,c.site(),binding);
            if(received+ordinary+amount>n(source.get("units")))throw fail("fba_receipt_exceeds_source","规格"+sku+"本次接收"+units+"件超过当前待收，请保留输入并核对最新数量。");
            sum=Math.addExact(sum,amount);
        }
        if(sum!=units)throw fail("fba_allocation_invalid","请明确本次各来源分配，合计须等于接收数量。");
        String key="manual-"+batch+"-"+id(line,"line_id");
        String fingerprint=fingerprint(key);
        var reference=receiptReference(c,scope,shipment,payload);
        db.update("INSERT INTO fba_receipt_event(site_id,scope_id,batch_id,source_row,sku_id,event_key,fingerprint,reference_id,units,occurred_at,occurred_local,business_date,fulfillment_center,catalog_version,evidence,actor_id,source_kind,shipment_id,time_precision) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'MANUAL',?,?)",c.site(),scope.get("id"),batch,id(line,"line_id"),sku,bytes(key),fingerprint,reference.get("id"),units,stamp==null?null:Timestamp.from(stamp.toInstant()),stamp==null?date:occurred,java.sql.Date.valueOf(date),"",scope.get("catalog_version"),reason,c.actor(),shipment,stamp==null?"DAY":"TIMESTAMP");
        long event=last();
        for(var allocation:line.path("allocations"))db.update("INSERT INTO fba_event_allocation(site_id,event_id,binding_id,units) VALUES(?,?,?,?)",c.site(),event,id(allocation,"binding_id"),receiptUnits(allocation,"units"));
        inventory.applyFba(c,List.of(new InventoryService.Delta(new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),"QUALIFIED",units,"手工验收","FBA逻辑范围")),"fba_receipt",event,1,token,reason,date);
    }
    private long receiptNet(long site,long event) {
        return db.queryForObject("""
            WITH RECURSIVE receipt_tree AS (
                SELECT id,units FROM fba_receipt_event WHERE site_id=? AND id=?
                UNION ALL
                SELECT e.id,e.units FROM fba_receipt_event e JOIN receipt_tree t ON e.correction_of=t.id WHERE e.site_id=?
            ) SELECT COALESCE(SUM(units),0) FROM receipt_tree
            """,Long.class,site,event,site);
    }
    private List<Map<String,Object>> receiptCandidates(ProductionContext c,long scope,long sku,String reference,String quality) {
        return rows("""
            WITH RECURSIVE receipt_tree AS (
                SELECT id AS root,id,units FROM fba_receipt_event WHERE site_id=? AND scope_id=? AND sku_id=? AND source_kind='MANUAL' AND units>0
                UNION ALL
                SELECT t.root,e.id,e.units FROM receipt_tree t JOIN fba_receipt_event e ON e.correction_of=t.id WHERE e.site_id=?
            )
            SELECT e.id,e.shipment_id,e.reference_id AS reference_link_id,e.units,e.business_date,e.evidence,e.source_kind,
                net.units-COALESCE((SELECT SUM(v.units) FROM fba_report_coverage v WHERE v.site_id=e.site_id AND v.event_id=e.id),0) AS uncovered_units,
                COALESCE((SELECT i.quality FROM inventory_event i WHERE i.site_id=e.site_id AND i.document_kind='fba_receipt' AND i.document_id=e.id LIMIT 1),'QUALIFIED') AS quality
            FROM fba_receipt_event e JOIN (SELECT root,SUM(units) AS units FROM receipt_tree GROUP BY root) net ON net.root=e.id
            WHERE e.site_id=? AND e.reference_id IN (SELECT id FROM fba_reference WHERE site_id=? AND scope_id=? AND reference_key=?) ORDER BY e.id
            """,c.site(),scope,sku,c.site(),c.site(),c.site(),scope,bytes(reference)).stream().filter(item->quality.equals(item.get("quality"))).toList();
    }
    private Object save(ProductionContext c,JsonNode b,String token){
        long id=id(b,"batch_id");var before=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),id);revision(before,b);if(Set.of("POSTED","ABANDONED").contains(before.get("status")))throw fail("fba_batch_read_only","批次已结束，保留原记录；更正请上传新证据。");
        var originals=new HashSet<Integer>();for(var row:node(before.get("source_rows")))originals.add(row.path("source_row").asInt());var seen=new HashSet<Integer>();
        if(!b.path("decisions").isArray()||b.path("decisions").size()!=originals.size())throw fail("fba_row_coverage","每条原始明细必须有且只有一个处理决定，不能漏掉未匹配行。");
        for(var d:b.path("decisions"))if(!originals.contains(d.path("source_row").asInt())||!seen.add(d.path("source_row").asInt())||!Set.of("PENDING","NEW","SAME").contains(d.path("decision").asText()))throw fail("fba_row_coverage","决定的行号或类型无效。");
        String reason=required(b,"reason",2000);db.update("UPDATE fba_receipt_batch SET decisions=?,revision=revision+1 WHERE site_id=? AND id=?",encode(b.path("decisions")),c.site(),id);inventory.audit(c,"fba_batch",id,n(before.get("revision"))+1,token,"SAVE",reason,null,b.path("decisions"));return batch(c,id);
    }
    private Object abandon(ProductionContext c,JsonNode b,String token){
        long id=id(b,"batch_id");var before=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),id);revision(before,b);if(!Set.of("DRAFT","PARTIAL").contains(before.get("status")))throw fail("fba_batch_read_only","批次已结束。");String reason=required(b,"reason",2000);db.update("UPDATE fba_receipt_batch SET status='ABANDONED',revision=revision+1 WHERE site_id=? AND id=?",c.site(),id);inventory.audit(c,"fba_batch",id,n(before.get("revision"))+1,token,"ABANDON",reason,null,Map.of("posted_events_retained",true));return batch(c,id);
    }
    private Object confirm(ProductionContext c,JsonNode b,String token){
        long batchId=id(b,"batch_id");var batch=one("SELECT * FROM fba_receipt_batch WHERE site_id=? AND id=? FOR UPDATE",c.site(),batchId);revision(batch,b);if(!Set.of("DRAFT","PARTIAL").contains(batch.get("status")))throw fail("fba_batch_read_only","批次已结束，不能重复确认。");var scope=scope(c,n(batch.get("scope_id")));String reason=required(b,"reason",2000);
        var selected=new HashSet<Integer>();for(var r:b.path("source_rows"))if(!selected.add(r.asInt()))throw fail("fba_row_coverage","选择行重复。");if(selected.isEmpty())throw fail("fba_rows_required","请先选择本次确认的原表行。");
        var decisions=new HashMap<Integer,JsonNode>();for(var d:node(batch.get("decisions")))decisions.put(d.path("source_row").asInt(),d);
        for(var issue:node(batch.get("source_issues")))if(selected.contains(issue.path("row").asInt()))throw fail("fba_source_issue","所选原表行存在格式或质量问题，请下载问题并保留待核。");
        for(var row:node(batch.get("source_rows"))){int sourceRow=row.path("source_row").asInt();if(!selected.remove(sourceRow))continue;
            if(db.queryForObject("SELECT COUNT(*) FROM fba_receipt_resolution WHERE site_id=? AND batch_id=? AND source_row=?",Long.class,c.site(),batchId,sourceRow)>0)throw fail("fba_row_already_processed","该原表行已处理，不能再次记账。");
            var d=decisions.get(sourceRow);if(d==null||d.path("decision").asText().equals("PENDING"))throw fail("fba_decision_required","每条所选明细必须明确新增事件或关联已有事件。");String evidence=required(d,"reason",2000),decision=d.path("decision").asText();if(!Set.of("NEW","SAME").contains(decision))throw fail("fba_decision_required","请选择本次新增接收或关联已有事件。");long event;
            long confirmed=d.hasNonNull("quantity")?receiptUnits(d,"quantity"):row.path("quantity").asLong();long linked=0;
            if(d.hasNonNull("quantity")&&confirmed!=row.path("quantity").asLong())required(d,"adjustment_reason",2000);
            if(Long.signum(confirmed)!=Long.signum(row.path("quantity").asLong()))throw fail("fba_quantity_invalid","核对数量不能改变原始事件的增减方向，更正须关联原事件。");

            if(decision.equals("SAME")){
                event=id(d,"existing_event_id");var prior=one("SELECT fingerprint,scope_id FROM fba_receipt_event WHERE site_id=? AND id=?",c.site(),event);
                boolean exact=prior.get("fingerprint").equals(row.path("fingerprint").asText())&&confirmed==row.path("quantity").asLong();
                boolean reviewed=db.queryForObject("SELECT COUNT(*) FROM fba_receipt_resolution WHERE site_id=? AND event_id=? AND source_fingerprint=? AND confirmed_units=?",Long.class,c.site(),event,row.path("fingerprint").asText(),confirmed)>0;
                if(n(prior.get("scope_id"))!=n(scope.get("id"))||(!exact&&!reviewed))throw fail("fba_duplicate_conflict","已有事件不属于同一账号或原始明细及确认数量不一致，请核对原接收记录。");
            }else{
                linked=linkReport(c,scope,b,row,d,batchId);
                if(linked>0&&linked>confirmed)throw fail("fba_coverage_invalid","报告关联量超过本次确认量。");
                long remaining=confirmed-linked;
                if(remaining==0){event=id(d.path("receipt_links").get(0),"event_id");}
                else{
                    var effective=row.deepCopy();((tools.jackson.databind.node.ObjectNode)effective).put("quantity",Long.toString(remaining));
                    ((tools.jackson.databind.node.ObjectNode)effective).put("source_fingerprint",row.path("fingerprint").asText());
                    if(remaining!=row.path("quantity").asLong())((tools.jackson.databind.node.ObjectNode)effective).put("fingerprint",fingerprint(row.path("fingerprint").asText()+":"+remaining));
                    event=postReceipt(c,scope,b,effective,d,batchId,token);
                    if(remaining>0)db.update("INSERT INTO fba_report_coverage(site_id,batch_id,source_row,event_id,units,evidence,actor_id) VALUES(?,?,?,?,?,?,?)",c.site(),batchId,sourceRow,event,remaining,evidence,c.actor());
                }
            }
            db.update("INSERT INTO fba_receipt_resolution(site_id,batch_id,source_row,event_id,decision,evidence,source_fingerprint,confirmed_units,linked_units) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),batchId,sourceRow,event,decision,evidence,row.path("fingerprint").asText(),confirmed,linked);
        }
        if(!selected.isEmpty())throw fail("fba_row_coverage","所选原表行不存在。");
        long processed=db.queryForObject("SELECT COUNT(*) FROM fba_receipt_resolution WHERE site_id=? AND batch_id=?",Long.class,c.site(),batchId);String status=processed==node(batch.get("source_rows")).size()?"POSTED":"PARTIAL";
        db.update("UPDATE fba_receipt_batch SET status=?,revision=revision+1 WHERE site_id=? AND id=?",status,c.site(),batchId);inventory.audit(c,"fba_batch",batchId,n(batch.get("revision"))+1,token,"CONFIRM",reason,null,Map.of("processed",processed,"status",status));return batch(c,batchId);
    }
    private long linkReport(ProductionContext c,Map<String,Object> scope,JsonNode body,JsonNode row,JsonNode decision,long batch) {
        if(decision.path("receipt_links").isMissingNode()||decision.path("receipt_links").isNull())return 0;
        var identities=identityRows(c,n(scope.get("id")),row);
        if(identities.size()!=1)throw fail("fba_identity_unmatched","报告商品身份未明确。");
        var reference=one("SELECT id,shipment_id FROM fba_reference WHERE site_id=? AND scope_id=? AND reference_key=?",c.site(),scope.get("id"),bytes(row.path("raw").path("Reference ID").asText()));
        receiptShipment(c,scope,n(reference.get("shipment_id")));
        currentIdentity(c,scope,body,n(identities.getFirst().get("sku_id")));
        if(!Boolean.parseBoolean(identities.getFirst().get("tracked").toString()))throw fail("fba_not_tracked","该规格尚未纳入跟踪。");
        String store=row.path("raw").path("Store").asText();
        if(!store.isEmpty()&&!store.equals(scope.get("store_evidence"))||!row.path("raw").path("Country").asText().equals("US")||!row.path("raw").path("Event Type").asText().equals("Receipts"))throw fail("fba_source_issue","报告店铺、国家或事件类型不一致。");
        time(row.path("occurred_at").asText());
        String disposition=row.path("raw").path("Disposition").asText().trim().toUpperCase(Locale.ROOT);
        String quality=switch(disposition) {
            case "", "SELLABLE"->"QUALIFIED";
            case "PENDING"->"PENDING";
            case "CUSTOMER_DAMAGED","DEFECTIVE","CARRIER_DAMAGED","WAREHOUSE_DAMAGED","DISTRIBUTOR_DAMAGED","EXPIRED","UNSELLABLE"->"DEFECTIVE";
            default->throw fail("fba_source_issue","报告质量处置未支持。");
        };
        long linked=0;
        var seen=new HashSet<Long>();
        for(var link:decision.path("receipt_links")) {
            long event=id(link,"event_id"),units=receiptUnits(link,"units");
            if(!seen.add(event))throw fail("fba_coverage_invalid","同一手工接收记录不能重复关联。");
            var prior=one("SELECT * FROM fba_receipt_event WHERE site_id=? AND id=? FOR UPDATE",c.site(),event);
            if(!"MANUAL".equals(prior.get("source_kind"))||n(prior.get("scope_id"))!=n(scope.get("id"))||n(prior.get("sku_id"))!=n(identities.getFirst().get("sku_id"))||n(prior.get("shipment_id"))!=n(reference.get("shipment_id"))||!Objects.equals(prior.get("reference_id"),reference.get("id"))||n(prior.get("units"))<=0)throw fail("fba_coverage_invalid","已选接收记录的账号、出货或商品不一致。");
            String originalQuality=db.queryForObject("SELECT quality FROM inventory_event WHERE site_id=? AND document_kind='fba_receipt' AND document_id=? ORDER BY id LIMIT 1",String.class,c.site(),event);
            if(!quality.equals(originalQuality))throw fail("fba_coverage_invalid","报告与手工接收质量不一致，请从状态调整入口核对。");
            long net=receiptNet(c.site(),event);
            long covered=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM fba_report_coverage WHERE site_id=? AND event_id=?",Long.class,c.site(),event);
            if(units>net-covered)throw fail("fba_coverage_invalid","所选接收记录可关联数量已变化，不能重复覆盖，请重新核对。");
            db.update("INSERT INTO fba_report_coverage(site_id,batch_id,source_row,event_id,units,evidence,actor_id) VALUES(?,?,?,?,?,?,?)",c.site(),batch,row.path("source_row").asInt(),event,units,required(decision,"reason",2000),c.actor());
            linked=Math.addExact(linked,units);
        }
        return linked;
    }
    private long postReceipt(ProductionContext c,Map<String,Object> scope,JsonNode body,JsonNode row,JsonNode decision,long batch,String token){
        long scopeId=n(scope.get("id"));var identities=identityRows(c,scopeId,row);if(identities.size()!=1)throw fail("fba_identity_unmatched","MSKU/FNSKU/ASIN未共同匹配同账号已确认规格，原行保留待核。");var identity=identities.getFirst();long sku=n(identity.get("sku_id"));currentIdentity(c,scope,body,sku);
        if(!Boolean.parseBoolean(identity.get("tracked").toString()))throw fail("fba_not_tracked","该规格未纳入跟踪；原行保留，选择跟踪不自动产生入库。");
        String store=row.path("raw").path("Store").asText();if(!store.isEmpty()&&!scope.get("store_evidence").equals(store))throw fail("fba_store_conflict","原表Store与明确范围不符，不能猜店铺。");
        if(!row.path("raw").path("Country").asText().equals("US")||!row.path("raw").path("Event Type").asText().equals("Receipts"))throw fail("fba_source_issue","接收类型、国家或质量不支持过账。");
        long qty;try{String value=row.path("quantity").asText();if(!value.matches("-?[1-9][0-9]{0,8}"))throw new NumberFormatException();qty=Long.parseLong(value);}catch(NumberFormatException ex){throw fail("fba_quantity_invalid","接收须为带符号非零整数。");}
        var stamp=time(row.path("occurred_at").asText());String date=stamp.toLocalDate().toString();checkFactDate(c,scope,sku,receiptQuality(row),date);
        String referenceKey=required(row.path("raw"),"Reference ID",255);
        var references=rows("SELECT * FROM fba_reference WHERE site_id=? AND scope_id=? AND reference_key=?",c.site(),scopeId,bytes(referenceKey));
        boolean historical=decision.path("historical_receipt").asBoolean();
        Map<String,Object> reference;
        if(historical){
            if(!Boolean.parseBoolean(scope.get("simulated").toString())||!references.isEmpty()||!decision.path("allocations").isEmpty()||!decision.path("receipt_links").isEmpty())
                throw fail("fba_historical_source_conflict","历史验收仅用于本地明确期初、尚无系统出货绑定的原始报告。已有出货或接收关联请沿原流程核对。");
            reference=Collections.emptyMap();
        }else{
            if(references.size()!=1)throw fail("fba_source_conflict","请先关联已确认出货，历史验收须明确选择历史来源并提供依据。");
            reference=references.getFirst();
            var shipment=one("SELECT status,revision,destination_id FROM production_shipment WHERE site_id=? AND id=? FOR UPDATE",c.site(),reference.get("shipment_id"));
            if(!"CONFIRMED".equals(shipment.get("status"))||!shipment.get("revision").equals(reference.get("shipment_revision"))||!shipment.get("destination_id").equals(scope.get("warehouse_id")))throw fail("fba_source_conflict","来源出货修订或目的范围已变化。");
        }
        String eventKey=required(decision,"event_key",255),evidence=required(decision,"reason",2000);
        boolean manualCandidate=receiptCandidates(c,scopeId,sku,referenceKey,receiptQuality(row)).stream().anyMatch(event->n(event.get("shipment_id"))==n(reference.get("shipment_id"))&&n(event.get("uncovered_units"))>0);
        if(qty>0&&manualCandidate&&decision.path("receipt_links").isEmpty()&&!decision.path("independent_occurrence").asBoolean())throw fail("fba_manual_overlap_required","本批已有手工接收，请在统一接收表核对关联量或明确本次为另一次新增接收。");
        long similar=db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=? AND scope_id=? AND fingerprint=?",Long.class,c.site(),scopeId,row.path("fingerprint").asText());
        if((similar>0||!row.path("same_file_candidates").isEmpty())&&!decision.path("independent_occurrence").asBoolean())throw fail("fba_duplicate_decision_required","存在相同明细候选；确认是独立发生的新事件并提供证据，或明确关联已有事件。");
        if(db.queryForObject("SELECT COUNT(*) FROM fba_receipt_event WHERE site_id=? AND scope_id=? AND event_key=?",Long.class,c.site(),scopeId,bytes(eventKey))>0)throw fail("fba_event_key_exists","该人工事件核对引用已使用；重复复核请关联原事件。");
        String disposition=row.path("raw").path("Disposition").asText().trim().toUpperCase(Locale.ROOT);
        String receiptQuality=switch(disposition){case "", "SELLABLE"->"QUALIFIED";case "PENDING"->"PENDING";case "CUSTOMER_DAMAGED","DEFECTIVE","CARRIER_DAMAGED","WAREHOUSE_DAMAGED","DISTRIBUTOR_DAMAGED","EXPIRED","UNSELLABLE"->"DEFECTIVE";default->throw fail("fba_source_issue","接收质量处置尚未支持，请核对原表。");};
        Long correction=null;String correctionKey=text(decision,"correction_of",255);
        if(qty<0&&correctionKey.isEmpty())throw fail("fba_correction_required","负数须关联明确的原接收事件及更正依据。");
        if(!correctionKey.isEmpty()){
            var target=one("SELECT * FROM fba_receipt_event WHERE site_id=? AND scope_id=? AND event_key=?",c.site(),scopeId,bytes(correctionKey));correction=n(target.get("id"));
            boolean earlier=target.get("occurred_at")==null?stamp.toLocalDate().isBefore(LocalDate.parse(target.get("business_date").toString())):stamp.toInstant().isBefore(Instant.parse(target.get("occurred_at").toString()));
            if(n(target.get("sku_id"))!=sku||!Objects.equals(target.get("shipment_id"),reference.get("shipment_id"))||!Objects.equals(target.get("reference_id"),reference.get("id"))||earlier)throw fail("fba_correction_conflict","更正的商品、货件或时间与原事件不符。");
            if(historical){
                var originalBatch=one("SELECT source_rows FROM fba_receipt_batch WHERE site_id=? AND id=?",c.site(),target.get("batch_id"));
                boolean sameReference=false;
                for(var original:node(originalBatch.get("source_rows")))
                    if(original.path("source_row").asLong()==n(target.get("source_row")))sameReference=referenceKey.equals(original.path("raw").path("Reference ID").asText());
                if(!sameReference)throw fail("fba_correction_conflict","历史验收更正须关联同一货件的原始接收行。");
            }
            String originalQuality=db.queryForObject("SELECT quality FROM inventory_event WHERE site_id=? AND document_kind='fba_receipt' AND document_id=? ORDER BY id LIMIT 1",String.class,c.site(),correction);
            if(!receiptQuality.equals(originalQuality))throw fail("fba_correction_conflict","接收更正的库存状态须与原事件一致，状态变化请使用库存状态调整。");
            long original=n(target.get("units")),net=receiptNet(c.site(),correction);
            if(original*qty>=0||Math.abs(qty)>Math.abs(net))throw fail("fba_correction_conflict","更正方向或数量超过原事件尚可更正量。");
            long covered=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM fba_report_coverage WHERE site_id=? AND event_id=? AND batch_id<>?",Long.class,c.site(),correction,target.get("batch_id"));
            if(original>0&&net+qty<covered)throw fail("fba_coverage_dependency","原接收已被报告核对覆盖，不能使净接收少于关联量。请先核对原报告与接收依据。");
        }
        if(qty<0&&db.queryForObject("SELECT COUNT(*) FROM inventory_event e JOIN fba_action a ON a.site_id=e.site_id AND a.id=e.document_id AND a.status='POSTED' WHERE e.site_id=? AND e.warehouse_id=? AND e.owner_id=? AND e.sku_id=? AND e.document_kind='fba_fulfillment' AND e.delta_units<0 AND e.business_date>=?",Long.class,c.site(),scope.get("warehouse_id"),scope.get("owner_id"),sku,java.sql.Date.valueOf(date))>0)throw fail("fba_downstream_dependency","已有该规格后续实际履约，不能倒改接收；请先处理后续依赖。");
        long sum=0;var seen=new HashSet<Long>();var allocations=new ArrayList<Map<String,Object>>();
        for(var allocation:decision.path("allocations")){
            long binding=id(allocation,"binding_id"),units;try{units=Long.parseLong(allocation.path("units").asText());}catch(NumberFormatException ex){throw fail("fba_allocation_invalid","出货来源分配数量须为带符号整数。");}
            if(!seen.add(binding)||units==0||Long.signum(units)!=Long.signum(qty))throw fail("fba_allocation_invalid","出货来源分配重复或数量方向不符。");
            var source=one("SELECT * FROM destination_shipment_binding WHERE site_id=? AND id=? AND shipment_id=? AND sku_id=? AND is_active=TRUE",c.site(),binding,reference.get("shipment_id"),sku);
            long received=db.queryForObject("SELECT COALESCE(SUM(units),0) FROM fba_event_allocation WHERE site_id=? AND binding_id=?",Long.class,c.site(),binding);
            long ordinary=db.queryForObject("SELECT COALESCE(SUM(l.qualified_units+l.pending_units+l.defective_units),0) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=? AND l.binding_id=? AND r.status='POSTED'",Long.class,c.site(),binding);
            if(received+ordinary+units<0||received+ordinary+units>n(source.get("units")))throw fail("fba_receipt_exceeds_source","本次净接收超过出货来源待收数量，或更正超过已接收量。");
            sum=Math.addExact(sum,units);allocations.add(Map.of("binding",binding,"units",units));
        }
        if(!historical&&sum!=qty){
            long excess=decision.path("source_excess_units").asLong(-1);
            if(qty<=0||excess<=0||sum+excess!=qty||decision.hasNonNull("quantity")||!decision.path("receipt_links").isEmpty())
                throw fail("fba_allocation_invalid","出货来源分配合计须等于本次入账数量；原验收报告超收须单独核对差异。");
            required(decision,"source_excess_reason",2000);
            long remaining=db.queryForObject("SELECT COALESCE(SUM(b.units-COALESCE((SELECT SUM(a.units) FROM fba_event_allocation a WHERE a.site_id=b.site_id AND a.binding_id=b.id),0)-COALESCE((SELECT SUM(l.qualified_units+l.pending_units+l.defective_units) FROM destination_receipt_line l JOIN destination_receipt r ON r.site_id=l.site_id AND r.id=l.receipt_id WHERE l.site_id=b.site_id AND l.binding_id=b.id AND r.status='POSTED'),0)),0) FROM destination_shipment_binding b WHERE b.site_id=? AND b.shipment_id=? AND b.sku_id=? AND b.is_active=TRUE",Long.class,c.site(),reference.get("shipment_id"),sku);
            if(remaining!=sum)throw fail("fba_allocation_invalid","请先完整分配同货件同SKU的待收数量，再核对原报告超收差异。");
        }
        db.update("INSERT INTO fba_receipt_event(site_id,scope_id,batch_id,source_row,sku_id,event_key,fingerprint,reference_id,units,occurred_at,occurred_local,business_date,fulfillment_center,catalog_version,correction_of,evidence,actor_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",c.site(),scopeId,batch,row.path("source_row").asInt(),sku,bytes(eventKey),row.path("fingerprint").asText(),reference.get("id"),qty,Timestamp.from(stamp.toInstant()),row.path("raw").path("Date and Time").asText(),java.sql.Date.valueOf(date),row.path("raw").path("Fulfillment Center").asText(),scope.get("catalog_version"),correction,evidence,c.actor());long event=last();
        db.update("UPDATE fba_receipt_event SET shipment_id=?,source_fingerprint=? WHERE site_id=? AND id=?",reference.get("shipment_id"),row.path("source_fingerprint").asText(row.path("fingerprint").asText()),c.site(),event);
        for(var allocation:allocations)db.update("INSERT INTO fba_event_allocation(site_id,event_id,binding_id,units) VALUES(?,?,?,?)",c.site(),event,allocation.get("binding"),allocation.get("units"));

        inventory.applyFba(c,List.of(new InventoryService.Delta(new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),receiptQuality,qty,"平台接收","FBA逻辑范围")),"fba_receipt",event,1,token,evidence,date);
        new FbaClassificationStore(db,json).recordReceipt(c,scope,event,correction,disposition,token);
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
        return event;
    }
    private Object action(ProductionContext c,JsonNode b,String token){
        if(b.has("report_sales_key"))throw fail("fba_report_reference_invalid","经营日报销售记录由已发布报告自动维护。");
        var scope=scope(c,id(b,"scope_id"));String kind=required(b,"kind",16),key=required(b,"event_key",255),reason=required(b,"reason",2000);if(!Set.of("FULFILLMENT","RETURN","OBSERVATION").contains(kind))throw fail("fba_action_invalid","请选择实际履约、实物退回或只读观察。");
        if(!b.path("report_version_ids").isEmpty()&&!scope.get("report_source_scope_id").toString().equals(b.path("_report_source_scope_id").asText()))throw fail("fba_report_reference_invalid","关联报表必须属于同账号范围。");
        var stamp=time(required(b,"occurred_at",64));String date=stamp.toLocalDate().toString();var effects=new ArrayList<InventoryService.Delta>();Long related=null;Map<Long,Long> fulfilled=new HashMap<>(),returned=new HashMap<>();Map<Long,String> fulfilledOrders=new HashMap<>();
        boolean reportReturn=kind.equals("RETURN")&&b.path("_trusted_report_return").asBoolean();
        if(kind.equals("RETURN")&&!reportReturn){
            related=id(b,"fulfillment_id");var source=one("SELECT * FROM fba_action WHERE site_id=? AND id=? AND scope_id=? AND kind='FULFILLMENT' AND status='POSTED'",c.site(),related,scope.get("id"));
            if(node(source.get("payload")).has("report_sales_key"))throw fail("fba_return_invalid","日报汇总没有客户订单，请通过退货日报登记实物退回。");
            if(stamp.toInstant().isBefore(Instant.parse(source.get("occurred_at").toString())))throw fail("fba_return_invalid","实物退回不能早于实际履约。");
            for(var line:node(source.get("payload")).path("lines")){fulfilled.put(id(line,"sku_id"),id(line,"units"));fulfilledOrders.put(id(line,"sku_id"),line.path("customer_order_ref").asText());}
            for(var prior:rows("SELECT payload FROM fba_action WHERE site_id=? AND related_action_id=? AND kind='RETURN' AND status='POSTED'",c.site(),related))for(var line:node(prior.get("payload")).path("lines"))returned.merge(id(line,"sku_id"),id(line,"units"),Math::addExact);
        }
        if(!b.path("physical_fact_confirmed").asBoolean())throw fail("fba_physical_evidence_required","请明确实际履约/实物退回或观察证据；退款不直接形成库存事实。经营日报销售由发布流程自动扣减。");
        var seen=new HashSet<Long>();for(var line:b.path("lines")){
            long sku=id(line,"sku_id");if(!seen.add(sku))throw fail("fba_action_invalid","同一规格请合并为本次实际数量。");currentIdentity(c,scope,b,sku);var identity=one("SELECT tracked FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?",c.site(),scope.get("id"),sku);if(!Boolean.parseBoolean(identity.get("tracked").toString()))throw fail("fba_not_tracked","所选规格未纳入跟踪，历史仍保留。");
            var inventoryKey=new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku);inventory.checkDate(c.site(),inventoryKey,date);
            if(kind.equals("OBSERVATION")){for(String field:List.of("sellable","reserved","unsellable","held"))InventoryService.number(line,field);continue;}
            long units=id(line,"units");String quality=kind.equals("FULFILLMENT")?"QUALIFIED":required(line,"quality",16);InventoryService.bucket(quality);checkFactDate(c,scope,sku,quality,date);
            String sourceEvent=required(line,"source_event_ref",255),customerOrder=required(line,"customer_order_ref",255);
            if(db.queryForObject("SELECT COUNT(*) FROM fba_action_line l JOIN fba_action a ON a.site_id=l.site_id AND a.id=l.action_id WHERE l.site_id=? AND l.scope_id=? AND l.kind=? AND l.source_event_key=? AND l.sku_id=? AND a.status='POSTED'",Long.class,c.site(),scope.get("id"),kind,bytes(sourceEvent),sku)>0)throw fail("fba_source_event_exists","同账号该规格的实物事件已经登记，不能换批次引用重复扣增库存。");
            if(kind.equals("RETURN")&&!reportReturn&&!customerOrder.equals(fulfilledOrders.get(sku)))throw fail("fba_return_order_conflict","实物退回客户订单与原履约该规格不一致。");
            if(kind.equals("RETURN")&&!reportReturn&&returned.getOrDefault(sku,0L)+units>fulfilled.getOrDefault(sku,0L))throw fail("fba_return_exceeds_fulfillment","实物退回累计不能超过同账号该次实际履约量。");
            effects.add(new InventoryService.Delta(inventoryKey,quality,kind.equals("FULFILLMENT")?-units:units,kind.equals("FULFILLMENT")?"FBA逻辑范围":"客户实物退回",kind.equals("FULFILLMENT")?"实际履约":"FBA质量分桶"));
        }
        if(seen.isEmpty())throw fail("fba_rows_required","请填写本次实际规格数量。");
        if(db.queryForObject("SELECT COUNT(*) FROM fba_action WHERE site_id=? AND scope_id=? AND kind=? AND event_key=?",Long.class,c.site(),scope.get("id"),kind,bytes(key))>0)throw fail("fba_event_key_exists","该实际事实已有记录，请查看历史，不要重复扣增库存。");
        var encodedEffects=effects.stream().map(e->Map.of("sku_id",Long.toString(e.key().sku()),"quality",e.quality(),"units",Long.toString(e.units()))).toList();
        var publicBody=(tools.jackson.databind.node.ObjectNode)b.deepCopy();for(String field:List.of("_catalog","_actor_name","_report_source_scope_id","_trusted_report_return"))publicBody.remove(field);
        db.update("INSERT INTO fba_action(site_id,scope_id,kind,event_key,occurred_at,business_date,payload,effects,related_action_id,actor_id) VALUES(?,?,?,?,?,?,?,?,?,?)",c.site(),scope.get("id"),kind,bytes(key),Timestamp.from(stamp.toInstant()),java.sql.Date.valueOf(date),encode(publicBody),encode(encodedEffects),related,c.actor());long action=last();
        if(!kind.equals("OBSERVATION"))for(var line:b.path("lines"))db.update("INSERT INTO fba_action_line(site_id,scope_id,action_id,sku_id,kind,source_event_key,customer_order_ref,units,quality) VALUES(?,?,?,?,?,?,?,?,?)",c.site(),scope.get("id"),action,id(line,"sku_id"),kind,bytes(required(line,"source_event_ref",255)),required(line,"customer_order_ref",255),id(line,"units"),kind.equals("FULFILLMENT")?"QUALIFIED":line.path("quality").asText());
        if(!effects.isEmpty())inventory.applyFba(c,effects,"fba_"+kind.toLowerCase(Locale.ROOT),action,1,token,reason,date);
        if(kind.equals("RETURN"))new FbaClassificationStore(db,json).recordAction(c,scope,action,1,token,b,false);
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
        inventory.audit(c,"fba_action",action,1,token,kind,reason,null,Map.of("kind",kind,"event_key",key,"stock_effect",!effects.isEmpty()));return state(c,n(scope.get("warehouse_id")));
    }
    private Object syncReports(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));
        if(!b.has("_trusted_report_returns")||!scope.get("report_source_scope_id").toString().equals(b.path("_report_source_scope_id").asText()))throw fail("fba_report_reference_invalid","自动更新需要同店铺已发布日报依据。");
        requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
        var previous=rows("SELECT * FROM fba_action WHERE site_id=? AND scope_id=? AND kind='RETURN' AND status='POSTED' AND JSON_EXTRACT(payload,'$.report_return_key') IS NOT NULL",c.site(),scope.get("id"));
        var seen=new HashSet<String>();
        for(var line:b.path("_trusted_report_returns")){
            String source=required(line,"source_event_ref",255);if(!seen.add(source))throw fail("fba_report_reference_invalid","日报存在重复退回身份，请核对原表。");
            long sku=id(line,"sku_id");
            var prior=previous.stream().filter(a->node(a.get("payload")).path("report_return_key").asText().equals(source)).findFirst().orElse(null);
            Map<String,Long> manualClassification=Map.of();
            if(prior!=null){
                var old=node(prior.get("payload")).path("lines").get(0);
                if(old.path("units").asText().equals(line.path("units").asText())&&old.path("quality").asText().equals(line.path("quality").asText())){
                    if(line.path("quality").asText().equals("DEFECTIVE")&&(!old.path("reason_code").asText("UNCLASSIFIED").equals(line.path("reason_code").asText("UNCLASSIFIED"))||!old.path("raw_disposition").asText().equals(line.path("raw_disposition").asText())||!old.path("report_version_id").asText().equals(line.path("report_version_id").asText()))){
                        new FbaClassificationStore(db,json).reportReason(c,scope,n(prior.get("id")),line,token);
                        var payload=(tools.jackson.databind.node.ObjectNode)node(prior.get("payload")).deepCopy();
                        var savedLine=(tools.jackson.databind.node.ObjectNode)payload.path("lines").get(0);
                        savedLine.put("reason_code",line.path("reason_code").asText());savedLine.put("raw_disposition",line.path("raw_disposition").asText());savedLine.put("report_version_id",line.path("report_version_id").asText());
                        payload.set("report_version_ids",b.path("report_version_ids"));
                        db.update("UPDATE fba_action SET payload=? WHERE site_id=? AND id=?",encode(payload),c.site(),prior.get("id"));
                    }
                    continue;
                }
                manualClassification=new FbaClassificationStore(db,json).reportOverride(c,scope,n(prior.get("id")));
                var undo=(tools.jackson.databind.node.ObjectNode)b.deepCopy();undo.put("action_id",prior.get("id").toString());undo.put("expected_revision",prior.get("revision").toString());reverse(c,undo,token);
            }else{
                long existing=db.queryForObject("SELECT COUNT(*) FROM fba_action_line l JOIN fba_action a ON a.site_id=l.site_id AND a.id=l.action_id WHERE l.site_id=? AND l.scope_id=? AND l.sku_id=? AND l.kind='RETURN' AND l.customer_order_ref=? AND a.status='POSTED' AND JSON_EXTRACT(a.payload,'$.report_return_key') IS NULL",Long.class,c.site(),scope.get("id"),sku,line.path("customer_order_ref").asText());
                if(existing>0)throw fail("fba_manual_return_review","该客户订单已有人工退回记录，请先核对关联，避免重复增加库存。");
            }
            long revision=db.queryForObject("SELECT COUNT(*) FROM fba_action WHERE site_id=? AND scope_id=? AND kind='RETURN' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.report_return_key'))=?",Long.class,c.site(),scope.get("id"),source)+1;
            var input=(tools.jackson.databind.node.ObjectNode)b.deepCopy();
            input.remove(List.of("_trusted_report_returns","_trusted_report_sales","_report_set_complete"));
            input.put("kind","RETURN");input.put("event_key",source+":"+revision);input.put("report_return_key",source);
            input.put("occurred_at",line.path("occurred_at").asText());input.put("physical_fact_confirmed",true);input.put("_trusted_report_return",true);
            input.set("lines",json.createArrayNode().add(line));
            action(c,input,token);
            if(!manualClassification.isEmpty()){
                long replacement=db.queryForObject("SELECT id FROM fba_action WHERE site_id=? AND scope_id=? AND kind='RETURN' AND event_key=?",Long.class,c.site(),scope.get("id"),bytes(source+":"+revision));
                new FbaClassificationStore(db,json).inheritReportOverride(c,scope,replacement,manualClassification,line,token);
            }
        }
        if(b.path("_report_set_complete").asBoolean())for(var prior:previous){
            if(seen.contains(node(prior.get("payload")).path("report_return_key").asText()))continue;
            var undo=(tools.jackson.databind.node.ObjectNode)b.deepCopy();undo.put("action_id",prior.get("id").toString());undo.put("expected_revision",prior.get("revision").toString());reverse(c,undo,token);
        }
        if(b.has("_trusted_report_sales"))syncSales(c,scope,b,token);
        return state(c,n(scope.get("warehouse_id")));
    }

    // Report sales are an explicit accounting basis, not a fabricated Amazon shipment.
    // Manual fulfillment on the same account/day/SKU replaces that share of the report.
    private Object manualAction(ProductionContext c,JsonNode b,String token,boolean reversing){
        Map<String,Object> original=reversing?one("SELECT * FROM fba_action WHERE site_id=? AND id=?",c.site(),id(b,"action_id")):null;
        String kind=reversing?original.get("kind").toString():b.path("kind").asText();
        if(!kind.equals("FULFILLMENT"))return reversing?reverse(c,b,token):action(c,b,token);
        if(reversing&&node(original.get("payload")).has("report_sales_key"))throw fail("fba_report_managed","请在原经营日报更正或撤回发布，销售库存会自动更新。");
        long scopeId=reversing?n(original.get("scope_id")):id(b,"scope_id");
        var scope=scope(c,scopeId);requireScope(db,c.site(),n(scope.get("warehouse_id")),n(scope.get("owner_id")));
        JsonNode details=reversing?node(original.get("payload")):b;
        String day=reversing?original.get("business_date").toString():time(required(b,"occurred_at",64)).toLocalDate().toString();
        var skus=new HashSet<Long>();for(var line:details.path("lines"))skus.add(id(line,"sku_id"));
        var reports=json.createArrayNode();
        for(var prior:reportSales(c,scopeId)){
            var payload=node(prior.get("payload"));var sale=payload.path("report_sales");
            if(!sale.path("business_date").asText().equals(day)||!skus.contains(id(sale,"sku_id")))continue;
            reports.add(sale);undoReportSale(c,b,prior,token);
        }
        if(reversing)reverse(c,b,token);else action(c,b,token);
        var refresh=(tools.jackson.databind.node.ObjectNode)b.deepCopy();refresh.set("_trusted_report_sales",reports);refresh.put("_report_set_complete",false);
        syncSales(c,scope,refresh,token);
        return state(c,n(scope.get("warehouse_id")));
    }
    private List<Map<String,Object>> reportSales(ProductionContext c,long scopeId){
        return rows("SELECT * FROM fba_action WHERE site_id=? AND scope_id=? AND kind='FULFILLMENT' AND status='POSTED' AND JSON_EXTRACT(payload,'$.report_sales_key') IS NOT NULL ORDER BY id",c.site(),scopeId);
    }
    private void undoReportSale(ProductionContext c,JsonNode b,Map<String,Object> prior,String token){
        var scope=scope(c,n(prior.get("scope_id")));
        var sale=node(prior.get("payload")).path("report_sales");
        String snapshot=snapshotCutoffs(c,scope).get(id(sale,"sku_id")+":QUALIFIED");
        if(snapshot!=null&&prior.get("business_date").toString().compareTo(snapshot)<=0){
            long next=n(prior.get("revision"))+1;
            db.update("UPDATE fba_action SET status='REVERSED',revision=? WHERE site_id=? AND id=?",next,c.site(),prior.get("id"));
            inventory.audit(c,"fba_action",n(prior.get("id")),next,token,"REPORT_SALES","历史销量已包含在盘点中，仅更新原依据，不再次调整库存",node(prior.get("payload")),Map.of("status","REVERSED","snapshot_on",snapshot));
            return;
        }
        var undo=(tools.jackson.databind.node.ObjectNode)b.deepCopy();undo.put("action_id",prior.get("id").toString());undo.put("expected_revision",prior.get("revision").toString());undo.put("_report_sales_sync",true);reverse(c,undo,token);
    }
    private void syncSales(ProductionContext c,Map<String,Object> scope,JsonNode b,String token){
        var previous=reportSales(c,n(scope.get("id")));var seen=new HashSet<String>();
        var replacements=new ArrayList<JsonNode>();
        var snapshots=snapshotCutoffs(c,scope);
        for(var sale:b.path("_trusted_report_sales")){
            long sku=id(sale,"sku_id"),total=InventoryService.number(sale,"report_units");
            String date=required(sale,"business_date",10);var stamp=time(required(sale,"occurred_at",64));
            if(!stamp.toLocalDate().toString().equals(date)||!InventoryService.day(date).isAfter(InventoryService.day(scope.get("cutoff_on").toString()))||sale.path("report_version_ids").isEmpty())throw fail("fba_report_reference_invalid","日报销售日期或发布版本无效。");
            currentIdentity(c,scope,b,sku);
            var tracked=one("SELECT tracked FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?",c.site(),scope.get("id"),sku);
            if(!Boolean.parseBoolean(tracked.get("tracked").toString()))throw fail("fba_not_tracked","日报商品尚未启用，请核对商品设置。");
            String key="report-sales:"+date+":"+sku;
            if(!seen.add(key))throw fail("fba_report_reference_invalid","日报销售规格重复，请核对原表。");
            String snapshot=snapshots.get(sku+":QUALIFIED");
            if(snapshot!=null&&date.compareTo(snapshot)<=0){
                var covered=previous.stream().filter(a->node(a.get("payload")).path("report_sales_key").asText().equals(key)).findFirst().orElse(null);
                if(covered!=null)undoReportSale(c,b,covered,token);
                continue;
            }
            long manual=db.queryForObject("SELECT COALESCE(SUM(l.units),0) FROM fba_action_line l JOIN fba_action a ON a.site_id=l.site_id AND a.id=l.action_id WHERE a.site_id=? AND a.scope_id=? AND a.kind='FULFILLMENT' AND a.status='POSTED' AND a.business_date=? AND l.sku_id=? AND JSON_EXTRACT(a.payload,'$.report_sales_key') IS NULL",Long.class,c.site(),scope.get("id"),date,sku);
            long units=Math.max(0,total-manual);
            var prior=previous.stream().filter(a->node(a.get("payload")).path("report_sales_key").asText().equals(key)).findFirst().orElse(null);
            if(prior!=null&&node(prior.get("payload")).path("lines").get(0).path("units").asLong()==units){
                var payload=(tools.jackson.databind.node.ObjectNode)node(prior.get("payload")).deepCopy();
                if(!payload.path("report_sales").equals(sale)){
                    payload.set("report_sales",sale);payload.set("report_version_ids",sale.path("report_version_ids"));
                    long next=n(prior.get("revision"))+1;
                    db.update("UPDATE fba_action SET payload=?,revision=? WHERE site_id=? AND id=?",encode(payload),next,c.site(),prior.get("id"));
                    inventory.audit(c,"fba_action",n(prior.get("id")),next,token,"REPORT_SALES","经营日报销售依据更新，数量不变",node(prior.get("payload")),payload);
                }
                continue;
            }
            if(prior!=null)undoReportSale(c,b,prior,token);
            var prepared=(tools.jackson.databind.node.ObjectNode)sale.deepCopy();prepared.put("units",Long.toString(units));replacements.add(prepared);
        }
        if(b.path("_report_set_complete").asBoolean())for(var prior:previous)if(!seen.contains(node(prior.get("payload")).path("report_sales_key").asText()))undoReportSale(c,b,prior,token);
        for(var prepared:replacements){
            long sku=id(prepared,"sku_id"),units=InventoryService.number(prepared,"units");String date=prepared.path("business_date").asText(),key="report-sales:"+date+":"+sku;
            var sale=(tools.jackson.databind.node.ObjectNode)prepared.deepCopy();sale.remove("units");
            var line=json.createObjectNode().put("sku_id",Long.toString(sku)).put("units",Long.toString(units)).put("source_event_ref",key);
            var payload=json.createObjectNode().put("reason","经营日报发布后自动扣减销售数量").put("report_sales_key",key);
            payload.set("report_sales",sale);payload.set("report_version_ids",sale.path("report_version_ids"));payload.set("lines",json.createArrayNode().add(line));
            long sequence=db.queryForObject("SELECT COUNT(*) FROM fba_action WHERE site_id=? AND scope_id=? AND kind='FULFILLMENT' AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.report_sales_key'))=?",Long.class,c.site(),scope.get("id"),key)+1;
            var effects=units==0?List.<InventoryService.Delta>of():List.of(new InventoryService.Delta(new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),"QUALIFIED",-units,"FBA逻辑范围","经营日报销售"));
            inventory.checkDate(c.site(),new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),date);
            var encoded=effects.stream().map(e->Map.of("sku_id",Long.toString(sku),"quality","QUALIFIED","units",Long.toString(e.units()))).toList();
            db.update("INSERT INTO fba_action(site_id,scope_id,kind,event_key,occurred_at,business_date,payload,effects,actor_id) VALUES(?,?,'FULFILLMENT',?,?,?,?,?,?)",c.site(),scope.get("id"),bytes(key+":"+sequence),Timestamp.from(time(prepared.path("occurred_at").asText()).toInstant()),java.sql.Date.valueOf(date),encode(payload),encode(encoded),c.actor());long action=last();
            if(units>0){
                db.update("INSERT INTO fba_action_line(site_id,scope_id,action_id,sku_id,kind,source_event_key,customer_order_ref,units,quality) VALUES(?,?,?,?,'FULFILLMENT',?,'',?,'QUALIFIED')",c.site(),scope.get("id"),action,sku,bytes(key),units);
                inventory.applyFba(c,effects,"fba_fulfillment",action,1,token,payload.path("reason").asText(),date);
            }
            db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
            inventory.audit(c,"fba_action",action,1,token,"REPORT_SALES",payload.path("reason").asText(),null,payload);
        }
    }

    private Object quality(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));revision(scope,b);
        String from=required(b,"from_quality",16),target=required(b,"target_quality",16),reason=required(b,"reason",2000),date=required(b,"business_date",10);
        if(!Set.of("QUALIFIED","DEFECTIVE","PENDING").contains(from)||!Set.of("QUALIFIED","DEFECTIVE","PENDING").contains(target)||from.equals(target))throw fail("fba_quality_invalid","请选择不同的有效库存状态。");
        if(!b.path("lines").isArray()||b.path("lines").isEmpty()||b.path("lines").size()>500)throw fail("fba_rows_required","请选择本次调整的商品和数量。");
        var effects=new ArrayList<InventoryService.Delta>();var seen=new HashSet<Long>();
        var snapshots=snapshotCutoffs(c,scope);
        for(var line:b.path("lines")){
            long sku=id(line,"sku_id"),units=id(line,"units");if(!seen.add(sku))throw fail("fba_quality_invalid","同一规格请合并调整数量。");
            currentIdentity(c,scope,b,sku);
            one("SELECT sku_id FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?",c.site(),scope.get("id"),sku);
            var key=new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku);
            inventory.checkDate(c.site(),key,date);
            for(String quality:List.of(from,target)){
                String snapshot=snapshots.get(sku+":"+quality);
                if(snapshot!=null&&date.compareTo(snapshot)<=0)throw fail("fba_snapshot_covered","该日期的库存状态已包含在盘点中，不能重复调整。");
            }
            effects.add(new InventoryService.Delta(key,from,-units,"库存状态调整","库存状态调整"));
            effects.add(new InventoryService.Delta(key,target,units,"库存状态调整","库存状态调整"));
        }
        long next=n(scope.get("revision"))+1;
        inventory.applyFba(c,effects,"fba_quality",n(scope.get("id")),next,token,reason,date);
        new FbaClassificationStore(db,json).recordQuality(c,scope,b,next,token);
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
        inventory.audit(c,"fba_quality",n(scope.get("id")),next,token,"QUALITY",reason,null,Map.of("from_quality",from,"target_quality",target,"lines",b.path("lines")));
        return state(c,n(scope.get("warehouse_id")));
    }

    private Object reverse(ProductionContext c,JsonNode b,String token){
        var before=one("SELECT * FROM fba_action WHERE site_id=? AND id=? FOR UPDATE",c.site(),id(b,"action_id"));revision(before,b);if(!"POSTED".equals(before.get("status")))throw fail("fba_action_reversed","该记录已冲销。");
        if(db.queryForObject("SELECT COUNT(*) FROM fba_action WHERE site_id=? AND related_action_id=? AND status='POSTED'",Long.class,c.site(),before.get("id"))>0)throw fail("fba_downstream_dependency","已有实物退回关联，先处理下游记录，不能直接冲销履约。");
        if(node(before.get("payload")).has("report_sales_key")&&!b.path("_report_sales_sync").asBoolean())throw fail("fba_report_managed","请在原经营日报更正或撤回发布，销售库存会自动更新。");
        var scope=scope(c,n(before.get("scope_id")));String reason=required(b,"reason",2000);var deltas=new ArrayList<InventoryService.Delta>();
        for(var e:node(before.get("effects"))){long sku=id(e,"sku_id");currentIdentity(c,scope,b,sku);checkFactDate(c,scope,sku,e.path("quality").asText(),before.get("business_date").toString());deltas.add(new InventoryService.Delta(new InventoryService.Key(n(scope.get("warehouse_id")),n(scope.get("owner_id")),sku),e.path("quality").asText(),-e.path("units").asLong(),"冲销","保留原事实历史"));}
        if(!deltas.isEmpty())inventory.applyFba(c,deltas,"fba_"+before.get("kind").toString().toLowerCase(Locale.ROOT),n(before.get("id")),n(before.get("revision"))+1,token,reason,before.get("business_date").toString());
        if(before.get("kind").equals("RETURN"))new FbaClassificationStore(db,json).recordAction(c,scope,n(before.get("id")),n(before.get("revision"))+1,token,node(before.get("payload")),true);
        db.update("UPDATE fba_scope SET revision=revision+1 WHERE site_id=? AND id=?",c.site(),scope.get("id"));
        db.update("UPDATE fba_action SET status='REVERSED',revision=revision+1 WHERE site_id=? AND id=?",c.site(),before.get("id"));inventory.audit(c,"fba_action",n(before.get("id")),n(before.get("revision"))+1,token,"REVERSE",reason,null,Map.of("status","REVERSED"));return state(c,n(scope.get("warehouse_id")));
    }
    private Object correctClassification(ProductionContext c,JsonNode b,String token){
        var scope=scope(c,id(b,"scope_id"));revision(scope,b);
        currentIdentity(c,scope,b,id(b,"sku_id"));
        new FbaClassificationStore(db,json).correct(c,scope,b,token);
        var publicBody=(tools.jackson.databind.node.ObjectNode)b.deepCopy();
        publicBody.remove(List.of("_catalog","_actor_name"));
        inventory.audit(c,"fba_scope",n(scope.get("id")),n(scope.get("revision"))+1,token,"CLASSIFICATION",required(b,"reason",2000),null,publicBody);
        return state(c,n(scope.get("warehouse_id")));
    }
    Object classifications(ProductionContext c,Map<String,String> query){
        long id=ProductionService.positive(json.getNodeFactory().textNode(query.getOrDefault("scope_id","")),"scope_id");
        return new FbaClassificationStore(db,json).details(c,scope(c,id),query);
    }
    private Object stocktake(ProductionContext c, JsonNode body, String token) {
        var scope = scope(c, id(body, "scope_id"));
        revision(scope, body);
        String reason = required(body, "reason", 2000);
        LocalDate date;
        try { date = LocalDate.parse(required(body, "business_date", 10)); }
        catch (DateTimeException error) { throw new ProductionError(422, "invalid_business_date", "请选择有效盘点日期。"); }
        if (date.isAfter(LocalDate.now(ZoneId.of("America/Los_Angeles"))))
            throw new ProductionError(422, "invalid_business_date", "盘点日期不能晚于店铺当前日期。");
        var input = body.path("lines");
        if (!input.isArray() || input.isEmpty() || input.size() > 100)
            throw new ProductionError(422, "invalid_lines", "请选择1至100个盘点规格。");
        var lines = json.createArrayNode();
        var seen = new HashSet<Long>();
        for (var line : input) {
            long sku = id(line, "sku_id");
            if (!seen.add(sku)) throw new ProductionError(422, "duplicate_count_sku", "同一规格不能重复盘点。");
            currentIdentity(c, scope, body, sku);
            one("SELECT sku_id FROM fba_identity WHERE site_id=? AND scope_id=? AND sku_id=?", c.site(), scope.get("id"), sku);
            long revision = id(line, "balance_revision");
            long units = InventoryService.number(line, "units");
            var count = json.createObjectNode();
            count.put("sku_id", Long.toString(sku)); count.put("units", Long.toString(units));
            count.put("expected_balance_revision", Long.toString(revision));
            count.put("quality", "QUALIFIED"); count.put("purpose", "COUNT");
            count.put("counted_on", date.toString()); count.put("evidence", reason);
            lines.add(count);
        }
        var countBody = json.createObjectNode();
        countBody.set("_catalog", body.path("_catalog"));
        countBody.put("reason", reason);
        countBody.put("warehouse_id", scope.get("warehouse_id").toString());
        countBody.put("owner_id", scope.get("owner_id").toString());
        countBody.put("kind", "ADJUST"); countBody.put("business_date", date.toString());
        countBody.set("lines", lines);
        inventory.postFbaCount(c, countBody, token);
        return state(c, n(scope.get("warehouse_id")));
    }
    Object state(ProductionContext c,long warehouse){
        var found=rows("SELECT * FROM fba_scope WHERE site_id=? AND warehouse_id=? ORDER BY owner_id",c.site(),warehouse);var result=new LinkedHashMap<String,Object>();result.put("enabled",true);result.put("scopes",found);result.put("initialized",!found.isEmpty());
        for(var item:found){var opening=rows("SELECT opening_metadata FROM inventory_scope WHERE site_id=? AND warehouse_id=? AND owner_id=?",c.site(),warehouse,item.get("owner_id"));if(!opening.isEmpty()&&opening.getFirst().get("opening_metadata")!=null)item.put("opening_metadata",node(opening.getFirst().get("opening_metadata")));}
        if(found.isEmpty())return result;
        var classification=new LinkedHashMap<String,Object>();
        for(var item:found)classification.put(item.get("id").toString(),new FbaClassificationStore(db,json).summary(c,item));
        result.put("classification_summary",classification);
        // A warehouse can represent several owners; each returned row retains scope_id.
        result.put("identities",rows("SELECT i.scope_id,i.sku_id,i.style_id,i.seller_sku_raw AS seller_sku,CAST(i.fnsku AS CHAR CHARACTER SET utf8mb4) AS fnsku,CAST(i.asin AS CHAR CHARACTER SET utf8mb4) AS asin,i.tracked,i.catalog_version,i.evidence,b.qualified_units AS sellable,b.pending_units,b.defective_units AS unsellable,b.unassessed_units,b.revision AS balance_revision FROM fba_identity i JOIN fba_scope s ON s.site_id=i.site_id AND s.id=i.scope_id JOIN inventory_balance b ON b.site_id=s.site_id AND b.warehouse_id=s.warehouse_id AND b.owner_id=s.owner_id AND b.sku_id=i.sku_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY i.scope_id,i.style_id,i.sku_id",c.site(),warehouse));
        result.put("references",rows("SELECT r.id,r.scope_id,CAST(r.reference_key AS CHAR CHARACTER SET utf8mb4) AS reference_id,r.shipment_id,r.shipment_revision,r.evidence FROM fba_reference r JOIN fba_scope s ON s.site_id=r.site_id AND s.id=r.scope_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY r.id",c.site(),warehouse));
        result.put("shipment_totals",rows("SELECT s.id AS scope_id,b.shipment_id,SUM(b.units) AS shipped_units,SUM(COALESCE((SELECT SUM(a.units) FROM fba_event_allocation a WHERE a.site_id=b.site_id AND a.binding_id=b.id),0)) AS received_units FROM fba_scope s JOIN destination_shipment_binding b ON b.site_id=s.site_id AND b.is_active=TRUE WHERE s.site_id=? AND s.warehouse_id=? AND EXISTS(SELECT 1 FROM production_shipment p WHERE p.site_id=s.site_id AND p.id=b.shipment_id AND p.status='CONFIRMED' AND p.destination_id=s.warehouse_id AND p.owner_id=s.owner_id) GROUP BY s.id,b.shipment_id ORDER BY s.id,b.shipment_id",c.site(),warehouse));
        result.put("batches",rows("SELECT b.id,b.scope_id,b.filename,b.status,b.revision,b.digest,b.source_kind,b.shipment_id,b.created_at FROM fba_receipt_batch b JOIN fba_scope s ON s.site_id=b.site_id AND s.id=b.scope_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY b.id DESC",c.site(),warehouse));
        result.put("receipt_links",rows("SELECT v.batch_id,v.source_row,v.event_id,v.units,v.evidence,e.sku_id,e.shipment_id,b.filename FROM fba_report_coverage v JOIN fba_receipt_event e ON e.site_id=v.site_id AND e.id=v.event_id AND e.source_kind='MANUAL' JOIN fba_receipt_batch b ON b.site_id=v.site_id AND b.id=v.batch_id JOIN fba_scope s ON s.site_id=e.site_id AND s.id=e.scope_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY v.created_at,v.batch_id,v.source_row,e.id",c.site(),warehouse));
        result.put("quality_events",rows("SELECT s.id AS scope_id,e.sku_id,e.quality,e.delta_units AS units,e.created_at AS occurred_at FROM inventory_event e JOIN fba_scope s ON s.site_id=e.site_id AND s.warehouse_id=e.warehouse_id AND s.owner_id=e.owner_id WHERE e.site_id=? AND s.warehouse_id=? AND e.document_kind='fba_quality' ORDER BY e.id",c.site(),warehouse));
        result.put("events",rows("SELECT e.id,e.scope_id,e.batch_id,e.source_row,e.sku_id,CAST(e.event_key AS CHAR CHARACTER SET utf8mb4) AS event_key,e.units,e.occurred_at,e.occurred_local,e.business_date,e.fulfillment_center,e.correction_of,e.evidence,e.source_kind,e.shipment_id,e.time_precision,e.reference_id AS reference_link_id,(SELECT CAST(r.reference_key AS CHAR CHARACTER SET utf8mb4) FROM fba_reference r WHERE r.site_id=e.site_id AND r.id=e.reference_id) AS reference_number,COALESCE((SELECT ev.quality FROM inventory_event ev WHERE ev.site_id=e.site_id AND ev.document_kind='fba_receipt' AND ev.document_id=e.id ORDER BY ev.id LIMIT 1),'QUALIFIED') AS quality FROM fba_receipt_event e JOIN fba_scope s ON s.site_id=e.site_id AND s.id=e.scope_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY e.id",c.site(),warehouse));
        var actions=rows("SELECT a.id,a.scope_id,a.kind,CAST(a.event_key AS CHAR CHARACTER SET utf8mb4) AS event_key,a.occurred_at,a.status,a.revision,a.related_action_id,a.payload FROM fba_action a JOIN fba_scope s ON s.site_id=a.site_id AND s.id=a.scope_id WHERE s.site_id=? AND s.warehouse_id=? ORDER BY a.id DESC",c.site(),warehouse);for(var action:actions)action.put("payload",node(action.get("payload")));result.put("actions",actions);
        result.put("history",rows("SELECT document_kind,document_id,revision,operation_kind,actor_name,reason,created_at FROM production_revision WHERE site_id=? AND ((document_kind='fba_scope' AND document_id IN (SELECT id FROM fba_scope WHERE site_id=? AND warehouse_id=?)) OR (document_kind='fba_action' AND document_id IN (SELECT a.id FROM fba_action a JOIN fba_scope s ON s.site_id=a.site_id AND s.id=a.scope_id WHERE s.site_id=? AND s.warehouse_id=?)) OR (document_kind='stock' AND operation_kind='POST' AND document_id IN (SELECT d.id FROM inventory_document d JOIN fba_scope s ON s.site_id=d.site_id AND s.warehouse_id=d.warehouse_id AND s.owner_id=d.owner_id WHERE s.site_id=? AND s.warehouse_id=? AND d.kind='ADJUST' AND d.status='POSTED'))) ORDER BY id DESC",c.site(),c.site(),warehouse,c.site(),warehouse,c.site(),warehouse));
        result.put("stock",inventory.read(c,"availability",Map.of("warehouse_id",Long.toString(warehouse))));
        result.put("stocktakes",rows("SELECT e.id,s.id AS scope_id,e.document_id,e.sku_id,e.quality,e.delta_units AS units,e.business_date,e.reason FROM inventory_event e JOIN inventory_document d ON d.site_id=e.site_id AND d.id=e.document_id AND d.kind='ADJUST' AND d.status='POSTED' JOIN fba_scope s ON s.site_id=e.site_id AND s.warehouse_id=e.warehouse_id AND s.owner_id=e.owner_id WHERE e.site_id=? AND s.warehouse_id=? AND e.document_kind='stock' ORDER BY e.id",c.site(),warehouse));
        result.put("snapshot_is_stock_event",false);result.put("platform_observation_state",actions.stream().anyMatch(a->"OBSERVATION".equals(a.get("kind"))&&"POSTED".equals(a.get("status")))?"AVAILABLE":"UNKNOWN");return result;
    }
}
