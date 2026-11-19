import { useEffect, useState } from 'react';
import { render, screen, within, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, expect, it, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { CatalogGuidedFlow } from './CatalogGuidedFlow';
const catalogState=vi.hoisted(()=>({revision:3,scopeFails:false,unmatched:0,mappingFails:false}));
const state={scope:{status:'confirmed',seller_account_display_name:'示例店'},readiness:{return_snapshot_present:true,published_reports:2,published_return_reports:0}};
vi.mock('../../app/AuthzGenerationContext',()=>({useAuthzGeneration:()=>({generation:1,preferenceScope:'7:1',registerSensitivePurge:()=>()=>undefined})}));
vi.mock('../../api/client',()=>({requestApi:(path:string)=>catalogState.scopeFails&&path.endsWith('/source-scope')?Promise.reject(new Error('read failed')):Promise.resolve(path.endsWith('/source-scope')?state.scope:path.endsWith('/style-readiness')?state.readiness:{id:7,roles:['admin']})}));
vi.mock('./catalogApi',()=>({getCurrentCatalog:()=>Promise.resolve({catalog_publication_revision:catalogState.revision}),listCatalogUnmatched:()=>catalogState.mappingFails?Promise.reject(new Error("unavailable")):Promise.resolve({total_items:catalogState.unmatched})}));
vi.mock('./CatalogSetup',()=>({CatalogSetup:({onStateChange,mode}:{onStateChange:(value:unknown)=>void;mode:string})=>{
 useEffect(()=>onStateChange(state),[onStateChange]);
 return mode==='snapshot'?<p>快照已建立</p>:state.scope.status==='unconfirmed'?<><p>首次店铺配置</p><button onClick={()=>{state.scope.status='confirmed';onStateChange({...state,scope:{...state.scope}});}}>确认店铺</button></>:<p>店铺已确认</p>;
}}));
vi.mock('./CatalogListingSourcePage',()=>({CatalogListingSourcePage:({onReview,onManual,onGuardChange,selectedListing}:{selectedListing?:number;onReview:(id:number)=>void;onManual?:()=>void;onGuardChange:(value:object)=>void})=>{
 const [note,setNote]=useState('');
 return <>{selectedListing && <span>恢复商品表 {selectedListing}</span>}<input aria-label="商品文件备注" value={note} onChange={event=>{setNote(event.target.value);onGuardChange({dirty:true,busy:false,unknown:false});}}/><button onClick={()=>onReview(9)}>上传核对并保存候选</button><button onClick={onManual}>手工建档</button></>;
}}));
vi.mock('./CatalogProductionSourcePage',()=>({CatalogSpecificationSourcePage:()=> <p>内嵌手工建档</p>}));
vi.mock('./CatalogImportPage',()=>({CatalogImportPage:({onCompleted}:{onCompleted:()=>void})=><button onClick={onCompleted}>核对并批准目录</button>}));
vi.mock('./CatalogExportPanel',()=>({CatalogExportPanel:({onReview}:{onReview:(id:number)=>void})=><button onClick={()=>onReview(10)}>生成审核候选</button>}));
vi.mock('../import-review/ImportReviewFlow',()=>({ImportReviewFlow:({onGuardChange,onPublished}:{onGuardChange:(g:object)=>void;onPublished:()=>void})=><><input aria-label="报表上传测试" onChange={()=>onGuardChange({dirty:true,busy:false,unknown:false})}/><button onClick={()=>{onGuardChange({dirty:false,busy:false,unknown:false});onPublished();}}>正式发布报表</button></>}));

afterEach(()=>{cleanup();catalogState.revision=3;catalogState.scopeFails=false;catalogState.unmatched=0;catalogState.mappingFails=false;state.scope.status='confirmed';state.readiness.return_snapshot_present=true;state.readiness.published_return_reports=0;vi.unstubAllEnvs();});
function mount(mode:'product'|'analysis') {const router=createMemoryRouter([{path:'*',element:<CatalogGuidedFlow initialMode={mode} autoOpen/>}],{initialEntries:['/catalog/maintenance']});render(<RouterProvider router={router}/>);return router;}
async function productReady(){await screen.findByRole('button',{name:'上传核对并保存候选'});}
async function analysisReady(){await screen.findByRole('textbox',{name:'报表上传测试'});}

it('keeps upload, review and completion in one dialog without navigation',async()=>{
 const router=mount('product');const user=userEvent.setup();await productReady();await user.click(screen.getByRole('button',{name:'上传核对并保存候选'}));expect(screen.getAllByRole('dialog')).toHaveLength(1);await user.click(screen.getByRole('button',{name:'核对并批准目录'}));await user.click(screen.getByRole('button',{name:/^完成$/}));expect(screen.queryByRole('dialog')).not.toBeInTheDocument();expect(router.state.location.pathname).toBe('/catalog/maintenance');
});
it('includes report upload and snapshot in the analysis flow and guards unfinished work',async()=>{
 mount('analysis');const user=userEvent.setup();await analysisReady();await user.type(screen.getByRole('textbox',{name:'报表上传测试'}),'draft');await user.click(screen.getByRole('button',{name:'关闭对话框'}));expect(screen.getByRole('dialog',{name:'还有未保存的内容'})).toHaveTextContent('还有未保存的内容');await user.click(screen.getByRole('button',{name:'继续当前步骤'}));await user.click(screen.getByRole('button',{name:'正式发布报表'}));await user.click(screen.getByRole('button',{name:'报表已处理，继续'}));await screen.findByText('快照已建立');await user.click(screen.getByRole('button',{name:'下一步'}));expect(await screen.findByText('本次流程已完成')).toBeVisible();expect(screen.queryByRole('button',{name:'生成审核候选'})).not.toBeInTheDocument();expect(screen.getAllByRole('dialog')).toHaveLength(1);
});
it('allows existing-directory revision without repeating report upload or snapshot preparation',async()=>{
 const router=mount('analysis');await analysisReady();await userEvent.click(screen.getByRole('button',{name:'直接修订已有目录'}));
 expect(screen.getByRole('button',{name:'生成审核候选'})).toBeEnabled();expect(screen.queryByText('快照已建立')).not.toBeInTheDocument();expect(router.state.location.pathname).toBe('/catalog/maintenance');
});
it('requires a new review after completing and reopening the product flow',async()=>{
 mount('product');const user=userEvent.setup();await productReady();await user.click(screen.getByRole('button',{name:'上传核对并保存候选'}));await user.click(screen.getByRole('button',{name:'核对并批准目录'}));await user.click(screen.getByRole('button',{name:/^完成$/}));
 await user.click(screen.getByRole('button',{name:'开始商品建档'}));await productReady();expect(screen.queryByRole('button',{name:'完成审核'})).not.toBeInTheDocument();await user.click(screen.getByRole('button',{name:'上传核对并保存候选'}));expect(screen.getByRole('button',{name:/^完成$/})).toBeDisabled();
});
it('preserves first-catalog workbook import before report and snapshot preparation',async()=>{
 catalogState.revision=0;mount('analysis');await analysisReady();await userEvent.click(await screen.findByRole('button',{name:'导入目录维护工作簿'}));
 expect(screen.getByRole('button',{name:'生成审核候选'})).toBeEnabled();expect(screen.queryByText('快照已建立')).not.toBeInTheDocument();
});
it('opens only the explicitly chosen task from the unified workspace and restores its trigger',async()=>{
 vi.stubEnv('VITE_PRODUCTION_CATALOG_ENABLED','true');const closed=vi.fn();const router=createMemoryRouter([{path:'*',element:<CatalogGuidedFlow entryMode="workspace" onClosed={closed}/>}],{initialEntries:['/catalog/maintenance']});render(<RouterProvider router={router}/>);
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();const product=screen.getByRole('button',{name:/^商品建档$/});await userEvent.click(product);await productReady();expect(screen.getByRole('dialog',{name:'商品建档'})).toBeVisible();await userEvent.click(screen.getByRole('button',{name:'关闭对话框'}));await waitFor(()=>expect(product).toHaveFocus());expect(closed).toHaveBeenCalledTimes(1);
 await userEvent.click(screen.getByRole('button',{name:/^目录维护$/}));expect(screen.getByRole('dialog',{name:'目录维护'})).toBeVisible();expect(await screen.findByRole('button',{name:'生成审核候选'})).toBeEnabled();expect(screen.queryByText('店铺已确认')).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole('button',{name:'关闭对话框'}));await userEvent.click(screen.getByRole('button',{name:'报表准备'}));await analysisReady();expect(screen.getAllByRole('dialog')).toHaveLength(1);
});
it('keeps the feature flag boundary on the unified workspace',()=>{
 vi.stubEnv('VITE_PRODUCTION_CATALOG_ENABLED','false');const router=createMemoryRouter([{path:'*',element:<CatalogGuidedFlow entryMode="workspace"/>}],{initialEntries:['/catalog/maintenance']});render(<RouterProvider router={router}/>);
 expect(screen.queryByRole('button',{name:'商品建档'})).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'目录维护'})).toBeEnabled();expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});
it('blocks report continuation without a published return report and directs the user to the missing type',async()=>{
 state.readiness.return_snapshot_present=false;mount('analysis');await analysisReady();await waitFor(()=>expect(screen.getByRole('button',{name:'报表已处理，继续'})).toBeDisabled());expect(screen.getByText('请先上传并发布退货报告，才能建立退货快照。')).toBeVisible();
});
it('returns from candidate review to product checks and keeps manual entry inside the same dialog',async()=>{
 const router=mount('product');await productReady();expect(screen.queryByRole('button',{name:'完成审核'})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'上传核对并保存候选'}));await userEvent.click(screen.getByRole('button',{name:'返回商品核对'}));await productReady();await userEvent.click(screen.getByRole('button',{name:'手工建档'}));expect(screen.getByText('内嵌手工建档')).toBeVisible();expect(screen.getAllByRole('dialog')).toHaveLength(1);expect(router.state.location.pathname).toBe('/catalog/maintenance');
});

it('returns to confirmed shop settings and then to the product step',async()=>{
 mount('product');await productReady();
 await userEvent.type(screen.getByRole('textbox',{name:'商品文件备注'}),'保留文件输入');
 await userEvent.click(screen.getByRole('button',{name:'上一步'}));
 expect(await screen.findByText('确认本次使用的店铺')).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'下一步'}));
 await productReady();expect(screen.getByRole('textbox',{name:'商品文件备注'})).toHaveValue('保留文件输入');expect(screen.getAllByRole('dialog')).toHaveLength(1);
});
it.each(['product','analysis'] as const)('starts a confirmed single-store %s task without repeated store confirmation and allows returning to settings',async mode=>{
 mount(mode);if(mode==='product')await productReady();else await analysisReady();
 expect(screen.queryByText('确认本次使用的店铺')).not.toBeInTheDocument();expect(within(screen.getByRole('list',{name:'准备步骤'})).queryByText('确认店铺')).not.toBeInTheDocument();expect(screen.getByRole('button',{name:'上一步'})).toBeEnabled();expect(screen.getByText(mode==='product'?'第 1 / 2 步':'第 1 / 4 步')).toBeVisible();
});
it('keeps first-time source configuration available until it is confirmed',async()=>{
 state.scope.status='unconfirmed';mount('product');await screen.findByText('首次店铺配置');expect(screen.getByRole('button',{name:'下一步'})).toBeDisabled();expect(screen.queryByRole('button',{name:'上传核对并保存候选'})).not.toBeInTheDocument();await userEvent.click(screen.getByRole('button',{name:'确认店铺'}));await userEvent.click(screen.getByRole('button',{name:'下一步'}));await productReady();expect(screen.getByText('第 2 / 3 步')).toBeVisible();
});
it('does not infer a store after a failed source read and allows retry',async()=>{
 catalogState.scopeFails=true;mount('product');await screen.findByText('资料设置读取失败，请重新读取后继续。');expect(screen.queryByRole('button',{name:'上传核对并保存候选'})).not.toBeInTheDocument();catalogState.scopeFails=false;await userEvent.click(screen.getByRole('button',{name:'重新读取'}));await productReady();
});

it('blocks reuse while new report SKUs remain unmatched, and recovers after explicit approval',async()=>{
 catalogState.unmatched=18;mount('analysis');await analysisReady();await userEvent.click(screen.getByRole('button',{name:'直接修订已有目录'}));await screen.findByText('还有18个报表SKU待归属');expect(screen.getByRole('button',{name:'沿用当前已批准目录'})).toBeDisabled();expect(screen.queryByText('本次流程已完成')).not.toBeInTheDocument();
 await userEvent.click(screen.getByRole('button',{name:'生成审核候选'}));catalogState.unmatched=0;await userEvent.click(screen.getByRole('button',{name:'核对并批准目录'}));await waitFor(()=>expect(screen.getByRole('button',{name:'完成审核'})).toBeEnabled());await userEvent.click(screen.getByRole('button',{name:'完成审核'}));expect(await screen.findByText('本次流程已完成')).toBeVisible();
});
it('keeps completion blocked after a mapping read failure and supports retry',async()=>{
 catalogState.mappingFails=true;mount('analysis');await analysisReady();await userEvent.click(screen.getByRole('button',{name:'直接修订已有目录'}));await screen.findByText('商品归属检查失败，请重新检查后继续。');expect(screen.getByRole('button',{name:'沿用当前已批准目录'})).toBeDisabled();catalogState.mappingFails=false;await userEvent.click(screen.getByRole('button',{name:'重新检查商品归属'}));await waitFor(()=>expect(screen.getByRole('button',{name:'沿用当前已批准目录'})).toBeEnabled());await userEvent.click(screen.getByRole('button',{name:'沿用当前已批准目录'}));expect(await screen.findByText('本次流程已完成')).toBeVisible();
});

it('preserves report input when returning to shop settings and forward again',async()=>{
 mount('analysis');await analysisReady();
 await userEvent.type(screen.getByRole('textbox',{name:'报表上传测试'}),'待核报表');
 await userEvent.click(screen.getByRole('button',{name:'上一步'}));
 expect(await screen.findByText('确认本次使用的店铺')).toBeVisible();
 await userEvent.click(screen.getByRole('button',{name:'下一步'}));
 expect(await screen.findByRole('textbox',{name:'报表上传测试'})).toHaveValue('待核报表');
});

it('closes a completed saved product flow without another discard confirmation',async()=>{
 mount('product');await productReady();await userEvent.type(screen.getByRole('textbox',{name:'商品文件备注'}),'已保存的来源');
 await userEvent.click(screen.getByRole('button',{name:'上传核对并保存候选'}));await userEvent.click(screen.getByRole('button',{name:'核对并批准目录'}));await userEvent.click(screen.getByRole('button',{name:/^完成$/}));
 expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
});

it('resumes the requested source batch when returning to product intake', async () => {
 const router=createMemoryRouter([{path:'*',element:<CatalogGuidedFlow initialMode="product" autoOpen initialListing={42} entryMode="workspace"/>}],{initialEntries:['/catalog/maintenance?entry=product-intake&listing=42']});
 render(<RouterProvider router={router}/>);
 await productReady();
 expect(screen.getByText('恢复商品表 42')).toBeVisible();
 expect(screen.getAllByRole('dialog')).toHaveLength(1);
});
