package com.clsen.dataweb.production;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/internal/production/files")
public class ProductionFileController {
    private final ProductionFiles files;
    public ProductionFileController(ProductionFiles files){this.files=files;}
    private ProductionContext context(HttpServletRequest r){return (ProductionContext)r.getAttribute("production.context");}
    @PostMapping("/{kind}/preview") public Object preview(HttpServletRequest r,@PathVariable String kind,@RequestBody JsonNode body){return files.preview(context(r),kind,body);}
    @PostMapping("/previews/{id}/confirm") public Object confirm(HttpServletRequest r,@PathVariable String id,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return files.confirm(context(r),id,key,body);}
    @GetMapping(value="/{kind}/template",produces="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") public byte[] template(@PathVariable String kind,@RequestParam(defaultValue="v1") String version){return files.template(kind,version);}
    @GetMapping(value="/{kind}/export",produces="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") public byte[] export(HttpServletRequest r,@PathVariable String kind,@RequestParam(defaultValue="") String from,@RequestParam(defaultValue="") String to,@RequestParam(name="shipment_from",defaultValue="") String sf,@RequestParam(name="shipment_to",defaultValue="") String st,@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String status,@RequestParam(defaultValue="") String sku,@RequestParam(defaultValue="") String order,@RequestParam(defaultValue="") String tracking){return files.export(context(r),kind,from,to,sf,st,q,status,sku,order,tracking,java.util.Objects.toString(r.getParameter("factory"),""),java.util.Objects.toString(r.getParameter("progress"),""));}
}
