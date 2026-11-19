import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiRequestError } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { TransportPanel } from "./TransportPanel";
import { transportCsv, type TransportState } from "./transport";
const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const empty: TransportState = { registered: false, shipment_id: "7", shipment_revision: "3", shipment_status: "CONFIRMED", warehouse_id: "1", owner_id: "2", destination_id: "8", status: "UNREGISTERED", record: null, events: [], latest_event: null, destination_received_units: "98", shipment_units: "100", history: [] };
const event = { id: "12", transport_id: "10", revision: "2", event_kind: "SIGNED" as const, occurred_at: "2026-10-29T04:00:00Z", occurred_local: "2026-10-29T12:00", timezone: "Asia/Shanghai", location: "虚构站", description: "签收快照", source_reference: "虚构回单", signed_units: "100", created_at: "2026-10-29T04:10:00Z" };
const registered: TransportState = { ...empty, registered: true, source_revision_current: true, status: "SIGNED", record: { id: "10", revision: "4", shipment_id: "7", shipment_revision: "3", carrier: "虚构承运商", tracking_number: "000A", estimated_arrival: null, arrival_local: "", arrival_timezone: "", source_reference: "虚构委托单", source_snapshot: { sources: [{ id: "11", allocations: [{ id: "21", units: "60" }, { id: "22", units: "40" }] }] } }, events: [event], latest_event: event };
let state: TransportState;
const scroll = vi.fn();
function mount(canWrite = true, transportAnchor = false, onReceive?: (trigger: HTMLButtonElement) => void) { const router = createMemoryRouter([{ path: "*", element: <TransportPanel shipmentId="7" canWrite={canWrite} onReceive={onReceive} /> }], { initialEntries: [transportAnchor ? "/production/shipments/7#transport" : "/production/shipments/7"] }); return render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: [canWrite ? "data_manager" : "viewer"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><RouterProvider router={router} /></AuthzGenerationProvider>); }
beforeEach(() => { HTMLElement.prototype.scrollIntoView = scroll; scroll.mockReset(); state = structuredClone(empty); api.read.mockReset(); api.write.mockReset(); api.read.mockImplementation(() => Promise.resolve(state)); api.write.mockResolvedValue(registered); });
async function fillRegistration() { await userEvent.click(await screen.findByRole("button", { name: "登记运输资料" })); await userEvent.type(screen.getByRole("textbox", { name: "承运商" }), "测试承运商"); await userEvent.type(screen.getByRole("textbox", { name: "运单号" }), "000TEST"); await userEvent.type(screen.getByRole("textbox", { name: "来源依据（人工登记，请注明凭据）" }), "虚构来源"); }
it("keeps carrier cumulative signature separate from destination receipt for viewers", async () => { state = structuredClone(registered); mount(false); expect(await screen.findByText(/签收与实收相差 2 件/)).toBeVisible(); expect(within(screen.getByLabelText("本批收货进度")).getByText("98")).toBeVisible(); expect(screen.queryByRole("button", { name: "追加运输节点" })).not.toBeInTheDocument(); expect(screen.queryByRole("button", { name: "更正节点" })).not.toBeInTheDocument(); });
it("retains registration fields after a rejected save and sends the shipment scope", async () => { api.write.mockRejectedValueOnce(new ApiRequestError(422, "transport_time_invalid", "时区无效")); mount(); await fillRegistration(); fireEvent.change(screen.getByLabelText("预计到达时间"), { target: { value: "2026-10-30T10:00" } }); await userEvent.click(screen.getByRole("button", { name: "保存运输资料" })); expect(await screen.findByText("时区无效")).toBeVisible(); expect(screen.getByRole("textbox", { name: "运单号" })).toHaveValue("000TEST"); expect(api.write.mock.calls[0]?.[1]).toMatchObject({ body: { shipment_id: "7", expected_shipment_revision: "3", expected_warehouse_id: "1", expected_owner_id: "2", expected_destination_id: "8", expected_revision: "0", arrival_local: "2026-10-30T10:00" } }); });
it("locks unknown results and queries the original operation without writing a second event", async () => { api.write.mockRejectedValueOnce(new TypeError("response lost")); mount(); await fillRegistration(); await userEvent.click(screen.getByRole("button", { name: "保存运输资料" })); expect(await screen.findByText("保存结果待核实，已锁定当前输入")).toBeVisible(); expect(screen.getByRole("textbox", { name: "运单号" })).toBeDisabled(); const key = (api.write.mock.calls[0]?.[1] as { operationKey: string }).operationKey; state = structuredClone(registered); await userEvent.click(screen.getByRole("button", { name: "查询原操作结果" })); await waitFor(() => expect(screen.queryByRole("button", { name: "保存运输资料" })).not.toBeInTheDocument()); expect(api.read).toHaveBeenCalledWith(`/api/production/commands/${key}`); expect(api.write).toHaveBeenCalledTimes(1); });
it("corrects a node with both transport and event revisions", async () => { state = structuredClone(registered); mount(); await userEvent.click(await screen.findByText("物流节点与依据（1 条）")); await userEvent.click(screen.getByRole("button", { name: "更正节点" })); await userEvent.clear(screen.getByRole("textbox", { name: "承运商累计签收件数（未知可留空）" })); await userEvent.type(screen.getByRole("textbox", { name: "承运商累计签收件数（未知可留空）" }), "99"); await userEvent.type(screen.getByRole("textbox", { name: "更正原因" }), "回单复核"); await userEvent.click(screen.getByRole("button", { name: "保存运输节点" })); await waitFor(() => expect(api.write).toHaveBeenCalled()); expect(api.write.mock.calls[0]).toMatchObject(["/api/production/inventory/transport-events/12/correct", { body: { transport_id: "10", expected_transport_revision: "4", expected_revision: "2", signed_units: "99", reason: "回单复核" } }]); });
it("rereads a conflict without replacing the user's edited carrier", async () => { state = structuredClone(registered); api.write.mockRejectedValueOnce(new ApiRequestError(409, "transport_revision_conflict", "资料已变化")); mount(); await userEvent.click(await screen.findByRole("button", { name: "更多运输操作" })); await userEvent.click(screen.getByRole("menuitem", { name: "更正运输资料" })); const carrier = screen.getByRole("textbox", { name: "承运商" }); await userEvent.clear(carrier); await userEvent.type(carrier, "保留的新承运商"); await userEvent.type(screen.getByRole("textbox", { name: "更正原因" }), "人工核对"); await userEvent.click(screen.getByRole("button", { name: "保存运输资料" })); await screen.findByText("资料已变化"); state = { ...registered, record: { ...registered.record!, revision: "5" } }; await userEvent.click(screen.getByRole("button", { name: "读取当前修订，保留输入" })); expect(carrier).toHaveValue("保留的新承运商"); await userEvent.click(screen.getByRole("button", { name: "保存运输资料" })); await waitFor(() => expect(api.write).toHaveBeenCalledTimes(2)); expect(api.write.mock.calls[1]?.[1]).toMatchObject({ body: { expected_revision: "5", carrier: "保留的新承运商" } }); });
it("exports consistent columns, original linkage, timezone and safe spreadsheet text", () => { const value = { ...registered, events: [{ ...event, source_reference: '=SUM(A1)' }] }; const csv = transportCsv(value); expect(csv).toContain('"000A"'); expect(csv).toContain('"Asia/Shanghai"'); expect(csv).toContain("'=SUM(A1)"); expect(csv).toContain('""allocations""'); expect(transportCsv({ ...registered, events: [{ ...event, event_kind: "IN_TRANSIT", signed_units: null }] })).toContain('"不适用"'); const noEvents = transportCsv({ ...registered, events: [] }); expect(noEvents).toContain('"未登记运输节点"'); expect(noEvents.split("\r\n")).toHaveLength(2); });

it("positions an asynchronous transport anchor once and does not jump again on refresh", async () => {
  state = structuredClone(registered); mount(false, true);
  expect(scroll).not.toHaveBeenCalled();
  await screen.findByText(/虚构承运商 · 000A/);
  await waitFor(() => expect(scroll).toHaveBeenCalledTimes(1));
  await userEvent.click(screen.getByRole("button", { name: "更多运输操作" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "刷新运输资料" }));
  await waitFor(() => expect(api.read).toHaveBeenCalledTimes(2));
  expect(scroll).toHaveBeenCalledTimes(1);
});


it("offers one receipt entry next to quantities and prevents leaving an edited transport", async () => {
  state = structuredClone(registered);
  const receive = vi.fn();
  mount(true, false, receive);
  const trigger = await screen.findByRole("button", { name: "核对本批到仓入库" });
  expect(screen.getByRole("progressbar", { name: "本批入库完成度" })).toHaveAttribute("value", "98");
  await userEvent.click(trigger);
  expect(receive).toHaveBeenCalledWith(trigger);
  expect(screen.getByRole("table", { name: "物流节点" })).not.toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "追加运输节点" }));
  await userEvent.type(screen.getByRole("textbox", { name: "发生地点" }), "测试地点");
  expect(trigger).toBeDisabled();
  expect(api.write).not.toHaveBeenCalled();
});

it("changes the receipt action to history once the batch is received", async () => {
  state = { ...structuredClone(registered), destination_received_units: "100" };
  mount(true, false, vi.fn());
  expect(await screen.findByRole("button", { name: "查看本批接收记录" })).toBeEnabled();
  expect(screen.getByText("目的仓已收齐")).toBeVisible();
  expect(screen.queryByRole("button", { name: "核对本批到仓入库" })).not.toBeInTheDocument();
});
