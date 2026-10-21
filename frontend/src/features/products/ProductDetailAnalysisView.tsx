import { useId } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { Button, LinkButton, Skeleton, StatusBadge } from "../../design-system";
import { AnalyticsErrorState } from "./AnalyticsErrorState";
import type { AnalyticsFailure } from "./analyticsError";
import { MetricValueView, type MetricKind } from "./MetricValueView";
import { VariantReviewTable } from "./VariantReviewTable";
import { ProductTrendChart } from "./ProductTrendChart";
import { SeriesSelector } from "./SeriesSelector";
import { TrendPointMatrix } from "./TrendPointMatrix";
import type { StyleCardResponse } from "./productAnalyticsTypes";
import type { ProductDetailView } from "./productDetailState";
import css from "./ProductDetailAnalysisView.module.css";

type Props = {
  view: ProductDetailView; displayedView: ProductDetailView; canonical: string;
  styleId: string; focusId?: string; listTarget: string;
  response?: StyleCardResponse; failure?: AnalyticsFailure;
  loading: boolean; refreshing: boolean;
  labels: ReadonlyMap<string,string>; selected: readonly string[];
  colorOptions: StyleCardResponse["available_series"]; colorError?: string;
  update: (change: Partial<ProductDetailView>) => void;
  switchDimension: (dimension: ProductDetailView["dimension"]) => void;
  onRetry: () => void; onColorRetry: () => void;
};
const metrics: Array<{ key: MetricKind; label: string }> = [{ key:"units",label:"销量"},{key:"sales",label:"销售额"},{key:"returns",label:"退货"},{key:"sessions",label:"会话"},{key:"conversion",label:"转化率"}];
const dimensions: Array<{ key: ProductDetailView["dimension"]; label: string }> = [{key:"total",label:"款式合计"},{key:"color",label:"颜色"},{key:"size",label:"尺码"},{key:"sku",label:"实际 SKU"}];

const colorSwatches:Record<string,string>={white:"#fff",black:"#25282d",blue:"#3978bb","hot pink":"#d64987",navy:"#273b60",red:"#ba4652",红色:"#ba4652",蓝色:"#3978bb"};
function TrendChoice({label,value,options,onChange,appearance="segments"}:{label:string;value:string;options:readonly {key:string;label:string;disabled?:boolean}[];onChange:(value:string)=>void;appearance?:"metrics"|"segments"|"colors"}){
  const name=useId();
  return <fieldset className={css["trend-choice"]}><legend>{label}</legend><div>
    {options.map(option=><label key={option.key}><input type="radio" name={name} value={option.key} checked={value===option.key} disabled={option.disabled} onChange={()=>onChange(option.key)}/><span>
      {appearance==="colors"&&colorSwatches[option.label.toLowerCase()]&&<i aria-hidden="true" style={{background:colorSwatches[option.label.toLowerCase()]}}/>}{option.label}
    </span></label>)}
  </div></fieldset>;
}

export function ProductDetailAnalysisView({ view, displayedView, canonical, styleId, focusId, listTarget, response, failure, loading, refreshing, labels, selected, colorOptions, colorError, update, switchDimension, onRetry, onColorRetry }: Props) {
  const error = failure?.message;
  return <main className={css.workspace} id="main-content">
    <nav className={css["analytics-breadcrumb"]} aria-label="面包屑"><LinkButton icon={<ArrowLeft />} state={{restoreFocus:focusId}} to={listTarget}>产品总表</LinkButton><span>/</span><span>款式详情</span></nav>
    {loading&&!response&&<section aria-busy="true" aria-label="正在读取产品详情"><Skeleton lines={3} /></section>}
    <p aria-live="polite" className={css["analytics-live"]}>{loading?"正在更新筛选结果。":error??(response?`已读取 ${response.style.standard_name}`:"")}</p>
    {failure&&<AnalyticsErrorState title="产品详情读取失败" failure={failure} onRetry={onRetry} />}
    {response&&<>
      <header className={css["product-detail__header"]}><div><p className={css["analytics-eyebrow"]}>STYLE {response.style.style_code}</p><h1>{response.style.standard_name}</h1><p>{response.style.sku_count} 个实际 SKU · {response.style.color_count} 色 · {response.style.size_count} 码</p></div>
        <dl className={css["analytics-provenance"]}><div><dt>目录版本</dt><dd>{response.provenance.catalog_version}</dd></div><div><dt>事实口径</dt><dd>{response.provenance.fact_basis === "current" ? "当前事实" : "目录快照"}</dd></div><div><dt>退货口径</dt><dd>{response.effective_return_basis === "event_date" ? "事件日期" : "报表日期"}</dd></div><div><dt>贡献报表</dt><dd>{response.source_report_coverage.contributing_report_date_from??"无"} → {response.source_report_coverage.contributing_report_date_to??"无"}</dd></div><div><dt>一致时间</dt><dd>{response.provenance.consistent_as_of}</dd></div></dl>
      </header>
      <p className={css["analytics-range"]}>分析范围：{displayedView.from} 至 {displayedView.to}</p>
      {response.permissions.can_manage_catalog && <aside className={css["analytics-unmatched-callout"]}><div><strong>发现商品数据与源报表不一致？</strong><span>新发布 Seller SKU 在正式归属前不会计入本商品。可按当前日期与退货口径核对待归属清单。</span></div><Link to={`/catalog/unmatched?from=${displayedView.from}&to=${displayedView.to}&return_basis=${displayedView.return_basis}&return_to=${encodeURIComponent(`/products/${styleId}?${canonical}`)}`}>核对待归属来源</Link></aside>}
      <section className={css["detail-summary"]} aria-label="周期指标摘要">{metrics.map(item=><div key={item.key}><span>{item.label}</span><MetricValueView kind={item.key} metric={response.summary.metrics[item.key]}/></div>)}</section>
      <section className={css.workbench} aria-labelledby="trend-title"><div className={css["analytics-section-heading"]}><div><p className={css["analytics-eyebrow"]}>DAILY SERIES</p><h2 id="trend-title">每日趋势</h2></div><p>图表与下方矩阵来自同一响应；缺失点不插值。</p></div>
        <div className={css["trend-filter-panel"]}>
          <TrendChoice label="指标" appearance="metrics" value={view.metric} options={metrics} onChange={metric=>update({metric:metric as MetricKind,series:[]})}/>
          <div className={css["trend-filter-row"]}>
            <TrendChoice label="比较维度" value={view.dimension} options={dimensions.map(item=>({...item,disabled:item.key==="size"&&colorOptions.length===0&&view.dimension!=="size"}))} onChange={dimension=>switchDimension(dimension as ProductDetailView["dimension"])}/>
            <TrendChoice label="退货口径" value={view.return_basis} options={[{key:"event_date",label:"事件日期"},{key:"report_date",label:"报表日期"}]} onChange={return_basis=>update({return_basis:return_basis as ProductDetailView["return_basis"]})}/>
          </div>
          {view.dimension==="size"&&<div className={css["trend-color-row"]}>
            <TrendChoice label="限定颜色" appearance="colors" value={view.color_key??""} options={colorOptions} onChange={color_key=>update({color_key,series:[]})}/>
            {colorOptions.length===0&&<p role="status">{colorError??"正在读取颜色…"}</p>}
            <p className={css["trend-scope-note"]}>仅比较同一颜色下的尺码 · 色点为示意，以名称为准{colorError&&<Button onClick={onColorRetry}>重新读取颜色</Button>}</p>
          </div>}
        </div>
        <div className={css["trend-results"]} aria-busy={refreshing}>
          <p className={css["trend-update-status"]} role="status">{refreshing ? "正在更新 · 下方暂为上次结果，完成后整体替换" : ""}</p>
        <div inert={refreshing} className={refreshing?css["trend-results--pending"]:undefined}>
        <SeriesSelector available={response.available_series.filter(item=>item.dimension===displayedView.dimension)} onChange={series=>update({series})} selected={selected}/>
        <ProductTrendChart labels={labels} metric={displayedView.metric} series={response.series}/><TrendPointMatrix labels={labels} metric={displayedView.metric} series={response.series}/>
        </div></div>
      </section>
      <div className={css.variants}><VariantReviewTable key={styleId} response={response} /></div>
      <section className={css["style-reconciliation"]} aria-label="款式指标守恒"><strong>款式守恒</strong><span>汇总、趋势范围与 {response.variants.length} 个实际变体按服务端可计算状态核对。</span>{metrics.map(item=><StatusBadge key={item.key} tone={response.style_reconciliation.metric_status[item.key] === "evaluable" ? "good" : "quiet"} label={`${item.label} · ${response.style_reconciliation.metric_status[item.key] === "evaluable" ? "可计算" : "不可计算"}`} />)}</section>
    </>}
  </main>;
}
