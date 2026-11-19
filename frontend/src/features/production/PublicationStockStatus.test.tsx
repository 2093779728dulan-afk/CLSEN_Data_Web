import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { PublicationStockStatus } from "./PublicationStockStatus";
import { ShipmentDateNotice } from "./ShipmentDateNotice";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const pending = {scope_id:"1", warehouse_id:"3", owner_id:"9", warehouse_name:"美国FBA", status:"pending", issues:[{label:"可售数量不足"}], can_retry:true};
function mount(element: React.ReactNode) {
  return render(<AuthzGenerationProvider boundary={{principalId:1,roles:["data_manager"],siteId:7,siteConfigVersionId:1}} onRevoked={()=>undefined}><MemoryRouter initialEntries={["/review/2026-10-30"]}>{element}</MemoryRouter></AuthzGenerationProvider>);
}
beforeEach(() => { api.read.mockReset(); api.write.mockReset(); });
it("shows the actual published inventory status and retries without publishing again", async () => {
  let updated = false;
  api.read.mockImplementation(() => Promise.resolve({items:[{...pending,status:updated?"updated":"pending"}]}));
  api.write.mockImplementation(() => {updated=true;return Promise.resolve({updated:{},issues:[]});});
  mount(<PublicationStockStatus reportDate="2026-10-30" reportType="business_report" revision={1} canWrite />);
  expect(await screen.findByText("日报已发布 · 美国FBA待更新")).toBeVisible();
  await userEvent.click(screen.getByText("查看原因"));
  expect(screen.getByText("可售数量不足")).toBeVisible();
  expect(screen.getByRole("link",{name:"前往库存处理"})).toHaveAttribute("href","/production/warehouses/3?owner=9&fba_view=balance");
  await userEvent.click(screen.getByRole("button",{name:"重试库存更新"}));
  expect(await screen.findByText("日报已发布 · 库存已更新")).toBeVisible();
  expect(api.write).toHaveBeenCalledTimes(1);
  expect(api.write.mock.calls[0]?.[0]).toBe("/api/production/fba/daily/sync?scope_id=1");
});
it.each([false,true])("keeps ambiguous warehouse assignment out of automatic retry for manager %s", async canWrite => {
  api.read.mockResolvedValue({items:[{...pending,can_retry:false}]});
  mount(<PublicationStockStatus reportDate="2026-10-30" reportType="return_report" revision={2} canWrite={canWrite} />);
  await screen.findByText("日报已发布 · 美国FBA待更新");
  expect(screen.queryByRole("button",{name:"重试库存更新"})).not.toBeInTheDocument();
  expect(api.write).not.toHaveBeenCalled();
});
it("preserves an unread inventory result as a retryable read error", async () => {
  api.read.mockRejectedValueOnce(new Error("读取超时")).mockResolvedValue({items:[]});
  mount(<PublicationStockStatus reportDate="2026-10-30" reportType="business_report" revision={1} canWrite />);
  expect(await screen.findByText("库存更新结果暂未读取")).toBeVisible();
  expect(screen.queryByText("日报已发布 · 库存已更新")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button",{name:"重新读取"}));
  await waitFor(()=>expect(screen.queryByText("库存更新结果暂未读取")).not.toBeInTheDocument());
  expect(api.write).not.toHaveBeenCalled();
});
it("warns on the earliest imported receipt date and links the original shipment editor", () => {
  mount(<ShipmentDateNotice shipmentId="4" dispatchedOn="2026-11-09" receivedOn={["2026-11-10","2026-10-28"]} canWrite />);
  expect(screen.getByText("收货日期早于发货日期")).toBeVisible();
  expect(screen.getByText(/发货 2026-11-09 · 收货 2026-10-28/)).toBeVisible();
  expect(screen.getByRole("link",{name:"更正出货日期"})).toHaveAttribute("href",expect.stringContaining("/production/shipments/4/edit?return_to="));
  expect(api.write).not.toHaveBeenCalled();
});

it.each(["2026-11-09",null])("keeps a valid or unknown source date %s out of conflict warnings", date => {
  mount(<ShipmentDateNotice shipmentId="4" dispatchedOn={date} receivedOn={["2026-11-09",null]} canWrite />);
  expect(screen.queryByText("收货日期早于发货日期")).not.toBeInTheDocument();
});
