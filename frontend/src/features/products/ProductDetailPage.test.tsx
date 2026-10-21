import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { StyleCardResponse } from "./productAnalyticsTypes";

const loadStyleCard=vi.fn();vi.mock("./productAnalyticsApi",()=>({loadStyleCard:(...args:unknown[]):Promise<StyleCardResponse>=>loadStyleCard(...args) as Promise<StyleCardResponse>}));vi.mock("../../app/AuthzGenerationContext",()=>({useAuthzGeneration:()=>({generation:0})}));
import { ProductDetailPage } from "./ProductDetailPage";
const m={denominator:null,expected_days:31,is_partial:false,null_reason:null,numerator:null,observed_days:31,source_completeness:"complete",value:1,value_state:"observed"};
const response={available_series:[{active:true,dimension:"color",key:"red-key",label:"红色",sort_order:0,total:m}],effective_return_basis:"event_date",permissions:{},provenance:{catalog_version:8,consistent_as_of:"2026-08-24T10:00:00Z",fact_basis:"current"},series:[{key:"red-key",points:[{date:"2026-08-24",denominator:null,null_reason:null,numerator:null,source_completeness:"complete",value:1,value_state:"observed"}]}],source_report_coverage:{contributing_report_date_from:"2026-08-24",contributing_report_date_to:"2026-08-24"},style:{color_count:1,size_count:1,sku_count:1,standard_name:"标准夹克",status:"enabled",style_code:"J-1",style_id:"88"},style_reconciliation:{metric_status:{conversion:"evaluable",returns:"evaluable",sales:"evaluable",sessions:"evaluable",units:"evaluable"}},summary:{metrics:{units:m,sales:{...m,value:"10.00"},returns:m,sessions:m,conversion:{...m,value:"1.000000"}}},trend_effective_return_basis:null,variants:[{internal_display_sku:"SKU-DISPLAY-1",metrics:{units:m,sales:{...m,value:"10.00"},returns:m,sessions:m,conversion:{...m,value:"1.000000"}},seller_sku_aliases:[{is_truncated:false,is_unsafe:true,preview:"<unsafe>",sha256:"sha256:1234567890abcdef",source_ref_id:"ref-1"}],sku_id:"sku-1",standard_color:"红色",standard_size:"M",status:"enabled"}]} as unknown as StyleCardResponse;
describe("ProductDetailPage",()=>{beforeEach(()=>loadStyleCard.mockReset().mockResolvedValue(response));it("renders standard identity, same-response chart/matrix and actual variants",async()=>{render(<MemoryRouter initialEntries={["/products/88"]}><Routes><Route element={<ProductDetailPage today="2026-08-24"/>} path="/products/:style_id"/></Routes></MemoryRouter>);expect(await screen.findByRole("heading",{level:1,name:"标准夹克"})).toBeVisible();expect(screen.getByRole("img",{name:/产品每日趋势/})).toBeVisible();expect(screen.getByText("SKU-DISPLAY-1")).toBeVisible();fireEvent.click(screen.getByText("1 个来源别名"));expect(screen.getByText("[含危险字符的来源]")).toBeVisible();expect(loadStyleCard).toHaveBeenCalledWith("88",expect.objectContaining({dimension:"color",metric:"units"}),expect.any(AbortSignal));});});

function ReturnDestination() {
  const location = useLocation();
  return <output>{JSON.stringify({search:location.search,state:location.state as unknown})}</output>;
}
it("keeps the chart mounted with its original metric while new results load", async () => {
  loadStyleCard.mockResolvedValue(response);
  render(<MemoryRouter initialEntries={["/products/88"]}><Routes><Route path="/products/:style_id" element={<ProductDetailPage today="2026-08-24"/>}/></Routes></MemoryRouter>);
  const chart=await screen.findByRole("img",{name:/产品每日趋势/});
  let finish!:(value:StyleCardResponse)=>void;
  loadStyleCard.mockImplementation(()=>new Promise<StyleCardResponse>(resolve=>{finish=resolve;}));
  fireEvent.click(screen.getByRole("radio",{name:"销售额"}));
  expect(screen.getByRole("img",{name:/产品每日趋势/})).toBe(chart);
  expect(screen.getByText(/下方暂为上次结果/)).toBeVisible();
  expect(screen.queryByLabelText("正在读取产品详情")).not.toBeInTheDocument();
  await waitFor(()=>expect(finish).toBeDefined());
  finish({...response,series:response.series.map(item=>({...item,points:item.points.map(point=>({...point,value:"10.00"}))}))});
  await waitFor(()=>expect(screen.queryByText(/下方暂为上次结果/)).not.toBeInTheDocument());
  expect(screen.getByRole("img",{name:/产品每日趋势/})).toBe(chart);
});
it("loads version-bound colors for a direct size link and clears series when color changes", async () => {
  const colors=[...response.available_series,{...response.available_series[0],key:"blue-key",label:"蓝色"}];
  loadStyleCard.mockImplementation((_id:string,query:{dimension:string})=>Promise.resolve(query.dimension==="color"
    ? {...response,available_series:colors}
    : {...response,available_series:[{...response.available_series[0],dimension:"size",key:"size-m",label:"M"}]}));
  render(<MemoryRouter initialEntries={["/products/88?from=2026-08-01&to=2026-08-24&dimension=size&color_key=red-key"]}><Routes><Route path="/products/:style_id" element={<ProductDetailPage today="2026-08-24"/>}/></Routes></MemoryRouter>);
  await screen.findByRole("radio",{name:"蓝色"});
  expect(screen.getByRole("radio",{name:"红色"})).toBeChecked();
  expect(loadStyleCard).toHaveBeenCalledWith("88",expect.objectContaining({dimension:"color",color_key:null,catalog_version:"8",series:[]}),expect.any(AbortSignal));
  fireEvent.click(screen.getByRole("radio",{name:"蓝色"}));
  await waitFor(()=>expect(loadStyleCard).toHaveBeenCalledWith("88",expect.objectContaining({dimension:"size",color_key:"blue-key",series:[]}),expect.any(AbortSignal)));
});
it("preserves ledger filters and focus after detail normalization and metric changes", async () => {
  loadStyleCard.mockResolvedValue(response);
  render(<MemoryRouter initialEntries={[{pathname:"/products/88",state:{focusId:"style-88",ledgerUrl:"?search=J-1&from=2026-08-01&to=2026-08-24"}}]}><Routes><Route path="/products/:style_id" element={<ProductDetailPage today="2026-08-24"/>}/><Route path="/products" element={<ReturnDestination/>}/></Routes></MemoryRouter>);
  await screen.findByRole("heading",{name:"标准夹克",level:1});
  loadStyleCard.mockResolvedValue({...response,series:response.series.map(series=>({...series,points:series.points.map(point=>({...point,value:"10.00"}))}))});
  fireEvent.click(screen.getByRole("radio",{name:"销售额"}));
  await waitFor(()=>expect(loadStyleCard).toHaveBeenLastCalledWith("88",expect.objectContaining({metric:"sales"}),expect.any(AbortSignal)));
  fireEvent.click(screen.getByRole("link",{name:"产品总表"}));
  expect(screen.getByRole("status")).toHaveTextContent(JSON.stringify({search:"?search=J-1&from=2026-08-01&to=2026-08-24",state:{restoreFocus:"style-88"}}));
});
