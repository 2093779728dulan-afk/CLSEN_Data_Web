package com.clsen.dataweb.production;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

record ProductionContext(long site, long actor, Set<String> roles, String actorName) {
    ProductionContext(long site,long actor,Set<String> roles){this(site,actor,roles,"账号"+actor);}
    void requireWrite() {
        if (!roles.contains("admin") && !roles.contains("data_manager"))
            throw new ProductionError(403,"role_forbidden","当前账号只能查看生产记录。");
    }
}

@Component
class InternalIdentityFilter extends OncePerRequestFilter {
    private final byte[] credential;
    private final boolean writesEnabled;
    private final boolean openingEnabled;
    private final boolean inventoryWritesEnabled;
    private final boolean orderShipmentWritesEnabled;
    private final boolean identityRebindingEnabled;
    InternalIdentityFilter(String token,boolean writesEnabled){this(token,writesEnabled,false,false,false);}
    InternalIdentityFilter(String token,boolean writesEnabled,boolean openingEnabled){this(token,writesEnabled,openingEnabled,false,false);}
    InternalIdentityFilter(String token,boolean writesEnabled,boolean openingEnabled,boolean inventoryWritesEnabled){this(token,writesEnabled,openingEnabled,inventoryWritesEnabled,false);}
    InternalIdentityFilter(String token,boolean writesEnabled,boolean openingEnabled,boolean inventoryWritesEnabled,boolean orderShipmentWritesEnabled){this(token,writesEnabled,openingEnabled,inventoryWritesEnabled,orderShipmentWritesEnabled,false);}
    @org.springframework.beans.factory.annotation.Autowired
    InternalIdentityFilter(@Value("${PRODUCTION_SERVICE_TOKEN}") String token, @Value("${PRODUCTION_WRITES_ENABLED:true}") boolean writesEnabled, @Value("${PRODUCTION_OPENING_ENABLED:false}") boolean openingEnabled, @Value("${PRODUCTION_INVENTORY_WRITES_ENABLED:false}") boolean inventoryWritesEnabled, @Value("${PRODUCTION_ORDER_SHIPMENT_WRITES_ENABLED:false}") boolean orderShipmentWritesEnabled, @Value("${PRODUCTION_IDENTITY_REBIND_ENABLED:false}") boolean identityRebindingEnabled) {
        if (token.length()<32) throw new IllegalArgumentException("Production service token must have at least 32 characters");
        credential=("Bearer "+token).getBytes(StandardCharsets.UTF_8);
        this.writesEnabled=writesEnabled;
        this.openingEnabled=openingEnabled;
        this.inventoryWritesEnabled=inventoryWritesEnabled;
        this.orderShipmentWritesEnabled=orderShipmentWritesEnabled;
        this.identityRebindingEnabled=identityRebindingEnabled;
    }
    @Override protected void doFilterInternal(HttpServletRequest request,HttpServletResponse response,FilterChain chain) throws ServletException,IOException {
        String supplied=request.getHeader("Authorization");
        if (supplied==null || !MessageDigest.isEqual(credential,supplied.getBytes(StandardCharsets.UTF_8))) {
            response.setStatus(403);response.setContentType("application/json");
            response.getWriter().write("{\"error\":{\"code\":\"service_identity_required\",\"message\":\"Internal service identity required.\"}}");return;
        }
        try {
            long site=Long.parseLong(request.getHeader("X-Production-Site"));
            long actor=Long.parseLong(request.getHeader("X-Production-Actor"));
            String roles=request.getHeader("X-Production-Roles");
            if(site<1 || actor<1 || roles==null)throw new IllegalArgumentException();
            String name=request.getHeader("X-Production-Actor-Name");
            if(name!=null)name=new String(java.util.Base64.getUrlDecoder().decode(name),StandardCharsets.UTF_8);
            if(name!=null&&name.length()>255)throw new IllegalArgumentException();
            request.setAttribute("production.context",new ProductionContext(site,actor,Arrays.stream(roles.split(",")).collect(Collectors.toUnmodifiableSet()),name==null?"账号"+actor:name));
        } catch(IllegalArgumentException error) {
            response.setStatus(403);response.setContentType("application/json");
            response.getWriter().write("{\"error\":{\"code\":\"service_context_invalid\",\"message\":\"Internal context invalid.\"}}");return;
        }
        boolean opening=openingEnabled && request.getMethod().equals("POST") && Set.of("/internal/production/inventory/openings/preview","/internal/production/inventory/openings/confirm").contains(request.getRequestURI());
        String inventoryPrefix="/internal/production/inventory/",path=request.getRequestURI();
        boolean inventory=inventoryWritesEnabled && request.getMethod().equals("POST") && Set.of("documents","holds","reservations","loans","plans","destination-bindings","destination-receipts","destination-settlements","destination-uploads").stream().anyMatch(resource->path.equals(inventoryPrefix+resource)||path.startsWith(inventoryPrefix+resource+"/"));
        boolean directory=(orderShipmentWritesEnabled||inventoryWritesEnabled)&&(path.matches("/internal/production/(factories|warehouses)(/[1-9][0-9]*)?")&&(request.getMethod().equals("POST")||request.getMethod().equals("PUT")));
        boolean orderShipment=orderShipmentWritesEnabled && (path.equals("/internal/production/orders")||path.startsWith("/internal/production/orders/")||path.equals("/internal/production/shipments")||path.startsWith("/internal/production/shipments/"));
        boolean sourceCheck=orderShipmentWritesEnabled && request.getMethod().equals("POST") && Set.of("/internal/production/sources/orders/check","/internal/production/sources/shipments/check").contains(path);
        boolean rebind=identityRebindingEnabled && request.getMethod().equals("POST") && path.equals(inventoryPrefix+"identity-rebindings") && ((ProductionContext)request.getAttribute("production.context")).roles().contains("admin");
        if(!writesEnabled && !opening && !inventory && !directory && !orderShipment && !sourceCheck && !rebind && !Set.of("GET","HEAD").contains(request.getMethod())) {
            response.setStatus(403);response.setContentType("application/json");response.setCharacterEncoding("UTF-8");
            String message=orderShipmentWritesEnabled?"当前开放预计订单、实际出货及日常库存操作，库存期初仍未启用。":inventoryWritesEnabled?"当前仅开放日常库存操作，库存期初、订单及出货尚未启用。":"当前环境仅开放查询，库存期初、单据及收发操作尚未启用。";
            response.getWriter().write("{\"error\":{\"code\":\"production_read_only\",\"message\":\""+message+"\"}}");return;
        }
        chain.doFilter(request,response);
    }
}
