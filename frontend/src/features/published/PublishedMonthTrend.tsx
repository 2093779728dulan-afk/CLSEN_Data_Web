import { useEffect, useId, useRef, useState } from "react";
import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import type { DailyLedgerRow } from "../../api/generated";
import { EmptyState, FormField, Select } from "../../design-system";
import { comparePrevious, formatMetric, METRICS, monthlyPoints, total, type MonthlyMetric, type MonthlyPoint } from "./monthlyMetrics";
import styles from "./PublishedMonthTrend.module.css";

function TrendPlot({ points, metric, currencyCode, label }: { points: readonly MonthlyPoint[]; metric: MonthlyMetric; currencyCode: string; label: string }) {
  const id = useId();
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(700);
  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(Math.max(300, Math.round(entry.contentRect.width)));
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const values = points.flatMap((point) => point.value === null ? [] : [point.value]);
  if (!values.length) return <div ref={containerRef}><EmptyState title="这个范围暂无可绘制的数据" description="报告未发布或指标缺值；发布后会在对应日期显示，缺失日期不会补成 0。" /></div>;
  let min = 0n;
  let max = 0n;
  for (const value of values) { if (value < min) min = value; if (value > max) max = value; }
  const range = max === min ? 1n : max - min;
  const left = width < 500 ? 84 : 112;
  const right = width - 32;
  const x = (index: number) => left + (points.length === 1 ? (right - left) / 2 : index * (right - left) / (points.length - 1));
  const y = (value: bigint) => max === min ? 204 : 24 + Number((max - value) * 180_000n / range) / 1_000;
  const segments: string[][] = [];
  let segment: string[] = [];
  for (const [index, point] of points.entries()) {
    if (point.value === null) { if (segment.length) segments.push(segment); segment = []; }
    else segment.push(`${x(index)},${y(point.value)}`);
  }
  if (segment.length) segments.push(segment);
  const ticks = [...new Set([0, Math.floor((points.length - 1) / 2), points.length - 1])];
  const axisLabel = (value: bigint) => { const text = formatMetric(value, metric, currencyCode); return text.length > 15 ? `${text.slice(0, 12)}…` : text; };
  return <div aria-label="月内趋势图，可横向滚动" className={styles.plotScroll} ref={containerRef} role="region" tabIndex={0}>
    <svg aria-labelledby={`${id}-title ${id}-description`} className={styles.plot} role="img" viewBox={`0 0 ${width} 252`}>
      <title id={`${id}-title`}>{label}月内每日趋势</title>
      <desc id={`${id}-description`}>从 {points[0]?.date} 至 {points.at(-1)?.date}，{values.length} 个有效观测点。空缺日期不连线，空心大圆标记所选日。精确值见下方逐日数据表。</desc>
      {[max, (max + min) / 2n, min].filter((value, index, list) => list.indexOf(value) === index).map((value) => <g key={String(value)}>
        <line className={styles.gridLine} x1={left} x2={right} y1={y(value)} y2={y(value)} />
        <text className={styles.axisText} textAnchor="end" x={left - 12} y={y(value) + 4}><title>{formatMetric(value, metric, currencyCode)}</title>{axisLabel(value)}</text>
      </g>)}
      <line className={styles.selectedLine} x1={x(points.length - 1)} x2={x(points.length - 1)} y1="16" y2="208" />
      {segments.filter((line) => line.length > 1).map((line, index) => <polyline className={styles.series} key={index} points={line.join(" ")} />)}
      {points.map((point, index) => point.value === null ? null : <g key={point.date}>
        <circle className={styles.point} cx={x(index)} cy={y(point.value)} r="3.5"><title>{point.date}：{formatMetric(point.value, metric, currencyCode)}</title></circle>
        {index === points.length - 1 && <circle className={styles.selectedPoint} cx={x(index)} cy={y(point.value)} r="7" />}
      </g>)}
      {ticks.map((index) => <text className={styles.axisText} key={index} textAnchor="middle" x={x(index)} y="235">{points[index]?.date.slice(5)}</text>)}
    </svg>
  </div>;
}

export function PublishedMonthTrend({ rows, reportDate, currencyCode }: { rows: readonly DailyLedgerRow[]; reportDate: string; currencyCode: string }) {
  const [metric, setMetric] = useState<MonthlyMetric>("sales");
  const points = monthlyPoints(rows, reportDate, metric);
  const sales = monthlyPoints(rows, reportDate, "sales");
  const units = monthlyPoints(rows, reportDate, "units_ordered");
  const returns = monthlyPoints(rows, reportDate, "return_quantity");
  const available = points.filter((point) => point.value !== null).length;
  const label = METRICS.find((item) => item.key === metric)!.label;
  const comparison = comparePrevious(points, metric, currencyCode);
  const DirectionIcon = comparison.direction === "up" ? ArrowUpRight : comparison.direction === "down" ? ArrowDownRight : Minus;
  const covered = (values: MonthlyPoint[]) => `${values.filter((point) => point.value !== null).length} / ${values.length} 天有数据`;

  return <section aria-labelledby="published-month-title" className={styles.panel}>
    <header className={styles.header}>
      <div><p className={styles.eyebrow}>月内观察 · 当前发布版本</p><h2 id="published-month-title">本月趋势</h2><p className={styles.range}>{reportDate.slice(0, 7)}-01 至 {reportDate} · 截至所选报告日</p></div>
      <FormField label="趋势指标"><Select onChange={(event) => setMetric(event.target.value as MonthlyMetric)} value={metric}>
        {METRICS.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
      </Select></FormField>
    </header>
    <dl aria-label="月内累计" className={styles.totals}>
      <div><dt>月内累计销售额</dt><dd>{formatMetric(total(sales), "sales", currencyCode)}</dd><dd className={styles.coverage}>{covered(sales)}</dd></div>
      <div><dt>月内累计订购数</dt><dd>{formatMetric(total(units), "units_ordered", currencyCode)}</dd><dd className={styles.coverage}>{covered(units)}</dd></div>
      <div><dt>月内累计退货数</dt><dd>{formatMetric(total(returns), "return_quantity", currencyCode)}</dd><dd className={styles.coverage}>{covered(returns)}</dd></div>
    </dl>
    <div aria-live="polite" className={styles.observation}>
      <div><span className={styles.label}>{reportDate} · {label}</span><strong>{formatMetric(points.at(-1)?.value ?? null, metric, currencyCode)}</strong><span>{available} / {points.length} 天有可用观测值</span></div>
      <div className={styles.comparison}><span className={styles.label}>较前一日{points.at(-2) ? ` ${points.at(-2)!.date.slice(5)}` : ""}</span><strong><DirectionIcon aria-hidden="true" />{comparison.amount}</strong><span>{comparison.detail}</span></div>
    </div>
    <TrendPlot currencyCode={currencyCode} label={label} metric={metric} points={points} />
    <p className={styles.note}>圆点代表已发布数据；缺报或缺值留空，不补零、不跨缺口连线。增减仅比较相邻报告日，不直接表示经营好坏。</p>
    <details className={styles.details}>
      <summary>查看逐日数据 · {label}</summary>
      <div className={styles.tableScroll} role="region" aria-label="逐日趋势数据" tabIndex={0}>
        <table><caption>{label} · {reportDate.slice(0, 7)}-01 至 {reportDate}</caption><thead><tr><th scope="col">报告日期</th><th scope="col">{label}</th><th scope="col">数据情况</th></tr></thead><tbody>
          {points.map((point) => <tr className={point.date === reportDate ? styles.selectedRow : undefined} key={point.date}><th scope="row">{point.date}{point.date === reportDate ? "（所选日）" : ""}</th><td>{formatMetric(point.value, metric, currencyCode)}</td><td>{point.value === null ? "未发布或暂无指标值" : "来自当前发布版本"}</td></tr>)}
        </tbody></table>
      </div>
    </details>
  </section>;
}
