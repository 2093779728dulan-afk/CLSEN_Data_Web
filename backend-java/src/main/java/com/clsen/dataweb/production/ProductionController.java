package com.clsen.dataweb.production;

import jakarta.servlet.http.HttpServletRequest;
import java.util.Map;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/internal/production")
public class ProductionController {
    private final ProductionService service;
    public ProductionController(ProductionService service){this.service=service;}
    private ProductionContext context(HttpServletRequest request){return (ProductionContext)request.getAttribute("production.context");}
    @GetMapping("/health") public Object health(){return Map.of("status","ok","version","1.1.0-SNAPSHOT");}
    @GetMapping("/workbench") public Object workbench(){return Map.of("version",2,"directory_supported",true);}
    @GetMapping("/inventory/progress-chains") public Object chains(HttpServletRequest r,@RequestParam Map<String,String> q){return service.chains(context(r),q);}
    @GetMapping("/factories") public Object factories(HttpServletRequest r,@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="ACTIVE") String status,@RequestParam(defaultValue="1") int page){return service.directoryList(context(r),"factories",q,status,page,"","");}
    @PostMapping("/factories") public Object factory(HttpServletRequest r,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.createFactory(context(r),key,body);}
    @GetMapping("/factories/{id}") public Object factoryDetail(HttpServletRequest r,@PathVariable long id){return service.directoryDetail(context(r),"factories",id);}
    @PutMapping("/factories/{id}") public Object factoryEdit(HttpServletRequest r,@PathVariable long id,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.directorySave(context(r),"factories",id,key,body);}
    @GetMapping("/warehouses") public Object warehouses(HttpServletRequest r,@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String status,@RequestParam(defaultValue="1") int page,@RequestParam(defaultValue="") String type,@RequestParam(defaultValue="") String country){return service.directoryList(context(r),"warehouses",q,status,page,type,country);}
    @GetMapping("/warehouses/{id}") public Object warehouseDetail(HttpServletRequest r,@PathVariable long id){return service.directoryDetail(context(r),"warehouses",id);}
    @PostMapping("/warehouses") public Object warehouseCreate(HttpServletRequest r,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.directorySave(context(r),"warehouses",null,key,body);}
    @PutMapping("/warehouses/{id}") public Object warehouseEdit(HttpServletRequest r,@PathVariable long id,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.directorySave(context(r),"warehouses",id,key,body);}
    @GetMapping("/summary") public Object summary(HttpServletRequest request,@RequestParam(defaultValue="") String from,@RequestParam(defaultValue="") String to,@RequestParam(name="shipment_from",defaultValue="") String shipmentFrom,@RequestParam(name="shipment_to",defaultValue="") String shipmentTo,@RequestParam(defaultValue="") String sku,@RequestParam(defaultValue="") String order){return service.summary(context(request),from,to,shipmentFrom,shipmentTo,sku,order);}
    @GetMapping("/commands/{token}") public Object result(HttpServletRequest request,@PathVariable String token){return service.commandResult(context(request),token);}
    @PostMapping("/sources/{kind}/check") public Object sourceCheck(HttpServletRequest request,@PathVariable String kind,@RequestBody JsonNode body){return service.checkSource(context(request),kind,body);}
    @GetMapping("/{kind}") public Object list(HttpServletRequest request,@PathVariable String kind,@RequestParam(defaultValue="") String q,@RequestParam(defaultValue="") String status,@RequestParam(defaultValue="") String from,@RequestParam(defaultValue="") String to,@RequestParam(defaultValue="") String sku,@RequestParam(defaultValue="") String order,@RequestParam(defaultValue="1") int page,@RequestParam(name="page_size",defaultValue="20") int pageSize,@RequestParam(defaultValue="") String tracking,@RequestParam(defaultValue="false") boolean selectable,@RequestParam(defaultValue="") String factory){return service.list(context(request),kind,q,status,from,to,sku,order,page,pageSize,tracking,selectable,factory,java.util.Objects.toString(request.getParameter("warehouse_id"),""),java.util.Objects.toString(request.getParameter("owner_id"),""),java.util.Objects.toString(request.getParameter("progress"),""));}
    @GetMapping("/{kind}/{id}") public Object detail(HttpServletRequest request,@PathVariable String kind,@PathVariable long id){return service.get(context(request),kind,id);}
    @PostMapping("/{kind}") public Object create(HttpServletRequest request,@PathVariable String kind,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.command(context(request),kind,null,"create",key,body);}
    @PutMapping("/{kind}/{id}") public Object update(HttpServletRequest request,@PathVariable String kind,@PathVariable long id,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.command(context(request),kind,id,"update",key,body);}
    @DeleteMapping("/{kind}/{id}") public Object delete(HttpServletRequest request,@PathVariable String kind,@PathVariable long id,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){return service.command(context(request),kind,id,"delete",key,body);}
    @PostMapping("/{kind}/{id}/{action}") public Object command(HttpServletRequest request,@PathVariable String kind,@PathVariable long id,@PathVariable String action,@RequestHeader("Idempotency-Key") String key,@RequestBody JsonNode body){if(!java.util.Set.of("confirm","correct","void","demand-changes","close-tracking","reopen-tracking","allocation-corrections","production-progress","complete-production","reopen-production").contains(action))throw new ProductionError(404,"not_found","操作不存在。");return service.command(context(request),kind,id,action,key,body);}
}
