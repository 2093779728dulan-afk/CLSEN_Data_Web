import { expect, test } from "./catalogLiveFixtures";

test("release build serves approved catalog and P0 analytics without dev runtime", async ({
  viewerPage,
  viewerRequest,
}) => {
  test.setTimeout(60_000);
  expect(process.env.CATALOG_LIVE_CUTOVER_PHASE).toBe("p0");
  expect(process.env.VITE_PRODUCT_ANALYTICS_SOURCE).toBe("p0_catalog");

  const document = await viewerRequest.get("/");
  expect(document.status()).toBe(200);
  const html = await document.text();
  expect(html).not.toContain("/@vite/client");
  expect(html).toMatch(/\/assets\/index-[A-Za-z0-9_-]+\.js/);

  const catalog = await viewerRequest.get("/api/catalog/styles");
  expect(catalog.status()).toBe(200);
  const payload = await catalog.json() as {
    catalog: null | { catalog_version_id: number; styles: unknown[] };
  };
  expect(payload.catalog?.catalog_version_id).toBeGreaterThan(0);
  expect(payload.catalog?.styles.length).toBeGreaterThan(0);

  await viewerPage.goto("/products?from=2025-07-17&to=2025-07-17");
  await expect(viewerPage.locator(".app-shell")).toHaveAttribute(
    "data-product-analytics-source",
    "p0_catalog",
  );
  await expect(viewerPage.getByRole("heading", { level: 1, name: "产品总表" })).toBeVisible();
  const ledger = await viewerRequest.get("/api/dashboard/style-ledger", {
    params: { from: "2025-07-17", to: "2025-07-17" },
  });
  expect(ledger.status()).toBe(200);
  expect(ledger.headers()["x-identity-source"]).toBe("p0_catalog");
});
