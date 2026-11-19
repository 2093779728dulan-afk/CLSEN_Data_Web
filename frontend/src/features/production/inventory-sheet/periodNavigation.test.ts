import { expect, it } from 'vitest';
import { periodTarget } from './periodNavigation';

it.each([
  ['2026-10-25', 'week', -1, '2026-10-18'],
  ['2026-10-25', 'week', 1, '2026-11-01'],
  ['2026-11-10', 'week', 1, undefined],
  ['2026-10-25', 'month', -1, '2026-09-30'],
  ['2026-10-25', 'month', 1, '2026-11-10'],
  ['2026-09-30', 'month', 1, '2026-10-31'],
  ['2026-10-25', 'quarter', -1, '2026-09-30'],
  ['2026-09-30', 'quarter', 1, '2026-11-10'],
  ['2026-11-10', 'quarter', 1, undefined],
  ['2026-10-25', 'year', -1, '2025-12-31'],
  ['2026-11-10', 'year', 1, undefined],
  ['1900-01-01', 'month', -1, undefined],
] as const)('moves %s %s %s to the adjacent calendar period', (date, period, direction, expected) => {
  expect(periodTarget(date, period, direction, '2026-11-10')).toBe(expected);
});
it('keeps leap-month and cross-year boundaries', () => {
  expect(periodTarget('2024-03-10', 'month', -1, '2026-11-10')).toBe('2024-02-29');
  expect(periodTarget('2026-01-01', 'quarter', -1, '2026-11-10')).toBe('2025-12-31');
});
