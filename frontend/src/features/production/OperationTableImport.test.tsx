import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { OperationTableImport, type OperationImportPreview } from "./OperationTableImport";
import type { Document } from "./types";

const write = vi.hoisted(() => vi.fn());
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), writeApi: write }));
const order = { id: "10", revision: "2", lines:[{id:"101",sku_id:"1001"}] } as Document;
const valid: OperationImportPreview = { kind: "receipt", filename: "qa.xlsx", source_digest: "qa", order_id: "10", order_revision: "2", total_units: "4", box_count: 0, cartons: [], issues: [], rows: [{ row: 2, sku_id: "1001", order_line_id: "101", sku_label: "QA-M", qualified_units: "4" }] };
afterEach(() => { cleanup(); write.mockReset(); });

it.each(["business","reading"])("uses the shared grid only when the import has no reading errors (%s)", async stage => {
 const apply = vi.fn();
 write.mockResolvedValue({...valid,kind:"packing",warehouse_id:"1",owner_id:"7",rows:[],issues:[{row:2,message:"待核",stage}],source_rows:[{row:2,sku_code:"RAW-A",units:stage==="reading"?null:"5",source_cell:"D2"}]});
 render(<OperationTableImport inline kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={[]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),new File(["fixture"],"source.xlsx"));
 if(stage==="business") expect(apply).toHaveBeenCalledOnce();
 else {expect(await screen.findByText("请修正原表后重新导入")).toBeVisible();expect(apply).not.toHaveBeenCalled();}
});
function mount() {
  const apply = vi.fn(); const busy = vi.fn();
  const view = (context: string) => <OperationTableImport kind="receipt" order={order} context={context} eligible={["1001"]} locked={false} onBusy={busy} onApply={apply} />;
  const rendered = render(view("warehouse-1"), { wrapper: ({ children }) => <MemoryRouter><AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}>{children}</AuthzGenerationProvider></MemoryRouter> });
  return { apply, busy, changeScope: () => rendered.rerender(view("warehouse-2")) };
}
async function upload() {
  await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/), new File(["fictional"], "qa.xlsx"));
  await userEvent.click(screen.getByRole("button", { name: "读取并填入下方表格" }));
}
it("keeps row errors visible and never applies a partial import", async () => {
  write.mockResolvedValue({ ...valid, issues: [{ row: 3, message: "商品规格不属于当前订单" }] });
  const form = mount(); await upload();
  expect(await screen.findByText("第3行：商品规格不属于当前订单")).toBeInTheDocument();
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(form.apply).not.toHaveBeenCalled();
});
it("fills a valid preview once without a separate read-only table or apply step", async () => {
  write.mockResolvedValue(valid);
  const form = mount(); await upload();
  expect(form.apply).toHaveBeenCalledExactlyOnceWith(valid);
  expect(screen.queryByRole("table")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "应用表格到当前表单" })).not.toBeInTheDocument();
});
it("rejects a preview belonging to another order", async () => {
  write.mockResolvedValue({ ...valid, order_id: "11" });
  const form = mount(); await upload();
  expect(await screen.findByText(/预览来源或可操作商品范围已改变/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "应用表格到当前表单" })).not.toBeInTheDocument();
  expect(form.apply).not.toHaveBeenCalled();
});
it("does not expose a late preview after the operation scope changes", async () => {
  let resolve!: (value: OperationImportPreview) => void;
  const pending = new Promise<OperationImportPreview>(yes => { resolve = yes; });
  write.mockReturnValue(pending);
  const form = mount(); await upload(); form.changeScope();
  await act(async () => { resolve(valid); await pending; });
  expect(screen.queryByRole("button", { name: "应用表格到当前表单" })).not.toBeInTheDocument();
  expect(form.busy).toHaveBeenLastCalledWith(false);
  expect(form.apply).not.toHaveBeenCalled();
});

it("imports warehouse quantities and boxes without any production order",async()=>{
 const apply=vi.fn();const preview={...valid,kind:"packing",warehouse_id:"1",owner_id:"7",order_id:"",order_revision:"",source_id:"upload-shipments-abc",rows:[{row:2,sku_id:"1001",order_line_id:"",units:"2"}],cartons:[{number:"C1",items:[{sku_id:"1001",units:"2"}]}]};write.mockResolvedValue(preview);
 render(<OperationTableImport kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});await upload();expect(apply).toHaveBeenCalledExactlyOnceWith(preview);expect(write.mock.calls[0]?.[0]).toContain("/shipments/table/preview?warehouse_id=1&owner_id=7");
});
it("keeps form unchanged when a preview belongs to a different warehouse owner",async()=>{
 const apply=vi.fn();write.mockResolvedValue({...valid,kind:"packing",warehouse_id:"1",owner_id:"8"});render(<OperationTableImport kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});await upload();expect(await screen.findByText(/预览来源或可操作商品范围已改变/)).toBeVisible();expect(apply).not.toHaveBeenCalled();
});

it("explicitly selects original packing totals without changing the standard template link",async()=>{
 const apply=vi.fn();const preview={...valid,kind:"packing",warehouse_id:"1",owner_id:"7",order_id:"",order_revision:"",rows:[{row:2,sku_id:"1001",order_line_id:"",units:"4"}],cartons:[],box_count:0};write.mockResolvedValue(preview);
 render(<OperationTableImport kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.selectOptions(screen.getByLabelText("表格格式"),"packing_totals");expect(screen.getByText(/第一列作为SKU/)).toBeVisible();await upload();expect(write.mock.calls[0]?.[0]).toContain("layout=packing_totals");expect(screen.getByRole("link",{name:"下载出货模板"})).toHaveAttribute("href","/api/production/shipments/table/template?warehouse_id=1&owner_id=7");expect(apply).toHaveBeenCalledExactlyOnceWith(preview);
});

it("shows original row counts and located SKU issues without applying partial quantities",async()=>{
 const apply=vi.fn();write.mockResolvedValue({...valid,kind:"packing",warehouse_id:"1",owner_id:"7",order_id:"",order_revision:"",rows:[],source_row_count:10,source_total_units:"47",issues:[{row:2,sheet:"Sheet1",cell:"A2",message:"SKU UNKNOWN 未在当前仓库建账"}]});
 render(<OperationTableImport kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.selectOptions(screen.getByLabelText("表格格式"),"packing_totals");await upload();expect(await screen.findByText(/原单已读取10个规格，共47件/)).toBeVisible();expect(screen.getByText(/Sheet1 第2行（A2）/)).toBeVisible();expect(apply).not.toHaveBeenCalled();
});

it.each([false, true])("shows original SKU quantities before registration and distinguishes reading errors (%s)", async readingError => {
 const apply = vi.fn();
 write.mockResolvedValue({ ...valid, kind:"packing", warehouse_id:"1", owner_id:"7", rows:[],
  source_row_count:1, source_total_units:readingError ? null : "5",
  source_rows:[{row:2,sku_code:"UNKNOWN-Blue-M",units:readingError ? null : "5",source_cell:"D2"}],
  issues:[{row:2,sheet:"Sheet1",cell:"A2",message:"SKU未建账",stage:"business"},
   ...(readingError ? [{row:2,sheet:"Sheet1",cell:"D2",message:"数量须为正整数",stage:"reading"}] : [])],
 });
 render(<OperationTableImport kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={[]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.selectOptions(screen.getByLabelText("表格格式"),"packing_totals");
 await upload();
 const table = await screen.findByRole("table",{name:"原单商品明细"});
 expect(within(table).getByText("UNKNOWN-Blue-M")).toBeVisible();
 expect(within(table).getByText(readingError ? "待核" : "5")).toBeVisible();
 expect(screen.getByText(readingError ? "原单有内容待核对" : "原单读取完成")).toBeVisible();
 expect(screen.getByText(/后续出货校验/).closest("details")).not.toHaveAttribute("open");
 expect(screen.getByText(/SKU未建账/)).not.toBeVisible();
 expect(apply).not.toHaveBeenCalled();
 await userEvent.click(screen.getByRole("button",{name:"重新选择文件"}));
 expect(screen.queryByRole("table",{name:"原单商品明细"})).not.toBeInTheDocument();
 expect(screen.getByLabelText("表格格式")).toHaveValue("packing_totals");
 expect(screen.getByRole("button",{name:"读取并填入下方表格"})).toBeDisabled();
});


it("imports multiple packing lists together and applies only the combined preview", async () => {
 const apply=vi.fn();
 const first={...valid,kind:"packing",warehouse_id:"1",owner_id:"7",source_id:"upload-shipments-"+"a".repeat(64),filename:"first.xlsx",rows:[],source_rows:[{row:2,sku_code:"A",sku_id:"1001",units:"2",source_cell:"B2"}]};
 const second={...first,source_id:"upload-shipments-"+"b".repeat(64),filename:"second.xlsx"};
 const combined={...first,filename:"2份装箱单",source_files:[first,second],source_total_units:"4",source_rows:[...first.source_rows,{...second.source_rows[0],row:3}]};
 write.mockResolvedValueOnce(first).mockResolvedValueOnce(second).mockResolvedValueOnce(combined);
 render(<OperationTableImport inline kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),[new File(["a"],"first.xlsx"),new File(["b"],"second.xlsx")]);
 expect(write).toHaveBeenCalledTimes(3);
 expect(write.mock.calls[2]?.[0]).toBe("/api/production/shipments/table/combine");
 expect(apply).toHaveBeenCalledExactlyOnceWith(combined);
});

it("retains the current goods table when one of several packing files fails",async()=>{
 const apply=vi.fn();
 write.mockResolvedValueOnce({...valid,kind:"packing",warehouse_id:"1",owner_id:"7"}).mockRejectedValueOnce(new Error("second.xlsx 读取失败"));
 render(<OperationTableImport inline kind="packing" warehouse={{warehouse_id:"1",owner_id:"7"}} context="1:7" eligible={["1001"]} locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper:({children})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,roles:["admin"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>});
 await userEvent.upload(screen.getByLabelText(/本次导入的XLSX文件/),[new File(["a"],"first.xlsx"),new File(["b"],"second.xlsx")]);
 expect(await screen.findByText("second.xlsx 读取失败")).toBeVisible();
 expect(apply).not.toHaveBeenCalled();
});
