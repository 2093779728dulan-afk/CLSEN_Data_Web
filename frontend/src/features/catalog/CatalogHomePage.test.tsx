vi.mock("./CatalogSetup", () => ({ CatalogSetup: () => <div>初始化状态面板</div> }));
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogHomePage } from "./CatalogHomePage";

describe("CatalogHomePage", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("refreshes an uninitialized tab after another tab approves the catalog", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ catalog: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ catalog: { catalog_publication_revision: 1, version_number: 1, styles: [], skus: [] } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MemoryRouter><CatalogHomePage canManage={false} /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "商品主档尚未初始化" })).toBeVisible();
    fireEvent.focus(window);
    expect(await screen.findByRole("heading", { name: "当前批准主档" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "商品主档尚未初始化" })).not.toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
  it("shows the explicit uninitialized state", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ catalog: null }), { status: 200 }))));
    render(<MemoryRouter><CatalogHomePage canManage={false} /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "商品主档尚未初始化" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "生成候选" })).not.toBeInTheDocument();
  });

  it("switches between product cards and the batch table", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ catalog: { catalog_publication_revision: 3, catalog_version_id: 4, version_number: 2, skus: [], styles: [{ revision: 1, seller_sku_count: 3, source_summary: { first_seen_date: "2026-06-01", latest_seen_date: "2026-07-03", observation_count: 8, source_report_count: 2 }, standard_name: "经典衬衫", status: "enabled", style_code: "2301", style_id: 8, variant_count: 2 }] } }), { status: 200 }))));
    render(<MemoryRouter><CatalogHomePage canManage={false} /></MemoryRouter>);
    expect(await screen.findByRole("heading", { name: "经典衬衫" })).toBeVisible();
    expect(screen.getByText("已启用")).toBeVisible();
    expect(screen.getAllByText("款式编号").length).toBeGreaterThan(0);
    expect(screen.getByText("系统身份 STYLE #8")).toBeVisible();
    expect(screen.getByText("3", { selector: "dd" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "批量表格" }));
    expect(screen.getByRole("columnheader", { name: "Seller SKU" })).toBeVisible();
    expect(screen.getByRole("columnheader", { name: "款式编号" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "2301" })).toBeVisible();
  });
});
