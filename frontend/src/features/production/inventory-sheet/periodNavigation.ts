import { MIN_DATE, addDays, dateText, parseDate, ranges, type Period } from './model';

function calendarStart(cutoff: string, period: Period): string {
  if (period === 'week') return ranges('week', cutoff).current.start;
  const value = parseDate(cutoff);
  const month = period === 'year' ? 0 : period === 'quarter' ? Math.floor(value.getUTCMonth() / 3) * 3 : value.getUTCMonth();
  return dateText(new Date(Date.UTC(value.getUTCFullYear(), month, 1)));
}

export function periodTarget(cutoff: string, period: Period, direction: -1 | 1, maxDate: string): string | undefined {
  const current = calendarStart(cutoff, period);
  let target = addDays(current, direction === -1 ? -1 : 13);
  if (period !== 'week' && direction === 1) {
    const start = parseDate(current), months = { month: 1, quarter: 3, year: 12 }[period];
    target = dateText(new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + months * 2, 0)));
  }
  target = target < MIN_DATE ? MIN_DATE : target > maxDate ? maxDate : target;
  return calendarStart(target, period) !== current ? target : undefined;
}
