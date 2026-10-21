export const trendMetricLabels = {
  units: "销量（件）",
  sales: "销售额（报告原币）",
  returns: "退货（件）",
  sessions: "会话（次）",
  conversion: "转化率（比率）",
} as const;

const MONEY_PATTERN = /^-?(?:0|[1-9][0-9]*)\.[0-9]{2}$/;
const SIX_PLACE_PATTERN = /^-?(?:0|[1-9][0-9]*)\.[0-9]{6}$/;
const MAX_INTEGER_DIGITS = 30;

function canonicalParts(value: string, scale: 2 | 6): {
  negative: boolean;
  integer: string;
  fraction: string;
} {
  const pattern = scale === 2 ? MONEY_PATTERN : SIX_PLACE_PATTERN;
  if (!pattern.test(value)) throw new Error("Decimal string is not canonical.");
  const negative = value.startsWith("-");
  const unsigned = negative ? value.slice(1) : value;
  const [integer, fraction] = unsigned.split(".");
  if (integer === undefined || fraction === undefined) {
    throw new Error("Decimal string is not canonical.");
  }
  if (integer.length > MAX_INTEGER_DIGITS) {
    throw new Error("Decimal string exceeds the chart bound.");
  }
  return { negative, integer, fraction };
}

function localized(value: string, scale: 2 | 6): string {
  const { negative, integer, fraction } = canonicalParts(value, scale);
  const grouped = integer.replace(/\B(?=(?:[0-9]{3})+(?![0-9]))/g, ",");
  return `${negative ? "-" : ""}${grouped}.${fraction}`;
}

export function decimalStringToScaledBigInt(
  value: string,
  scale: 2 | 6,
): bigint {
  const { negative, integer, fraction } = canonicalParts(value, scale);
  const magnitude = BigInt(`${integer}${fraction}`);
  return negative ? -magnitude : magnitude;
}

export function formatMoney(value: string): string {
  return localized(value, 2);
}

export function formatSixPlaceDecimal(value: string | null): string {
  return value === null ? "—" : localized(value, 6);
}

export function formatCoverage(value: string | null): string {
  if (value === null) return "—";
  const scaled = decimalStringToScaledBigInt(value, 6);
  if (scaled < 0n || scaled > 1_000_000n) {
    throw new Error("Coverage must be between zero and one.");
  }
  return localized(value, 6);
}
