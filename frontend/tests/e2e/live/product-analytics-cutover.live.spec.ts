import { expect, test } from "./catalogLiveFixtures";

test("cutover phase bundle, navigation, and endpoint provenance agree", async ({ viewerPage, viewerRequest }) => {
  test.setTimeout(60_000);
  const phase = process.env.CATALOG_LIVE_CUTOVER_PHASE;
  const expectedSource = phase === "p0" ? "p0_catalog" : "legacy_parser";
  expect(["legacy-before", "p0", "legacy-rollback"]).toContain(phase);
  expect(process.env.VITE_PRODUCT_ANALYTICS_SOURCE).toBe(expectedSource);

  const requests: string[] = [];
  viewerPage.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.startsWith("/api/dashboard/")) requests.push(path);
  });
  await viewerPage.goto("/products");
  await expect(viewerPage.locator(".app-shell")).toHaveAttribute(
    "data-product-analytics-source",
    `product-analytics-source:${expectedSource}`,
  );
  await expect(viewerPage.getByRole("link", { name: "商品主档" })).toBeVisible();

  const range = { from: "2025-07-17", to: "2025-07-17" };
  if (expectedSource === "legacy_parser") {
    await expect(viewerPage).toHaveURL(/\?tab=products/);
    await expect(viewerPage.getByRole("link", { name: "产品分析" })).toHaveCount(0);
    expect(requests.some((path) => path.includes("style-ledger") || path.includes("/styles/"))).toBe(false);
    const legacy = await viewerRequest.get("/api/dashboard/product-ledger", { params: range });
    expect(legacy.status()).toBe(200);
    expect(legacy.headers()["x-identity-source"]).toBe("legacy_parser");
    return;
  }

  await expect(viewerPage).toHaveURL(/\/products/);
  await expect(viewerPage.getByRole("link", { name: "产品分析" })).toBeVisible();
  expect(requests).toContain("/api/dashboard/style-ledger");
  expect(requests.some((path) => path.includes("product-ledger") || path.includes("product-card"))).toBe(false);
  const legacy = await viewerRequest.get("/api/dashboard/product-ledger", { params: range });
  expect(legacy.status()).toBe(200);
  expect(legacy.headers()["x-identity-source"]).toBe("legacy_parser");
  const modern = await viewerRequest.get("/api/dashboard/style-ledger", { params: range });
  expect(modern.status()).toBe(200);
  expect(modern.headers()["x-identity-source"]).toBe("p0_catalog");
});
