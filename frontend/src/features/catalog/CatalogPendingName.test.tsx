import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, it, vi } from "vitest";
import { CatalogChangeReview } from "./CatalogChangeReview";
import { CatalogImportSectionTable, filterCatalogReviewRows, isCatalogRowPending } from "./CatalogImportSectionTable";
import { CatalogStyleView, type CatalogStyleDetail } from "./CatalogStyleView";
import type { CatalogStyle } from "./catalogApi";
import type { CatalogImportRow } from "./catalogTypes";

const row: CatalogImportRow = { section: "styles", row_key: "s", row_origin: "user_created", projection_state: "included", payload: { style_code: "QA-NAME", standard_name: null } };
const style = { style_id: 13, style_code: "QA-NAME", standard_name: "", category_id: null } as CatalogStyle;

it("shows a pending name as optional and keeps missing identity fields pending", () => {
  expect(isCatalogRowPending("styles", row)).toBe(false);
  expect(isCatalogRowPending("styles", { ...row, payload: { standard_name: null } })).toBe(true);
  expect(filterCatalogReviewRows("styles", [row], false, "名称待补")).toEqual([row]);
  render(<CatalogImportSectionTable importId={1} onSaved={vi.fn()} rows={[row]} section="styles" workflowRevision={0} />);
  expect(screen.getByText(/名称待补（选填）/)).toBeVisible();
  expect(screen.getByLabelText("s standard_name")).not.toBeRequired();
});

it("allows category preview with an empty name and never stores the display label", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn().mockResolvedValue({ before: { standard_name: "", category: {} }, after: { standard_name: "", category: {} } }), approve: vi.fn() };
  render(<CatalogChangeReview catalogPublicationRevision={1} style={style} onApproved={vi.fn()} services={services} />);
  fireEvent.click(screen.getByRole("button", { name: "修改名称 / 分类" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "生成变更预览" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "生成变更预览" }));
  await waitFor(() => expect(services.prepare).toHaveBeenCalledWith(style, 1, "", null));
  expect(screen.getAllByText("名称待补")).toHaveLength(2);
});

it("loads an explicitly selected report title into the ordinary preview without approving it", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn(), approve: vi.fn() };
  render(<CatalogChangeReview catalogPublicationRevision={1} style={style} onApproved={vi.fn()} services={services} nameSuggestion={{ name: "QA shirt", source: "经营报告 2026-10-01 · 版本#1" }} />);
  expect(await screen.findByLabelText("标准商品名称（选填）")).toHaveValue("QA shirt");
  expect(screen.getByText(/候选依据：经营报告/)).toBeVisible();
  expect(services.prepare).not.toHaveBeenCalled();
  expect(services.approve).not.toHaveBeenCalled();
});

it("keeps the name blank until a scoped official report title is selected", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn(), approve: vi.fn(), names: vi.fn().mockResolvedValue({ items: [{ name: "QA business title", source: "QA店 · 经营报告 2026-10-01" }, { name: "QA return title", source: "QA店 · 退货报告 2026-10-02" }], limited: false }) };
  render(<CatalogChangeReview catalogPublicationRevision={1} style={style} onApproved={vi.fn()} services={services} />);
  fireEvent.click(screen.getByRole("button", { name: "修改名称 / 分类" }));
  const select = await screen.findByLabelText("从官方报告选择名称（可选）");
  await waitFor(() => expect(select).toBeEnabled());
  expect(services.names).toHaveBeenCalledWith(13);
  expect(screen.getByLabelText("标准商品名称（选填）")).toHaveValue("");
  fireEvent.change(select, { target: { value: "1" } });
  expect(screen.getByLabelText("标准商品名称（选填）")).toHaveValue("QA return title");
  expect(screen.getByText(/参考来源：QA店 · 退货报告/)).toBeVisible();
  expect(services.approve).not.toHaveBeenCalled();
});

it("does not block an empty-name preview when report titles are unavailable", async () => {
  const services = { categories: vi.fn().mockResolvedValue([]), prepare: vi.fn(), approve: vi.fn(), names: vi.fn().mockRejectedValue(new Error("offline")) };
  render(<CatalogChangeReview catalogPublicationRevision={1} style={style} onApproved={vi.fn()} services={services} />);
  fireEvent.click(screen.getByRole("button", { name: "修改名称 / 分类" }));
  expect(await screen.findByText(/报告名称暂未读取成功/)).toBeVisible();
  expect(screen.getByRole("button", { name: "生成变更预览" })).toBeEnabled();
});

it("offers titles only from the requested variant evidence and only with edit permission", async () => {
  const source_summary = { first_seen_date: null, latest_seen_date: null, observation_count: 2, source_report_count: 2 };
  const value: CatalogStyleDetail = { catalog_version_id: 1, permissions: { can_edit: true, can_manage_categories: false }, style: { ...style, status: "enabled", source_summary }, skus: [{ sku_id: 14, style_id: 13, internal_display_sku: "QA-SOURCE", standard_color: "Olive", standard_size: "M", revision: 1, status: "enabled", seller_sku_count: 1, source_summary }] };
  const ref = { source_ref_id: "1", preview: "QA report title", digest: "sha256:" + "a".repeat(64), is_truncated: false, is_unsafe: false };
  const evidence = { evidence_id: 1, report_type: "business_report", report_date: "2026-10-01", event_date: null, dataset_id: 1, published_version_id: 2, source_row_id: 3, evidence_digest: "abc", seller_sku: ref, title: ref, parent_asin: null, child_asin: null, fnsku: null };
  const readers = { aliases: vi.fn().mockResolvedValue({ page: 1, page_size: 50, total_items: 0, items: [] }), evidence: vi.fn().mockResolvedValue({ page: 1, page_size: 50, total_items: 3, items: [evidence, { ...evidence, evidence_id: 2, title: { ...ref, is_truncated: true } }, { ...evidence, evidence_id: 3, title: { ...ref, is_unsafe: true } }] }) };
  const onNameSuggestion = vi.fn();
  const view = render(<MemoryRouter><CatalogStyleView value={value} readers={readers} onRefresh={vi.fn()} onNameSuggestion={onNameSuggestion} /></MemoryRouter>);
  await waitFor(() => expect(screen.getByRole("heading", { name: "名称待补" })).toBeVisible());
  fireEvent.click(screen.getByRole("button", { name: "展开 Seller SKU" }));
  fireEvent.click(await screen.findByRole("button", { name: "查看来源明细" }));
  fireEvent.click(await screen.findByRole("button", { name: "用此报告标题补名称" }));
  expect(readers.evidence).toHaveBeenCalledWith(14, 1);
  expect(onNameSuggestion).toHaveBeenCalledWith({ name: "QA report title", source: "经营报告 2026-10-01 · 版本#2 · 记录#3" });
  view.rerender(<MemoryRouter><CatalogStyleView value={{ ...value, permissions: { can_edit: false, can_manage_categories: false } }} readers={readers} onRefresh={vi.fn()} onNameSuggestion={onNameSuggestion} /></MemoryRouter>);
  expect(screen.queryByRole("button", { name: "用此报告标题补名称" })).not.toBeInTheDocument();
});
