import { useEffect, useState } from 'react';
import { ChevronLeft, LoaderCircle, X } from 'lucide-react';
import { requestApi } from '../../../api/client';
import { Button, Table } from '../../../design-system';
import { num, type Quantity, type Range, type SheetSku } from './model';

export type Detail = 'production' | 'stock' | 'transit' | 'shipments' | 'sales' | 'returns' | 'comparison' | 'adjustments';
export type DetailRequest = { type: Detail; key: string; label: string; range: Range;
  comparison?: { metric: 'units' | 'returns' | 'net'; current: Range; previous: Range } };
type Details = { grouped: boolean; columns: string[]; rows: { sku_id: string; cells: (string | null)[]; quantity?: Quantity }[];
  total: Quantity; comparison_totals?: Quantity[]; total_rows: number; page_size: number; stock_explanation?: Record<string, Quantity>; report_provenance: unknown };
type Props = { row: { sku: string; items: SheetSku[]; grouped: boolean }; request: DetailRequest; cutoff: string; query: string; version: string;
  close: () => void; openSettings: (skuId?: string) => void };

export function DetailPanel({ row, request, query, version, close, openSettings }: Props) {
  const [skuId, setSkuId] = useState(row.grouped ? '' : row.items[0]!.sku_id);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Details>();
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams(query);
    params.set('metric', request.key); params.set('version', version);
    params.set('style_id', row.items[0]!.style_id);
    if (skuId) params.set('sku_id', skuId);
    params.set('page', String(page)); params.set('page_size', '20');
    setData(undefined); setError('');
    requestApi<Details>(`/api/production/inventory/overview-sheet/details?${params}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch(failure => { if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '明细读取失败'); });
    return () => controller.abort();
  }, [query, version, request.key, row.items, skuId, page]);
  const label = skuId ? row.items.find(item => item.sku_id === skuId)?.sku : row.sku;
  const production = request.type === 'production';
  const columns = data?.columns.map((label, index) => ({ label, index }))
    .filter(column => !['状态', '版本', '修订', '口径', '说明'].includes(column.label) && !(production && ['跟进', '工厂直发'].includes(column.label))) ?? [];
  const total = data && (data.total.value === null ? data.total.evidence ? num(data.total.evidence.units) : '' : num(data.total.value));
  const comparison = request.comparison;
  const periodText = (range: Range) => {
    const includeYear = comparison && (comparison.current.start.slice(0, 4) !== comparison.previous.start.slice(0, 4)
      || range.start.slice(0, 4) !== range.end.slice(0, 4));
    return `${(includeYear ? range.start : range.start.slice(5)).replaceAll('-', '/')}—${(includeYear ? range.end : range.end.slice(5)).replaceAll('-', '/')}`;
  };
  const comparisonValue = (value: string | null | undefined, delta: boolean) => value == null || value === '0' ? ''
    : `${delta && BigInt(value) > 0n ? '+' : ''}${num(value)}`;
  return <section className={`detail-panel${comparison ? ' comparison-detail' : ''}${production ? ' production-detail' : ''}`} aria-label={`${label}${request.label}明细`}>
    <div className="detail-header">{production ? <div className="production-detail-heading"><h3>{label} · {request.label}</h3><span className="detail-cutoff">{request.range.end.replaceAll('-', '/')}</span>{data && <span className="detail-total" title={data.total.reason}>合计 <strong>{total}</strong></span>}</div> : <h3>{label} · {request.label}</h3>}<div>{row.grouped && skuId && <Button icon={<ChevronLeft size={14} />} onClick={() => { setSkuId(''); setPage(1); }}>返回整款</Button>}
      {request.key === 'available' && <Button onClick={() => openSettings(skuId || undefined)}>库存提醒设置</Button>}
      <Button variant="quiet" icon={<X size={18} />} aria-label="收起指标明细" onClick={close} /></div></div>
    {!comparison && !production && <p className="detail-description">{request.range.start === request.range.end ? `截至 ${request.range.end}` : `${request.range.start}—${request.range.end}`}{request.comparison && ` · 对比 ${request.comparison.previous.start}—${request.comparison.previous.end}`}</p>}
    {error ? <p role="alert">{error}</p> : !data ? <div className="detail-loading" role="status" aria-label="正在读取明细"><LoaderCircle size={16} className="loading-spinner" /></div> : <>
      {!comparison && !production && <div className="detail-totals"><span title={data.total.reason}>合计 {total}</span></div>}
      <Table className="detail-table" aria-label={`${request.label}对应记录`}><thead><tr>{columns.map(column => {
        const range = comparison && (column.index === 1 ? comparison.current : column.index === 2 ? comparison.previous : undefined);
        return <th key={column.index} title={range ? `${range.start}—${range.end}` : undefined}>{column.label}{range && <span className="detail-period">{periodText(range)}</span>}</th>;
      })}</tr></thead>
        <tbody>{data.rows.map((entry, index) => <tr key={`${entry.sku_id}:${index}`}>{columns.map(({ index: column }) => { const value = entry.cells[column]; return <td key={column} title={entry.quantity?.reason}>
          {data.grouped && column === 0 ? <button className="quantity" onClick={() => { setSkuId(entry.sku_id); setPage(1); }}>{value}</button> : !comparison && data.grouped && column === 1 && value === null && entry.quantity?.evidence ? num(entry.quantity.evidence.units) : comparison && column > 0 ? comparisonValue(value, column === 3) : value === '0' && request.type !== 'stock' ? '' : value ?? ''}
        </td>; })}</tr>)}{!data.rows.length && <tr><td colSpan={columns.length}>暂无记录</td></tr>}</tbody>{comparison && data.comparison_totals && <tfoot><tr><th scope="row">合计</th>{data.comparison_totals.map((value, index) => <td key={index} title={value.reason}>{comparisonValue(value.value, index === 2)}</td>)}</tr></tfoot>}</Table>
      {data.total_rows > data.page_size && <div className="detail-pagination"><Button disabled={page === 1} onClick={() => setPage(value => value - 1)}>上一页</Button><span>{page} / {Math.ceil(data.total_rows / data.page_size)}</span><Button disabled={page * data.page_size >= data.total_rows} onClick={() => setPage(value => value + 1)}>下一页</Button></div>}
    </>}
  </section>;
}
