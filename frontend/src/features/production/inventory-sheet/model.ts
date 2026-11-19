export type Period = 'week' | 'month' | 'quarter' | 'year';
export type Range = { start: string; end: string };
export type Quantity = { value: string | null; state: string; partial: boolean; reason: string; known_units?: string; unknown_count?: number; evidence?: { label: string; units: string } };
export type DisplayStyle = { id: string; style_code: string; sku_count: number };
export type StockSetting = { threshold: string; replenish: boolean };
export type StockSettings = Record<string, StockSetting>;
export type SourceReview = { backup_at: string; reports_through: string; stock_date: string; stock_literal_units: string; stock_matched_units: string; stock_pending_units: string; stock_deferred_units?: string; report_known_units: string; report_known_returns: string; report_known_net: string; pending_identity_count: number; fba_ledger?: { cutoff_on: string; scope_id: string } | null;
  packings: { filename: string; batch_date: string; boxes: number; packed_units: string; received_units: string | null; reference_id: string | null; differences: string[] }[]; issues: string[] };
export type SheetSku = { production_statuses?: { order_id: string; order_number: string; status: string }[]; sku_id: string; style_id: string; style_code: string; sku: string; standard_color: string; standard_size: string; values: Record<string, Quantity>; alert: { level: string; configurable: boolean }; };
export type SheetResponse = { version: string; today: string; as_of: string; reporting_timezone: string; rows: SheetSku[]; totals: Record<string, Quantity>; cumulative_from: string | null; source_review?: SourceReview | null;
  resolved_scope: { fba: { id: string }; domestic: { warehouse_id: string; owner_id: string } };
  settings: { revision: string; style_ids: string[]; sku_alert_settings: Record<string, StockSettings>; can_manage: boolean; can_manage_styles?: boolean }; display_styles: DisplayStyle[]; issues: { label: string }[]; };
export type ScopeOptions = { today: string; default_as_of?: string; reporting_timezone: string; domestic: { warehouse_id: string; owner_id: string; warehouse_name: string; owner_name: string; type: string }[]; fba: { id: string; warehouse_name: string; store_evidence: string }[] };
export const MIN_DATE = '1900-01-01';
export const periods: Period[] = ['week', 'month', 'quarter', 'year'];
const quantityFormat = new Intl.NumberFormat('zh-CN');
export function num(value: bigint | number | string) { return quantityFormat.format(BigInt(value)); }
export function change(value: bigint, previous: bigint) {
  if (previous <= 0n) return '不适用';
  const scaled = (value - previous) * 1000n / previous;
  return `${scaled / 10n}.${scaled < 0n ? -scaled % 10n : scaled % 10n}%`;
}
export function stockAlert(item: SheetSku, _cutoff: string, settings: StockSettings) {
  const raw = item.values.available?.value;
  const available = raw === null || raw === undefined ? null : BigInt(raw);
  const { threshold, replenish } = settings[item.sku_id] ?? { threshold: '20', replenish: true };
  let level = 'normal';
  if (available === null) level = 'unknown';
  else if (available <= 0n) level = replenish ? 'empty' : 'sold-out';
  else if (replenish && available <= BigInt(threshold)) level = 'low';
  return { available, threshold, replenish, level };
}
const DAY = 86400000;
export const parseDate = (value: string) => new Date(`${value}T00:00:00Z`);
export const dateText = (value: Date) => value.toISOString().slice(0, 10);
export const addDays = (value: string, days: number) => dateText(new Date(parseDate(value).getTime() + days * DAY));

function monthDate(year: number, month: number, day: number) {
  const last = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  return dateText(new Date(Date.UTC(year, month, Math.min(day, last))));
}

export function ranges(period: Period, cutoff: string): { current: Range; previous: Range; yearAgo: Range } {
  const date = parseDate(cutoff);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (period === 'week') {
    const start = addDays(cutoff, -((date.getUTCDay() + 6) % 7));
    return {
      current: { start, end: cutoff },
      previous: { start: addDays(start, -7), end: addDays(cutoff, -7) },
      yearAgo: { start: addDays(start, -364), end: addDays(cutoff, -364) },
    };
  }
  const months = { month: 1, quarter: 3, year: 12 }[period];
  let firstMonth = Math.floor(month / months) * months;
  let end = addDays(monthDate(year, firstMonth + months, 1), -1);
  if (end > cutoff) {
    firstMonth -= months;
    end = addDays(monthDate(year, firstMonth + months, 1), -1);
  }
  const start = monthDate(year, firstMonth, 1);
  return {
    current: { start, end },
    previous: { start: monthDate(year, firstMonth - months, 1), end: addDays(start, -1) },
    yearAgo: { start: monthDate(year - 1, firstMonth, 1), end: addDays(monthDate(year - 1, firstMonth + months, 1), -1) },
  };
}

export function weekHeading(range: Range): string {
  function monthWeek(value: string, includeYear: boolean) {
    const date = parseDate(value);
    const first = parseDate(`${value.slice(0, 7)}-01`);
    const week = Math.floor((date.getUTCDate() - 1 + (first.getUTCDay() + 6) % 7) / 7) + 1;
    return `${includeYear ? `${date.getUTCFullYear()}年` : ''}${date.getUTCMonth() + 1}月第${week}周`;
  }
  const start = monthWeek(range.start, true);
  if (range.start.slice(0, 7) === range.end.slice(0, 7)) return start;
  return `${start} / ${monthWeek(range.end, range.start.slice(0, 4) !== range.end.slice(0, 4))}`;
}

