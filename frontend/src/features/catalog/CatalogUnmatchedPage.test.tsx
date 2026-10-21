import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CatalogUnmatchedPage } from "./CatalogUnmatchedPage";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";

afterEach(() => vi.unstubAllGlobals());

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
    if (url.endsWith("/api/catalog/styles")) return Promise.resolve(new Response(JSON.stringify({ catalog: { styles: [{ style_id: 26, style_code: "1202", standard_name: "1202 Shorts" }] } }), { status: 200 }));
    if (url.includes("/pending-items")) return new Promise<Response>(() => undefined);
    return Promise.reject(new Error(`unexpected request: ${url}`));
  }));
  render(<MemoryRouter initialEntries={["/catalog/unmatched?from=2026-08-01&to=2026-08-06"]}><CatalogUnmatchedPage /></MemoryRouter>);
  expect(await screen.findByText("1202-Light Blue-XXL")).toBeVisible();
  expect(screen.getAllByText("1 件").length).toBeGreaterThan(0);
  expect(screen.getAllByText("US$35.99").length).toBeGreaterThan(0);
  expect(screen.getByRole("link", { name: /生成或继续审核候选/ })).toBeVisible();
  expect(screen.getByText("正在读取已有审核候选，来源清单可以先处理。")).toBeVisible();
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
