vi.mock("../../api/client", async importOriginal => {
  const original = await importOriginal<typeof import("../../api/client")>();
  return { ...original, requestApi: (path:string, options?: Parameters<typeof original.requestApi>[1]) => path.endsWith("/capabilities") ? Promise.resolve({scopes:[]}) : original.requestApi(path, options) };
});
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";
import { CatalogNavigationProvider } from "./CatalogNavigationContext";
import { CatalogHomePage } from "./CatalogHomePage";
import { CatalogLayout } from "./CatalogLayout";
import { CatalogUnmatchedPage } from "./CatalogUnmatchedPage";
import { CatalogImportPage } from "./CatalogImportPage";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";

vi.mock("./CatalogSetup", () => ({ CatalogSetup: () => null }));

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
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
  vi.stubEnv("VITE_PRODUCTION_CATALOG_ENABLED", "false");
  const result = render(<MemoryRouter><CatalogLayout canManage><p>内容</p></CatalogLayout></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual(["商品", "待归属与审核", "目录版本", "批量维护"]);
  result.rerender(<MemoryRouter><CatalogLayout canManage={false}><p>内容</p></CatalogLayout></MemoryRouter>);
  expect(screen.getAllByRole("link").map((link) => link.textContent)).toEqual(["商品"]);
});

it("opens authorized saved review tasks through the old import link and restores task filters", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.startsWith("/api/catalog/tasks?")) return response({
      page: 1, total_items: 1, has_next: false, complete: true,
      baseline: { catalog_publication_revision: 1 },
      items: [{ task_id: "catalog:2", import_id: 2, source_name: "100 · 商品 1", record_kind: "catalog_review", source_kind: "online", status: "needs_attention", actor: "fictional.admin", updated_at: "2026-09-11T00:00:00Z", workflow_revision: 1, review_path: "/catalog/imports/2", scope_ids: [1] }],
    });
    if (url.endsWith("/capabilities")) return response({ scopes: [] });
    if (url.includes("/rows/")) return response({ rows: [] });
    return response({ import_id: 2, status: "needs_attention", permissions: {}, workflow_revision: 1 });
  }));
  const taskPath = "/catalog/unmatched?tab=review&task_q=商品";
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><MemoryRouter initialEntries={[taskPath]}><CatalogNavigationProvider><Routes><Route path="/catalog/unmatched" element={<CatalogUnmatchedPage />} /><Route path="/catalog/imports/:import_id" element={<CatalogImportPage />} /></Routes></CatalogNavigationProvider></MemoryRouter></AuthzGenerationProvider>);
  const reviewLink = await screen.findByRole("link", { name: "100 · 商品 1 · 批次 2" });
  expect(reviewLink).toHaveAttribute("href", `/catalog/imports/2?return_to=${encodeURIComponent(taskPath)}`);
  await userEvent.click(reviewLink);
  expect(await screen.findByRole("heading", { name: "商品主档审核" })).toBeVisible();
  await userEvent.click(screen.getByRole("link", { name: "返回待归属与审核" }));
  expect(await screen.findByRole("heading", { name: "待审核候选" })).toBeVisible();
  expect(screen.getByLabelText("查找任务")).toHaveValue("商品");
});

it('merges enabled product intake and maintenance into one catalog destination',()=>{
 vi.stubEnv('VITE_PRODUCTION_CATALOG_ENABLED','true');render(<MemoryRouter initialEntries={['/catalog/maintenance']}><CatalogLayout canManage><p>内容</p></CatalogLayout></MemoryRouter>);
 expect(screen.getAllByRole('link').map(link=>link.textContent)).toEqual(['商品','建档与维护','待归属与审核','目录版本']);
 expect(screen.getByRole('link',{name:'建档与维护'})).toHaveAttribute('aria-current','page');expect(screen.queryByRole('link',{name:'商品建档'})).not.toBeInTheDocument();
});
