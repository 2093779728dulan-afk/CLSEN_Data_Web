import { ProductDetailAnalysisView } from "./ProductDetailAnalysisView";
import { analyticsError, type AnalyticsFailure } from "./analyticsError";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useParams, useSearchParams } from "react-router-dom";

import { ApiRequestError } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { loadStyleCard } from "./productAnalyticsApi";
import type { StyleCardResponse } from "./productAnalyticsTypes";
import { parseProductDetailSearch, serializeProductDetailSearch, updateProductDetailView, type ProductDetailView } from "./productDetailState";


type DetailLocationState = { focusId?: string; ledgerUrl?: string };
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
  const listTarget=state.ledgerUrl?.startsWith("?")?`/products${state.ledgerUrl}`:`/products?from=${view.from}&to=${view.to}&return_basis=${view.return_basis}&fact_basis=${view.fact_basis}${view.catalog_version ? `&catalog_version=${encodeURIComponent(view.catalog_version)}` : ""}`;
  const [colorResult,setColorResult]=useState<{key:string;scope:string;options:StyleCardResponse["available_series"];error?:string}>();
  const [colorReload,setColorReload]=useState(0);
  const colorScope=`${styleId}:${generation}:${response?.provenance.catalog_version_id??""}`;
  useEffect(()=>{
    if(!response || refreshing || view.dimension==="color") return;
    const controller=new AbortController();
    void loadStyleCard(styleId,{...view,dimension:"color",color_key:null,series:[],catalog_version:response.provenance.catalog_version_id},controller.signal)
      .then(value=>{if(!controller.signal.aborted)setColorResult({key,scope:colorScope,options:value.available_series.filter(item=>item.dimension==="color")});})
      .catch(()=>{if(!controller.signal.aborted)setColorResult({key,scope:colorScope,options:[],error:"颜色选项读取失败"});});
    return()=>controller.abort();
  },[response,refreshing,view,styleId,key,colorReload,colorScope]);
  const colorOptions=displayedView.dimension==="color" ? response?.available_series.filter(item=>item.dimension==="color")??[] : colorResult?.scope===colorScope ? colorResult.options : [];
  const colorError=colorResult?.key===key ? colorResult.error : undefined;
  const switchDimension=(dimension:ProductDetailView["dimension"])=>{ if(dimension==="size"){const color=colorOptions[0]?.key; if(!color)return; update({dimension,color_key:color,series:[]});}else update({dimension,series:[]}); };
  return <ProductDetailAnalysisView view={view} displayedView={displayedView} canonical={canonical} styleId={styleId} focusId={state.focusId} listTarget={listTarget}
    response={response} failure={currentFailure} loading={loading} refreshing={refreshing} labels={labels} selected={selected} colorOptions={colorOptions} colorError={colorError}
    update={update} switchDimension={switchDimension} onRetry={() => setReload(value => value + 1)} onColorRetry={() => setColorReload(value => value + 1)} />;
}
