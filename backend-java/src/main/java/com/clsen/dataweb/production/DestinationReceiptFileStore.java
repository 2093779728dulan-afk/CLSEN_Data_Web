package com.clsen.dataweb.production;

import java.security.MessageDigest;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.JsonNode;

/** Retains the original bytes independently of the editable business draft. */
final class DestinationReceiptFileStore {
    private final JdbcTemplate db;
    DestinationReceiptFileStore(JdbcTemplate db){this.db=db;}
    Object save(ProductionContext c,JsonNode input){
        long shipment=ProductionService.positive(input.get("shipment_id"),"shipment_id");
        if(db.queryForObject("SELECT COUNT(*) FROM production_shipment WHERE site_id=? AND id=?",Long.class,c.site(),shipment)!=1)
            throw new ProductionError(409,"shipment_missing","来源出货不存在或不属于当前站点。");
        String filename=ProductionService.text(input,"filename",255);
        if(filename.isBlank()||filename.contains("/")||filename.contains("\\")||filename.contains("\r")||filename.contains("\n"))
            throw new ProductionError(422,"invalid_filename","文件名无效。");
        byte[] bytes;
        try{bytes=Base64.getDecoder().decode(ProductionService.text(input,"file_base64",2_800_000));}
        catch(IllegalArgumentException error){throw new ProductionError(422,"invalid_file","文件编码无效。");}
        if(bytes.length==0||bytes.length>2_000_000)throw new ProductionError(422,"invalid_file","请选择不超过2MB的标准表。");
        String digest;
        try{digest=HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));}
        catch(java.security.NoSuchAlgorithmException error){throw new IllegalStateException(error);}
        String id=UUID.randomUUID().toString();
        db.update("INSERT INTO destination_receipt_upload(id,site_id,shipment_id,actor_id,filename,digest,file_data) VALUES(?,?,?,?,?,?,?)",id,c.site(),shipment,c.actor(),filename,digest,bytes);
        return Map.of("upload_id",id,"filename",filename,"sha256",digest);
    }
    byte[] original(ProductionContext c,String id){
        c.requireWrite();
        try{UUID.fromString(id);}catch(IllegalArgumentException error){throw new ProductionError(422,"invalid_upload","原件身份无效。");}
        var rows=db.queryForList("SELECT file_data FROM destination_receipt_upload WHERE site_id=? AND id=?",c.site(),id);
        if(rows.isEmpty())throw new ProductionError(404,"upload_missing","原件不存在或不属于当前站点。");
        return (byte[])rows.getFirst().get("file_data");
    }
}
