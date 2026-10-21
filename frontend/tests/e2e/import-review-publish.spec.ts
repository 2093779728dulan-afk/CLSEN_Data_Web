import { expect, test, type Page, type Route } from "@playwright/test";

const reportType = "business_report" as const;
const rulesetVersion = "business_report_v1";
const csrfToken = "playwright-csrf-token";
const parseDigest = "a".repeat(64);
const draftDigest = "b".repeat(64);
const validationDigest = "c".repeat(64);
const productAnalyticsSource = process.env.VITE_PRODUCT_ANALYTICS_SOURCE ?? "p0_catalog";

type CapturedCommand = {
  body: Record<string, unknown>;
  csrf: string | undefined;
  idempotencyKey: string | undefined;
};

type CapturedFlow = {
  confirmParse?: CapturedCommand;
  markReady?: CapturedCommand;
  materialize?: CapturedCommand;
  publish?: CapturedCommand;
  runValidation?: CapturedCommand;
  upload?: {
    bytes: number;
    csrf: string | undefined;
    filename: string | undefined;
    idempotencyKey: string | undefined;
  };
};

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({
    body: JSON.stringify(payload),
    contentType: "application/json",
    status,
  });
}

function jsonObject(route: Route): Record<string, unknown> {
  const value: unknown = route.request().postDataJSON();
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`Expected a JSON object for ${route.request().method()} ${route.request().url()}.`);
  }
  return value as Record<string, unknown>;
}

function captureCommand(route: Route): CapturedCommand {
  const headers = route.request().headers();
  return {
    body: jsonObject(route),
    csrf: headers["x-csrf-token"],
    idempotencyKey: headers["idempotency-key"],
  };
}

function stateError(route: Route, message: string) {
  return json(route, {
    error: {
      code: "invalid_e2e_fixture_state",
      message,
      request_id: "playwright",
    },
  }, 409);
}

async function installReviewApi(page: Page): Promise<CapturedFlow> {
  const captured: CapturedFlow = {};
  let uploaded = false;
  let inspected = false;
  let parsed = false;
  let materialized = false;
  let validated = false;
  let ready = false;
  let published = false;
  let reportDate = "";

  await page.context().addCookies([{
    name: "clsen_csrf",
    sameSite: "Lax",
    url: "http://127.0.0.1:5173",
    value: csrfToken,
  }]);

  const validationSummary = () => ({
    schema_version: 1,
    report_date: reportDate,
    report_type: reportType,
    row_count: 1,
    totals: { ordered_product_sales: "10.00" },
    stages: {
      parse_fidelity: {
        data_digest: parseDigest,
        row_count: 1,
        totals: { ordered_product_sales: "10.00" },
        warning_count: 0,
        blocking_count: 0,
      },
      draft_explainability: {
        data_digest: draftDigest,
        row_count: 1,
        totals: { ordered_product_sales: "10.00" },
        warning_count: 0,
        blocking_count: 0,
      },
    },
  });

  const head = () => ({
    version_id: 301,
    dataset_id: 201,
    version_no: 1,
    status: ready ? "ready_for_publish" : "draft",
    data_revision: 0,
    review_revision: ready ? 1 : 0,
    pointed_at: "2026-08-10T01:00:00Z",
  });

  const validation = () => ({
    id: 401,
    version_id: 301,
    data_revision: 0,
    ruleset_version: rulesetVersion,
    status: "succeeded",
    result: "passed",
    data_digest: validationDigest,
    summary: validationSummary(),
    started_at: "2026-08-10T01:01:00Z",
    completed_at: "2026-08-10T01:01:01Z",
    is_current: true,
    issues: [],
  });

  const version = () => ({
    dataset_id: 201,
    version_id: 301,
    report_date: reportDate,
    report_type: reportType,
    version_no: 1,
    status: published ? "published" : ready ? "ready_for_publish" : "draft",
    data_revision: 0,
    review_revision: ready ? 1 : 0,
    created_at: "2026-08-10T01:00:00Z",
    sealed_at: published ? "2026-08-10T01:02:00Z" : null,
    is_current_publication: published,
    published_at: published ? "2026-08-10T01:02:00Z" : null,
    is_active_draft: materialized && !published,
    draft_pointed_at: materialized && !published ? "2026-08-10T01:00:00Z" : null,
  });

  const workspace = () => ({
    head: head(),
    report_date: reportDate,
    report_type: reportType,
    ruleset_version: rulesetVersion,
    source_batches: [{ batch_id: 101 }],
    fields: [{
      ascii_only: false,
      editable: true,
      included_in_totals: true,
      kind: "decimal",
      max_length: null,
      name: "ordered_product_sales",
      nullable: false,
      precision: 12,
      required_on_add: true,
      scale: 2,
    }],
    rows: [{
      base_row_id: 601,
      cells: [{
        base: { type: "decimal", value: "10.00" },
        changed_from_base: false,
        changed_from_source: false,
        current: { type: "decimal", value: "10.00" },
        field_name: "ordered_product_sales",
        history: [],
        notes: [],
        parent_restore_options: [],
        source: { type: "decimal", value: "10.00" },
        source_restore_option: {
          parsed_source_row_id: 701,
          source_batch_id: 101,
          value: { type: "decimal", value: "10.00" },
        },
      }],
      history: [],
      logical_row_id: "00000000-0000-4000-8000-000000000601",
      notes: [],
      original_parsed_source_row_id: 701,
      row_id: 601,
      row_ordinal: 1,
      row_state: "active",
    }],
    version_notes: [],
    latest_full_validation: validated ? validation() : null,
    publication_mode: "ordinary",
    published_move: null,
    pagination: { page: 1, page_size: 50, total_rows: 1, total_pages: 1 },
  });

  await page.route((url) => url.pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();

    if (path === "/api/auth/me" && method === "GET") {
      return json(route, {
        id: 1,
        username: "stage-eight-admin",
        display_name: "阶段八管理员",
        roles: ["admin"],
      });
    }
    if (path === "/api/data-calendar/site-context" && method === "GET") {
      return json(route, {
        site_id: 1,
        site_code: "amazon_us",
        display_name: "Amazon US",
        site_config_version_id: 1,
        source_timezone: "America/Los_Angeles",
        reporting_timezone: "America/Los_Angeles",
        currency_code: "USD",
      });
    }
    if (path === "/api/data-calendar" && method === "GET") {
      return json(route, published ? [version()] : []);
    }
    if (path === "/api/data-calendar/days" && method === "GET") {
      return json(route, [{
        report_date: reportDate,
        status: published ? "blue" : materialized ? "yellow" : "gray",
        published_report_types: published ? [reportType] : [],
        draft_report_types: materialized && !published ? [reportType] : [],
        reasons: materialized && !published ? ["draft"] : [],
      }]);
    }
    if (path.startsWith("/api/workbench/dates/") && method === "GET") {
      const workbenchDate = path.slice("/api/workbench/dates/".length);
      return json(route, {
        actions: [],
        columns: [],
        head: null,
        pagination: { page: 1, page_size: 50, total_pages: 1, total_rows: 0 },
        pending_upload_count: 0,
        permissions: { can_create_revision: false, can_edit: false, can_publish: false, can_undo: false, can_upload: true, can_validate: false },
        report_date: workbenchDate,
        report_type: url.searchParams.get("report_type") ?? reportType,
        rows: [],
        source: "empty",
        tabs: [
          { dataset_id: null, report_type: "business_report", source: "empty", status: null, version_id: null },
          { dataset_id: null, report_type: "return_report", source: "empty", status: null, version_id: null },
        ],
        validation: null,
      });
    }
    if (path === "/api/admin/published-moves/undoable" && method === "GET") {
      return json(route, []);
    }
    if (path === "/api/imports/batch-reviews" && method === "GET") {
      return json(route, { items: [], has_next: false });
    }
    if (path === "/api/dashboard/daily-ledger" && method === "GET") {
      return json(route, {
        publications: [],
        range: {
          from_date: url.searchParams.get("from") ?? "2026-08-01",
          to_date: url.searchParams.get("to") ?? "2026-08-31",
        },
        rows: published && reportDate ? [{
          business_status: "published",
          conversion_rate: "0.1",
          counts_as_incomplete: true,
          overall_status: "partial",
          pending_summary: "退货报告缺失",
          reasons: [],
          report_date: reportDate,
          return_quantity: null,
          return_status: "missing",
          sales: "10.00",
          sessions: 10,
          units_ordered: 1,
        }] : [],
        site_config_versions: [],
      });
    }
    if (path === "/api/dashboard/product-ledger" && method === "GET") {
      return json(route, {
        direction: url.searchParams.get("direction") ?? "desc",
        page: Number(url.searchParams.get("page") ?? 1),
        page_size: Number(url.searchParams.get("page_size") ?? 25),
        publications: [],
        range: { from_date: url.searchParams.get("from"), to_date: url.searchParams.get("to") },
        rows: published ? [{
          color_count: 1,
          conversion_rate: "0.1",
          latest_published_date: reportDate,
          name_status: "available",
          product_name: "浏览器验收商品",
          published_days: 1,
          return_quantity: 0,
          row_kind: "product",
          sales: "10.00",
          sessions: 10,
          size_count: 1,
          style_code: "2301",
          unclassified_sku: null,
          units_ordered: 1,
          variant_count: 1,
        }] : [],
        site_config_versions: [],
        sort: url.searchParams.get("sort") ?? "sales",
        total_rows: published ? 1 : 0,
      });
    }
    if (path === "/api/dashboard/product-card/2301" && method === "GET") {
      return json(route, {
        latest_published_date: reportDate,
        name_status: "available",
        product_name: "浏览器验收商品",
        publications: [],
        range: { from_date: url.searchParams.get("from"), to_date: url.searchParams.get("to") },
        site_config_versions: [],
        style_code: "2301",
        summary: { conversion_rate: "0.1", published_days: 1, return_quantity: 0, sales: "10.00", sessions: 10, units_ordered: 1 },
        trend: [{ conversion_rate: "0.1", report_date: reportDate, return_quantity: 0, sales: "10.00", sessions: 10, units_ordered: 1 }],
        variants: [{ asins: ["B000000001"], color: "White", fnskus: ["X000000001"], product_name: "浏览器验收商品", seller_sku: "2301-White-S", size: "S" }],
      });
    }
    if (path === "/api/imports" && method === "POST") {
      uploaded = true;
      reportDate = url.searchParams.get("report_date") ?? "2026-08-10";
      const headers = request.headers();
      captured.upload = {
        bytes: request.postDataBuffer()?.byteLength ?? 0,
        csrf: headers["x-csrf-token"],
        filename: headers["x-original-filename"],
        idempotencyKey: headers["idempotency-key"],
      };
      return json(route, {
        batch_id: 101,
        raw_file_id: 91,
        sha256_hex: "a".repeat(64),
        duplicate: false,
        content_reused: false,
      }, 201);
    }
    if (path === "/api/imports/101/inspect" && method === "POST") {
      if (!uploaded) return stateError(route, "Inspection must follow immutable upload.");
      inspected = true;
      return json(route, {
        status: "recognized",
        report_type: reportType,
        report_date: reportDate,
        encoding: "utf-8-sig",
        ruleset_version: rulesetVersion,
        issue_codes: [],
      });
    }
    if (path === "/api/imports/101/raw-file" && method === "HEAD") {
      return route.fulfill({ body: "", status: 200 });
    }
    if (path === "/api/imports/101/confirm-parse" && method === "POST") {
      if (!inspected) return stateError(route, "Parse confirmation must follow inspection.");
      parsed = true;
      captured.confirmParse = captureCommand(route);
      return json(route, {
        result: {
          batch_id: 101,
          parse_attempt_id: 111,
          parse_baseline_id: 121,
          confirmation_revision: 1,
          report_type: reportType,
          source_row_count: 1,
        },
      });
    }
    if (path === "/api/datasets/materialize" && method === "POST") {
      if (!parsed) return stateError(route, "Draft materialization must follow a successful parse.");
      materialized = true;
      captured.materialize = captureCommand(route);
      return json(route, {
        data_revision: 0,
        dataset_id: 201,
        operation_token: captured.materialize.idempotencyKey,
        review_revision: 0,
        source_dataset_id: null,
        source_version_id: null,
        status: "draft",
        superseded_version_ids: [],
        version_id: 301,
      });
    }
    if (path === "/api/drafts/301" && method === "GET") {
      if (!materialized) return stateError(route, "Draft head does not exist before materialization.");
      return json(route, head());
    }
    if (path === "/api/drafts/301/review-workspace" && method === "GET") {
      if (!materialized) return stateError(route, "Review workspace does not exist before materialization.");
      return json(route, workspace());
    }
    if (path === "/api/validation-runs/301" && method === "POST") {
      if (!materialized) return stateError(route, "Validation must target a materialized draft.");
      validated = true;
      captured.runValidation = captureCommand(route);
      return json(route, {
        validation_run_id: 401,
        version_id: 301,
        data_revision: 0,
        status: "succeeded",
        result: "passed",
        data_digest: validationDigest,
        summary: validationSummary(),
      });
    }
    if (path === "/api/drafts/301/mark-ready" && method === "POST") {
      if (!validated) return stateError(route, "Human confirmation requires a current validation.");
      captured.markReady = captureCommand(route);
      ready = true;
      return json(route, {});
    }
    if (path === "/api/datasets/201/publish" && method === "POST") {
      if (!ready) return stateError(route, "Publication requires a ready draft.");
      captured.publish = captureCommand(route);
      published = true;
      return json(route, {
        operation_token: captured.publish.idempotencyKey,
        command_id: 501,
        command_type: "publish",
        transitions: [{
          dataset_id: 201,
          event_id: 501,
          event_type: "published",
          next_version_id: 301,
          peer_dataset_id: null,
          previous_version_id: null,
          sequence_number: 1,
        }],
        completed_at: "2026-08-10T01:02:00Z",
      });
    }
    if (path === "/api/versions" && method === "GET") {
      return json(route, materialized ? [version()] : []);
    }
    if (path === "/api/versions/301" && method === "GET") {
      if (!published) return stateError(route, "Immutable version detail is available after publication.");
      return json(route, {
        ...version(),
        parents: [],
        children: [],
        viewer_visible_notes: [{
          body: "浏览器验收发布版本",
          created_at: "2026-08-10T01:01:30Z",
          note_key: "e2e-public-note",
          revision_number: 1,
        }],
      });
    }
    return json(route, {
      error: {
        code: "unhandled_e2e_route",
        message: `${method} ${path} is not handled by the browser fixture.`,
        request_id: "playwright",
      },
    }, 500);
  });

  return captured;
}

test("orchestrates upload, review, publication, and immutable-version viewing against strict API fixtures", async ({ page }) => {
  const browserErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) browserErrors.push(`${response.status()} ${response.url()}`);
  });
  const captured = await installReviewApi(page);
  await page.goto("/");

  expect(browserErrors).toEqual([]);
  await expect(page.getByRole("heading", { name: "发布数据总表" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "每日总表" })).toBeVisible();
  await page.getByRole("button", { name: "进入今日审核" }).click();
  await expect(page.getByRole("heading", { name: "导入先审核，发布后才进入看板" })).toBeVisible();
  const dateInput = page.getByLabel("识别不到日期时的归属日");
  const selectedDate = await dateInput.inputValue();
  await page.getByLabel("CSV 文件", { exact: true }).setInputFiles({
    name: "经营日报.csv",
    mimeType: "text/csv",
    // API parsing is covered by backend integration tests. This browser fixture
    // verifies the UI state machine and exact HTTP command contracts.
    buffer: Buffer.from("(Parent) ASIN,Title\nB000000001,示例商品\n", "utf8"),
  });
  await page.getByRole("button", { name: "保存并检查文件" }).click();

  await expect(page.getByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
  await expect(page.getByLabel("所属报告日")).toHaveValue(selectedDate);
  await page.getByRole("button", { name: "确认并解析" }).click();
  await expect(page.getByRole("heading", { name: "已解析 1 行源数据" })).toBeVisible();

  await page.getByLabel("生成草稿原因").fill("浏览器主流程验收");
  await page.getByRole("button", { name: "生成审核草稿" }).click();
  await expect(page.getByRole("heading", { name: "草稿审核 · v1" })).toBeVisible();
  await expect(page.getByText("当前筛选没有匹配行", { exact: true })).toBeVisible();
  await page.getByLabel("仅看差异").uncheck();
  await expect(page.getByRole("button", { name: "ordered_product_sales，当前值 10.00" })).toBeVisible();

  await page.getByRole("button", { name: "运行草稿校验" }).click();
  await expect(page.getByText("完整校验已通过。")).toBeVisible();
  await page.getByLabel("审核确认说明").fill("已与原表逐项核对");
  await page.getByRole("button", { name: "确认结果并标记待发布" }).click();

  await expect(page.getByText("审核结果已确认，草稿进入待发布状态。")).toBeVisible();
  await page.getByRole("button", { name: "打开发布确认" }).click();
  await page.getByLabel("发布说明").fill("确认发布浏览器验收版本");
  await page.getByRole("button", { name: "确认发布" }).click();
  await expect(page.getByRole("heading", { name: "版本 v1 已发布" })).toBeVisible();

  await page.getByRole("link", { name: /发布总表/ }).click();
  await expect(page.getByRole("heading", { name: "发布数据总表" })).toBeVisible();
  await expect(page.getByText(selectedDate)).toBeVisible();
  await expect(page.getByText("退货报告缺失")).toBeVisible();
  if (productAnalyticsSource === "legacy_parser") {
    await page.getByRole("tab", { name: "产品总表" }).click();
    await page.getByRole("row", { name: "打开款号 2301 商品信息" }).click();
    await expect(page.getByRole("heading", { name: "浏览器验收商品" })).toBeVisible();
    await expect(page.getByText("2301-White-S")).toBeVisible();
    await expect(page.getByText("B000000001")).toBeVisible();
    await page.getByRole("button", { name: "关闭商品信息" }).click();
  } else {
    await expect(page.getByRole("tab", { name: "产品总表" })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "产品分析" })).toBeVisible();
  }

  await page.getByRole("link", { name: /版本记录/ }).click();
  await expect(page.getByRole("button", { name: /查看版本 v1/ })).toBeVisible();
  await expect(page.getByText("浏览器验收发布版本")).toBeVisible();
  await expect(page.getByText(selectedDate).first()).toBeVisible();

  expect(captured.upload).toEqual({
    bytes: Buffer.byteLength("(Parent) ASIN,Title\nB000000001,示例商品\n", "utf8"),
    csrf: csrfToken,
    filename: encodeURIComponent("经营日报.csv"),
    idempotencyKey: undefined,
  });
  expect(captured.confirmParse?.body).toEqual({
    encoding: "utf-8-sig",
    report_date: selectedDate,
    report_type: reportType,
  });
  expect(captured.materialize?.body).toEqual({
    batch_id: 101,
    expected_active_draft: null,
    expected_publication_version_id: null,
    merge_decisions: [],
    parse_baseline_id: 121,
    reason: "浏览器主流程验收",
    report_date: selectedDate,
    strategy: "merge",
  });
  expect(captured.runValidation?.body).toEqual({
    data_revision: 0,
    dataset_id: 201,
    ruleset_version: rulesetVersion,
  });
  expect(captured.markReady?.body).toMatchObject({
    confirmed_report_date: selectedDate,
    confirmed_report_type: reportType,
    confirmed_row_count: 1,
    confirmed_totals: { ordered_product_sales: "10.00" },
    data_revision: 0,
    dataset_id: 201,
    reason: "已与原表逐项核对",
    review_revision: 0,
    ruleset_version: rulesetVersion,
    status: "draft",
    validation_data_digest: validationDigest,
    validation_run_id: 401,
  });
  expect(captured.publish?.body).toMatchObject({
    confirmation: {
      confirmed_report_date: selectedDate,
      report_type: reportType,
      row_count: 1,
      totals: [{ field_name: "ordered_product_sales", value: "10.00" }],
    },
    expected_draft: {
      data_revision: 0,
      review_revision: 1,
      status: "ready_for_publish",
      version_id: 301,
    },
    expected_publication: { published_at: null, version_id: null },
    reason: "确认发布浏览器验收版本",
    validation: {
      data_digest: validationDigest,
      data_revision: 0,
      ruleset_version: rulesetVersion,
      run_id: 401,
      version_id: 301,
    },
  });
  for (const command of [
    captured.confirmParse,
    captured.materialize,
    captured.runValidation,
    captured.markReady,
    captured.publish,
  ]) {
    expect(command?.csrf).toBe(csrfToken);
    expect(command?.idempotencyKey).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
  }
  expect(browserErrors).toEqual([]);
});
