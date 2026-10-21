import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { RotateCcw, Layers } from "lucide-react";
import type { components } from "../../api/generated";
import { Button, EmptyState } from "../../design-system";
import css from "./ProductAnalytics.module.css";
import type { MetricKind } from "./MetricValueView";
import { decimalStringToScaledBigInt, trendMetricLabels } from "./metricFormatting";

type TrendSeries = components["schemas"]["TrendSeries"];

const dashPatterns = ["", "7 4", "", "7 4", "", "7 4", "", "7 4"];
const colors = ["var(--chart-series-1)", "var(--chart-series-2)", "var(--chart-series-3)", "var(--chart-series-4)", "#C04B55", "#087F8C", "#A35813", "#9B4F96"];

function scaled(value: number | string, metric: MetricKind): bigint {
  if (typeof value === "number") return BigInt(value);
  return decimalStringToScaledBigInt(value, metric === "sales" ? 2 : 6);
}

function axisValue(value: bigint, metric: MetricKind): string {
  const places = metric === "sales" ? 2 : metric === "conversion" ? 6 : 0;
  if (places === 0) return value.toLocaleString("zh-CN");
  const negative = value < 0n;
  const absolute = negative ? -value : value;
  const factor = 10n ** BigInt(places);
  const whole = absolute / factor;
  const fraction = String(absolute % factor).padStart(places, "0");
  return `${negative ? "-" : ""}${whole.toLocaleString("zh-CN")}.${fraction}`;
}

function axisDisplay(value: bigint, metric: MetricKind): string {
  const exact = axisValue(value, metric);
  return exact.length > 13 ? `${exact.slice(0, 10)}…` : exact;
}

export function ProductTrendChart({ series, labels, metric }: {
  series: readonly TrendSeries[];
  labels: ReadonlyMap<string, string>;
  metric: MetricKind;
}) {
  const id = useId();
  const metricLabel = trendMetricLabels[metric];
  const containerRef = useRef<HTMLElement>(null);
  const tooltipRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(760);
  const [activeDate, setActiveDate] = useState<string>();
  const [focusedKey, setFocusedKey] = useState<string>();
  const [showPoints, setShowPoints] = useState(true);
  const [replay, setReplay] = useState(0);
  const [hover, setHover] = useState<{key:string;keys:string[];date:string;left:number;top:number;series:readonly TrendSeries[];metric:MetricKind}>();
  useEffect(() => {
    const element = containerRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry) {setWidth(Math.max(320, Math.round(entry.contentRect.width)));setHover(undefined);}
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  // Use the complete available-series identity set, never the selected order.
  const paletteKeys=[...new Set([...labels.keys(),...series.map(item=>item.key)])].sort();
  const paletteIndex=(key:string)=>paletteKeys.indexOf(key);
  const seriesColor=(key:string)=>{
    const index=paletteIndex(key);
    return colors[index]??`hsl(${Math.round(index*137.508)%360} 55% 38%)`;
  };
  const seriesDash=(key:string)=>dashPatterns[paletteIndex(key)%dashPatterns.length];
  useLayoutEffect(()=>{
    const tip=tooltipRef.current;
    if(!tip||!hover)return;
    const box=tip.getBoundingClientRect();
    if(!box.width||!box.height)return;
    const top=Math.max(8,Math.min(box.top,window.innerHeight-box.height-8));
    const left=Math.max(8,Math.min(box.left,window.innerWidth-box.width-8));
    tip.style.top=`${hover.top+top-box.top}px`;
    tip.style.left=`${hover.left+left-box.left}px`;
  },[hover,series,metric,labels]);
  useEffect(()=>{
    const clearOutsideScroll=(event:Event)=>{
      if(event.target instanceof Node&&tooltipRef.current?.contains(event.target))return;
      setHover(undefined);
    };
    window.addEventListener("scroll",clearOutsideScroll,true);
    window.addEventListener("resize",clearOutsideScroll);
    return()=>{window.removeEventListener("scroll",clearOutsideScroll,true);window.removeEventListener("resize",clearOutsideScroll);};
  },[]);
  const all = series.flatMap((item) => item.points
    .filter((point) => point.value !== null)
    .map((point) => scaled(point.value!, metric)));
  if (all.length === 0) {
    return <EmptyState title="没有可绘制的观测点" description="缺失报表与未定义分母会保留在每日点矩阵中。" />;
  }

  let min = all[0]!;
  let max = all[0]!;
  for (const value of all) {
    if (value < min) min = value;
    if (value > max) max = value;
  }

  const dates = [...new Set(series.flatMap((item) => item.points.map((point) => point.date)))].sort();
  const dateIndex = new Map(dates.map((date, index) => [date, index]));
  const selectedDate = activeDate && dateIndex.has(activeDate) ? activeDate : dates.at(-1)!;
  const selectedIndex = dateIndex.get(selectedDate)!;
  const focus = series.some((item) => item.key === focusedKey) ? focusedKey : undefined;
  const range = max === min ? 1n : max - min;
  const height = 292;
  const left = width < 500 ? 68 : 92;
  const right = width < 500 ? 12 : 20;
  const top = 20;
  const bottom = 42;
  const plotBottom = height - bottom;
  const x = (index: number) => left + (dates.length <= 1
    ? (width - left - right) / 2
    : index * (width - left - right) / (dates.length - 1));
  const y = (value: bigint) => max === min
    ? top + (plotBottom - top) / 2
    : top + Number(((max - value) * BigInt(plotBottom - top) * 10_000n) / range) / 10_000;
  const yTicks = [...new Set([max, min + range / 2n, min])];
  const xTicks = dates.length <= (width < 500 ? 4 : 10)
    ? dates.map((_, index) => index)
    : [...new Set([0, Math.floor((dates.length - 1) / 2), dates.length - 1])];
  const hoverValid = hover?.series===series && hover.metric===metric;

  return <figure className={css["trend-chart"]} ref={containerRef} onKeyDown={event=>{if(event.key==="Escape")setHover(undefined);}}>
    <div className={css["trend-chart__toolbar"]}>
      <div className={css["trend-chart__hint"]}><strong>{metricLabel}</strong><span>{focus ? `正在突出：${labels.get(focus) ?? focus} · ` : ""}悬停查看读数 · 点击下方图例聚焦</span>{metric === "conversion" && <span>按小数比率显示，0.05 = 5%</span>}{metric === "sales" && <span>币种沿用源报告，金额保留两位小数</span>}</div>
      <div className={css["trend-chart__tools"]}>
        <label><input type="checkbox" checked={showPoints} onChange={(event) => setShowPoints(event.target.checked)} />数据点</label>
        <Button icon={<RotateCcw />} variant="quiet" onClick={() => {setHover(undefined);setReplay((value) => value + 1);}}>重播动画</Button>
        {focus&&<Button icon={<Layers />} variant="quiet" onClick={() => setFocusedKey(undefined)}>恢复全部曲线</Button>}
      </div>
    </div>
    <svg aria-label={`产品每日趋势 · ${metricLabel}`} aria-describedby={`${id}-desc`} role="img" viewBox={`0 0 ${width} ${height}`}
      onPointerLeave={event=>{if(!(event.relatedTarget instanceof Node)||!tooltipRef.current?.contains(event.relatedTarget))setHover(undefined);}}
      onPointerMove={(event) => {
        const rect = event.currentTarget.getBoundingClientRect();
        if (!rect.width) return;
        const position = (event.clientX - rect.left) * width / rect.width;
        const index = Math.round((position - left) / (width - left - right) * (dates.length - 1));
        const date=dates[Math.max(0, Math.min(dates.length - 1, index))]!;
        setActiveDate(date);
        const pointerY=(event.clientY-rect.top)*height/rect.height;
        const candidates=series.flatMap(item=>{
          const point=item.points.find(entry=>entry.date===date);
          return point?.value!=null?[{key:item.key,value:scaled(point.value,metric),distance:Math.hypot((x(dateIndex.get(date)!)-position)*rect.width/width,(y(scaled(point.value,metric))-pointerY)*rect.height/height)}]:[];
        }).sort((a,b)=>a.distance-b.distance);
        const nearest=candidates[0];
        const bounds=containerRef.current?.getBoundingClientRect();
        if(nearest&&nearest.distance<=22&&position>=left-6&&position<=width-right+6&&pointerY>=top-6&&pointerY<=plotBottom+6&&bounds){
          setHover({key:nearest.key,keys:candidates.filter(item=>item.value===nearest.value).map(item=>item.key),date,left:Math.max(8,Math.min(event.clientX-bounds.left+14,bounds.width-288)),top:Math.max(rect.top-bounds.top,event.clientY-bounds.top-100),series,metric});
        }else setHover(undefined);
      }}>
      <desc id={`${id}-desc`}>{series.length} 条系列，从 {dates[0]} 至 {dates.at(-1)}；缺失点不连线。纵轴和下方矩阵保留精确指标值，颜色、线型和文字标签共同识别系列。</desc>
      {yTicks.map((value) => <g key={String(value)}>
        <line className={css["trend-chart__grid"]} x1={left} x2={width - right} y1={y(value)} y2={y(value)} />
        <text className={css["trend-chart__axis-label"]} textAnchor="end" x={left - 10} y={y(value) + 4}><title>{axisValue(value, metric)}</title>{axisDisplay(value, metric)}</text>
      </g>)}
      <line className={css["trend-chart__axis"]} x1={left} x2={left} y1={top} y2={plotBottom} />
      <line className={css["trend-chart__axis"]} x1={left} x2={width - right} y1={plotBottom} y2={plotBottom} />
      <line className={css["trend-chart__cursor"]} style={{transform:`translateX(${x(selectedIndex)}px)`}} x1={0} x2={0} y1={top} y2={plotBottom} />
      <g className={css["trend-chart__growth"]} key={`${metric}:${JSON.stringify(series)}:${replay}`}>
      {series.map((item) => {
        const segments: string[][] = [];
        let segment: string[] = [];
        item.points.forEach((point) => {
          if (point.value === null) {
            if (segment.length) segments.push(segment);
            segment = [];
            return;
          }
          segment.push(`${x(dateIndex.get(point.date) ?? 0)},${y(scaled(point.value, metric))}`);
        });
        if (segment.length) segments.push(segment);
        return <g key={item.key} className={css["trend-chart__series"]} opacity={focus && focus !== item.key ? 0.18 : 1}>
          {segments.map((points, index) => points.length <= 1 ? null
            : <polyline className={css["trend-chart__line"]} fill="none" key={index} points={points.join(" ")} stroke={seriesColor(item.key)} strokeDasharray={seriesDash(item.key)} strokeWidth={focus === item.key ? 3.2 : 2.4} strokeLinecap="round" strokeLinejoin="round" />)}
          {item.points.map((point, index) => {
            if (point.value === null) return null;
            const isolated = item.points[index - 1]?.value == null && item.points[index + 1]?.value == null;
            return <circle className={css["trend-chart__point"]} key={point.date} cx={x(dateIndex.get(point.date)!)} cy={y(scaled(point.value, metric))}
              opacity={showPoints || isolated || point.date === selectedDate ? 1 : 0}
              r={point.date === selectedDate ? 4.5 : 2.7} fill="var(--color-surface)" stroke={seriesColor(item.key)} strokeWidth={point.date === selectedDate ? 2.5 : 1.6} />;
          })}
        </g>;
      })}
      </g>
      {xTicks.map((index) => <text className={css["trend-chart__axis-label"]} key={index} textAnchor={dates.length > 1 && index === dates.length - 1 ? "end" : "middle"} x={x(index)} y={height - 14}>{dates[index]?.slice(5)}</text>)}
    </svg>
    {hover&&hoverValid&&<div ref={tooltipRef} role="tooltip" tabIndex={0} aria-label="数据点详情" onPointerLeave={()=>setHover(undefined)} className={css["trend-chart__tooltip"]} style={{left:hover.left,top:hover.top}}>
      <time>{hover.date}</time><strong>{metricLabel}{hover.keys.length>1?` · ${hover.keys.length} 个重合点`:""}</strong>
      {series.map((item)=>{
        if(!hover.keys.includes(item.key))return null;
        const point=item.points.find(entry=>entry.date===hover.date);
        const value=!point||point.value_state==="missing_report"?"无报表":point.value_state==="undefined_denominator"?"分母为 0":point.value===null?"不可计算":axisValue(scaled(point.value,metric),metric);
        return <div className={css["trend-chart__tooltip-row"]} key={item.key} data-nearest={item.key===hover.key}>
          <span><i aria-hidden="true" style={{background:seriesColor(item.key)}}/>{labels.get(item.key)??item.key}</span><b>{value}</b>
          {point?.source_completeness==="partial"&&<small>部分数据</small>}
        </div>;
      })}
    </div>}
    <figcaption className={css["trend-chart__legend"]}>
      {series.map((item) => <button type="button" key={item.key} aria-pressed={focus === item.key}
        onClick={() => setFocusedKey(focus === item.key ? undefined : item.key)}>
        <svg aria-hidden="true" viewBox="0 0 28 8"><line stroke={seriesColor(item.key)} strokeDasharray={seriesDash(item.key)} strokeWidth="2" x1="1" x2="27" y1="4" y2="4" /></svg>
        {labels.get(item.key) ?? item.key}
      </button>)}
    </figcaption>
    <div className={css["trend-chart__readout"]}>
      <div className={css["trend-chart__date"]}>
        <label htmlFor={`${id}-date`}>每日读数 · {metricLabel} <strong>{selectedDate}</strong></label>
        <input id={`${id}-date`} aria-label="查看日期" aria-valuetext={selectedDate} type="range" min={0} max={dates.length - 1}
          value={selectedIndex} disabled={dates.length === 1} onChange={(event) => {setHover(undefined);setActiveDate(dates[Number(event.target.value)]);}} />
        <small>拖动或用方向键逐日查看</small>
      </div>
      <dl className={css["trend-chart__values"]}>
        {series.map((item) => {
          const point = item.points.find((entry) => entry.date === selectedDate);
          const value = !point || point.value_state === "missing_report" ? "无报表"
            : point.value_state === "undefined_denominator" ? "分母为 0"
            : point.value === null ? "不可计算" : axisValue(scaled(point.value, metric), metric);
          return <div key={item.key} data-muted={!!focus && focus !== item.key}>
            <dt><i style={{ background: seriesColor(item.key) }} aria-hidden="true" />{labels.get(item.key) ?? item.key}</dt>
            <dd>{value}{point?.source_completeness === "partial" && <small>部分数据</small>}</dd>
          </div>;
        })}
      </dl>
    </div>
  </figure>;
}
