package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class IdentityRebindingFilterTest {
    void check(boolean enabled,String role,String path,boolean expected) throws Exception {
        String token="test-rebinding-internal-token-0123456789";
        var filter=new InternalIdentityFilter(token,false,false,false,false,enabled);
        var request=new MockHttpServletRequest("POST",path);request.addHeader("Authorization","Bearer "+token);request.addHeader("X-Production-Site","1");request.addHeader("X-Production-Actor","1");request.addHeader("X-Production-Roles",role);
        var called=new AtomicBoolean();var response=new MockHttpServletResponse();filter.doFilter(request,response,(r,s)->called.set(true));assertEquals(expected,called.get());if(!expected)assertEquals(403,response.getStatus());
    }
    @Test void onlyTheExplicitMaintenanceRouteIsOpened() throws Exception {
        check(true,"admin","/internal/production/inventory/identity-rebindings",true);
        for(String path:java.util.List.of("/internal/production/inventory/documents","/internal/production/inventory/openings/confirm","/internal/production/orders","/internal/production/shipments"))check(true,"admin",path,false);
    }
    @Test void disabledOrNonAdminCannotUseTheMaintenanceRoute() throws Exception {
        check(false,"admin","/internal/production/inventory/identity-rebindings",false);
        check(true,"data_manager","/internal/production/inventory/identity-rebindings",false);
        check(true,"viewer","/internal/production/inventory/identity-rebindings",false);
    }
    @Test void factoryCreationFollowsOnlyTheOrderWriteScope() throws Exception {
        String token="test-rebinding-internal-token-0123456789";
        for(boolean enabled:java.util.List.of(false,true)) {
            var filter=new InternalIdentityFilter(token,false,false,false,enabled,false);
            var request=new MockHttpServletRequest("POST","/internal/production/factories");request.addHeader("Authorization","Bearer "+token);request.addHeader("X-Production-Site","1");request.addHeader("X-Production-Actor","1");request.addHeader("X-Production-Roles","admin");
            var called=new AtomicBoolean();filter.doFilter(request,new MockHttpServletResponse(),(r,s)->called.set(true));assertEquals(enabled,called.get());
        }
    }
    @Test void scopedImportAndFbaDoNotRequireGeneralWrites() throws Exception {
        String token="test-rebinding-internal-token-0123456789";
        for(boolean enabled:java.util.List.of(false,true))for(String path:java.util.List.of("/internal/production/files/orders/preview","/internal/production/files/shipments/preview","/internal/production/files/previews/11111111-2222-3333-4444-555555555555/confirm","/internal/production/inventory/fba-scopes","/internal/production/inventory/fba-stocktake")){
            var filter=new InternalIdentityFilter(token,false,false,enabled,enabled,false);
            var request=new MockHttpServletRequest("POST",path);request.addHeader("Authorization","Bearer "+token);request.addHeader("X-Production-Site","1");request.addHeader("X-Production-Actor","1");request.addHeader("X-Production-Roles","admin");
            var called=new AtomicBoolean();filter.doFilter(request,new MockHttpServletResponse(),(r,t)->called.set(true));assertEquals(enabled,called.get(),path);
        }
        check(false,"admin","/internal/production/files/other/preview",false);
        check(false,"admin","/internal/production/inventory/openings/confirm",false);
    }
}
