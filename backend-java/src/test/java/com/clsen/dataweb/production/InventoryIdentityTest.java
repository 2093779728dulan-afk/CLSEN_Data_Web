package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class InventoryIdentityTest {
    @Test void parsesThePersistedBackupIdentityWithoutChangingItsBusinessFields() {
        var identity=InventoryService.displayIdentity("2205 · 正式SKU待补 · Black / L");
        assertEquals("2205",identity.get("style_code"));
        assertEquals("正式SKU待补",identity.get("display_sku"));
        assertEquals("Black",identity.get("standard_color"));
        assertEquals("L",identity.get("standard_size"));
        assertTrue(InventoryService.displayIdentity("未结构化身份").isEmpty());
    }
}
