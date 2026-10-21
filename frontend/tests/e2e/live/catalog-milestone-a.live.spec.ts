import { mkdir } from "node:fs/promises";
import { join } from "node:path";

import type { Locator, Page } from "@playwright/test";

import {
  expect,
  mutateWorkbookEField,
  requiredEnv,
  saveLiveResult,
  sha256File,
  test,
} from "./catalogLiveFixtures";

type ImportDetail = { status: string; workflow_revision: number };
type CatalogSection = "styles" | "skus" | "mappings" | "exceptions" | "evidence";
type CurrentCatalog = {
  catalog: null | {
    catalog_version_id: number;
    skus: Array<{ internal_display_sku: string }>;
    styles: Array<{ standard_name: string }>;
  };
};

const SECTION_LABELS: Record<CatalogSection, string> = {
  evidence: "来源证据",
  exceptions: "解析异常",
  mappings: "SKU 映射",
  skus: "SKU 标准化",
  styles: "款式命名",
};

async function saveRow(page: Page, row: Locator) {
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && response.url().includes("/api/catalog/imports/")
      && response.url().endsWith("/decisions")
  ));
  const reloadPromise = page.waitForResponse((response) => (
    response.request().method() === "GET"
      && /\/api\/catalog\/imports\/\d+$/.test(new URL(response.url()).pathname)
  ));
  const rowsReloadPromise = page.waitForResponse((response) => (
    response.request().method() === "GET"
      && /\/api\/catalog\/imports\/\d+\/rows\/(styles|skus|mappings|exceptions|evidence)$/.test(
        new URL(response.url()).pathname,
      )
  ));
  await row.getByRole("button", { name: "保存此行" }).click();
  const response = await responsePromise;
  const request = response.request();
  const responsePayload = await response.json() as unknown;
  const diagnostic = JSON.stringify({
    body: request.postDataJSON() as unknown,
    hasCsrf: Boolean(await request.headerValue("x-csrf-token")),
    idempotencyKey: await request.headerValue("idempotency-key"),
    response: responsePayload,
  });
  expect(response.ok(), diagnostic).toBeTruthy();
  expect((await reloadPromise).ok()).toBeTruthy();
  expect((await rowsReloadPromise).ok()).toBeTruthy();
  await expect(row.getByRole("button", { name: "保存此行" })).toBeEnabled();
}

async function selectSection(page: Page, section: CatalogSection) {
  const tab = page.getByRole("tab", { name: SECTION_LABELS[section] });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  if (section === "evidence") {
    await expect(page.getByRole("region", { name: "安全来源证据" })).toBeVisible();
  } else {
    await expect(page.locator(".catalog-table-scroll tbody tr").first()).toBeVisible();
  }
}

async function setReviewField(row: Locator, field: string, value: string) {
  const selector = `[aria-label$=" ${field}"]`;
  const editor = row.locator(selector);
  await expect(editor).toHaveCount(1);
  if (await editor.evaluate((element) => element.tagName === "SELECT")) {
    const hasValue = await editor.evaluate(
      (element, expected) => Array.from((element as HTMLSelectElement).options)
        .some((option) => option.value === expected),
      value,
    );
    if (hasValue) {
      await editor.selectOption(value);
      return;
    }
    await editor.selectOption("__manual__");
  }
  await row.locator(`input${selector}, textarea${selector}`).fill(value);
}

async function assertRequiredDraftFields(page: Page, importId: number) {
  const detailResponse = await page.request.get(`/api/catalog/imports/${importId}`);
  expect(detailResponse.ok()).toBeTruthy();
  const detail = await detailResponse.json() as ImportDetail;
  const requirements: Record<string, readonly string[]> = {
    mappings: ["identity_decision"],
    skus: ["internal_display_sku", "standard_color", "standard_size"],
    styles: ["standard_name"],
  };
  const missing: string[] = [];
  for (const [section, fields] of Object.entries(requirements)) {
    const response = await page.request.get(
      `/api/catalog/imports/${importId}/rows/${section}?page=1&page_size=200&workflow_revision=${detail.workflow_revision}`,
    );
    expect(response.ok()).toBeTruthy();
    const payload = await response.json() as {
      rows: Array<{ payload: Record<string, unknown>; projection_state: string; row_key: string }>;
    };
    for (const row of payload.rows) {
      if (row.projection_state !== "included") continue;
      for (const field of fields) {
        if (row.payload[field] === null || row.payload[field] === undefined || row.payload[field] === "") {
          missing.push(`${section}:${row.row_key.slice(0, 12)}:${field}`);
        }
      }
    }
  }
  expect(missing, JSON.stringify(missing)).toEqual([]);
}

test("Milestone A performs a real catalog approval, XLSX upload, RBAC, and reveal", async ({ page, viewerRequest }) => {
  test.setTimeout(120_000);
  const runtimeRoot = requiredEnv("CATALOG_LIVE_RUNTIME_ROOT");
  const downloadDirectory = join(runtimeRoot, "downloads");
  await mkdir(downloadDirectory, { recursive: true });

  await page.goto("/catalog");
  await expect(page.getByRole("heading", { name: "商品主档尚未初始化" })).toBeVisible();
  await page.getByRole("link", { name: "进入批量维护" }).click();
  await expect(page.getByRole("heading", { name: "批量维护" })).toBeVisible();
  const exportResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && response.url().endsWith("/api/catalog/exports")
  ));
  await page.getByRole("button", { name: "生成候选" }).click();
  const exportResponse = await exportResponsePromise;
  const exportRequest = exportResponse.request();
  const exportCreated = await exportResponse.json() as {
    export_id?: number;
    export_status?: string;
  };
  const exportDiagnostic = JSON.stringify({
    body: exportRequest.postDataJSON() as unknown,
    hasCsrf: Boolean(await exportRequest.headerValue("x-csrf-token")),
    idempotencyKey: await exportRequest.headerValue("idempotency-key"),
    response: exportCreated,
  });
  expect(exportResponse.ok(), exportDiagnostic).toBeTruthy();
  expect(exportCreated.export_id).toBeGreaterThan(0);
  await expect.poll(async () => {
    const response = await page.request.get(`/api/catalog/exports/${exportCreated.export_id}`);
    const status = await response.json() as {
      export_status: string;
      failure_reason_code: string | null;
      workbook_status: string | null;
    };
    if (status.export_status === "failed") {
      throw new Error(JSON.stringify(status));
    }
    return `${status.export_status}:${status.workbook_status}`;
  }, { timeout: 45_000 }).toBe("ready:ready");
  const downloadLink = page.getByRole("link", { name: "下载兼容 XLSX" });
  await expect(downloadLink).toBeVisible({ timeout: 45_000 });
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    downloadLink.click(),
  ]);
  const downloadedPath = join(downloadDirectory, "catalog-ready.xlsx");
  await download.saveAs(downloadedPath);
  const downloadSha256 = await sha256File(downloadedPath);

  await page.getByRole("button", { name: "开始在线审核" }).click();
  await page.waitForURL(/\/catalog\/imports\/\d+$/);
  const onlineImportId = Number(page.url().match(/\/imports\/(\d+)$/)?.[1]);
  expect(onlineImportId).toBeGreaterThan(0);

  const importResponse = await page.request.get(`/api/catalog/imports/${onlineImportId}`);
  const importDetail = await importResponse.json() as ImportDetail;
  const styleRowsResponse = await page.request.get(
    `/api/catalog/imports/${onlineImportId}/rows/styles?page=1&page_size=200&workflow_revision=${importDetail.workflow_revision}`,
  );
  const styleRowsPayload = await styleRowsResponse.json() as { rows: Array<{ row_key: string }> };
  expect(
    styleRowsPayload.rows.length,
    JSON.stringify({ importStatus: importDetail.status, styleRowCount: styleRowsPayload.rows.length }),
  ).toBeGreaterThan(0);

  const styleRows = page.locator(".catalog-table-scroll tbody tr");
  await expect(styleRows.first()).toBeVisible({ timeout: 15_000 });
  const onlyPending = page.getByRole("checkbox", { name: "仅看待处理" });
  await expect(onlyPending).toBeChecked();
  await onlyPending.uncheck();
  expect(await styleRows.count()).toBe(2);
  for (let index = 0; index < await styleRows.count(); index += 1) {
    const row = styleRows.nth(index);
    await setReviewField(
      row,
      "standard_name",
      index === 0 ? "Live 标准商品名称" : `Live 标准商品名称 ${index + 1}`,
    );
    await saveRow(page, row);
  }

  await selectSection(page, "skus");
  const skuRows = page.locator(".catalog-table-scroll tbody tr");
  expect(await skuRows.count()).toBe(11);
  for (let index = 0; index < await skuRows.count(); index += 1) {
    const row = skuRows.nth(index);
    await setReviewField(row, "internal_display_sku", `LIVE-DISPLAY-${index + 1}`);
    await setReviewField(row, "standard_color", `Live Color ${index + 1}`);
    await setReviewField(row, "standard_size", `Live Size ${index + 1}`);
    await saveRow(page, row);
  }

  await selectSection(page, "mappings");
  const mappingRows = page.locator(".catalog-table-scroll tbody tr");
  expect(await mappingRows.count()).toBeGreaterThanOrEqual(2);
  let sharedTarget = "";
  for (let index = 0; index < await mappingRows.count() && sharedTarget === ""; index += 1) {
    sharedTarget = await mappingRows.nth(index).locator('[aria-label$=" target_sku_row_key"]').inputValue();
  }
  expect(sharedTarget).not.toBe("");
  let correctedAnomaly = false;
  let excludedCandidate = false;
  for (let index = 0; index < await mappingRows.count(); index += 1) {
    const row = mappingRows.nth(index);
    const suggestedTarget = await row.locator('[aria-label$=" target_sku_row_key"]').inputValue();
    if (suggestedTarget !== "" && suggestedTarget !== sharedTarget && !excludedCandidate) {
      await setReviewField(row, "identity_decision", "excluded");
      await setReviewField(row, "exclusion_reason", "Excluded candidate retained for live audit evidence");
      await setReviewField(row, "change_reason", "Live audit-only candidate mapping");
      excludedCandidate = true;
    } else if (suggestedTarget !== "") {
      await setReviewField(row, "identity_decision", "mapped");
      await setReviewField(row, "change_reason", "Accepted strict live candidate");
    } else if (!correctedAnomaly) {
      await setReviewField(row, "identity_decision", "mapped");
      await setReviewField(row, "target_sku_row_key", sharedTarget);
      await setReviewField(row, "change_reason", "Live corrected anomaly mapping");
      correctedAnomaly = true;
    } else {
      await setReviewField(row, "identity_decision", "excluded");
      await setReviewField(row, "exclusion_reason", "Excluded by live acceptance evidence");
      await setReviewField(row, "change_reason", "Live excluded anomaly mapping");
    }
    await saveRow(page, row);
  }
  expect(correctedAnomaly).toBeTruthy();
  expect(excludedCandidate).toBeTruthy();

  await selectSection(page, "exceptions");
  const exceptionRows = page.locator(".catalog-table-scroll tbody tr");
  expect(await exceptionRows.count()).toBeGreaterThanOrEqual(2);
  const corrected = exceptionRows.first();
  await setReviewField(corrected, "action", "correct_parse");
  await setReviewField(corrected, "target_sku_row_key", sharedTarget);
  await setReviewField(corrected, "corrected_style_code", "100");
  await setReviewField(corrected, "corrected_standard_color", "Live Color 1");
  await setReviewField(corrected, "corrected_standard_size", "Live Size 1");
  await saveRow(page, corrected);
  for (let index = 1; index < await exceptionRows.count(); index += 1) {
    const excluded = exceptionRows.nth(index);
    await setReviewField(excluded, "action", "exclude");
    await setReviewField(excluded, "exclusion_reason", "Excluded by live acceptance evidence");
    await saveRow(page, excluded);
  }

  await assertRequiredDraftFields(page, onlineImportId);

  const validateResponsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
      && response.url().endsWith(`/api/catalog/imports/${onlineImportId}/validate`)
  ));
  await page.getByRole("button", { name: "重新校验" }).click();
  const validateResponse = await validateResponsePromise;
  const validateEnvelope = await validateResponse.json() as {
    safe_result?: {
      blocking_issue_count?: number;
      status?: string;
      workflow_revision?: number;
    };
    blocking_issue_count?: number;
    status?: string;
    workflow_revision?: number;
  };
  const validateResult = validateEnvelope.safe_result ?? validateEnvelope;
  expect(validateResponse.ok(), JSON.stringify(validateResult)).toBeTruthy();
  expect(validateResult.blocking_issue_count, JSON.stringify(validateResult)).toBe(0);
  expect(validateResult.status, JSON.stringify(validateResult)).toBe("validated");
  await expect.poll(async () => {
    const response = await page.request.get(`/api/catalog/imports/${onlineImportId}`);
    if (!response.ok()) return "http-error";
    const detail = await response.json() as ImportDetail & { permissions: { can_submit: boolean } };
    return `${detail.status}:${detail.workflow_revision}:${detail.permissions.can_submit}`;
  }).toBe(`validated:${validateResult.workflow_revision}:true`);
  await expect(page.getByRole("button", { name: "提交审核" })).toBeVisible();
  await page.getByRole("button", { name: "提交审核" }).click();
  await expect(page.getByRole("button", { name: "生成批准预览" })).toBeVisible();
  await page.getByRole("button", { name: "生成批准预览" }).click();
  await expect(page.getByText("风险：普通")).toBeVisible();
  await page.getByRole("button", { name: "确认批准目录" }).click();

  await expect.poll(async () => {
    const response = await page.request.get("/api/catalog/styles");
    if (!response.ok()) return null;
    return (await response.json() as CurrentCatalog).catalog?.catalog_version_id ?? null;
  }).not.toBeNull();
  const currentResponse = await page.request.get("/api/catalog/styles");
  const current = await currentResponse.json() as CurrentCatalog;
  const catalogVersionId = current.catalog?.catalog_version_id ?? 0;
  expect(current.catalog?.styles).toHaveLength(2);
  expect(current.catalog?.styles.map((style) => style.standard_name).sort()).toEqual([
    "Live 标准商品名称",
    "Live 标准商品名称 2",
  ].sort());
  expect(current.catalog?.skus).toHaveLength(10);

  await page.goto(`/catalog/imports/${onlineImportId}`);
  await selectSection(page, "evidence");
  const dangerousRaw = 'LIVE-DANGER</script>&"RAW';
  await expect(page.locator("body")).not.toContainText(dangerousRaw);
  const unsafeItem = page.locator("li", { hasText: "LIVE-DANGER /script RAW" });
  await expect(unsafeItem).toBeVisible();
  await expect(unsafeItem).toContainText("含危险字符");
  await unsafeItem.getByRole("button", { name: "查看完整标识" }).click();
  await expect(unsafeItem.locator("output")).toHaveText(dangerousRaw);
  await page.goto("/catalog");
  await expect(page.locator("body")).not.toContainText(dangerousRaw);

  const mutatedPath = join(downloadDirectory, "catalog-ready-e-field.xlsx");
  await mutateWorkbookEField(downloadedPath, mutatedPath);
  await page.getByRole("link", { name: "进入批量维护" }).click();
  await expect(page.getByRole("heading", { name: "批量维护" })).toBeVisible();
  await page.locator('input[type="file"][accept=".xlsx"]').setInputFiles(mutatedPath);
  await page.getByRole("button", { name: "上传并进入审核" }).click();
  await page.waitForURL(/\/catalog\/imports\/\d+$/);
  const rawImportId = Number(page.url().match(/\/imports\/(\d+)$/)?.[1]);
  expect(rawImportId).toBeGreaterThan(onlineImportId);
  let rawStatus = "";
  await expect.poll(async () => {
    const response = await page.request.get(`/api/catalog/imports/${rawImportId}`);
    if (!response.ok()) return "http-error";
    rawStatus = (await response.json() as ImportDetail).status;
    return rawStatus;
  }, { timeout: 45_000 }).not.toMatch(/^(uploaded|parsing)$/);
  expect(rawStatus).not.toBe("parse_failed");

  expect((await viewerRequest.get("/api/catalog/styles")).status()).toBe(200);
  for (const path of [
    `/api/catalog/imports/${onlineImportId}`,
    `/api/catalog/imports/${rawImportId}/file`,
    "/api/catalog/versions",
    `/api/catalog/versions/${catalogVersionId}/diff`,
    `/api/catalog/evidence?version_id=${catalogVersionId}`,
  ]) {
    expect((await viewerRequest.get(path)).status(), path).toBe(403);
  }

  await saveLiveResult({
    catalog_version_id: catalogVersionId,
    download_path: downloadedPath,
    download_sha256: downloadSha256,
    online_import_id: onlineImportId,
    raw_import_id: rawImportId,
    raw_import_status: rawStatus,
  });
});
