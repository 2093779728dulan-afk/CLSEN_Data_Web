package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class ProductionPlanTest {
    final ObjectMapper json=new ObjectMapper();
    @Test void defaultsFollowDemandAndExplicitPlansRemainIndependent() {
        assertNull(ProductionService.productionPlan(json.createObjectNode(),Map.of(),100,"").units());
        var old=Map.<String,Object>of("expected_units","100","planned_production_units","70","production_plan_reason","use stock","produced_units","20");
        assertEquals(70L,ProductionService.productionPlan(json.createObjectNode(),old,110,"").units());
        assertEquals("use stock",ProductionService.productionPlan(json.createObjectNode(),old,110,"unrelated correction").reason());
        assertEquals(0L,ProductionService.productionPlan(json.valueToTree(Map.of("planned_production_units","0")),Map.of(),100,"use stock").units());
        var follow=json.createObjectNode();follow.putNull("planned_production_units");
        assertNull(ProductionService.productionPlan(follow,old,110,"restore default").units());
    }
    @Test void changedPlansRequireReasonsAndCannotRewriteActualProduction() {
        var input=json.valueToTree(Map.of("planned_production_units","70"));
        assertEquals("production_plan_reason_required",assertThrows(ProductionError.class,()->ProductionService.productionPlan(input,Map.of(),100,"")).code);
        var old=Map.<String,Object>of("expected_units","100","produced_units","80");
        assertEquals("production_plan_below_actual",assertThrows(ProductionError.class,()->ProductionService.productionPlan(input,old,100,"use stock")).code);
        for(String bad:List.of("-1","1.5","9223372036854775808"))assertEquals("invalid_production_plan",assertThrows(ProductionError.class,()->ProductionService.productionPlan(json.valueToTree(Map.of("planned_production_units",bad)),Map.of(),100,"reason")).code);
    }
}
