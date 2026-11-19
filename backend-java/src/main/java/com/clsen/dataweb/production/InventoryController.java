package com.clsen.dataweb.production;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/internal/production/inventory")
public class InventoryController {
    private final InventoryService service;
    public InventoryController(InventoryService service){this.service=service;}
    private ProductionContext context(HttpServletRequest r){return (ProductionContext)r.getAttribute("production.context");}
    @GetMapping("/{resource}") public Object read(HttpServletRequest r,@PathVariable String resource,@RequestParam Map<String,String> q){return service.read(context(r),resource,q);}
    @GetMapping("/documents/{id}") public Object detail(HttpServletRequest r,@PathVariable long id){return service.read(context(r),"documents/"+id,Map.of());}
    @GetMapping("/destination-receipts/{id}") public Object destinationReceipt(HttpServletRequest r,@PathVariable long id){return service.read(context(r),"destination-receipts/"+id,Map.of());}
    @GetMapping("/fba-batches/{id}") public Object fbaBatch(HttpServletRequest r,@PathVariable long id){return service.read(context(r),"fba-batches/"+id,Map.of());}
    @GetMapping("/fba-scopes/{id}") public Object fbaScope(HttpServletRequest r,@PathVariable long id){return service.read(context(r),"fba-scopes/"+id,Map.of());}
    @GetMapping(value="/fba-batches/{id}/original",produces="text/csv") public byte[] fbaOriginal(HttpServletRequest r,@PathVariable long id){return service.fbaOriginal(context(r),id);}
    @GetMapping(value="/destination-uploads/{id}/original",produces="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet") public byte[] destinationOriginal(HttpServletRequest r,@PathVariable String id){return service.destinationOriginal(context(r),id);}
    @PostMapping("/{resource}") public Object create(HttpServletRequest r,@PathVariable String resource,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode b){return service.command(context(r),resource,b,key);}
    @PostMapping("/{resource}/{action}") public Object opening(HttpServletRequest r,@PathVariable String resource,@PathVariable String action,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode b){return service.command(context(r),resource+"/"+action,b,key);}
    @PostMapping("/{resource}/{id}/{action}") public Object change(HttpServletRequest r,@PathVariable String resource,@PathVariable long id,@PathVariable String action,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode b){return service.command(context(r),resource+"/"+id+"/"+action,b,key);}
}
