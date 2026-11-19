import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { tableChanges, withoutTableBaseline, type TableBaseline } from "./tableImportDiff";
import { useTableBaseline } from "./useTableBaseline";
import { TableImportReview } from "./TableImportReview";
import { CountTable, CountTableImport } from "./CountTable";

const api=vi.hoisted(()=>({read:vi.fn(),write:vi.fn()}));
vi.mock("../../api/client",async original=>({...await original<typeof import("../../api/client")>(),requestApi:api.read,writeApi:api.write}));
afterEach(()=>{cleanup();api.read.mockReset();api.write.mockReset();});
const baseline:TableBaseline={id:`table-baseline-${"a".repeat(64)}`,kind:"count",filename:"fictional.xlsx",rows:[{key:"11:QUALIFIED",label:"SIM-M",row:8,values:{"状态":"合格","实盘总数":"2"}}]};
const wrapper=({children}:{children:React.ReactNode})=><MemoryRouter><AuthzGenerationProvider boundary={{principalId:1,siteId:1,roles:["admin"],siteConfigVersionId:1}} onRevoked={()=>undefined}>{children}</AuthzGenerationProvider></MemoryRouter>;
it("shows final net edits, removed and new rows; restored original values clear edits",()=>{
  expect(tableChanges(baseline.rows,baseline.rows)).toEqual([]);
  expect(tableChanges(baseline.rows,[{...baseline.rows[0]!,values:{"状态":"合格","实盘总数":"0"}}])).toEqual([expect.objectContaining({before:"2",after:"0",row:8})]);
  expect(tableChanges(baseline.rows,[{key:"12:PENDING",label:"SIM-L",values:{"状态":"待检","实盘总数":"3"}}]).map(change=>change.field)).toEqual(["移除明细","手工新增"]);
});
it("restores original values by opaque reference after reopening and preserves user notes",async()=>{
  api.read.mockResolvedValue(baseline);
  function Reopened(){const audit=useTableBaseline(`送货依据\n表格基准=${baseline.id}`,"count");return <>{audit.feedback}<button disabled={audit.blocked} onClick={()=>{const note=audit.withNote("保留依据");expect(withoutTableBaseline(note)).toBe("保留依据");expect(note).toContain(baseline.id);}}>保存</button><TableImportReview baseline={audit.baseline} rows={[{...baseline.rows[0]!,values:{"状态":"合格","实盘总数":"0"}}]}/></>;}
  render(<Reopened/>,{wrapper});
  await waitFor(()=>expect(screen.getByRole("button",{name:"保存"})).toBeEnabled());
  expect(screen.getByRole("table",{name:"原表与当前填写对照"})).toHaveTextContent("第8行");
  await userEvent.click(screen.getByRole("button",{name:"保存"}));
});
it("count grid preserves unknown balance and explicit zero, showing shortages in the difference cell",()=>{
  const {rerender}=render(<CountTable lines={[{sku_id:"11",quality:"QUALIFIED",units:"0",purpose:"COUNT"}]} skus={[]} balanceFor={()=>undefined} change={()=>undefined} add={()=>undefined} remove={()=>undefined} errorFor={()=>undefined}/>,{wrapper});
  expect(screen.getAllByText("待核")).toHaveLength(2);
  expect(screen.getByLabelText("盘点商品1实盘总数")).toHaveValue("0");
  rerender(<CountTable lines={[{sku_id:"11",quality:"QUALIFIED",units:"0",purpose:"COUNT"}]} skus={[]} balanceFor={()=>({qualified_units:"3"})} change={()=>undefined} add={()=>undefined} remove={()=>undefined} errorFor={()=>undefined}/>);
  expect(screen.getByText("-3")).toHaveAttribute("class",expect.stringContaining("danger"));
});
it("imports counts directly to the editable table and refuses partial imports",async()=>{
  const apply=vi.fn();api.write.mockResolvedValue({filename:"count.xlsx",rows:[{sku_id:"11",units:"0",quality:"QUALIFIED",purpose:"COUNT"}],issues:[],table_baseline:baseline});
  render(<CountTableImport warehouse="1" owner="7" locked={false} onBusy={()=>undefined} onApply={apply}/>,{wrapper});
  await userEvent.upload(screen.getByLabelText(/盘点XLSX文件/),new File(["fictional"],"count.xlsx"));
  expect(apply).toHaveBeenCalledWith(expect.objectContaining({rows:[expect.objectContaining({units:"0"})]}));
  api.write.mockResolvedValue({rows:[],issues:[{row:4,message:"数量不可为负"}]});
  await userEvent.upload(screen.getByLabelText(/盘点XLSX文件/),new File(["fictional2"],"count.xlsx"));
  expect(await screen.findByText("第4行 数量不可为负")).toBeInTheDocument();expect(apply).toHaveBeenCalledTimes(1);
});
