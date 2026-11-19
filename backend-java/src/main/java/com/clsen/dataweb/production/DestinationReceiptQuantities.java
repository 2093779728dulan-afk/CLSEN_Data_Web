package com.clsen.dataweb.production;

/** Integer-only receipt arithmetic shared by receipt and shortage settlement. */
final class DestinationReceiptQuantities {
    private DestinationReceiptQuantities() {}

    static long received(long qualified, long pending, long defective) {
        requireNonnegative(qualified, pending, defective);
        try { return Math.addExact(Math.addExact(qualified, pending), defective); }
        catch (ArithmeticException ex) {
            throw new ProductionError(422, "integer_out_of_range", "实收数量合计超出支持范围。");
        }
    }

    static long remaining(long shipped, long received, long settled) {
        requireNonnegative(shipped, received, settled);
        if (received > shipped || settled > shipped - received)
            throw new ProductionError(422, "receipt_exceeds_remaining", "实收及已结案数量超过发出量，请保留差异并重新核对。");
        return shipped - received - settled;
    }

    private static void requireNonnegative(long... values) {
        for (long value : values) if (value < 0)
            throw new ProductionError(422, "invalid_integer", "数量必须是非负整数。");
    }
}
