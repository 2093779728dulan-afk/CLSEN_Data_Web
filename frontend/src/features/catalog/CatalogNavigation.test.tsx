import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { CatalogNavigationProvider } from "./CatalogNavigationContext";
import { CatalogHomePage } from "./CatalogHomePage";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogUnmatchedPage } from "./CatalogUnmatchedPage";
import { CatalogImportPage } from "./CatalogImportPage";

vi.mock("./CatalogSetup", () => ({ CatalogSetup: () => null }));

afterEach(() => vi.unstubAllGlobals());
const styles = Array.from({ length: 15 }, (_, i) => ({ style_id: i + 1, style_code: String(100 + i), standard_name: `商品 ${i + 1}`, status: "enabled", source_summary: {}, variant_count: 1, seller_sku_count: 1 }));
const response = (value: unknown) => Promise.resolve(new Response(JSON.stringify(value), { status: 200 }));

it("retains query, sorting, page and view on return, then clears them at a new identity boundary", async () => {
  vi.stubGlobal("fetch", vi.fn(() => response({ catalog: { styles, version_number: 1 } })));
  function Workspace({ boundary }: { boundary: string }) {
    return <MemoryRouter initialEntries={["/catalog"]}><CatalogNavigationProvider key={boundary}><Routes><Route path="/catalog" element={<CatalogHomePage canManage />} /><Route path="/catalog/styles/:style_id" element={<Link to="/catalog">返回商品主档</Link>} /></Routes></CatalogNavigationProvider></MemoryRouter>;
  }
  const result = render(<Workspace boundary="site-1" />);
  await screen.findByRole("heading", { name: "当前批准主档" });
  await userEvent.type(screen.getByLabelText("查找商品"), "商品");
  await userEvent.click(screen.getByRole("combobox", { name: "排序" }));
  await userEvent.keyboard("{End}{Enter}");
  await userEvent.click(screen.getByRole("combobox", { name: "商品状态" }));
  await userEvent.keyboard("{Home}{ArrowDown}{Enter}");
  await userEvent.click(screen.getByRole("button", { name: "批量表格" }));
  await userEvent.click(screen.getByRole("button", { name: "下一页" }));
  await userEvent.click(screen.getAllByRole("link").find((link) => link.getAttribute("href")?.startsWith("/catalog/styles/"))!);
  await userEvent.click(screen.getByRole("link", { name: "返回商品主档" }));
  await waitFor(() => expect(screen.getByLabelText("第 2 / 2 页")).toBeVisible());
  expect(screen.getByLabelText("查找商品")).toHaveValue("商品");
  expect(screen.getByRole("combobox", { name: "排序" })).toHaveTextContent("商品名称");
  expect(screen.getByRole("combobox", { name: "商品状态" })).toHaveTextContent("已启用");
  expect(screen.getByRole("button", { name: "批量表格" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("heading", { name: "目录工作簿" })).not.toBeInTheDocument();
  result.rerender(<Workspace boundary="site-2" />);
  await waitFor(() => expect(screen.getByLabelText("第 1 / 2 页")).toBeVisible());
  expect(screen.getByLabelText("查找商品")).toHaveValue("");
  expect(screen.getByRole("combobox", { name: "商品状态" })).toHaveTextContent("全部状态");
  expect(screen.getByRole("button", { name: "商品卡" })).toHaveAttribute("aria-pressed", "true");
});

it("offers four manager destinations but hides management navigation from viewers", () => {
  const result = render(<MemoryRouter><CatalogLayout canManage><p>内容</p></CatalogLayout></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual(["商品", "待处理", "目录版本", "批量维护"]);
  result.rerender(<MemoryRouter><CatalogLayout canManage={false}><p>内容</p></CatalogLayout></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual(["商品"]);
});

it("reuses authorized pending summaries and preserves the old import deep link with a return path", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.endsWith("/styles")) return response({ catalog: { styles: styles.slice(0, 2) } });
    if (url.includes("/api/catalog/unmatched")) return response({
      page: 1, page_size: 25, total_items: 0, items: [],
      range: { from_date: "2026-08-01", to_date: "2026-08-06", return_basis: "event_date" },
      baseline: { catalog_version_id: 1, consistent_as_of: "2026-09-11T00:00:00Z", publication_refs: [] },
      impact: { business_fact_rows: 0, return_fact_rows: 0, units: 0, return_quantity: 0, unresolved_return_rows: 0, sales_by_currency: [] },
    });
    if (url.endsWith("/pending-items")) return response({ permissions: { can_review: !url.includes("/styles/2/") }, items: [{ import_id: 2, review_path: "/catalog/imports/2", status: "needs_attention", variant_count: 1, seller_sku_count: 1, seller_sku_previews: [] }] });
    if (url.includes("/rows/")) return response({ rows: [] });
    return response({ import_id: 2, status: "needs_attention", permissions: {}, workflow_revision: 1 });
  }));
  render(<MemoryRouter initialEntries={["/catalog/unmatched"]}><CatalogNavigationProvider><Routes><Route path="/catalog/unmatched" element={<CatalogUnmatchedPage />} /><Route path="/catalog/imports/:import_id" element={<CatalogImportPage />} /></Routes></CatalogNavigationProvider></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "100 · 商品 1" })).toBeVisible();
  expect(screen.queryByRole("link", { name: "101 · 商品 2" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("link", { name: "进入审核" }));
  expect(await screen.findByRole("heading", { name: "商品主档审核" })).toBeVisible();
  await userEvent.click(screen.getByRole("link", { name: "返回来源页面" }));
  expect(await screen.findByRole("heading", { name: "已有审核候选" })).toBeVisible();
});
