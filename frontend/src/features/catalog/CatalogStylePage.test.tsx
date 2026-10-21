import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogStylePage } from "./CatalogStylePage";

describe("CatalogStylePage", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("shows only actual variants returned for the stable style ID", async () => {
    const sourceSummary = { first_seen_date: "2026-06-01", latest_seen_date: "2026-07-01", observation_count: 4, source_report_count: 2 };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/pending-items")) return Promise.resolve(new Response(JSON.stringify({ items: [], permissions: { can_review: false } }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ catalog_version_id: 4, style: { revision: 1, seller_sku_count: 2, source_summary: sourceSummary, standard_name: "标准款", status: "active", style_code: "A", style_id: 8, variant_count: 1 }, skus: [{ internal_display_sku: "A-BLUE-S", revision: 1, seller_sku_count: 2, sku_id: 9, source_summary: sourceSummary, standard_color: "蓝", standard_size: "S", status: "active", style_id: 8 }] }), { status: 200 }));
    }));
    render(<MemoryRouter initialEntries={["/catalog/styles/8"]}><Routes><Route element={<CatalogStylePage />} path="/catalog/styles/:style_id" /></Routes></MemoryRouter>);
    await waitFor(() => expect(screen.getByRole("heading", { name: "标准款" })).toBeVisible());
    expect(within(screen.getByRole("article", { name: "变体 A-BLUE-S" })).getByText("已启用")).toBeVisible();
    expect(screen.getAllByText("款式编号").length).toBeGreaterThan(0);
    expect(screen.getByText("A-BLUE-S")).toBeVisible();
    expect(screen.getByText("系统身份 SKU #9", { exact: false })).toBeVisible();
  });

  it("loads N:1 Seller SKU aliases and source evidence only when requested", async () => {
    const sourceSummary = { first_seen_date: "2026-06-01", latest_seen_date: "2026-07-01", observation_count: 4, source_report_count: 2 };
    const safeRef = (id: string, preview: string) => ({ digest: `sha256:${"a".repeat(64)}`, is_truncated: false, is_unsafe: false, preview, source_ref_id: id });
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/pending-items")) return Promise.resolve(new Response(JSON.stringify({ items: [], permissions: { can_review: true } }), { status: 200 }));
      if (url.includes("/seller-skus")) return Promise.resolve(new Response(JSON.stringify({ items: [{ mapping_id: 1, mapping_status: "mapped", marketplace: "amazon_us", seller_account: "US 主账号", seller_sku: safeRef("mapping:1", "2301-BLACK-M-OLD"), source_summary: sourceSummary }, { mapping_id: 2, mapping_status: "mapped", marketplace: "amazon_us", seller_account: "US 主账号", seller_sku: safeRef("mapping:2", "2301-BLACK-M-NEW"), source_summary: sourceSummary }], page: 1, page_size: 50, total_items: 2 }), { status: 200 }));
      if (url.includes("/evidence")) return Promise.resolve(new Response(JSON.stringify({ items: [{ child_asin: null, dataset_id: 5, event_date: "2026-07-01", evidence_digest: `sha256:${"b".repeat(64)}`, evidence_id: 12, fnsku: null, parent_asin: null, published_version_id: 7, report_date: "2026-07-02", report_type: "business_report", seller_sku: safeRef("31", "2301-BLACK-M-OLD"), source_row_id: 44, source_filename: "returns.csv", source_record_number: 5, title: safeRef("32", "Classic shirt") }], page: 1, page_size: 50, total_items: 1 }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ catalog_version_id: 4, style: { revision: 1, seller_sku_count: 2, source_summary: sourceSummary, standard_name: "标准款", status: "enabled", style_code: "2301", style_id: 8, variant_count: 1 }, skus: [{ internal_display_sku: "2301-BLACK-M", revision: 1, seller_sku_count: 2, sku_id: 9, source_summary: sourceSummary, standard_color: "黑色", standard_size: "M", status: "enabled", style_id: 8 }] }), { status: 200 }));
    }));
    render(<MemoryRouter initialEntries={["/catalog/styles/8"]}><Routes><Route element={<CatalogStylePage />} path="/catalog/styles/:style_id" /></Routes></MemoryRouter>);
    await userEvent.click(await screen.findByRole("button", { name: "展开 Seller SKU" }));
    expect(await screen.findByText("2301-BLACK-M-OLD")).toBeVisible();
    expect(screen.getByText("2301-BLACK-M-NEW")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "查看来源明细" }));
    expect(await screen.findByText("Classic shirt")).toBeVisible();
    expect(screen.getByText("报告归属日：2026-07-02")).toBeVisible();
    expect(screen.getByText("记录事件日期：2026-07-01")).toBeVisible();
    expect(screen.getByText("来源文件：returns.csv")).toBeVisible();
    expect(screen.getByText(/原表记录序号：5/)).toBeVisible();
    expect(screen.getByRole("link", { name: "查看来源报告版本" })).toHaveAttribute("href", "/versions?report_date=2026-07-02&report_type=business_report");
    await userEvent.click(screen.getByText("系统追溯信息"));
    expect(screen.getByText("系统版本编号 7 · 系统记录编号 44（非文件行号）")).toBeVisible();
  });

  it("links a style's pending variant and Seller SKU candidates to the existing review", async () => {
    const sourceSummary = { first_seen_date: null, latest_seen_date: null, observation_count: 0, source_report_count: 0 };
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/pending-items")) return Promise.resolve(new Response(JSON.stringify({ items: [{ import_id: 27, review_path: "/catalog/imports/27", seller_sku_count: 1, seller_sku_previews: ["2301-NAVY-L"], status: "needs_attention", updated_at: "2026-09-08T09:00:00Z", variant_count: 1, workflow_revision: 0 }], permissions: { can_review: true } }), { status: 200 }));
      return Promise.resolve(new Response(JSON.stringify({ catalog_version_id: 4, catalog_publication_revision: 2, permissions: { can_edit: false, can_manage_categories: false }, style: { category_code: null, category_id: null, category_name: null, category_recorded: true, revision: 1, seller_sku_count: 2, source_summary: sourceSummary, standard_name: "标准款", status: "enabled", style_code: "2301", style_id: 8, variant_count: 1 }, skus: [] }), { status: 200 }));
    }));
    render(<MemoryRouter initialEntries={["/catalog/styles/8"]}><Routes><Route element={<CatalogStylePage />} path="/catalog/styles/:style_id" /><Route element={<p>审核工作台</p>} path="/catalog/imports/:import_id" /></Routes></MemoryRouter>);

    await waitFor(() => expect(screen.getByRole("heading", { name: "新变体与 Seller SKU 候选" })).toBeVisible());
    expect(screen.getByText("2301-NAVY-L")).toBeVisible();
    await userEvent.click(screen.getByRole("link", { name: "进入审核" }));
    expect(screen.getByText("审核工作台")).toBeVisible();
  });
});
