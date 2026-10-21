import { analyticsError, type AnalyticsFailure } from "./analyticsError";
import { AnalyticsErrorState } from "./AnalyticsErrorState";
import { Button, LinkButton, Skeleton } from "../../design-system";
import { ArrowLeft } from "lucide-react";
import css from "./ProductAnalytics.module.css";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link, useLocation, useParams, useSearchParams } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { VariantReviewTable } from "./VariantReviewTable";
import { loadStyleCard } from "./productAnalyticsApi";
import type { StyleCardResponse } from "./productAnalyticsTypes";
import { MetricValueView, type MetricKind } from "./MetricValueView";
import { ProductTrendChart } from "./ProductTrendChart";
import { SeriesSelector } from "./SeriesSelector";
import { TrendPointMatrix } from "./TrendPointMatrix";
import { parseProductDetailSearch, serializeProductDetailSearch, updateProductDetailView, type ProductDetailView } from "./productDetailState";


type DetailLocationState = { focusId?: string; ledgerUrl?: string };
const metrics: Array<{ key: MetricKind; label: string }> = [{ key:"units",label:"销量"},{key:"sales",label:"销售额"},{key:"returns",label:"退货"},{key:"sessions",label:"会话"},{key:"conversion",label:"转化率"}];
const dimensions: Array<{ key: ProductDetailView["dimension"]; label: string }> = [{key:"total",label:"款式合计"},{key:"color",label:"颜色"},{key:"size",label:"尺码"},{key:"sku",label:"实际 SKU"}];

const colorSwatches:Record<string,string>={white:"#fff",black:"#25282d",blue:"#3978bb","hot pink":"#d64987",navy:"#273b60",red:"#ba4652",红色:"#ba4652",蓝色:"#3978bb"};
function TrendChoice({label,value,options,onChange,appearance="segments"}:{label:string;value:string;options:readonly {key:string;label:string;disabled?:boolean}[];onChange:(value:string)=>void;appearance?:"metrics"|"segments"|"colors"}){
  const name=useId();
  return <fieldset className={`${css["trend-choice"]} ${css[`trend-choice--${appearance}`]}`}><legend>{label}</legend><div>
    {options.map(option=><label key={option.key}><input type="radio" name={name} value={option.key} checked={value===option.key} disabled={option.disabled} onChange={()=>onChange(option.key)}/><span>
      {appearance==="colors"&&colorSwatches[option.label.toLowerCase()]&&<i aria-hidden="true" style={{background:colorSwatches[option.label.toLowerCase()]}}/>}{option.label}
    </span></label>)}
  </div></fieldset>;
}

export function ProductDetailPage({ today }: { today: string }) {
  const { style_id: styleId = "" } = useParams(); const location=useLocation(); const state=(location.state ?? {}) as DetailLocationState;
  const { generation }=useAuthzGeneration(); const [parameters,setParameters]=useSearchParams(); const raw=parameters.toString();
  const view=useMemo(()=>parseProductDetailSearch(new URLSearchParams(raw),today),[raw,today]); const canonical=useMemo(()=>serializeProductDetailSearch(view).toString(),[view]); const key=`${styleId}?${canonical}`;
  const [loaded,setLoaded]=useState<{key:string;styleId:string;generation:typeof generation;view:ProductDetailView;value:StyleCardResponse}>(); const [failure,setFailure]=useState<{key:string;failure:AnalyticsFailure}>(); const [loadingKey,setLoadingKey]=useState<string>(); const [reload,setReload]=useState(0); const sequence=useRef(0); const repaired=useRef(new Set<string>());
  useEffect(()=>{if(raw!==canonical)setParameters(new URLSearchParams(canonical),{replace:true,state:location.state as DetailLocationState | null});},[canonical,location.state,raw,setParameters]);
  useEffect(()=>{ const current=++sequence.current; const controller=new AbortController(); setFailure(undefined);setLoadingKey(key);
    void loadStyleCard(styleId,view,controller.signal).then(value=>{if(current!==sequence.current||controller.signal.aborted)return;setLoaded({key,styleId,generation,view,value});setLoadingKey(undefined);}).catch((error:unknown)=>{if(current!==sequence.current||controller.signal.aborted)return;
      if(error instanceof ApiRequestError && !repaired.current.has(key) && (error.code==="catalog_color_not_found"||error.code==="analytics_series_invalid")){repaired.current.add(key); const fixed=error.code==="catalog_color_not_found"?{...view,color_key:null,dimension:"color" as const,series:[]}:{...view,series:[]}; setParameters(serializeProductDetailSearch(fixed),{replace:true,state:location.state as DetailLocationState | null});return;}
      setFailure({key,failure:analyticsError(error,"无法读取产品详情，请稍后重试。")});setLoadingKey(undefined);}); return()=>controller.abort(); },[generation,key,location.state,reload,setParameters,styleId,view]);
  const currentFailure=failure?.key===key?failure.failure:undefined;
  const error=currentFailure?.message;
  const response=!error&&loaded?.styleId===styleId&&loaded.generation===generation?loaded.value:undefined;
  const refreshing=!!response&&loaded?.key!==key;
  const loading=loadingKey===key||refreshing;
  const displayedView=response&&loaded?loaded.view:view;
  const update=(change:Partial<ProductDetailView>,replace=false)=>setParameters(serializeProductDetailSearch(updateProductDetailView(view,change)),{replace,state:location.state as DetailLocationState | null});
  const labels=useMemo(()=>new Map(response?.available_series.map(item=>[item.key,item.label])??[]),[response]);
  const selected=response ? (displayedView.series.length?displayedView.series:response.series.map(item=>item.key)) : view.series;
  const listTarget=state.ledgerUrl?.startsWith("?")?`/products${state.ledgerUrl}`:`/products?from=${view.from}&to=${view.to}&return_basis=${view.return_basis}&fact_basis=${view.fact_basis}`;
  const [colorResult,setColorResult]=useState<{key:string;scope:string;options:StyleCardResponse["available_series"];error?:string}>();
  const [colorReload,setColorReload]=useState(0);
  const colorScope=`${styleId}:${generation}:${response?.provenance.catalog_version??""}`;
  useEffect(()=>{
    if(!response || refreshing || view.dimension==="color") return;
    const controller=new AbortController();
    void loadStyleCard(styleId,{...view,dimension:"color",color_key:null,series:[],catalog_version:String(response.provenance.catalog_version)},controller.signal)
      .then(value=>{if(!controller.signal.aborted)setColorResult({key,scope:colorScope,options:value.available_series.filter(item=>item.dimension==="color")});})
      .catch(()=>{if(!controller.signal.aborted)setColorResult({key,scope:colorScope,options:[],error:"颜色选项读取失败"});});
    return()=>controller.abort();
  },[response,refreshing,view,styleId,key,colorReload,colorScope]);
  const colorOptions=displayedView.dimension==="color" ? response?.available_series.filter(item=>item.dimension==="color")??[] : colorResult?.scope===colorScope ? colorResult.options : [];
  const colorError=colorResult?.key===key ? colorResult.error : undefined;
  const switchDimension=(dimension:ProductDetailView["dimension"])=>{ if(dimension==="size"){const color=colorOptions[0]?.key; if(!color)return; update({dimension,color_key:color,series:[]});}else update({dimension,series:[]}); };
  return <main className={css["product-analytics"] + " " + "product-detail"} id="main-content">
    <nav className={css["analytics-breadcrumb"]} aria-label="面包屑"><LinkButton icon={<ArrowLeft />} state={{restoreFocus:state.focusId}} to={listTarget}>产品总表</LinkButton><span>/</span><span>款式详情</span></nav>
    {loading&&!response&&<section aria-busy="true" aria-label="正在读取产品详情"><Skeleton lines={3} /></section>}
    <p aria-live="polite" className={css["analytics-live"]}>{loading?"正在更新筛选结果。":error??(response?`已读取 ${response.style.standard_name}`:"")}</p>
    {currentFailure&&<AnalyticsErrorState title="产品详情读取失败" failure={currentFailure} onRetry={()=>setReload(value=>value+1)} />}
    {response&&<>
      <header className={css["product-detail__header"]}><div><p className={css["analytics-eyebrow"]}>STYLE {response.style.style_code}</p><h1>{response.style.standard_name}</h1><p>{response.style.sku_count} 个实际 SKU · {response.style.color_count} 色 · {response.style.size_count} 码</p></div>
        <dl className={css["analytics-provenance"]}><div><dt>目录版本</dt><dd>{response.provenance.catalog_version}</dd></div><div><dt>事实口径</dt><dd>{response.provenance.fact_basis === "current" ? "当前事实" : "目录快照"}</dd></div><div><dt>退货口径</dt><dd>{response.effective_return_basis === "event_date" ? "事件日期" : "报表日期"}</dd></div><div><dt>贡献报表</dt><dd>{response.source_report_coverage.contributing_report_date_from??"无"} → {response.source_report_coverage.contributing_report_date_to??"无"}</dd></div><div><dt>一致时间</dt><dd>{response.provenance.consistent_as_of}</dd></div></dl>
      </header>
      <p className={css["analytics-range"]}>分析范围：{displayedView.from} 至 {displayedView.to}</p>
      {response.permissions.can_manage_catalog && <aside className={css["analytics-unmatched-callout"]}><div><strong>发现商品数据与源报表不一致？</strong><span>新发布 Seller SKU 在正式归属前不会计入本商品。可按当前日期与退货口径核对待归属清单。</span></div><Link to={`/catalog/unmatched?from=${displayedView.from}&to=${displayedView.to}&return_basis=${displayedView.return_basis}&return_to=${encodeURIComponent(`/products/${styleId}?${canonical}`)}`}>核对待归属来源</Link></aside>}
      <section className={css["detail-summary"]} aria-label="周期指标摘要">{metrics.map(item=><div key={item.key}><span>{item.label}</span><MetricValueView kind={item.key} metric={response.summary.metrics[item.key]}/></div>)}</section>
      <section className="trend-workbench" aria-labelledby="trend-title"><div className={css["analytics-section-heading"]}><div><p className={css["analytics-eyebrow"]}>DAILY SERIES</p><h2 id="trend-title">每日趋势</h2></div><p>图表与下方矩阵来自同一响应；缺失点不插值。</p></div>
        <div className={css["trend-filter-panel"]}>
          <TrendChoice label="指标" appearance="metrics" value={view.metric} options={metrics} onChange={metric=>update({metric:metric as MetricKind,series:[]})}/>
          <div className={css["trend-filter-row"]}>
            <TrendChoice label="比较维度" value={view.dimension} options={dimensions.map(item=>({...item,disabled:item.key==="size"&&colorOptions.length===0&&view.dimension!=="size"}))} onChange={dimension=>switchDimension(dimension as ProductDetailView["dimension"])}/>
            <TrendChoice label="退货口径" value={view.return_basis} options={[{key:"event_date",label:"事件日期"},{key:"report_date",label:"报表日期"}]} onChange={return_basis=>update({return_basis:return_basis as ProductDetailView["return_basis"]})}/>
          </div>
          {view.dimension==="size"&&<div className={css["trend-color-row"]}>
            <TrendChoice label="限定颜色" appearance="colors" value={view.color_key??""} options={colorOptions} onChange={color_key=>update({color_key,series:[]})}/>
            {colorOptions.length===0&&<p role="status">{colorError??"正在读取颜色…"}</p>}
            <p className={css["trend-scope-note"]}>仅比较同一颜色下的尺码 · 色点为示意，以名称为准{colorError&&<Button onClick={()=>setColorReload(value=>value+1)}>重新读取颜色</Button>}</p>
          </div>}
        </div>
        <div className={css["trend-results"]} aria-busy={refreshing}>
          <p className={css["trend-update-status"]} role="status">{refreshing ? "正在更新 · 下方暂为上次结果，完成后整体替换" : ""}</p>
        <div inert={refreshing} className={refreshing?css["trend-results--pending"]:undefined}>
        <SeriesSelector available={response.available_series.filter(item=>item.dimension===displayedView.dimension)} onChange={series=>update({series})} selected={selected}/>
        <ProductTrendChart labels={labels} metric={displayedView.metric} series={response.series}/><TrendPointMatrix labels={labels} metric={displayedView.metric} series={response.series}/>
        </div></div>
      </section>
      <VariantReviewTable key={styleId} response={response} />
      <section className={css["style-reconciliation"]} aria-label="款式指标守恒"><strong>款式守恒</strong><span>汇总、趋势范围与 {response.variants.length} 个实际变体按服务端可计算状态核对。</span>{metrics.map(item=><span className={css["analytics-status"] + " " + (css[`analytics-status--${response.style_reconciliation.metric_status[item.key]}`] ?? "")} key={item.key}>{item.label} · {response.style_reconciliation.metric_status[item.key]}</span>)}</section>
    </>}
  </main>;
}
