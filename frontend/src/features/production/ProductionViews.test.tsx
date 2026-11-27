import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { DocumentContent, DocumentTable, ProductionProductTable, RevisionHistory, SummaryContent } from "./ProductionViews";
import type { Document, Sku, Summary } from "./types";

const order: Document = {
  id: "23", system_number: "PO-DEMO-23", business_number: "虚构订单23", business_date: "2026-10-14",
  notes: "", status: "CONFIRMED", revision: "2", expected_units: "7", actual_units: "0", difference_units: "7", pending_units: "7",
  lines: [{ id: "1", sku_id: "1003", sku_label: "RED-M", expected_units: "7", actual_units: "0", difference_units: "7", pending_units: "7" }],
};
const shipment: Document = {
  id: "34", system_number: "SH-DEMO-34", business_number: "虚构出货34", business_date: "2026-10-14",
  notes: "", status: "CONFIRMED", revision: "2", actual_units: "3", stock_tracked: true, warehouse_id: "900", dispatch_purpose: "OUTWARD_ORDER",
  sources: [{ id: "1", sku_id: "1003", sku_label: "RED-M", actual_units: "3", allocations: [] }],
};

function show(kind: "orders" | "shipments", document: Document) {
  render(<AuthzGenerationProvider boundary={{principalId:1,roles:["viewer"],siteId:1,siteConfigVersionId:1}} onRevoked={()=>undefined}><MemoryRouter><DocumentContent kind={kind} document={document} /></MemoryRouter></AuthzGenerationProvider>);
}

describe("document status explanations", () => {
  it("shows saved destination and carton contents while keeping a draft separate from actual dispatch", () => {
    show("shipments", { ...shipment, status: "DRAFT", destination: "虚构海外仓", cartons: [{ number: "QA-BOX", items: [{ sku_id: "1003", units: "3" }] }] });
    expect(screen.getByText("虚构海外仓")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "本批装箱明细" })).toHaveTextContent("QA-BOXRED-M3");
    expect(screen.getByText("装箱草稿尚未扣库存或计入订单已发。")).toBeInTheDocument();
    expect(screen.queryByText("订单对外发运（已交接）", { exact: true })).not.toBeInTheDocument();
  });
  it("shows cumulative production history as readable before and after values", async () => {
    render(<RevisionHistory history={[{ revision: "2", actor_id: "1", actor_name: "QA operator", reason: "fictional factory update", created_at: "2026-10-23T00:00:00Z", operation_kind: "PRODUCTION_PROGRESS", before_value: { lines: [{ sku_label: "QA Blue M", produced_units: null }] }, after_value: { lines: [{ sku_label: "QA Blue M", produced_units: "80" }] } }]} />);
    await userEvent.click(screen.getByText(/修订2 · 更新生产进度/));
    expect(screen.getByRole("cell", { name: "QA Blue M · 累计实际生产" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "未提供" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "80" })).toBeInTheDocument();
  });
  it("shows received quantities and receipt links separately from shipped quantities", () => {
    show("orders", { ...order, received_units: "3", lines: [{ ...order.lines![0]!, received_units: "3" }], receipts: [{ document_id: "81", line_number: "1", order_line_id: "1", sku_id: "1003", units: "3", quality: "PENDING", business_date: "2026-10-19", status: "POSTED", warehouse_id: "1" }, { document_id: "82", line_number: "1", order_line_id: "1", sku_id: "1003", units: "2", quality: "QUALIFIED", business_date: "2026-10-19", status: "REVERSED", warehouse_id: "1" }] });
    expect(screen.getByRole("heading", { name: "生产实收入库" })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "SKU累计实收" })).toHaveTextContent("3");
    expect(screen.getByRole("table", { name: "SKU预计与出货" })).toHaveTextContent("RED-M707");
    expect(screen.getByRole("link", { name: "库存单81 · 明细1" })).toHaveAttribute("href", "/production/stock/movements/81");
    expect(screen.getByText("已冲销 · 不计入累计实收")).toBeInTheDocument();
  });
  it("keeps confirmed order follow-up but removes current tasks from a void order", () => {
    show("orders", order);
    expect(screen.getByText("当前待跟进（全部累计）")).toBeInTheDocument();
    show("orders", { ...order, status: "VOID", revision: "3" });
    const tables = screen.getAllByRole("table", { name: "SKU预计与出货" });
    expect(within(tables[1]!).getByText("不适用（已作废）")).toBeInTheDocument();
    expect(screen.getByText(/下方数量保留供历史核对/)).toBeInTheDocument();
    expect(screen.getAllByText("当前待跟进（全部累计）")).toHaveLength(1);
  });

  it("distinguishes current stock deduction, void reversal and stockless history", () => {
    show("shipments", shipment);
    expect(screen.getByText("仓库出货明细已联动库存 · 仓库900")).toBeInTheDocument();
    show("shipments", { ...shipment, status: "VOID", revision: "3" });
    expect(screen.getByText("原仓库出货影响已撤销 · 仓库900")).toBeInTheDocument();
    expect(screen.getByText("原登记出货数量（已作废）")).toBeInTheDocument();
    show("shipments", { ...shipment, status: "VOID", stock_tracked: false });
    expect(screen.getByText("原单据已作废，不影响当前库存")).toBeInTheDocument();
  });

  it("explains a production-direct source separately from warehouse stock", () => {
    show("shipments", { ...shipment, stock_tracked: false, warehouse_id: null, sources: [{ ...shipment.sources![0]!, fulfillment_mode: "PRODUCTION_DIRECT", actual_units: "30" }], actual_units: "30" });
    expect(screen.getByText("全部明细为生产直发，不进入或扣减仓库库存")).toBeInTheDocument();
    expect(screen.getByText("生产完成后直接出货：计入订单实际已发，不影响仓库库存。")).toBeInTheDocument();
  });
});


describe("readable production identities and quantities", () => {
  it("keeps the literal product label and system identity available without repeating the variant in the preview", async () => {
    const user = userEvent.setup();
    const sku: Sku = { sku_id: "9001", style_id: "71", code: "Seller · literal-001", label: "QA-1101 · Seller · literal-001 · Olive / M", standard_color: "Olive", standard_size: "M", status: "active", catalog_version: "28:31" };
    render(<MemoryRouter><ProductionProductTable items={[sku, { ...sku, sku_id: "9002", code: null, label: "QA-1102 · 正式SKU待补 · Navy / L", status: "disabled" }]} /></MemoryRouter>);
    const table = screen.getByRole("table", { name: "款式、颜色、尺码与SKU" });
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["商品与规格", "状态", "查看业务"]);
    const row = within(table).getAllByRole("row")[1]!;
    const title = within(row).getByText(sku.code!);
    expect(title.closest("summary")?.firstElementChild?.textContent).toBe(sku.code);
    expect(within(row).getByText(sku.label, { exact: true })).not.toBeVisible();
    await user.click(title);
    expect(within(row).getByText(sku.label, { exact: true })).toBeVisible();
    expect(within(row).getByText("9001", { exact: true })).toBeVisible();
    expect(within(row).getByText("28:31", { exact: true })).toBeVisible();
    expect(within(row).getByRole("link", { name: "订单" })).toHaveAttribute("href", "/production/orders?sku=9001");
    expect(within(row).getByRole("link", { name: "出货" })).toHaveAttribute("href", "/production/shipments?sku=9001");
    expect(within(row).getByRole("link", { name: "库存" })).toHaveAttribute("href", "/production/stock");
    const pending = within(table).getAllByRole("row")[2]!;
    expect(within(pending).getByText("已停用", { exact: true })).toBeVisible();
    expect(within(pending).getByText("正式SKU待补", { exact: true })).toBeVisible();
    expect(within(pending).getByRole("link", { name: "订单" })).toHaveAttribute("href", "/production/orders?sku=9002");
  });

  it("shortens the summary order reference while preserving its full number, stable link and period quantity basis", async () => {
    const user = userEvent.setup();
    const number = "PO-d50e0336-5db4-4230-a615-b7107c5c3aaf";
    const summary: Summary = {
      expected_units: "10", actual_units: "1", difference_units: "9", pending_units: "8", closed_units: "0", overage_units: "0", cumulative_actual_units: "2", cumulative_difference_units: "8", shipment_period_filtered: true,
      items: [{ id: "line-51", order_id: "37", order_number: number, sku_id: "9001", sku_label: "QA-1101 · Seller-Code · Olive / M", expected_units: "10", actual_units: "1", difference_units: "9", pending_units: "8" }],
      skus: [{ sku_id: "9001", sku_label: "QA-1101 · Seller-Code · Olive / M", expected_units: "10", actual_units: "1", difference_units: "9" }],
    };
    render(<MemoryRouter><SummaryContent summary={summary} /></MemoryRouter>);
    const table = screen.getByRole("table", { name: "订单与SKU明细" });
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByRole("link", { name: "订单 7c5c3aaf" })).toHaveAttribute("href", "/production/orders/37");
    expect(within(row).getByText(number)).not.toBeVisible();
    await user.click(within(row).getByText("查看完整系统编号"));
    expect(within(row).getByText(number)).toBeVisible();
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["订单 / 商品", "预计", "本期间出货", "期间差额", "待跟进"]);
    expect(within(row).getAllByRole("cell").slice(1).map(cell => cell.textContent)).toEqual(["10", "1", "9", "8"]);
    expect(screen.getAllByText(/期间差额＝预计－本期间出货，不是剩余需求/)).toHaveLength(2);
    const mobile = screen.getByLabelText("订单与SKU明细", { selector: "section" });
    expect(within(mobile).getByText("待跟进（全部累计）")).toBeInTheDocument();
    expect(within(mobile).getByText("订单 7c5c3aaf", { exact: true })).toHaveAttribute("href", "/production/orders/37");
  });

  it("keeps empty product and quantity lists understandable", () => {
    render(<MemoryRouter><ProductionProductTable items={[]} /><SummaryContent summary={{ expected_units: "0", actual_units: "0", difference_units: "0", shipment_period_filtered: false, items: [], skus: [] }} /></MemoryRouter>);
    expect(within(screen.getByRole("table", { name: "款式、颜色、尺码与SKU" })).getByText(/商品主档尚未初始化/)).toBeVisible();
    expect(within(screen.getByRole("table", { name: "订单与SKU明细" })).getByText("当前条件下没有已确认订单。")).toBeVisible();
    expect(within(screen.getByRole("table", { name: "SKU合计" })).getByText("当前条件下没有SKU汇总。")).toBeVisible();
  });
});


describe("order and shipment reading layouts", () => {
  it("groups order metadata and follow-up without changing quantities or the detail link", async () => {
    const user = userEvent.setup();
    render(<MemoryRouter><DocumentTable kind="orders" items={[order, { ...order, id: "24", business_number: "虚构作废订单", status: "VOID" }]} /></MemoryRouter>);
    const table = screen.getByRole("table", { name: "订单记录" });
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["单据信息", "状态与跟进", "预计", "累计已发", "差额"]);
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByRole("link", { name: "虚构订单23" })).toHaveAttribute("href", "/production/orders/23");
    expect(within(row).getByText("修订 2")).toBeVisible();
    expect(within(row).getByText("已确认")).toBeVisible();
    expect(within(row).getByText("跟进中 · 待跟进 7件")).toBeVisible();
    expect(within(row).getAllByRole("cell").slice(2).map(cell => cell.textContent)).toEqual(["7", "0", "7"]);
    await user.click(within(row).getByText("查看完整系统编号"));
    expect(within(row).getByText("PO-DEMO-23")).toBeVisible();
    const voidRow = within(table).getAllByRole("row")[2]!;
    expect(within(voidRow).getByText("已作废")).toBeVisible();
    expect(within(voidRow).getByText("未计入有效跟进")).toBeVisible();
  });

  it("keeps separate shipment sources and allocations while showing the original void quantity", () => {
    render(<MemoryRouter><DocumentTable kind="shipments" items={[{ ...shipment, status: "VOID", actual_units: "5", sources: [
      { id: "source-1", sku_id: "1003", sku_label: "QA-1101 · RED-M · Red / M", actual_units: "3", allocations: [{ order_line_id: "line-1", order_id: "23", order_number: "PO-DEMO-23", order_business_number: "虚构订单23", units: "3" }] },
      { id: "source-2", sku_id: "1004", sku_label: "QA-2202 · NAVY-L · Navy / L", actual_units: "2", allocations: [{ order_line_id: "line-2", order_number: "缺少订单引用的历史原号", units: "2" }] },
    ] }]} /></MemoryRouter>);
    const table = screen.getByRole("table", { name: "出货记录" });
    expect(within(table).getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["单据信息", "商品与批次来源", "状态", "本次实际"]);
    const row = within(table).getAllByRole("row")[1]!;
    expect(within(row).getByRole("link", { name: "虚构出货34" })).toHaveAttribute("href", "/production/shipments/34");
    expect(within(row).getByRole("link", { name: "虚构订单23" })).toHaveAttribute("href", "/production/orders/23");
    expect(within(row).getByText("QA-1101")).toBeVisible();
    expect(within(row).getByText("QA-2202")).toBeVisible();
    expect(within(row).getByText("分配 3件")).toBeVisible();
    expect(within(row).getByText("分配 2件")).toBeVisible();
    expect(within(row).getByText("缺少订单引用的历史原号")).toBeVisible();
    expect(within(row).getByText("已作废")).toBeVisible();
    expect(within(row).getAllByRole("cell")[3]).toHaveTextContent("5");
    expect(within(table).getAllByRole("link")).toHaveLength(2);
    expect(screen.getByText(/每张单据记录一次实际发运/)).toHaveTextContent("已作废单据保留原登记数量，不计入有效汇总。");
  });

  it.each(["orders", "shipments"] as const)("keeps a filtered empty %s list clear", kind => {
    render(<MemoryRouter><DocumentTable kind={kind} items={[]} filtered /></MemoryRouter>);
    expect(within(screen.getByRole("table", { name: kind === "orders" ? "订单记录" : "出货记录" })).getByText("没有匹配当前筛选的记录。请调整条件或清空筛选。")).toBeVisible();
  });
});


it("uses the current formal SKU for historical shipment summaries while retaining the source label", async () => {
  const label="1112 · 1112-Black-S · Black / S";
  const sku:Sku={sku_id:"1003",code:"1112-Black-S",label:"1112-Black-S",status:"active",catalog_version:"2"};
  render(<MemoryRouter><DocumentTable kind="shipments" catalog={[sku]} items={[{...shipment,sources:[{...shipment.sources![0]!,sku_label:label}]}]}/></MemoryRouter>);
  const row=within(screen.getByRole("table",{name:"出货记录"})).getAllByRole("row")[1]!;
  expect(within(row).getByText("1112-Black-S",{exact:true})).toBeVisible();
  const original=within(row).getByText(label,{exact:true});
  expect(original).not.toBeVisible();
  await userEvent.click(within(row).getByText("1112-Black-S",{exact:true}));
  expect(original).toBeVisible();
});


it("shows the human completion decision before and after without inventing quantity changes", async () => {
  render(<RevisionHistory history={[{revision:"4",actor_id:"1",actor_name:"QA reviewer",reason:"用户确认生产与入库已完成",created_at:"2026-11-02T00:00:00Z",operation_kind:"COMPLETE_PRODUCTION",before_value:{production_completion_state:"OPEN"},after_value:{production_completion_state:"COMPLETED"}}]}/>);
  await userEvent.click(screen.getByText(/修订4 · 人工确认生产完成/));
  expect(screen.getByRole("table",{name:"修订4的变化"})).toHaveTextContent("生产完成确认进行中已完成");
});
