package com.clsen.dataweb.production;

import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;

class DestinationReceiptQuantitiesTest {
    @Test void partialReceiptsAndSettlementRemainSeparate() {
        assertEquals(60, DestinationReceiptQuantities.received(56, 2, 2));
        assertEquals(38, DestinationReceiptQuantities.received(38, 0, 0));
        assertEquals(2, DestinationReceiptQuantities.remaining(100, 98, 0));
        assertEquals(0, DestinationReceiptQuantities.remaining(100, 98, 2));
    }
    @Test void refusesOverflowNegativeAndOverReceipt() {
        assertThrows(ProductionError.class, () -> DestinationReceiptQuantities.received(-1, 0, 0));
        assertThrows(ProductionError.class, () -> DestinationReceiptQuantities.received(Long.MAX_VALUE, 1, 0));
        assertThrows(ProductionError.class, () -> DestinationReceiptQuantities.remaining(100, 99, 2));
        assertThrows(ProductionError.class, () -> DestinationReceiptQuantities.remaining(100, -1, 0));
    }
}
