import { ProductionConfirmDialog } from "../production/ProductionConfirmDialog";
import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Dialog, FormField, StatusMessage } from '../../design-system';
import { requestApi } from '../../api/client';
import type { Principal } from '../../api/types';
import type { AnalyticsReadiness, CatalogScopeStatusResponse } from '../../api/generated';
import { useAuthzGeneration } from '../../app/AuthzGenerationContext';
import { useProductionLeave } from '../production/useProductionLeave';
import { ImportReviewFlow } from '../import-review/ImportReviewFlow';
import { CatalogSetup } from './CatalogSetup';
import { CatalogListingSourcePage } from './CatalogListingSourcePage';
import { CatalogSpecificationSourcePage, type CatalogPrimaryAction } from './CatalogProductionSourcePage';
import type { CatalogDraftSaveAction } from "./catalogTypes";
import { CatalogImportPage } from './CatalogImportPage';
import { getCurrentCatalog, listCatalogUnmatched } from './catalogApi';
import { CatalogExportPanel } from './CatalogExportPanel';
import { ArrowRight, Check } from 'lucide-react';
import css from './CatalogGuidedFlow.module.css';

type Guard={dirty:boolean;busy:boolean;unknown:boolean};
const clean:Guard={dirty:false,busy:false,unknown:false};
type FlowMode='product'|'analysis'|'catalog';
type Destination=number|'close'|'manual'|'file'|'reviewBack'|'productMode'|'analysisMode';
export function CatalogGuidedFlow({initialMode='analysis',autoOpen=false,initialListing,entryMode='single',onClosed}:{initialMode?:FlowMode;autoOpen?:boolean;initialListing?:number;entryMode?:'single'|'workspace';onClosed?:()=>void}){
 const {generation,preferenceScope,registerSensitivePurge}=useAuthzGeneration();const [,siteId]=preferenceScope.split(':').map(Number);
 const [open,setOpen]=useState(autoOpen);const [mode,setMode]=useState(initialMode);const [step,setStep]=useState(0);const [review,setReview]=useState<number>();
 const [state,setState]=useState<{scope:CatalogScopeStatusResponse;readiness:AnalyticsReadiness}>();const onState=useCallback((value:NonNullable<typeof state>)=>setState(value),[]);
 const [guard,setGuard]=useState(clean);const [inputGuard,setInputGuard]=useState(clean);const [sourceRevisit,setSourceRevisit]=useState(false);const [changed,setChanged]=useState(false);const [pending,setPending]=useState<Destination>();const [refresh,setRefresh]=useState(0);const [approved,setApproved]=useState(false);
 const [skipSource,setSkipSource]=useState(false);
 const [saveAction,setSaveAction]=useState<CatalogDraftSaveAction>();
 const [manualAction,setManualAction]=useState<CatalogPrimaryAction>();
 const [manual,setManual]=useState(false);const [listing,setListing]=useState<number|undefined>(initialListing);const [readinessLoading,setReadinessLoading]=useState(false);
 const content=useRef<HTMLDivElement>(null);
 const [catalogRevision,setCatalogRevision]=useState(0);
 const [mappingCheck,setMappingCheck]=useState<{total:number|null;loading:boolean;error:string}>({total:null,loading:false,error:""});
 const [reportType,setReportType]=useState<'business_report'|'return_report'>('business_report');const [date]=useState(()=>new Date().toLocaleDateString('en-CA'));const [operator,setOperator]=useState<Principal>();const [error,setError]=useState('');
 const trigger=useRef<HTMLButtonElement>(null);const reportChanged=useRef(false);
 useEffect(()=>registerSensitivePurge(()=>{setOpen(false);setStep(0);setSkipSource(false);setManual(false);setListing(undefined);setApproved(false);setCatalogRevision(0);setError('');setState(undefined);setReview(undefined);setGuard(clean);setChanged(false);setPending(undefined);setOperator(undefined);}),[registerSensitivePurge]);
 useEffect(()=>{let active=true;void requestApi<Principal>('/api/auth/me').then(value=>{if(active)setOperator(value);}).catch(()=>{if(active)setError('账号读取失败，请重新打开准备流程。');});return()=>{active=false;};},[generation,refresh]);
 useEffect(()=>{const warn=(event:BeforeUnloadEvent)=>{if(open&&(guard.dirty||inputGuard.dirty||guard.busy||guard.unknown||changed)){event.preventDefault();event.returnValue='';}};window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);},[open,guard,inputGuard,changed]);
 useEffect(()=>{let active=true;void getCurrentCatalog().then(value=>{if(active)setCatalogRevision(value?.catalog_publication_revision||0);}).catch(()=>{if(active)setError('目录版本读取失败，请重新读取。');});return()=>{active=false;};},[refresh,generation]);
 useEffect(()=>{if(!open||!(mode==='catalog'||step===0||mode==='analysis'&&step===1))return;let active=true;setReadinessLoading(true);setError('');void Promise.all([requestApi<CatalogScopeStatusResponse>('/api/catalog/source-scope'),requestApi<AnalyticsReadiness>('/api/dashboard/style-readiness')]).then(([scope,readiness])=>{if(active){setState({scope,readiness});setError('');if(mode!=='catalog'&&step===0&&scope.status==='confirmed'&&!sourceRevisit){setSkipSource(true);setStep(1);}}}).catch(()=>{if(active){setState(undefined);setError(mode==='catalog'?'准备状态读取失败，请重新读取；已有目录工作簿仍可上传。':'资料设置读取失败，请重新读取后继续。');}}).finally(()=>{if(active)setReadinessLoading(false);});return()=>{active=false;};},[open,mode,step,refresh,generation,sourceRevisit]);
 const leave=useProductionLeave(open&&(guard.dirty||inputGuard.dirty||changed),open&&guard.busy,open&&guard.unknown);
 const canManage=!!operator?.roles.some(role=>role==='admin'||role==='data_manager');
 const allSteps=mode==='product'?['确认店铺','上传与审核商品','完成']:mode==='catalog'?['维护目录','完成']:['确认店铺','上传与审核报表','建立退货快照','审核商品目录','完成'];
 const steps=skipSource&&mode!=='catalog'?allSteps.slice(1):allSteps;
 const stepIndex=step-(skipSource&&mode!=='catalog'?1:0);
 const lastStep=allSteps.length-1;
 const sourceStep=mode!=='catalog'&&step===0;
 const checkingSource=sourceStep&&!state;
 function activate(next:Destination){
  setPending(undefined);setChanged(false);setGuard(clean);
  if(next==='close'){setInputGuard(clean);setSourceRevisit(false);setOpen(false);setReview(undefined);setApproved(false);setManual(false);setStep(0);setRefresh(value=>value+1);onClosed?.();}
  else if(next==='manual'||next==='file'){setManual(next==='manual');setApproved(false);}
  else if(next==='productMode'||next==='analysisMode'){setMode(next==='productMode'?'product':'analysis');setSkipSource(false);setState(undefined);setReview(undefined);setApproved(false);setRefresh(value=>value+1);}
  else if(next==='reviewBack'){setReview(undefined);setApproved(false);setRefresh(value=>value+1);}
  else{if(next===0){setSkipSource(false);setSourceRevisit(true);}setStep(next);setRefresh(value=>value+1);}
 }
 function launch(next:FlowMode){setInputGuard(clean);setSourceRevisit(false);setMode(next);setStep(0);setSkipSource(false);setManual(false);setListing(undefined);setReview(undefined);setApproved(false);setPending(undefined);setChanged(false);setGuard(clean);setError('');setState(undefined);setRefresh(value=>value+1);setOpen(true);}
 function request(next:Destination){if(guard.busy||guard.unknown||inputGuard.busy||inputGuard.unknown)return;if(step===lastStep&&next==='close'){activate(next);return;}if((typeof next==='number'||next==='reviewBack')&&(!guard.dirty||step===1&&!review))activate(next);else if(guard.dirty||inputGuard.dirty||changed)setPending(next);else activate(next);}
 function openReview(id:number){setGuard(clean);setApproved(false);setReview(id);}
 const productStep=mode==='product'&&step===1;
 const inputGuardChanged=useCallback((value:Guard)=>{setInputGuard(previous=>previous.dirty===value.dirty&&previous.busy===value.busy&&previous.unknown===value.unknown?previous:value);if(step===1&&!review)setGuard(value);},[step,review]);
 const catalogStep=mode==='analysis'&&step===3||mode==='catalog'&&step===0;
 const completed=useCallback(()=>{setApproved(true);setChanged(false);setInputGuard(clean);},[]);
 const mappingOptions={from:state?.readiness.coverage_from||undefined,to:state?.readiness.coverage_to||undefined,returnBasis:"report_date" as const,pageSize:1};
 useEffect(()=>{
  if(!open||mode!=="analysis"||!catalogStep||review&&!approved)return;
  let active=true;setMappingCheck({total:null,loading:true,error:""});
  void listCatalogUnmatched({from:state?.readiness.coverage_from||undefined,to:state?.readiness.coverage_to||undefined,returnBasis:"report_date",pageSize:1}).then(value=>{if(active)setMappingCheck({total:value.total_items,loading:false,error:""});}).catch(()=>{if(active)setMappingCheck({total:null,loading:false,error:"商品归属检查失败，请重新检查后继续。"});});
  return()=>{active=false;};
 },[open,mode,catalogStep,review,approved,refresh,generation,state?.readiness.coverage_from,state?.readiness.coverage_to]);
 async function continueReports(){
  setMappingCheck({total:null,loading:true,error:""});
  try{const result=await listCatalogUnmatched(mappingOptions);setMappingCheck({total:result.total_items,loading:false,error:""});request(result.total_items===0&&catalogRevision>0?lastStep:3);}catch{setMappingCheck({total:null,loading:false,error:"商品归属检查失败，请重新检查后继续。"});}
 }
 async function finish(){
  if(mode!=="analysis"){request("close");return;}
  setMappingCheck({total:null,loading:true,error:""});
  try{const result=await listCatalogUnmatched(mappingOptions);setMappingCheck({total:result.total_items,loading:false,error:""});if(result.total_items===0)request(lastStep);}catch{setMappingCheck({total:null,loading:false,error:"商品归属检查失败，请重新检查后继续。"});}
 }
 const reportPrerequisites=!!state&&state.scope.status==="confirmed"&&state.readiness.return_snapshot_present&&(state.readiness.published_business_reports??state.readiness.published_reports)>0;
 const mappingsReady=mode!=="analysis"||reportPrerequisites&&mappingCheck.total===0&&!mappingCheck.loading&&!mappingCheck.error;

 useEffect(()=>{if(open&&content.current){content.current.scrollTop=0;content.current.focus({preventScroll:true});}},[open,step,review,manual]);
 const reportGuard=inputGuardChanged;
 const reportPublished=useCallback(()=>{reportChanged.current=false;setChanged(false);setRefresh(value=>value+1);},[]);
 return <>
 <div className={css.entry}>{entryMode==='workspace'?<>{import.meta.env.VITE_PRODUCTION_CATALOG_ENABLED==='true'&&<Button variant="secondary" onClick={event=>{trigger.current=event.currentTarget;launch('product');}}>商品建档</Button>}<Button variant="secondary" onClick={event=>{trigger.current=event.currentTarget;launch('catalog');}}>目录维护</Button><Button variant="secondary" onClick={event=>{trigger.current=event.currentTarget;launch('analysis');}}>报表准备</Button></>:<Button ref={trigger} variant="primary" onClick={()=>launch(initialMode)}>开始{initialMode==='product'?'商品建档':'准备流程'}</Button>}</div>
 <Dialog open={open} title={mode==='product'?'商品建档':mode==='catalog'?'目录维护':'商品分析准备'} size="large" contentClassName={`${css.dialog} ${sourceStep&&!checkingSource||step===lastStep?css.startDialog:''}`} returnFocusTarget={trigger} closeOnOutsideClick={false} dismissDisabled={guard.busy||guard.unknown} onOpenChange={value=>{if(!value)request('close');}}>
  <div className={css.workflow}>
   {sourceStep&&!checkingSource&&entryMode==='single'&&<div className={css.modeSwitch} role="group" aria-label="选择维护任务"><Button variant="quiet" disabled={guard.busy||guard.unknown} aria-pressed={mode==='product'} onClick={()=>request('productMode')}>建档商品</Button><Button variant="quiet" disabled={guard.busy||guard.unknown} aria-pressed={mode==='analysis'} onClick={()=>request('analysisMode')}>准备报表分析</Button></div>}
   {!checkingSource&&<ol className={css.steps} aria-label="准备步骤">{steps.map((label,index)=><li key={label} aria-current={index===stepIndex?'step':undefined}><span className={css.stepNumber} aria-hidden="true">{index+1}</span><span className={css.stepLabel}>{label}</span></li>)}</ol>}
   {error&&<StatusMessage kind="danger" title={error} action={<Button disabled={guard.busy||guard.unknown} onClick={()=>setRefresh(value=>value+1)}>重新读取</Button>}/>}
   <ProductionConfirmDialog open={pending!==undefined} onOpenChange={open=>{if(!open)setPending(undefined);}} title="还有未保存的内容" description="继续当前步骤，或明确放弃输入后切换。"><Button onClick={()=>setPending(undefined)}>继续当前步骤</Button><Button variant="danger" disabled={guard.busy||guard.unknown} onClick={()=>{if(pending!==undefined)activate(pending);}}>放弃输入并继续</Button></ProductionConfirmDialog>
   <div ref={content} tabIndex={-1} className={`${css.content} ${sourceStep?css.sourceContent:''}`} onChangeCapture={event=>{if(mode==='analysis'&&step===1&&(event.target as HTMLElement).closest('[data-report-content]')){reportChanged.current=true;setChanged(true);}}}>
    {checkingSource&&!error&&<p role="status">正在读取资料设置…</p>}
    {sourceStep&&!checkingSource&&<><h3 className={css.stepHeading}>确认本次使用的店铺</h3><CatalogSetup editable={canManage} mode="source" refreshKey={refresh} onStateChange={onState} onGuardChange={setGuard}/></>}
    {(productStep||catalogStep)&&review&&<CatalogImportPage key={review} embeddedId={review} onSaveAction={setSaveAction} onGuardChange={setGuard} onNavigate={openReview} onCompleted={completed}/>}
    {open&&mode==='product'&&state?.scope.status==='confirmed'&&<div hidden={!productStep||!!review}>{manual?<CatalogSpecificationSourcePage embedded onPrimaryAction={setManualAction} onGuardChange={inputGuardChanged} onReview={openReview}/>:<CatalogListingSourcePage simplified selectedListing={listing} onListingSelected={setListing} onManual={()=>request('manual')} scopeRefresh={refresh} onGuardChange={inputGuardChanged} onSetup={()=>request(0)} onReview={openReview}/>}</div>}
    {open&&mode==='analysis'&&state?.scope.status==='confirmed'&&<div hidden={step!==1}>
     <div className={css.actions}><FormField label="报表类型"><select value={reportType} disabled={guard.busy||guard.dirty||changed} onChange={e=>setReportType(e.target.value as typeof reportType)}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></select></FormField></div>
     {!readinessLoading&&state&&(state.readiness.published_return_reports??0)===0&&!state.readiness.return_snapshot_present&&<StatusMessage kind="info" title="请先上传并发布退货报告，才能建立退货快照。"/>}
     {operator&&canManage?<div data-report-content><ImportReviewFlow key={`${reportType}:${date}`} canFinalizePublishedMove={operator.roles.includes('admin')} canForceRebuild={operator.roles.includes('admin')} onPublished={reportPublished} onGuardChange={reportGuard} embedded operator={operator} reportDate={date} siteId={siteId} userId={operator.id} initialReportType={reportType}/></div>:<StatusMessage kind="warning" title="当前账号无权上传审核报表"/>}
    </div>}
    {mode==='analysis'&&step===2&&mappingCheck.error&&<StatusMessage kind="danger" title={mappingCheck.error}/>}
    {mode==='analysis'&&step===2&&<CatalogSetup editable={canManage} mode="snapshot" refreshKey={refresh} onStateChange={onState} onGuardChange={setGuard}/>}
    {catalogStep&&mode==='analysis'&&<>{!reportPrerequisites&&<StatusMessage kind="warning" title="经营报告或退货快照尚未准备完成" action={<Button disabled={guard.busy||guard.unknown} onClick={()=>request(1)}>返回报表处理</Button>}/>}{mappingCheck.loading?<p role="status">正在检查报表商品归属…</p>:mappingCheck.error?<StatusMessage kind="danger" title={mappingCheck.error} action={<Button onClick={()=>setRefresh(value=>value+1)}>重新检查商品归属</Button>}/>:mappingCheck.total!==null&&mappingCheck.total>0?<StatusMessage kind="warning" title={`还有${mappingCheck.total}个报表SKU待归属`}>请在本窗生成候选、核对并批准商品归属，再完成报表准备。</StatusMessage>:null}</>}
    {catalogStep&&!review&&<CatalogExportPanel onGuardChange={setGuard} generationReady={!!state&&state.scope.status==='confirmed'&&state.readiness.return_snapshot_present&&state.readiness.published_reports>0} catalogPublicationRevision={catalogRevision} onReview={openReview}/>}
    {step===lastStep&&<div className={css.complete}><Check aria-hidden="true"/><h3>本次流程已完成</h3></div>}
   </div>
   {leave.prompt}
   <footer className={css.footer}>
    {!checkingSource&&<span className={css.stepCount}>第 {stepIndex+1} / {steps.length} 步</span>}
    {(sourceStep&&!checkingSource||skipSource&&step===1)&&mode==='analysis'&&<Button variant="quiet" disabled={guard.busy||guard.unknown} onClick={()=>request(3)}>{catalogRevision>0?'直接修订已有目录':'导入目录维护工作簿'}</Button>}
    {(productStep||catalogStep)&&review?<Button disabled={guard.busy||guard.unknown} onClick={()=>request('reviewBack')}>{productStep?'返回商品核对':'返回目录维护'}</Button>:productStep&&manual?<Button disabled={guard.busy||guard.unknown} onClick={()=>request('file')}>返回产品表</Button>:step>0&&<Button disabled={guard.busy||guard.unknown} onClick={()=>request(step-1)}>上一步</Button>}
    {sourceStep&&!checkingSource&&<Button variant="primary" icon={<ArrowRight size={16}/>} disabled={state?.scope.status!=='confirmed'||guard.busy||guard.unknown} onClick={()=>request(1)}>下一步</Button>}
    {mode==='analysis'&&step===1&&<Button disabled={readinessLoading||!state||!((state.readiness.published_return_reports??0)>0||state.readiness.return_snapshot_present)||guard.busy||guard.unknown} variant="primary" onClick={()=>request(2)}>报表已处理，继续</Button>}
    {mode==='analysis'&&step===2&&<Button disabled={!state?.readiness.return_snapshot_present||guard.busy||guard.unknown||mappingCheck.loading} variant="primary" onClick={()=>void continueReports()}>下一步</Button>}
    {catalogStep&&!review&&catalogRevision>0&&<Button variant="primary" disabled={guard.dirty||guard.busy||guard.unknown||!mappingsReady} onClick={()=>void finish()}>沿用当前已批准目录</Button>}
    {(productStep||catalogStep)&&review&&saveAction&&<Button variant="primary" disabled={saveAction.disabled} onClick={saveAction.run}>{saveAction.label}</Button>}
    {(productStep||catalogStep)&&review&&!saveAction&&<Button variant="primary" disabled={!approved||guard.busy||guard.unknown||!mappingsReady} onClick={()=>void finish()}>{mode==="analysis"?"完成审核":"完成"}</Button>}
    {productStep&&manual&&!review&&manualAction&&<Button variant="primary" disabled={manualAction.disabled} onClick={manualAction.run}>{manualAction.label}</Button>}
    {step===lastStep&&<Button variant="primary" onClick={()=>request('close')}>完成</Button>}
   </footer>
  </div>
 </Dialog>
 </>;
}
