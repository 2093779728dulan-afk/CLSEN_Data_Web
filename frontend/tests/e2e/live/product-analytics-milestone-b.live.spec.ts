import { expect, test } from "./catalogLiveFixtures";

type CurrentCatalog = { catalog: null | { skus: unknown[]; styles: Array<{ standard_name: string; style_code: string; style_id: string | number }> } };

test("Milestone B verifies real legacy and P0 product analytics without route mocks", async ({ viewerPage, viewerRequest }) => {
  test.setTimeout(90_000);
  const catalogResponse=await viewerRequest.get("/api/catalog/styles"); expect(catalogResponse.status()).toBe(200);
  const catalog=await catalogResponse.json() as CurrentCatalog; const style=catalog.catalog?.styles[0]; expect(style).toBeTruthy();
  expect(catalog.catalog?.skus).toHaveLength(10);
  const range={from:"2025-07-17",to:"2025-07-17"};
  const legacyLedger=await viewerRequest.get("/api/dashboard/product-ledger",{params:range}); expect(legacyLedger.status()).toBe(200); expect(legacyLedger.headers()["x-identity-source"]).toBe("legacy_parser"); expect(legacyLedger.headers()["x-identity-version"]).toBe("seller_sku_parser_v1");
  const p0Ledger=await viewerRequest.get("/api/dashboard/style-ledger",{params:range}); expect(p0Ledger.status(),await p0Ledger.text()).toBe(200); expect(p0Ledger.headers()["x-identity-source"]).toBe("p0_catalog"); const ledger=await p0Ledger.json() as {rows:Array<{style_id:string;standard_name:string}>}; expect(ledger.rows.some(row=>row.style_id===String(style?.style_id))).toBe(true);
  const legacyMissing=await viewerRequest.get("/api/dashboard/product-card/23010000",{params:range}); expect(legacyMissing.status()).toBe(404);
  const p0Missing=await viewerRequest.get("/api/dashboard/styles/23010000/card",{params:range}); expect(p0Missing.status()).toBe(404); expect(p0Missing.headers()["x-identity-source"]).toBeUndefined();
  const p0Requests:string[]=[]; viewerPage.on("request",request=>{const path=new URL(request.url()).pathname;if(path.startsWith("/api/dashboard/"))p0Requests.push(path);});
  await viewerPage.goto(`/products?from=${range.from}&to=${range.to}`); await expect(viewerPage.getByRole("heading",{level:1,name:"产品总表"})).toBeVisible(); const styleInfoTrigger=viewerPage.getByRole("button",{name:`查看款号 ${style!.style_code} 商品信息`}); await expect(styleInfoTrigger).toBeVisible();
  await styleInfoTrigger.click(); const productInfoDialog=viewerPage.getByRole("dialog"); await expect(productInfoDialog).toBeVisible(); const styleLink=productInfoDialog.getByRole("link",{name:"进入款式详情"}); await expect(styleLink).toBeVisible();
  await styleLink.click(); await expect(viewerPage).toHaveURL(new RegExp(`/products/${style!.style_id}`)); await expect(viewerPage.getByRole("heading",{level:1,name:style!.standard_name,exact:true})).toBeVisible(); await expect(viewerPage.getByRole("img",{name:/产品每日趋势/})).toBeVisible();
  expect(p0Requests).toContain("/api/dashboard/style-ledger"); expect(p0Requests).toContain(`/api/dashboard/styles/${style!.style_id}/card`); expect(p0Requests.some(path=>path.includes("product-ledger")||path.includes("product-card"))).toBe(false);
  for(const viewport of [{width:1440,height:900},{width:768,height:900},{width:390,height:844}]){await viewerPage.setViewportSize(viewport);await viewerPage.reload();await expect(viewerPage.getByRole("heading",{level:1,name:style!.standard_name})).toBeVisible();expect(await viewerPage.evaluate(()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth)).toBe(true);}
});
