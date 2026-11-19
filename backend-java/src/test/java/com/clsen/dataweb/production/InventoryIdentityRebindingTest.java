package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

class InventoryIdentityRebindingTest {
    final ObjectMapper json=new ObjectMapper();
    @Test void rewritesOnlyNamedSkuReferencesAndPreservesQuantitiesAndOriginalSnapshot() {
        var original=json.readTree("{\"sku_id\":\"900000000001\",\"units\":\"3\",\"source\":\"900000000001\",\"nested\":[{\"sku_id\":900000000001,\"units\":7}]}");
        var changed=InventoryIdentityRebinding.rewriteSkuReferences(original,Map.of(900000000001L,270L));
        assertEquals("270",changed.path("sku_id").asText());
        assertEquals(270L,changed.path("nested").get(0).path("sku_id").asLong());
        assertTrue(changed.path("nested").get(0).path("sku_id").isNumber());
        assertEquals("3",changed.path("units").asText());
        assertEquals(7,changed.path("nested").get(0).path("units").asInt());
        assertEquals("900000000001",changed.path("source").asText());
        assertEquals("900000000001",original.path("sku_id").asText());
    }
    @Test void exactAsciiIdentityAndOnlyExplicitScopedColorConfirmationsAreAccepted() {
        assertTrue(InventoryIdentityRebinding.sameIdentity("1123","SKY BLUE","M","1123","Sky Blue","M",false));
        assertFalse(InventoryIdentityRebinding.sameIdentity("2204","Light Brown","S","2204","Brown","S",true));
        assertFalse(InventoryIdentityRebinding.sameIdentity("1126","GREY","M","1126","Gray","M",false));
        assertTrue(InventoryIdentityRebinding.sameIdentity("1126","GREY","M","1126","Gray","M",true));
        assertTrue(InventoryIdentityRebinding.sameIdentity("2121","LT GREY","L","2121","Light Gray","L",true));
        assertFalse(InventoryIdentityRebinding.sameIdentity("22003","Khaki","S","2203","Khaki","S",true));
        assertFalse(InventoryIdentityRebinding.sameIdentity("1126","GREY","M","1126","Gray","L",true));
        assertFalse(InventoryIdentityRebinding.sameIdentity("1123","ＧＲＥＹ","M","1123","GREY","M",true));
    }
}
