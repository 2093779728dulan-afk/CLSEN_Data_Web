import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ApiRequestError, requestApi, writeApi, StableOperationKeyStore } from '../../../api/client';
import { RequestGate } from '../../../api/requestGate';
import { useAuthzGeneration } from '../../../app/AuthzGenerationContext';
import { LinkButton, Menu } from '../../../design-system';
import { useProductionLeave } from '../useProductionLeave';
import { ArrowDown, ArrowRightLeft, ArrowUp, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Download, Filter, LoaderCircle, Maximize2, Minimize2, Search, X } from 'lucide-react';
import { Button } from '../../../design-system/Button';
import { Input } from '../../../design-system/Input';
import { Table } from '../../../design-system/Table';
import './styles.css';
import { MIN_DATE, addDays, change, num, periods, ranges, stockAlert, weekHeading, type SheetSku, type Period, type Range, type StockSettings, type SheetResponse, type ScopeOptions, type Quantity } from './model';
import { DetailPanel, type Detail, type DetailRequest } from './DetailPanel';
import { StockAlertPanel } from './StockAlertPanel';
import { StyleDisplayPicker } from './StyleDisplayPicker';
import { SheetReads } from './SheetReads';
import { periodTarget } from './periodNavigation';
import { useLoad } from '../useProductionApi';

type GridRow = { id: string; sku: string; items: SheetSku[]; values: Record<string, bigint | null>; states: Record<string, Quantity> };
type Comparison = { current: string; previous: string; metric: 'units' | 'returns' | 'net' };
type WeekView = 'units' | 'net';
type PeriodView = 'net' | 'split';
type SummaryPeriod = 'month' | 'quarter' | 'year';
type PeriodViews = Record<SummaryPeriod, PeriodView>;
type Tone = 'production' | 'inventory' | 'sales' | 'returns';
type Column = { key: string; label: string; heading?: string; headerLabel?: string; tone?: Tone; ratio?: boolean; comparison?: Comparison; detail?: Detail; range?: Range; title?: string };
type Group = { key: string; label: string; columns: Column[]; defaultKeys?: string[]; tone?: Tone };
type StyleGroup = { id: string; code: string; row: GridRow; skus: GridRow[]; partial: boolean };
type Sort = { key: string; direction: 0 | 1 | -1 };
type StockFilter = 'all' | 'empty' | 'low' | 'stopped';
type SheetFilters = { cutoff: string; query: string; stockFilter: StockFilter };
type SheetSnapshot = { data: SheetResponse; filters: SheetFilters };
type OpenDetail = { rowId: string } & (DetailRequest | { type: 'alerts'; key: 'available'; label: string; range: Range; skuId?: string });
const STOCK_FILTER_LABELS = { all: '全部', empty: '缺货', low: '低库存', stopped: '停止补货' };
const DEFAULT_PERIOD_VIEWS: PeriodViews = { month: 'net', quarter: 'net', year: 'net' };
const PERIOD_LABELS = { week: '周度', month: '月度', quarter: '季度', year: '年度' };
const ACCUMULATED_COLUMNS = [['dispatched', '发货合计'], ['units', '累计销量'], ['returns', '累计退货'], ['net', '累计净销量']] as const;
const ADJUSTMENT_COLUMNS = [['removed', '移除订单'], ['warehouseDamaged', '仓库损坏'], ['warehouseLost', '仓库丢失'], ['carrierDamaged', '承运商损坏'], ['unreceivedReturn', '未收到退货'], ['defective', '缺陷'], ['customerDamaged', '客户损坏'], ['shipmentDifference', '货件差异']] as const;

function makeRow(sku: string, items: SheetSku[]): GridRow {
  const states = items[0]!.values;
  return { id: `sku:${items[0]!.sku_id}`, sku, items,
    values: Object.fromEntries(Object.entries(states).map(([key, value]) => [key, value.value === null ? null : BigInt(value.value)])), states };
}

function aggregateRows(id: string, label: string, rows: GridRow[]): GridRow {
  const states: Record<string, Quantity> = {};
  const values: GridRow['values'] = {};
  for (const key of Object.keys(rows[0]?.values ?? {})) {
    const entries = rows.map(row => row.states[key]!);
    const unknown = entries.some(value => value.value === null);
    const sum = entries.reduce((total, value) => total + BigInt(value.value ?? value.known_units ?? '0'), 0n);
    values[key] = unknown ? null : sum;
    const partial = entries.find(value => value.partial);
    states[key] = { value: unknown ? null : sum.toString(), state: partial?.state ?? 'ready', partial: Boolean(partial),
      reason: [...new Set(entries.map(value => value.reason).filter(Boolean))].join('；') };
    const evidence = entries.flatMap(value => value.evidence ? [value.evidence] : []);
    if (evidence.length && new Set(evidence.map(value => value.label)).size === 1) {
      states[key].evidence = { label: evidence[0]!.label, units: evidence.reduce((total, value) => total + BigInt(value.units), 0n).toString() };
    }
  }
  return { id, sku: label, items: rows.flatMap(row => row.items), values, states };
}

function rowStockAlerts(row: GridRow, cutoff: string, settings: StockSettings) {
  const alerts = row.items.map(item => ({ sku: item.sku, ...stockAlert(item, cutoff, settings) }));
  const entries = alerts.filter(alert => alert.level === 'empty' || alert.level === 'low');
  let level = alerts.every(alert => alert.level === 'sold-out') ? 'sold-out' : 'normal';
  if (entries.length) level = entries.some(alert => alert.level === 'empty') ? 'empty' : 'low';
  const note = alerts.filter(alert => !alert.replenish || alert.level === 'empty' || alert.level === 'low')
    .map(alert => `${alert.sku}，可售${alert.available === null ? '待核' : num(alert.available)}件，提醒值${num(alert.threshold)}件${alert.replenish ? '' : '，停止补货'}`).join('。');
  return { level, note };
}

function dateHeading(range: Range): string {
  const start = range.start.replaceAll('-', '/');
  if (range.start === range.end) return start;
  const end = range.start.slice(0, 4) === range.end.slice(0, 4) ? range.end.slice(5) : range.end;
  return `${start}—${end.replaceAll('-', '/')}`;
}

function periodHeading(period: 'month' | 'quarter' | 'year', range: Range): string {
  const year = range.start.slice(0, 4);
  const month = Number(range.start.slice(5, 7));
  if (period === 'month') return `${year}年${month}月`;
  if (period === 'quarter') return `${year}年第${Math.ceil(month / 3)}季度`;
  return `${year}年`;
}

function makeGroups(cutoff: string, weekView: WeekView, periodViews: PeriodViews, cumulativeFrom = cutoff): Group[] {
  const all = { start: cumulativeFrom, end: cutoff };
  const groups: Group[] = [
    {
      key: 'production', label: '未完成订单', tone: 'production',
      columns: ([['pending', '待生产'], ['pendingReceipt', '待入库']] as const).map(([key, label]) => ({
        key: `production.${key}`, label, heading: `截至 ${dateHeading({ start: cutoff, end: cutoff })}`,
        detail: 'production', range: { start: cutoff, end: cutoff }, title: `截至当日未完成订单的${label}，点击查看对应明细`,
      })),
    },
    {
      key: 'inventory', label: `库存 ${dateHeading({ start: cutoff, end: cutoff })}`, tone: 'inventory', defaultKeys: ['domestic', 'available', 'transit'],
      columns: [
        { key: 'domestic', label: '广州成品仓', heading: '成品仓库存', detail: 'stock', range: { start: cutoff, end: cutoff } },
        { key: 'available', label: '可售', heading: '美国FBA', detail: 'stock', range: { start: cutoff, end: cutoff } },
        { key: 'transit', label: '在途', heading: '美国FBA', detail: 'transit', range: { start: cutoff, end: cutoff } },
        { key: 'unsellable', label: '不可售', heading: '美国FBA', detail: 'stock', range: { start: cutoff, end: cutoff } },
        { key: 'fba', label: '实际在库', heading: '美国FBA', detail: 'stock', range: { start: cutoff, end: cutoff } },
        ...ADJUSTMENT_COLUMNS.map(([key, label]) => ({ key, label, heading: '库存调整',
          detail: 'adjustments' as const, range: { start: cutoff, end: cutoff } })),
      ],
    },
  ];
  for (const period of periods) {
    const dates = ranges(period, cutoff);
    const current = (metric: string) => `${period}.${metric}`;
    const previous = (metric: string) => `${period}.previous.${metric}`;
    if (period === 'week') {
      for (const tone of ['sales', 'returns'] as const) {
        const metric = tone === 'returns' ? 'returns' : weekView;
        const label = { units: '销量', returns: '退货', net: '净销量' }[metric];
        const dailyColumns: Column[] = [];
        for (let date = dates.current.start; date <= cutoff; date = addDays(date, 1)) {
          dailyColumns.push({
            key: `day.${date}.${metric}`, label, headerLabel: date.slice(5).replace('-', '/'),
            detail: tone, range: { start: date, end: date }, title: `${dateHeading({ start: date, end: date })}${label}`,
          });
        }
        const summaries: Column[] = [
          { key: current(metric), label, headerLabel: metric === 'net' ? '本周净销量' : '本周合计', detail: tone, range: dates.current,
            title: `${weekHeading(dates.current)} ${dateHeading(dates.current)}` },
          { key: `${period}.${metric}Mom`, label: `${label}变化`, headerLabel: '对比上周',
            comparison: { current: current(metric), previous: previous(metric), metric } },
        ];
        groups.push({ key: `week-${tone}`, label: `${label} ${weekHeading(dates.current)}`, tone, columns: [...summaries, ...dailyColumns] });
      }
      continue;
    }
    const currentHeading = periodHeading(period, dates.current);
    const previousHeading = periodHeading(period, dates.previous);
    const comparisonHeading = `对比${{ month: '上月', quarter: '上季度', year: '上年' }[period]}`;
    const metrics = periodViews[period] === 'net' ? ['net'] as const : ['units', 'returns'] as const;
    const periodColumns: Column[] = [];
    for (const [range, heading, key] of [[dates.current, currentHeading, current], [dates.previous, previousHeading, previous]] as const) {
      for (const metric of metrics) {
        periodColumns.push({ key: key(metric), label: { units: '销量', returns: '退货', net: '净销量' }[metric], heading,
          detail: metric === 'returns' ? 'returns' : 'sales', range, title: dateHeading(range) });
      }
    }
    for (const metric of metrics) {
      periodColumns.push({ key: `${period}.${metric}Mom`, label: `${{ units: '销量', returns: '退货', net: '净销量' }[metric]}变化`,
        heading: comparisonHeading, comparison: { current: current(metric), previous: previous(metric), metric } });
    }
    groups.push({
      key: period,
      label: `${PERIOD_LABELS[period]} ${currentHeading}`,
      defaultKeys: metrics.map(metric => current(metric)),
      columns: periodColumns,
    });
  }
  groups.push({ key: 'cumulative', label: '累计销售与退货', columns: ACCUMULATED_COLUMNS.map(([key, label]) => ({ key, label, detail: key === 'dispatched' ? 'shipments' : key === 'returns' ? 'returns' : 'sales', range: all })) });
  return groups.map(group => ({
    ...group,
    columns: group.columns.map(column => ({
      ...column,
      tone: group.tone,
      heading: column.heading ?? dateHeading(group.key === 'inventory' ? { start: cutoff, end: cutoff } : all),
    })),
  }));
}

function comparisonData(row: GridRow, comparison: Comparison) {
  const value = row.values[comparison.current] ?? null;
  const previous = row.values[comparison.previous] ?? null;
  if (value === null || previous === null) return { delta: null, label: '', title: '当前或上期数据不完整', tone: 0 };
  const delta = value - previous;
  const direction = delta > 0n ? 1 : delta < 0n ? -1 : 0;
  const tone = direction * (comparison.metric === 'returns' ? -1 : 1);
  const partial = row.states[comparison.current]?.partial || row.states[comparison.previous]?.partial;
  const label = (delta > 0n ? `↑ ${num(delta)}` : delta < 0n ? `↓ ${num(-delta)}` : '→ 0');
  const description = delta > 0n ? `增加 ${num(delta)} 件` : delta < 0n ? `减少 ${num(-delta)} 件` : '持平';
  let percentage = `变化 ${change(value, previous)}`;
  if (previous === 0n && delta !== 0n) percentage = '上期为 0，百分比不适用';
  if (comparison.metric === 'net' && previous < 0n) percentage = '上期为负数，百分比不适用';
  const metric = { units: '销量', returns: '退货', net: '净销量' }[comparison.metric];
  return { delta, label, title: `${metric}${description}，本期 ${num(value)} 件，上期 ${num(previous)} 件，${percentage}${partial ? '，包含部分数据或完整性未定' : ''}`, tone };
}

function ComparisonValue({ row, comparison }: { row: GridRow; comparison: Comparison }) {
  const result = comparisonData(row, comparison);
  return <span className="change" data-tone={result.tone} title={result.title} aria-label={result.title}>{result.delta === 0n ? '' : result.label}</span>;
}

function nextSort(sort: Sort, key: string): Sort {
  if (sort.key !== key || sort.direction === 0) return { key, direction: -1 };
  if (sort.direction === -1) return { key, direction: 1 };
  return { key: 'sku', direction: 0 };
}

function compareNumbers(left: bigint | null, right: bigint | null, direction: 1 | -1): number {
  if (left === right) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  return direction * (left > right ? 1 : -1);
}

function sortForGroups(sort: Sort, oldGroups: Group[], nextGroups: Group[], expanded: string[]): Sort {
  const oldGroup = oldGroups.find(group => group.columns.some(column => column.key === sort.key));
  if (!oldGroup) return sort;
  const nextGroup = nextGroups.find(group => group.key === oldGroup.key)!;
  const shown = nextGroup.defaultKeys && !expanded.includes(nextGroup.key)
    ? nextGroup.columns.filter(column => nextGroup.defaultKeys!.includes(column.key)) : nextGroup.columns;
  if (shown.some(column => column.key === sort.key)) return sort;
  const oldColumn = oldGroup.columns.find(column => column.key === sort.key)!;
  const prefix = sort.key.slice(0, sort.key.lastIndexOf('.') + 1);
  const replacement = oldColumn.comparison ? shown.find(column => column.comparison)
    : shown.find(column => !column.comparison && column.key.startsWith(prefix));
  return { ...sort, key: replacement?.key ?? shown[0]!.key };
}

function DateNavigation({ date, maxDate, onDateChange, jumpTo, prepare }: {
  date: string; maxDate: string; onDateChange: (date: string) => void; jumpTo: (key: string) => void; prepare: (dates: string[]) => void;
}) {
  const [period, setPeriod] = useState<Period>('week');
  const unit = { week: '周', month: '个月', quarter: '季度', year: '年' }[period];
  const previous = periodTarget(date, period, -1, maxDate);
  const next = periodTarget(date, period, 1, maxDate);
  useEffect(() => {
    const readNeighbors = () => prepare([previous, next].filter((value): value is string => Boolean(value)));
    if (window.requestIdleCallback) {
      const idle = window.requestIdleCallback(readNeighbors, { timeout: 1000 });
      return () => window.cancelIdleCallback(idle);
    }
    const timeout = window.setTimeout(readNeighbors, 150);
    return () => window.clearTimeout(timeout);
  }, [previous, next, prepare]);
  return <div className="date-controls" role="group" aria-label="周期日期导航">
    <label className="period-picker" title={PERIOD_LABELS[period]}>
      <CalendarDays size={16} aria-hidden="true" /><ChevronDown size={11} aria-hidden="true" />
      <select aria-label="日期切换周期" value={period} onChange={event => {
        const value = event.target.value as Period; setPeriod(value); jumpTo(value === 'week' ? 'week-sales' : value);
      }}>{periods.map(value => <option key={value} value={value}>{PERIOD_LABELS[value]}</option>)}</select>
    </label>
    <Button icon={<ChevronLeft size={15} />} variant="quiet" aria-label={`上一${unit}`} title={`上一${unit}`} disabled={!previous}
      onPointerEnter={() => { if (previous) prepare([previous]); }} onFocus={() => { if (previous) prepare([previous]); }} onClick={() => onDateChange(previous!)} />
    <Input type="date" aria-label="统计截止日期" title="统计截止日期" min={MIN_DATE} max={maxDate} value={date}
      onChange={event => { const value = event.target.value; if (value >= MIN_DATE && value <= maxDate) onDateChange(value); }} />
    <Button icon={<ChevronRight size={15} />} variant="quiet" aria-label={`下一${unit}`} title={`下一${unit}`} disabled={!next}
      onPointerEnter={() => { if (next) prepare([next]); }} onFocus={() => { if (next) prepare([next]); }} onClick={() => onDateChange(next!)} />
  </div>;
}

function SheetTable({ scopeQuery, defaultDate, today }: { scopeQuery: string; defaultDate: string; today: string }) {
  const { generation, productionReads } = useAuthzGeneration();
  const dataRevision = useSyncExternalStore(productionReads.subscribe, productionReads.version);
  const [params, setParams] = useSearchParams();
  const gate = useRef<RequestGate | undefined>(undefined);
  useEffect(() => {
    gate.current = new RequestGate();
    return () => gate.current?.dispose();
  }, []);
  const [snapshot, setSnapshot] = useState<SheetSnapshot>();
  const confirmedSnapshot = useRef<SheetSnapshot | undefined>(undefined);
  const reads = useRef(new SheetReads(productionReads));
  useEffect(() => () => reads.current.clear(), []);
  const data = snapshot?.data;
  const [loadError, setLoadError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const cacheRefresh = useRef(`${refresh}:${dataRevision}`);
  const [saving, setSaving] = useState(false);
  const [saveUnknown, setSaveUnknown] = useState(false);
  const operationKeys = useRef(new StableOperationKeyStore());
  const dateParam = params.get('as_of');
  const queryParam = params.get('q') ?? '';
  const filterParam = params.get('stock_filter') ?? 'all';
  const conditions = useMemo<SheetFilters>(() => ({
    cutoff: dateParam && /^\d{4}-\d{2}-\d{2}$/.test(dateParam) && dateParam >= MIN_DATE ? dateParam : defaultDate,
    query: queryParam, stockFilter: filterParam in STOCK_FILTER_LABELS ? filterParam as StockFilter : 'all',
  }), [dateParam, queryParam, filterParam, defaultDate]);
  const setConditions = useCallback((update: SheetFilters | ((current: SheetFilters) => SheetFilters)) => {
    const next = typeof update === 'function' ? update(conditions) : update;
    setParams(current => {
      const value = new URLSearchParams(current);
      value.set('as_of', next.cutoff);
      if (next.query) value.set('q', next.query); else value.delete('q');
      if (next.stockFilter !== 'all') value.set('stock_filter', next.stockFilter); else value.delete('stock_filter');
      return value;
    }, { replace: true });
  }, [conditions, setParams]);
  const [searchText, setSearchText] = useState(conditions.query);
  const { cutoff, query, stockFilter } = snapshot?.filters ?? conditions;
  const [showLoading, setShowLoading] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(false);
  const stockSettings: StockSettings = useMemo(() => data?.settings.sku_alert_settings[data.resolved_scope.fba.id] ?? {}, [data?.settings.sku_alert_settings, data?.resolved_scope.fba.id]);
  const catalog = useMemo(() => data?.rows ?? [], [data?.rows]);
  const MAX_DATE = data?.today ?? today;
  const [navigationReset, setNavigationReset] = useState(0);
  const [weekView, setWeekView] = useState<WeekView>('units');
  const [periodViews, setPeriodViews] = useState<PeriodViews>(DEFAULT_PERIOD_VIEWS);
  const store = '广州店';
  const [sort, setSort] = useState<Sort>({ key: 'sku', direction: 0 });
  const [expandedGroups, setExpandedGroups] = useState<string[]>([]);
  const [expandedStyles, setExpandedStyles] = useState<string[]>([]);
  const [detail, setDetail] = useState<OpenDetail>();
  const [viewport, setViewport] = useState({ top: 0, height: 0 });
  const [detailHeight, setDetailHeight] = useState(0);
  const [focusedRow, setFocusedRow] = useState('');
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [stylePicker, setStylePicker] = useState(false);
  const [pendingAction, setPendingAction] = useState<(() => void)>();
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState('');
  const [fullscreen, setFullscreen] = useState(false);
  const fullscreenTrigger = useRef<HTMLButtonElement>(null);
  const fullscreenExit = useRef<HTMLButtonElement>(null);
  const sheet = useRef<HTMLDivElement>(null);
  const groupHeaders = useRef(new Map<string, HTMLTableCellElement>());
  const pendingGroup = useRef<string | undefined>(undefined);
  const detailOrigin = useRef<{ left: number; top: number } | undefined>(undefined);
  const pendingDetailScroll = useRef<{ left: number; top: number } | undefined>(undefined);
  const leave = useProductionLeave(settingsDirty, saving, saveUnknown);
  useEffect(() => {
    if (!fullscreen || !sheet.current) return;
    const trigger = fullscreenTrigger.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const background: { element: HTMLElement; inert: boolean }[] = [];
    for (let element: HTMLElement | null = sheet.current; element?.parentElement; element = element.parentElement) {
      for (const sibling of element.parentElement.children) {
        if (sibling instanceof HTMLElement && sibling !== element) {
          background.push({ element: sibling, inert: sibling.inert }); sibling.inert = true;
        }
      }
      if (element.parentElement === document.body) break;
    }
    fullscreenExit.current?.focus({ preventScroll: true });
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !event.defaultPrevented) setFullscreen(false); };
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('keydown', escape);
      document.body.style.overflow = overflow;
      for (const item of background) item.element.inert = item.inert;
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, [fullscreen]);
  const requestQuery = new URLSearchParams(scopeQuery);
  requestQuery.set('as_of', conditions.cutoff);
  requestQuery.set('q', conditions.query);
  requestQuery.set('stock_filter', conditions.stockFilter);
  const requestQueryText = requestQuery.toString();
  const displayedQuery = new URLSearchParams(scopeQuery);
  displayedQuery.set('as_of', cutoff);
  displayedQuery.set('q', query);
  displayedQuery.set('stock_filter', stockFilter);
  const queryText = displayedQuery.toString();
  const updating = loading || cacheRefresh.current !== `${refresh}:${dataRevision}` || (!loadError && (requestQueryText !== queryText || searchText !== conditions.query));
  const selectedDate = loadError ? cutoff : conditions.cutoff;
  useEffect(() => { setSearchText(conditions.query); }, [conditions.query]);
  useEffect(() => {
    if (searchText === conditions.query) return;
    const timeout = window.setTimeout(() => setConditions(current => ({ ...current, query: searchText })), 250);
    return () => window.clearTimeout(timeout);
  }, [searchText, conditions.query, setConditions]);
  useEffect(() => {
    if (!updating) { setShowLoading(false); return; }
    const timeout = window.setTimeout(() => setShowLoading(true), 300);
    return () => window.clearTimeout(timeout);
  }, [updating]);
  useEffect(() => {
    let active = true;
    const revision = `${refresh}:${dataRevision}`;
    if (cacheRefresh.current !== revision) { reads.current.clear(true); cacheRefresh.current = revision; }
    reads.current.retain([requestQueryText]);
    const cached = reads.current.peek(requestQueryText);
    if (cached) setSnapshot({ data: cached, filters: conditions });
    setLoading(true); setLoadError('');
    const job = reads.current.read(requestQueryText);
    job.promise.then(value => { if (active && !job.controller.signal.aborted) {
        const next = { data: value, filters: conditions };
        confirmedSnapshot.current = next; setSnapshot(next); setLoading(false);
      } })
      .catch(error => { if (active && !job.controller.signal.aborted) { reads.current.forget(requestQueryText); setSnapshot(confirmedSnapshot.current); setLoadError(error instanceof Error ? error.message : '总表读取失败'); setLoading(false); } });
    return () => { active = false; };
  }, [requestQueryText, refresh, dataRevision, conditions]);
  useEffect(() => {
    const revalidate = () => {
      if (document.visibilityState === 'visible' && !settingsDirty && !saving && !saveUnknown && !productionReads.isFresh(`/api/production/inventory/overview-sheet?${requestQueryText}&summary=1&compact=1`)) setRefresh(value => value + 1);
    };
    window.addEventListener('focus', revalidate);
    document.addEventListener('visibilitychange', revalidate);
    return () => { window.removeEventListener('focus', revalidate); document.removeEventListener('visibilitychange', revalidate); };
  }, [settingsDirty, saving, saveUnknown, productionReads, requestQueryText]);
  const prepareDates = useCallback((dates: string[]) => {
    if (settingsDirty || saving || saveUnknown || !data || requestQueryText !== queryText) return;
    const keys = dates.map(date => {
      const target = new URLSearchParams(requestQueryText); target.set('as_of', date);
      return target.toString();
    });
    reads.current.retain([requestQueryText, ...keys]);
    for (const key of keys) reads.current.prefetch(key);
  }, [settingsDirty, saving, saveUnknown, data, requestQueryText, queryText]);
  const filtered = useMemo(() => catalog, [catalog]);
  const allGroups = useMemo(() => makeGroups(cutoff, weekView, periodViews, data?.cumulative_from ?? cutoff).map(group => ({
    ...group, columns: group.columns.map(column => {
      const labels = [...new Set(data?.rows.flatMap(row => row.values[column.key]?.evidence ? [row.values[column.key]!.evidence!.label] : []) ?? [])];
      const hasBalance = data?.rows.some(row => row.values[column.key]?.value != null && BigInt(row.values[column.key]!.value!) !== 0n);
      return labels.length === 1 && !hasBalance ? { ...column, label: column.key === 'dispatched' ? '装箱已发' : labels[0]! } : column;
    }),
  })), [cutoff, weekView, periodViews, data]);
  const groups = allGroups.map(group => ({
    ...group,
    columns: group.defaultKeys && !expandedGroups.includes(group.key)
      ? group.columns.filter(column => group.defaultKeys!.includes(column.key)) : group.columns,
  }));
  const columns = groups.flatMap(group => group.columns);
  const dateHeaders = groups.flatMap(group => {
    const headings: { key: string; label: string; count: number; column?: Column; tone?: Tone; first: boolean; pinned?: boolean }[] = [];
    for (const [index, column] of group.columns.entries()) {
      const last = headings.at(-1);
      const pinned = group.key === 'inventory' && ['available', 'transit'].includes(column.key);
      if (column.headerLabel) headings.push({ key: column.key, label: column.headerLabel, count: 1, column, tone: group.tone, first: index === 0 });
      else if (last && !last.column && last.label === column.heading && last.pinned === pinned) last.count += 1;
      else headings.push({ key: column.key, label: column.heading!, count: 1, tone: group.tone, first: index === 0, pinned });
    }
    return headings.map(heading => ({ ...heading, groupKey: group.key }));
  });
  const rows = useMemo(() => {
    const bySku = new Map<string, SheetSku[]>();
    for (const item of filtered) bySku.set(item.sku_id, [...(bySku.get(item.sku_id) || []), item]);
    return [...bySku.values()].map(items => makeRow(items[0]!.sku, items));
  }, [filtered]);
  const total = useMemo(() => aggregateRows('total', '合计', rows), [rows]);
  const styles = useMemo(() => {
    const byStyle = new Map<string, GridRow[]>();
    for (const row of rows) {
      const id = row.items[0]!.style_id;
      byStyle.set(id, [...(byStyle.get(id) || []), row]);
    }
    return [...byStyle].map(([id, skus]): StyleGroup => {
      const code = skus[0]!.items[0]!.style_code;
      const count = new Set(catalog.filter(item => item.style_id === id).map(item => item.sku_id)).size;
      return { id, code, skus, partial: skus.length < count, row: aggregateRows(`style:${id}`, code, skus) };
    });
  }, [rows, catalog]);
  const stockAlerts = useMemo(() => new Map([...rows, ...styles.map(style => style.row)].map(row => [row.id, rowStockAlerts(row, cutoff, stockSettings)])), [rows, styles, cutoff, stockSettings]);
  const sortDefinition = columns.find(column => column.key === sort.key);
  function compareRows(a: GridRow, b: GridRow) {
    if (sort.direction === 0 || sort.key === 'sku') return (sort.direction || 1) * a.sku.localeCompare(b.sku, 'en', { numeric: true });
    const value = (row: GridRow) => {
      if (!sortDefinition?.comparison) return row.values[sort.key] ?? null;
      const comparison = sortDefinition.comparison;
      return comparisonData(row, comparison).delta;
    };
    return compareNumbers(value(a), value(b), sort.direction);
  }
  const sortedStyles = [...styles].sort((a, b) => compareRows(a.row, b.row) || a.code.localeCompare(b.code, 'en', { numeric: true }));
  function compareSkus(a: GridRow, b: GridRow) {
    const left = a.items[0]!;
    const right = b.items[0]!;
    const sizeOrder = ['XS', 'S', 'M', 'L', 'XL', 'XXL', '3XL'];
    const leftSize = sizeOrder.indexOf(left.standard_size);
    const rightSize = sizeOrder.indexOf(right.standard_size);
    const defaultOrder = left.standard_color.localeCompare(right.standard_color)
      || (leftSize < 0 ? sizeOrder.length : leftSize) - (rightSize < 0 ? sizeOrder.length : rightSize)
      || left.sku.localeCompare(right.sku, 'en', { numeric: true });
    if (sort.direction !== 0 && sort.key !== 'sku') return compareRows(a, b) || defaultOrder;
    return (sort.direction || 1) * defaultOrder;
  }
  const visibleRows = sortedStyles.flatMap(style => {
    const leaves = [...style.skus].sort(compareSkus);
    return [{ row: style.row, style, isStyle: true }, ...(expandedStyles.includes(style.id) ? leaves.map(row => ({ row, style, isStyle: false })) : [])];
  });
  // Labelled SKU rows reserve one extra line; the open detail stays mounted
  // outside the viewport so scrolling cannot discard its settings draft.
  const detailIndex = visibleRows.findIndex(item => item.row.id === detail?.rowId);
  const openDetailHeight = detailIndex < 0 ? 0 : detailHeight || 280;
  const rowHeights = visibleRows.map(item => !item.isStyle && item.row.items[0]?.production_statuses?.length ? 46 : 30);
  const rowStarts = [0];
  for (const height of rowHeights) rowStarts.push(rowStarts[rowStarts.length - 1]! + height);
  const rowOffset = (index: number) => rowStarts[index]! + (detailIndex >= 0 && index > detailIndex ? openDetailHeight : 0);
  const windowed = viewport.height > 0 && visibleRows.length > 80;
  const firstVisible = Math.max(0, visibleRows.findIndex((_, index) => rowOffset(index + 1) > viewport.top));
  const lastVisible = visibleRows.findIndex((_, index) => rowOffset(index) > viewport.top + viewport.height - 84);
  const first = windowed ? Math.max(0, firstVisible - 6) : 0;
  const end = windowed ? Math.min(visibleRows.length, (lastVisible < 0 ? visibleRows.length : lastVisible) + 6) : visibleRows.length;
  const rowIndices = new Set(Array.from({ length: end - first }, (_, index) => first + index));
  if (detailIndex >= 0) rowIndices.add(detailIndex);
  const focusedIndex = visibleRows.findIndex(item => item.row.id === focusedRow);
  if (focusedIndex >= 0) rowIndices.add(focusedIndex);
  type RowSlot = { kind: 'row'; index: number } | { kind: 'space'; index: number; height: number };
  const rowSlots: RowSlot[] = [];
  let rowCursor = 0;
  for (const index of [...rowIndices].sort((a, b) => a - b)) {
    const height = rowOffset(index) - rowOffset(rowCursor);
    if (height > 0) rowSlots.push({ kind: 'space', index, height });
    rowSlots.push({ kind: 'row', index }); rowCursor = index + 1;
  }
  if (rowCursor < visibleRows.length) rowSlots.push({ kind: 'space', index: visibleRows.length, height: rowOffset(visibleRows.length) - rowOffset(rowCursor) });
  function fixedColumnWidth(key: string) {
    const label = columns.find(column => column.key === key)?.label ?? '';
    return Math.max(64, label.length * 14 + 14, ...[...visibleRows.map(item => item.row), total].map(row => {
      const value = row.values[key] ?? row.states[key]?.evidence?.units;
      return value == null ? 0 : num(value).length * 8 + 32;
    }));
  }
  useLayoutEffect(() => {
    if (stockFilter !== 'all' || query) setExpandedStyles([...new Set(filtered.map(item => item.style_id))]);
  }, [filtered, stockFilter, query]);
  useLayoutEffect(() => {
    const element = sheet.current;
    if (!element) return;
    let narrow = false;
    let wideScroll = 0;
    const measure = () => {
      element.style.setProperty('--sheet-top', `${Math.round(element.getBoundingClientRect().top + window.scrollY)}px`);
      const nextNarrow = window.matchMedia('(max-width: 760px)').matches;
      const scroller = element.querySelector<HTMLElement>(':scope > section > div');
      const available = element.querySelector<HTMLElement>('thead th[data-column="available"]');
      if (scroller && available && nextNarrow !== narrow) {
        if (nextNarrow) {
          wideScroll = scroller.scrollLeft;
          scroller.scrollTo({ left: scroller.scrollLeft + available.getBoundingClientRect().left - scroller.getBoundingClientRect().left, behavior: 'instant' });
        } else scroller.scrollTo({ left: wideScroll, behavior: 'instant' });
      }
      narrow = nextNarrow;
    };
    measure();
    const observer = new ResizeObserver(measure);
    if (element.parentElement) observer.observe(element.parentElement);
    window.addEventListener('resize', measure);
    return () => { observer.disconnect(); window.removeEventListener('resize', measure); };
  }, []);
  useLayoutEffect(() => {
    const scroller = sheet.current?.querySelector<HTMLElement>(':scope > section > div');
    if (!scroller) return;
    const measure = () => {
      const top = Math.floor(scroller.scrollTop / 30) * 30, height = scroller.clientHeight;
      setViewport(current => current.top === top && current.height === height ? current : { top, height });
    };
    measure();
    const observer = new ResizeObserver(measure); observer.observe(scroller);
    scroller.addEventListener('scroll', measure, { passive: true });
    return () => { observer.disconnect(); scroller.removeEventListener('scroll', measure); };
  }, []);
  useLayoutEffect(() => {
    const expanded = sheet.current?.querySelector<HTMLElement>('.expanded-row');
    if (!expanded) { setDetailHeight(0); return; }
    const measure = () => setDetailHeight(Math.ceil(expanded.getBoundingClientRect().height));
    measure(); const observer = new ResizeObserver(measure); observer.observe(expanded);
    return () => observer.disconnect();
  }, [detail?.rowId]);
  useLayoutEffect(() => {
    const scroller = sheet.current?.querySelector<HTMLElement>(':scope > section > div');
    if (pendingDetailScroll.current) {
      scroller?.scrollTo({ ...pendingDetailScroll.current, behavior: 'instant' });
      pendingDetailScroll.current = undefined;
    } else if (detail && scroller) {
      const expanded = scroller.querySelector<HTMLElement>('.expanded-row');
      const head = scroller.querySelector('table')?.tHead;
      if (expanded && head) scroller.scrollTo({
        top: Math.max(0, scroller.scrollTop + expanded.getBoundingClientRect().top - scroller.getBoundingClientRect().top - head.offsetHeight - 28),
        behavior: 'instant',
      });
    }
  }, [detail]);
  useLayoutEffect(() => {
    if (pendingGroup.current) {
      const key = pendingGroup.current;
      pendingGroup.current = undefined;
      jumpTo(key);
    }
  }, [expandedGroups, cutoff, weekView, periodViews]);

  function jumpTo(key: string) {
    const scroller = sheet.current?.querySelector<HTMLElement>(':scope > section > div');
    const heading = groupHeaders.current.get(key);
    if (scroller && heading) {
      const pinnedWidth = sheet.current!.querySelector('.group-head > .identity-cell')!.getBoundingClientRect().width
        + (window.matchMedia('(min-width: 1000px)').matches
          ? ['available', 'transit'].reduce((width, column) => width + (sheet.current!.querySelector(`thead th[data-column="${column}"]`)?.getBoundingClientRect().width ?? 0), 0) : 0);
      const offset = heading.getBoundingClientRect().left - scroller.getBoundingClientRect().left;
      scroller.scrollTo({ left: Math.max(0, scroller.scrollLeft + offset - pinnedWidth), behavior: 'instant' });
    }
  }
  function afterSettings(action: () => void) {
    if (saving || saveUnknown) return;
    if (settingsDirty) setPendingAction(() => action);
    else action();
  }
  function changeDetail(next?: OpenDetail) {
    afterSettings(() => {
      const scroller = sheet.current?.querySelector<HTMLElement>(':scope > section > div');
      if (next && scroller) detailOrigin.current = { left: scroller.scrollLeft, top: scroller.scrollTop };
      if (!next) pendingDetailScroll.current = detailOrigin.current;
      setDetail(next);
    });
  }
  function openColumn(row: GridRow, column: Column) {
    if (updating) return;
    const periodRanges = column.comparison ? ranges(column.key.split('.')[0] as Period, cutoff) : undefined;
    const range = column.range ?? periodRanges!.current;
    const label = column.comparison
      ? `${{ units: '销量', returns: '退货', net: '净销量' }[column.comparison.metric]} · ${column.headerLabel ?? column.heading}`
      : column.key === 'domestic' ? '广州成品仓库存'
      : column.detail === 'stock' || column.detail === 'transit' ? `美国FBA${column.label}` : column.label;
    const request: OpenDetail = { rowId: row.id, type: column.comparison ? 'comparison' : column.detail!,
      key: column.key, label, range,
      comparison: column.comparison ? { metric: column.comparison.metric, current: periodRanges!.current, previous: periodRanges!.previous } : undefined };
    const same = detail?.rowId === row.id && detail.key === column.key && detail.type === request.type
      && detail.range.start === range.start && detail.range.end === range.end;
    changeDetail(same ? undefined : request);
  }
  function discardSettings() {
    setSettingsDirty(false);
    setPendingAction(undefined);
    window.setTimeout(() => pendingAction?.(), 0);
  }
  function reset() {
    afterSettings(() => {
      setSearchText(''); setConditions({ cutoff: defaultDate, query: '', stockFilter: 'all' }); setDetail(undefined); setExportError('');
      setNavigationReset(value => value + 1);
      setWeekView('units'); setPeriodViews(DEFAULT_PERIOD_VIEWS); pendingGroup.current = 'production';
      setExpandedGroups([]); setExpandedStyles([]);
      setSort({ key: 'sku', direction: 0 }); jumpTo('production');
      sheet.current?.querySelector<HTMLElement>(':scope > section > div')?.scrollTo({ left: 0, top: 0 });
    });
  }
  function sortBy(key: string) {
    setSort(current => nextSort(current, key));
  }
  async function saveSettings(styleIds: string[], changes?: StockSettings): Promise<string | undefined> {
    if (!data || updating || !(changes ? data.settings.can_manage : data.settings.can_manage_styles ?? data.settings.can_manage) || !gate.current) return '当前无法保存设置，请等待更新完成。';
    const command = changes ? 'alerts' : 'styles';
    const ticket = gate.current.begin([command], generation);
    const path = '/api/production/inventory/display-settings';
    const body = { expected_revision: data.settings.revision, style_ids: styleIds,
      ...(changes ? { sku_alert_settings: { [data.resolved_scope.fba.id]: changes } } : {}) };
    const operationKey = operationKeys.current.forCommand(command, path, body);
    setSaving(true);
    try {
      const settings = await writeApi<SheetResponse['settings']>(path, { body: { ...body, operation_token: operationKey }, operationKey, signal: ticket.signal });
      if (!ticket.isCurrent()) return undefined;
      operationKeys.current.complete(command, operationKey);
      reads.current.clear();
      setSnapshot(current => {
        const next = current ? { ...current, data: { ...current.data, settings: { ...settings, can_manage: current.data.settings.can_manage, can_manage_styles: settings.can_manage } } } : current;
        confirmedSnapshot.current = next; return next;
      });
      setSaveUnknown(false); setPendingAction(undefined); setSettingsDirty(false);
      setRefresh(value => value + 1);
      return undefined;
    } catch (error) {
      if (!ticket.isCurrent()) return undefined;
      if (error instanceof ApiRequestError && error.status === 409) {
        const latest = await requestApi<SheetResponse['settings']>(path, { signal: ticket.signal });
        if (!ticket.isCurrent()) return undefined;
        reads.current.clear();
        setSnapshot(current => {
          const next = current ? { ...current, data: { ...current.data, settings: { ...latest, can_manage: current.data.settings.can_manage, can_manage_styles: latest.can_manage } } } : current;
          confirmedSnapshot.current = next; return next;
        });
        if (!changes) setRefresh(value => value + 1);
        return '设置已被其他人修改，已读取最新修订。输入已保留，请核对后再保存。';
      }
      setSaveUnknown(!(error instanceof ApiRequestError) || error.code === 'production_result_unknown');
      return error instanceof Error ? error.message : '保存失败，输入已保留，请重发原操作核实结果。';
    } finally { if (ticket.isCurrent()) setSaving(false); }
  }
  function changeWeekView(value: WeekView) {
    if (value === weekView) return;
    pendingGroup.current = 'week-sales';
    setSort(current => sortForGroups(current, allGroups, makeGroups(cutoff, value, periodViews), expandedGroups));
    setWeekView(value);
  }
  function togglePeriodView(period: SummaryPeriod) {
    const next: PeriodViews = { ...periodViews, [period]: periodViews[period] === 'net' ? 'split' : 'net' };
    pendingGroup.current = period;
    setSort(current => sortForGroups(current, allGroups, makeGroups(cutoff, weekView, next), expandedGroups));
    setPeriodViews(next);
  }
  function changeDate(value: string, targetGroup?: string) {
    afterSettings(() => {
      if (targetGroup) pendingGroup.current = targetGroup;
      setConditions(current => ({ ...(loadError ? { cutoff, query, stockFilter } : current), cutoff: value, query: loadError ? query : searchText })); setDetail(undefined); setExportError('');
      if (sort.key.startsWith('day.')) setSort({ key: 'sku', direction: 0 });
    });
  }
  async function exportExcel() {
    if (!data || !rows.length || exporting || updating || !gate.current) return;
    const ticket = gate.current.begin(['export'], generation);
    const exportQuery = new URLSearchParams(queryText);
    exportQuery.set('version', data.version);
    exportQuery.set('columns', groups.flatMap(group => [...group.columns.map(column => column.key), ...(group.key === 'inventory' ? ['sku'] : [])]).join(','));
    exportQuery.set('sort', sort.key); exportQuery.set('direction', String(sort.direction));
    exportQuery.set('expanded_styles', expandedStyles.join(','));
    exportQuery.set('style_order', sortedStyles.map(style => style.id).join(','));
    exportQuery.set('sku_order', sortedStyles.flatMap(style => [...style.skus].sort(compareSkus).map(row => row.items[0]!.sku_id)).join(','));
    setExporting(true); setExportError('');
    try {
      const url = await requestApi<Blob>(`/api/production/inventory/overview-sheet/export?${exportQuery}`, { signal: ticket.signal, headers: { Accept: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' } }, undefined, 'blob');
      if (!ticket.isCurrent()) return;
      const objectUrl = URL.createObjectURL(url);
      const link = document.createElement('a');
      link.href = objectUrl; link.download = `库存变动总表_${cutoff}.xlsx`;
      document.body.append(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (error) { if (ticket.isCurrent()) setExportError(error instanceof Error ? error.message : '导出失败，请重试。'); }
    finally { if (ticket.isCurrent()) setExporting(false); }
  }
  function toggleGroup(key: string) {
    pendingGroup.current = key;
    const next = expandedGroups.includes(key) ? expandedGroups.filter(value => value !== key) : [...expandedGroups, key];
    setSort(current => sortForGroups(current, allGroups, allGroups, next));
    setExpandedGroups(next);
  }
  function search(value: string) {
    afterSettings(() => {
      setSearchText(value); setDetail(undefined); setLoadError('');
      if (loadError) setConditions({ cutoff, query: value, stockFilter });
      else if (!value) { setConditions(current => ({ ...current, query: '' })); setExpandedStyles([]); }
    });
  }
  function filterStock(value: StockFilter, text = query) {
    afterSettings(() => {
      setSearchText(text); setConditions(current => ({ ...(loadError ? { cutoff, query, stockFilter } : current), stockFilter: value, query: text })); setDetail(undefined); setExportError('');
    });
  }
  function header(label: string, key: string, context = '') {
    const next = nextSort(sort, key);
    const action = next.direction === -1 ? '降序排列' : next.direction === 1 ? '升序排列' : '恢复默认顺序';
    return <button className="sort-button" onClick={() => sortBy(key)} title={`点击${action}`} aria-label={`按${context}${label}排序`}>
      {label}{sort.direction !== 0 && sort.key === key ? sort.direction === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} /> : null}
    </button>;
  }
  function cellValue(row: GridRow, column: Column, summary = false) {
    if (column.comparison) {
      const result = comparisonData(row, column.comparison);
      const value = <ComparisonValue row={row} comparison={column.comparison} />;
      if (summary || result.delta === null || result.delta === 0n) return value;
      return <button className="quantity comparison-quantity" disabled={updating} aria-label={`查看${row.sku}${column.headerLabel ?? column.heading}${column.label}明细`}
        onClick={() => openColumn(row, column)}>{value}</button>;
    }
    const value = row.values[column.key] ?? null;
    const evidence = row.states[column.key]?.evidence;
    if (value === null && evidence && (BigInt(evidence.units) !== 0n || column.label === evidence.label || column.label === '装箱已发')) {
      const content = BigInt(evidence.units) === 0n ? '' : num(evidence.units);
      return summary ? <span title={row.states[column.key]?.reason}>{content}</span> : <button className="quantity" disabled={updating} title={row.states[column.key]?.reason} aria-label={`查看${row.sku}${evidence.label}明细`} onClick={() => openColumn(row, column)}>{content}</button>;
    }
    if (column.key === 'available') {
      const text = value === 0n ? '' : value === null ? '' : num(value);
      if (summary) return <span title={row.states.available?.reason}>{text}</span>;
      const alert = stockAlerts.get(row.id)!;
      const alertLabel = ({ empty: '缺货', low: '低库存', 'sold-out': '停止补货' } as Record<string, string>)[alert.level];
      const title = [alertLabel, alert.note, row.states.available?.reason].filter(Boolean).join('；') || '美国FBA可售库存明细';
      return <button className="quantity stock-quantity" disabled={updating} title={title} aria-label={`查看${row.sku}可售库存明细${alertLabel ? `，${alertLabel}` : ''}`}
        onClick={() => openColumn(row, column)}>{text}</button>;
    }
    const state = row.states[column.key];
    const blankZero = value === 0n;
    const net = column.key === 'net' || column.key.endsWith('.net');
    const negative = net && value !== null && value < 0n;
    const text = blankZero ? '' : value === null ? '' : num(value);
    const prefix = column.key.slice(0, -3);
    const title = state?.partial ? state.reason || state.state : net && value !== null ? `销量${num(row.values[`${prefix}units`]!)}－退货${num(row.values[`${prefix}returns`]!)}＝净销量${num(value)}`
      : blankZero ? '0 件' : undefined;
    if (!column.detail || summary || blankZero) return <span className={negative ? 'net-negative' : undefined} title={title}>{text}</span>;
    return <button className={`quantity${negative ? ' net-negative' : ''}`} disabled={updating} title={title} aria-label={`查看${row.sku}${column.label}${column.range ? `${column.range.start}至${column.range.end}` : ''}${blankZero ? '，0件' : ''}`}
      onClick={() => openColumn(row, column)}>{text}</button>;
  }

  return <main className="inventory-overview-sheet" id="main-content">
    <header className="page-header"><h1>库存变动总表</h1></header>
    <div className="toolbar" role="search" aria-label="筛选总表">
      <label className="search-field"><Search size={16} aria-hidden="true" /><Input aria-label="搜索SKU或款号" placeholder="搜索 SKU、款号、颜色" value={loadError ? query : searchText} onChange={event => search(event.target.value)} />
        {(loadError ? query : searchText) && <button className="clear-search" aria-label="清除搜索" onClick={() => search('')}><X size={16} /></button>}</label>
      <label className="stock-filter" data-active={(loadError ? stockFilter : conditions.stockFilter) !== 'all' || undefined} title={`${STOCK_FILTER_LABELS[stockFilter]} · ${styles.length}款 / ${rows.length} SKU`}>
        <Filter size={16} aria-hidden="true" />
        <select aria-label="库存状态筛选" value={loadError ? stockFilter : conditions.stockFilter} onChange={event => filterStock(event.target.value as StockFilter, loadError ? query : searchText)}>
          {Object.entries(STOCK_FILTER_LABELS).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
        </select>
      </label>
      <DateNavigation key={navigationReset} date={selectedDate} maxDate={MAX_DATE} onDateChange={changeDate} jumpTo={jumpTo} prepare={prepareDates} />
      <div className="page-actions">
        <div className="update-state" role="status" aria-live="polite" title={loadError || undefined}>
          {loadError ? <><span>更新失败</span><Button variant="quiet" onClick={() => setRefresh(value => value + 1)}>重试</Button></> : showLoading && <LoaderCircle size={16} className="loading-spinner" aria-label="正在更新" />}
        </div>
        <Button icon={<Download size={16} />} onClick={() => void exportExcel()} disabled={!rows.length || updating || settingsDirty} loading={exporting} loadingLabel="导出中…" aria-label="导出 Excel"><span className="action-label">导出</span></Button>
        <Button ref={fullscreenTrigger} className="fullscreen-toggle" icon={<Maximize2 size={16} />} aria-label="全屏查看" title="表格全屏" aria-pressed={fullscreen} onClick={() => setFullscreen(true)}><span className="action-label">全屏</span></Button>
        <Menu label="更多" items={[
          ...((data?.settings.can_manage_styles ?? data?.settings.can_manage) ? [{ id: 'styles', label: '设置展示款号', disabled: saving || saveUnknown || updating, onSelect: () => afterSettings(() => { setDetail(undefined); setStylePicker(true); }) }] : []),
          { id: 'refresh', label: '刷新', disabled: updating, onSelect: () => afterSettings(() => { setDetail(undefined); setRefresh(value => value + 1); }) },
          { id: 'reset', label: '重置筛选', onSelect: reset },
          { id: 'source', label: '数据来源与口径', disabled: !data, onSelect: () => afterSettings(() => setSourceOpen(value => !value)) },
        ]} />
      </div>
    </div>
    {leave.prompt}
    {stylePicker && data && <StyleDisplayPicker styles={data.display_styles} selected={data.settings.style_ids} busy={saving || updating} unknown={saveUnknown} save={ids => saveSettings(ids)} close={() => setStylePicker(false)} onDirtyChange={setSettingsDirty} />}
    {sourceOpen && data && <section className="source-review" aria-label="数据来源与口径">
      <div className="detail-header"><h3>数据来源与口径</h3><Button variant="quiet" icon={<X size={16} />} aria-label="关闭数据来源" onClick={() => setSourceOpen(false)} /></div>
      <dl className="source-fields"><div><dt>统计截止</dt><dd>{cutoff}</dd></div><div><dt>报告时区</dt><dd>{data.reporting_timezone}</dd></div><div><dt>读取版本</dt><dd>{data.version}</dd></div></dl>
      {data.source_review && <>
        <dl className="source-fields"><div><dt>资料备份</dt><dd>{new Date(data.source_review.backup_at).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}</dd></div><div><dt>日报发布至</dt><dd>{data.source_review.reports_through}</dd></div><div><dt>广州盘点日</dt><dd>{data.source_review.stock_date}</dd></div></dl>
        <Table className="detail-table" aria-label="装箱与FBA验收基准"><thead><tr><th>装箱批次</th><th>箱数</th><th>装箱量</th><th>接收净量</th><th>货件号</th><th>来源</th></tr></thead>
          <tbody>{data.source_review.packings.map(batch => <tr key={batch.filename}><th>{batch.batch_date}</th><td>{batch.boxes}</td><td>{num(batch.packed_units)}</td><td>{batch.received_units === null ? '—' : num(batch.received_units)}</td><td>{batch.reference_id ?? '—'}</td><td>{batch.differences.join('。') || batch.filename}</td></tr>)}</tbody>
        </Table>
      </>}
      {!!data.issues.length && <ul>{data.issues.map((issue, index) => <li key={index}>{issue.label}</li>)}</ul>}
    </section>}
    {exportError && <div className="export-error" role="alert">{exportError}</div>}
    <div className={`sheet${!data && loading ? ' sheet-loading' : ''}${fullscreen ? ' is-fullscreen' : ''}`} ref={sheet} aria-busy={updating}
      style={{ '--available-width': `${fixedColumnWidth('available')}px`, '--transit-width': `${fixedColumnWidth('transit')}px` } as CSSProperties}>
      {fullscreen && <Button ref={fullscreenExit} className="fullscreen-exit" icon={<Minimize2 size={16} />} aria-label="退出全屏" title="退出全屏（Esc）" onClick={() => setFullscreen(false)} />}
      <Table className="inventory-sheet" aria-label="完整库存销售退货总表" aria-rowcount={visibleRows.length + 4 + (detailIndex >= 0 ? 1 : 0)}>
        <colgroup>{groups.map(group => <Fragment key={group.key}>
          {group.columns.map(column => <col key={column.key} data-column={column.key} />)}
          {group.key === 'inventory' && <col />}
        </Fragment>)}</colgroup>
        <thead>
          <tr className="group-head">{groups.map(group => <Fragment key={group.key}><th colSpan={group.key === 'inventory' ? 1 : group.columns.length} scope="colgroup" data-group={group.key} data-tone={group.tone}
            ref={element => { if (element) groupHeaders.current.set(group.key, element); else groupHeaders.current.delete(group.key); }}>
            {group.key === 'week-sales'
              ? <button className="group-toggle" aria-label="切换周销量与净销量" aria-pressed={weekView === 'net'}
                title={`当前${weekView === 'net' ? '净销量' : '销量'}，点击显示${weekView === 'net' ? '销量' : '净销量'}`}
                onClick={() => changeWeekView(weekView === 'net' ? 'units' : 'net')}>
                {group.label}<ArrowRightLeft size={13} aria-hidden="true" />
              </button>
              : group.defaultKeys
              ? <button className="group-toggle" aria-label={group.key === 'inventory' ? '库存明细' : group.key === 'production' ? '未完成订单明细' : `${PERIOD_LABELS[group.key as keyof typeof PERIOD_LABELS]}数据`} aria-expanded={expandedGroups.includes(group.key)} onClick={() => toggleGroup(group.key)}>
                {expandedGroups.includes(group.key) ? <ChevronDown size={13} /> : <ChevronRight size={13} />}{group.label}
              </button>
              : <span className="group-label">{group.label}</span>}
          </th>{group.key === 'inventory' && <>
            <th className="stock-group-head" colSpan={2} scope="colgroup" data-tone="inventory">美国FBA</th>
            {group.columns.length > 3 && <th colSpan={group.columns.length - 3} scope="colgroup" data-tone="inventory">库存明细</th>}
            <th className="identity-cell" rowSpan={3} scope="col">{header('款号 / SKU', 'sku')}</th>
          </>}</Fragment>)}</tr>
          <tr className="date-head">{dateHeaders.map(heading => <th key={heading.column ? heading.key : `${heading.groupKey}.${heading.label}.${heading.pinned ? 'pinned' : ''}`} colSpan={heading.count} rowSpan={heading.column ? 2 : 1} scope={heading.column ? 'col' : 'colgroup'}
            data-column={heading.column?.key} data-tone={heading.tone} title={heading.column?.title} className={`${heading.first ? 'group-start' : ''}${heading.pinned ? ' stock-date-head' : ''}`}
            aria-sort={sort.direction !== 0 && sort.key === heading.column?.key ? sort.direction === 1 ? 'ascending' : 'descending' : undefined}>
            {heading.column ? header(heading.label, heading.key, heading.tone === 'returns' ? '退货' : weekView === 'net' ? '净销量' : '销量')
              : ['month', 'quarter', 'year'].includes(heading.groupKey) && !heading.key.endsWith('Mom')
                ? <button className="period-toggle" aria-label={`${heading.label}，切换${PERIOD_LABELS[heading.groupKey as SummaryPeriod]}指标`}
                  aria-pressed={periodViews[heading.groupKey as SummaryPeriod] === 'net'}
                  title={`当前${periodViews[heading.groupKey as SummaryPeriod] === 'net' ? '净销量' : '销量与退货'}，点击切换`}
                  onClick={() => togglePeriodView(heading.groupKey as SummaryPeriod)}>
                  {heading.label}<ArrowRightLeft size={12} aria-hidden="true" />
                </button> : heading.pinned ? dateHeading({ start: cutoff, end: cutoff }) : heading.label}
          </th>)}</tr>
          <tr>{groups.flatMap(group => group.columns.filter(column => !column.headerLabel).map((column, index) => <th key={column.key} scope="col" title={column.title} data-column={column.key} data-tone={column.tone} className={index === 0 ? 'group-start' : ''}
            aria-sort={sort.direction !== 0 && sort.key === column.key ? sort.direction === 1 ? 'ascending' : 'descending' : undefined}>{header(column.label, column.key, column.tone === 'inventory' ? column.heading : '')}</th>))}</tr>
        </thead>
        <tbody onFocusCapture={event => setFocusedRow(event.target.closest('tr[data-row-id]')?.getAttribute('data-row-id') ?? '')}
          onBlurCapture={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setFocusedRow(''); }}>
          {rowSlots.map(slot => {
          if (slot.kind === 'space') return <tr key={`space:${slot.index}`} className="virtual-space" aria-hidden="true"><td colSpan={columns.length + 1} style={{ height: slot.height }} /></tr>;
          const { row, style, isStyle } = visibleRows[slot.index]!;
          const expanded = detail?.rowId === row.id;
          const styleOpen = expandedStyles.includes(style.id);
          return <Fragment key={row.id}>
            <tr className={isStyle ? 'style-row' : 'sku-row'} style={{ height: rowHeights[slot.index] }} data-row-id={row.id} aria-rowindex={slot.index + 4 + (detailIndex >= 0 && slot.index > detailIndex ? 1 : 0)} data-level={isStyle ? 'style' : 'sku'} data-style-id={style.id} data-selected={expanded || undefined}>
              {groups.map(group => <Fragment key={group.key}>
                {group.columns.map((column, index) => <td key={column.key} data-column={column.key} data-tone={column.tone}
                  data-alert={column.key === 'available' ? stockAlerts.get(row.id)!.level : undefined}
                  data-zero={column.headerLabel && row.values[column.key] === 0n || undefined} className={index === 0 ? 'group-start' : ''}>{cellValue(row, column)}</td>)}
                {group.key === 'inventory' && <th className="identity-cell" scope="row">{isStyle ? <button className="style-button" aria-label={`${styleOpen ? '收起' : '展开'}款号${style.code}`} aria-expanded={styleOpen}
                onClick={() => afterSettings(() => { setExpandedStyles(current => styleOpen ? current.filter(id => id !== style.id) : [...current, style.id]); setDetail(undefined); })}>
                {styleOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />}{style.code}
              </button> : <span className="sku-label">{row.sku}{row.items[0]?.production_statuses?.length ? <span className="production-label" title={row.items[0].production_statuses.map(item => `${item.order_number}：${item.status}`).join("；")}>{[...new Set(row.items[0].production_statuses.map(item => item.status))].join(" / ")}</span> : null}</span>}</th>}
              </Fragment>)}
            </tr>
            {expanded && <tr className="expanded-row"><td colSpan={columns.length + 1}>
              {detail.type === 'alerts' ? <StockAlertPanel key={`${row.id}:${detail.skuId ?? ''}:${cutoff}`}
                label={detail.label} items={detail.skuId ? row.items.filter(item => item.sku_id === detail.skuId) : row.items} cutoff={cutoff}
                settings={stockSettings} save={changes => saveSettings(data!.settings.style_ids, changes)} busy={saving || updating} unknown={saveUnknown} canManage={Boolean(data?.settings.can_manage)} close={() => changeDetail()} onDirtyChange={setSettingsDirty}
                confirmClose={Boolean(pendingAction)} keepEditing={() => setPendingAction(undefined)} discard={discardSettings} />
                : <DetailPanel key={`${row.id}:${detail.key}:${detail.range.start}:${detail.range.end}:${cutoff}:${store}`}
                row={{ sku: row.sku, items: row.items, grouped: isStyle }} request={detail} cutoff={cutoff} query={queryText} version={data?.version ?? ""} close={() => changeDetail()}
                openSettings={skuId => changeDetail({ rowId: row.id, type: 'alerts', key: 'available',
                  label: skuId ? row.items.find(item => item.sku_id === skuId)!.sku : row.sku, skuId, range: { start: cutoff, end: cutoff } })} />}
            </td></tr>}
          </Fragment>;
        })}
        {!data && loading ? <tr aria-hidden="true"><td colSpan={columns.length + 1}><div className="sheet-skeleton" /></td></tr> : !rows.length && <tr><td colSpan={columns.length + 1} className="empty"><span>没有匹配的 SKU</span><Button variant="quiet" onClick={() => filterStock('all', '')}>清除筛选</Button></td></tr>}</tbody>
        {!!rows.length && <tfoot><tr>{groups.map(group => <Fragment key={group.key}>
          {group.columns.map((column, index) => <td key={column.key} data-column={column.key} data-tone={column.tone} className={index === 0 ? 'group-start' : ''}>{cellValue(total, column, true)}</td>)}
          {group.key === 'inventory' && <th className="identity-cell" scope="row">合计</th>}
        </Fragment>)}</tr></tfoot>}
      </Table>
    </div>
  </main>;
}

export function InventoryOverviewSheet() {
  const { generation } = useAuthzGeneration();
  const [params] = useSearchParams();
  const [refresh, setRefresh] = useState(0);
  const optionsRead = useLoad<ScopeOptions>('/api/production/inventory/overview-sheet/options', refresh, true, true);
  const options = optionsRead.value, error = optionsRead.error;
  const matching = options?.domestic.filter(scope => (!params.has('domestic_warehouse_id') || scope.warehouse_id === params.get('domestic_warehouse_id'))
    && (!params.has('domestic_owner_id') || scope.owner_id === params.get('domestic_owner_id'))) ?? [];
  const domestic = matching.length === 1 ? matching[0]!.warehouse_id : '';
  const owner = matching.length === 1 ? matching[0]!.owner_id : '';
  const fbaScopes = options?.fba.filter(scope => !params.has('fba_scope_id') || scope.id === params.get('fba_scope_id')) ?? [];
  const fba = fbaScopes.length === 1 ? fbaScopes[0]!.id : '';
  const scopeQuery = new URLSearchParams({ domestic_warehouse_id: domestic, domestic_owner_id: owner, fba_scope_id: fba }).toString();
  if (options && domestic && owner && fba) return <SheetTable key={`${generation}:${scopeQuery}`} scopeQuery={scopeQuery} defaultDate={options.default_as_of ?? options.today} today={options.today} />;
  return <main className="inventory-overview-sheet" id="main-content"><header className="page-header"><h1>库存变动总表</h1></header>
    {error ? <div className="scope-status" role="alert"><span title={error}>读取失败</span><Button onClick={() => setRefresh(value => value + 1)}>重试</Button></div>
      : options ? <div className="scope-status" role="status"><span>查看范围待确定</span><LinkButton to="/production/stock">选择仓库</LinkButton></div>
      : <div className="sheet-skeleton initial-skeleton" role="status" aria-label="正在读取总表" />}
  </main>;
}
