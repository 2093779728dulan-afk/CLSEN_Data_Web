import { describe, expect, it } from "vitest";

import {
  decimalStringToScaledBigInt,
  formatCoverage,
  formatMoney,
  formatSixPlaceDecimal,
} from "./metricFormatting";

describe("exact metric formatting", () => {
  it.each([
    ["0.00", "0.00"],
    ["1234567.80", "1,234,567.80"],
    ["-12.50", "-12.50"],
  ])("formats canonical money %s without binary float", (value, expected) => {
    expect(formatMoney(value)).toBe(expected);
  });

  it.each(["1", "01.00", "1.0", "+1.00", "1.000", "NaN"])(
    "rejects non-canonical money %s",
    (value) => expect(() => formatMoney(value)).toThrow(),
  );

  it.each([
    ["-0.250000", "-0.250000"],
    ["0.000000", "0.000000"],
    ["1.000001", "1.000001"],
    ["12.345678", "12.345678"],
    [null, "—"],
  ])("preserves signed conversion %s", (value, expected) => {
    expect(formatSixPlaceDecimal(value)).toBe(expected);
  });

  it.each([
    ["0.000000", "0.000000"],
    ["1.000000", "1.000000"],
    [null, "—"],
  ])("formats bounded coverage %s", (value, expected) => {
    expect(formatCoverage(value)).toBe(expected);
  });

  it.each(["-0.000001", "1.000001", "2.000000"])(
    "rejects out-of-range coverage %s",
    (value) => expect(() => formatCoverage(value)).toThrow(),
  );

  it("parses chart coordinates as bounded scaled BigInt", () => {
    expect(decimalStringToScaledBigInt("-12.500000", 6)).toBe(-12_500_000n);
    expect(decimalStringToScaledBigInt("359.88", 2)).toBe(35_988n);
    expect(() => decimalStringToScaledBigInt(`${"9".repeat(40)}.00`, 2)).toThrow();
  });
});
