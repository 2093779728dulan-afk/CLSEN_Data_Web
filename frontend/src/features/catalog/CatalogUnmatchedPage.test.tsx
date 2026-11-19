import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { render as rtlRender, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CatalogPlatformStatus } from "./CatalogPlatformStatus";
import { CatalogUnmatchedPage } from "./CatalogUnmatchedPage";
import { CatalogUnmatchedView } from "./CatalogUnmatchedView";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";

function render(ui: ReactNode) { return rtlRender(<AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}>{ui}</AuthzGenerationProvider>); }

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it.each([undefined, "/products?from=2026-10-01&to=2026-10-02"])("keeps the styled analysis return visible while loading for entry %s", returnTo => {
  render(<MemoryRouter><CatalogUnmatchedView onRetry={() => undefined} onOpenStyle={() => undefined} page={1} returnBasis="event_date" returnTo={returnTo} maintenancePath="/catalog/maintenance" changePage={() => undefined} /></MemoryRouter>);
  const link = screen.getByRole("link", { name: "返回产品分析" });
  expect(link).toHaveAttribute("href", returnTo ?? "/products");
  expect(link.className).not.toBe("");
  expect(screen.getByRole("status")).toBeVisible();
});

it.each(["catalog_snapshot_unavailable"])("explains %s without futile retries or false zero results", async (code) => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/unmatched")) return Promise.resolve(new Response(JSON.stringify({ error: { code, message: "The catalog operation could not be completed." } }), { status: 409 }));
    if (url.includes("style-readiness")) return Promise.resolve(new Response(JSON.stringify({ published_reports: 74, coverage_from: "2026-07-01", coverage_to: "2026-08-06", source_scope_confirmed: false, catalog_approved: false, return_snapshot_present: false }), { status: 200 }));
    if (url.includes("source-scope")) return Promise.resolve(new Response(JSON.stringify({ status: "unconfirmed", permissions: { can_confirm: false } }), { status: 200 }));
    return Promise.reject(new Error("unexpected request"));
  }));
  render(<MemoryRouter><AuthzGenerationProvider boundary={{ principalId: 1, roles: ["admin"], siteConfigVersionId: 1, siteId: 1 }} onRevoked={() => undefined}><CatalogUnmatchedPage /></AuthzGenerationProvider></MemoryRouter>);
  expect(await screen.findByRole("heading", { name: "待处理清单尚未就绪" })).toBeVisible();
  expect(await screen.findByLabelText("已发布报表")).toHaveTextContent("74 份");
  expect(screen.getByRole("link", { name: "前往批量维护，完成初始化" })).toHaveAttribute("href", "/catalog/maintenance");
  expect(screen.queryByRole("button", { name: "重新读取" })).not.toBeInTheDocument();
  expect(screen.queryByText("The catalog operation could not be completed.")).not.toBeInTheDocument();
  expect(screen.queryByText("当前范围没有未归属来源。")).not.toBeInTheDocument();
});

it("does not disclose preparation data on permission failure", async () => {
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ error: { code: "catalog_admin_required", message: "Forbidden" } }), { status: 403 })));
  vi.stubGlobal("fetch", fetchMock);
  render(<MemoryRouter><CatalogUnmatchedPage /></MemoryRouter>);
  expect(await screen.findByText(/当前账号没有查看此商品主档页面的权限/)).toBeVisible();
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "重新读取" })).not.toBeInTheDocument();
});

it("shows current fact impact and an unmatched SKU without prior catalog evidence", async () => {
  const unmatched = {
    page: 1, page_size: 25, total_items: 1,
    range: { from_date: "2026-08-01", to_date: "2026-08-06", return_basis: "event_date" },
    baseline: { catalog_version_id: 35, catalog_publication_revision: 8, fact_basis: "current", consistent_as_of: "2026-09-11T00:00:00Z", publication_refs: [] },
    impact: { business_fact_rows: 1, units: 1, sales_by_currency: [{ currency_code: "USD", value: "35.99" }], return_fact_rows: 0, return_quantity: 0, unresolved_return_rows: 0 },
    items: [{
      source_identity: { report_source_scope_id: 1, seller_sku_sha256: "sha256:a", seller_sku_match: "match-a" },
      source_ref_id: null, preview: "1202-Light Blue-XXL", digest: "sha256:b", is_unsafe: false, is_truncated: false,
      report_types: ["business_report"], first_seen_date: "2026-08-04", latest_seen_date: "2026-08-04", published_version_ids: ["80"],
      business: { rows: 1, units: 1, sales_by_currency: [{ currency_code: "USD", value: "35.99" }] },
      returns: { rows: 0, quantity: 0, unresolved_rows: 0 }, candidate: { status: "not_started", review_path: null },
    }],
  };
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url;
    if (url.includes("/api/catalog/unmatched")) return Promise.resolve(new Response(JSON.stringify(unmatched), { status: 200 }));
    if (url.split("?")[0]?.endsWith("/api/catalog/styles")) return Promise.resolve(new Response(JSON.stringify({ catalog: { styles: [{ style_id: 26, style_code: "1202", standard_name: "1202 Shorts" }] } }), { status: 200 }));
    if (url.includes("/pending-items")) return new Promise<Response>(() => undefined);
    return Promise.reject(new Error(`unexpected request: ${url}`));
  }));
  render(<MemoryRouter initialEntries={["/catalog/unmatched?from=2026-08-01&to=2026-08-06"]}><CatalogUnmatchedPage /></MemoryRouter>);
  expect(await screen.findByText("1202-Light Blue-XXL")).toBeVisible();
  expect(screen.getAllByText("1 件").length).toBeGreaterThan(0);
  expect(screen.getAllByText("US$35.99").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: /多商品批量维护/ })).toBeVisible();
  expect(screen.getByRole("button", { name: "处理本条" })).toBeVisible();
  expect(screen.getByRole("button", { name: "待审核" })).toBeVisible();
});

it("does not present missing publication evidence as zero unmatched success", async () => {
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/unmatched")) return Promise.resolve(new Response(JSON.stringify({
      page: 1, page_size: 25, total_items: 0, items: [],
      range: { from_date: "2099-05-01", to_date: "2099-05-01" },
      baseline: { catalog_version_id: 36, consistent_as_of: "2026-09-11T00:00:00Z", publication_refs: [] },
      impact: { business_fact_rows: 0, return_fact_rows: 0, units: 0, return_quantity: 0, unresolved_return_rows: 0, sales_by_currency: [] },
    }), { status: 200 }));
    return new Promise<Response>(() => undefined);
  }));
  render(<MemoryRouter><CatalogUnmatchedPage /></MemoryRouter>);
  expect(await screen.findByText("所选日期尚未到达")).toBeVisible();
  expect(screen.queryByText("少计销量")).not.toBeInTheDocument();
  expect(screen.queryByText("当前范围没有未归属来源。")).not.toBeInTheDocument();
});

it("shows existing platform conflicts separately from unmatched source identities", async () => {
  vi.stubEnv("VITE_PRODUCTION_CATALOG_ENABLED", "true");
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (url.includes("/platform/status")) return Promise.resolve(new Response(JSON.stringify({ state: "pending", message: "官方来源出现多个子ASIN，受影响关联列入待核。", conflicts: [{ style_id: "18", sku_id: "19", scope_id: "1", seller_sku: "0012-Olive-M", official_asins: ["B000000001", "B000000002"] }] }), { status: 200 }));
    if (url.includes("/unmatched")) return Promise.resolve(new Response(JSON.stringify({
      page: 1, page_size: 25, total_items: 0, items: [],
      range: { from_date: "2026-10-01", to_date: "2026-10-02" },
      baseline: { catalog_version_id: 28, consistent_as_of: "2026-10-15T00:00:00Z", publication_refs: [1] },
      impact: { business_fact_rows: 0, return_fact_rows: 0, units: 0, return_quantity: 0, unresolved_return_rows: 0, sales_by_currency: [] },
    }), { status: 200 }));
    return Promise.resolve(new Response(JSON.stringify({ catalog: { styles: [] } }), { status: 200 }));
  }));
  render(<MemoryRouter><CatalogUnmatchedPage /></MemoryRouter>);
  expect(await screen.findByText("平台身份待核")).toBeVisible();
  expect(screen.getByRole("link", { name: "0012-Olive-M" })).toHaveAttribute("href", "/catalog/styles/18");
  expect(screen.getByText(/范围与下方按日期筛选的/)).toBeVisible();
  expect(screen.getByText("当前范围没有未归属来源。")).toBeVisible();
});

it('keeps healthy platform evidence collapsed and accessible on request', async () => {
 vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve(new Response(JSON.stringify({state:'clear',message:'当前未发现多子ASIN冲突',conflicts:[]})))));
 render(<MemoryRouter><CatalogPlatformStatus compact revision={0}/></MemoryRouter>);
 const toggle=await screen.findByText('平台资料核对');
 expect(screen.getByText('当前未发现多子ASIN冲突')).not.toBeVisible();
 expect(screen.getByRole('link',{name:'查看或导入亚马逊商品清单',hidden:true})).not.toBeVisible();
 await userEvent.click(toggle);
 expect(screen.getByText('当前未发现多子ASIN冲突')).toBeVisible();
 expect(screen.getByRole('link',{name:'查看或导入亚马逊商品清单'})).toBeVisible();
});
it('keeps incomplete platform evidence visible in the compact page', async () => {
 vi.stubGlobal('fetch',vi.fn(()=>Promise.resolve(new Response(JSON.stringify({state:'incomplete',message:'缺少官方依据，尚未完成核对',conflicts:[]})))));
 render(<MemoryRouter><CatalogPlatformStatus compact revision={0}/></MemoryRouter>);
 expect(await screen.findByText('缺少官方依据，尚未完成核对')).toBeVisible();
 expect(screen.queryByText('平台资料核对')).not.toBeInTheDocument();
});
