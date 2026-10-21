import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import type { DraftHead, ReviewWorkspace, ValidationRun, VersionSummary } from "../../api/types";
import { ImportReviewFlow } from "./ImportReviewFlow";
import { initialImportReviewState } from "./importReviewReducer";
import { reviewRecoveryKey, saveReviewRecovery } from "./reviewRecovery";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function jsonRequestBody(init?: RequestInit) {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body.");
  return JSON.parse(init.body) as Record<string, unknown>;
}

function pathOf(input: string | URL | Request) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

const draftHead = {
  dataset_id: 41,
  version_id: 51,
  version_no: 1,
  status: "draft",
  data_revision: 0,
  review_revision: 0,
  pointed_at: "2026-08-10T02:00:00Z",
} as const;

const validation: ValidationRun = {
  validation_run_id: 61,
  version_id: 51,
  data_revision: 0,
  status: "succeeded",
  result: "passed",
  data_digest: "a".repeat(64),
  summary: {
    schema_version: 1,
    report_date: "2026-08-10",
    report_type: "business_report",
    row_count: 2,
    totals: { ordered_product_sales: "42.50", units_ordered: "3" },
    stages: {
      parse_fidelity: {
        data_digest: "b".repeat(64),
        row_count: 2,
        totals: { ordered_product_sales: "42.50", units_ordered: "3" },
        warning_count: 0,
        blocking_count: 0,
      },
      draft_explainability: {
        data_digest: "a".repeat(64),
        row_count: 2,
        totals: { ordered_product_sales: "42.50", units_ordered: "3" },
        warning_count: 0,
        blocking_count: 0,
      },
    },
  },
};

function reviewWorkspace(
  head: DraftHead = draftHead,
  latestValidation: ValidationRun | null = null,
): ReviewWorkspace {
  return {
    head,
    report_date: "2026-08-10",
    report_type: "business_report",
    ruleset_version: "business_report_v1",
    publication_mode: "ordinary",
    published_move: null,
    source_batches: [{ batch_id: 11 }],
    fields: [],
    rows: [],
    version_notes: [],
    latest_full_validation: latestValidation ? {
      id: latestValidation.validation_run_id,
      data_revision: latestValidation.data_revision,
      ruleset_version: "business_report_v1",
      status: latestValidation.status,
      result: latestValidation.result,
      data_digest: latestValidation.data_digest,
      summary: latestValidation.summary,
      started_at: "2026-08-10T02:30:00Z",
      completed_at: "2026-08-10T02:31:00Z",
      is_current: true,
      issues: [],
    } : null,
    pagination: { page: 1, page_size: 50, total_rows: 0, total_pages: 0 },
  };
}

function targetVersion(overrides: Partial<VersionSummary> = {}): VersionSummary {
  return {
    created_at: "2026-08-10T01:00:00Z",
    data_revision: 2,
    dataset_id: 42,
    dedup_publication_revision: null,
    draft_pointed_at: null,
    is_active_draft: false,
    is_current_publication: true,
    published_at: "2026-08-10T02:00:00Z",
    publication_revision: null,
    report_date: "2026-08-10",
    report_type: "business_report",
    review_revision: 1,
    sealed_at: "2026-08-10T02:00:00Z",
    status: "published",
    version_id: 62,
    version_no: 4,
    ...overrides,
  };
}

describe("ImportReviewFlow", () => {
  it("starts the empty advanced intake with the route's report type", async () => {
    render(<ImportReviewFlow reportDate="2026-08-13" initialReportType="return_report" onPublished={vi.fn()} />);
    expect(await screen.findByText("2026-08-13 · 退货报告")).toBeVisible();
  });

  beforeEach(() => {
    window.sessionStorage.clear();
    setSessionCsrfToken("csrf-test-token");
  });

  afterEach(() => {
    setSessionCsrfToken(undefined);
    window.sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("inspects the explicit source instead of restoring an old draft", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path.endsWith("/inspect")) return Promise.resolve(jsonResponse({ status: "recognized", report_type: "business_report", report_date: "2026-08-10", encoding: "utf-8-sig", ruleset_version: "test-v1", issue_codes: [] }));
      return Promise.resolve(jsonResponse({ batch_id: 44, columns: [], rows: [], page: 1, page_size: 30, total_pages: 0, total_rows: 0 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ImportReviewFlow initialBatchId={44} initialVersionId={51} onPublished={vi.fn()} reportDate="2026-08-10" />);
    expect(await screen.findByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
    expect(fetchMock.mock.calls.some(([path]) => pathOf(path) === "/api/imports/44/inspect")).toBe(true);
    expect(fetchMock.mock.calls.some(([path]) => pathOf(path).startsWith("/api/drafts/51/"))).toBe(false);
    expect(screen.getByRole("link", { name: "下载原始 CSV" })).toHaveAttribute("href", "/api/imports/44/raw-file");
  });

  it("prefills the draft reason from the authenticated operator and source batch", async () => {
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    }));

    const user = userEvent.setup();
    const view = render(
      <ImportReviewFlow
        onPublished={vi.fn()}
        operator={{ id: 3, username: "manager", display_name: "录入审核" }}
        reportDate="2026-08-10"
      />,
    );
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    await user.click(await screen.findByRole("button", { name: "确认并解析" }));

    expect(await screen.findByLabelText("生成草稿原因")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：生成 2026-08-10 经营报告审核草稿；来源：导入批次 #11 · 原始文件 经营报告.csv。",
    );
    expect(screen.getByText(/操作人来源：当前登录会话/)).toBeVisible();
    expect(screen.getByRole("button", { name: "生成审核草稿" })).toBeEnabled();
    view.unmount();
    window.sessionStorage.clear();
  });

  it("exposes batch notes after the original file is saved without reading them eagerly", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/notes") return Promise.resolve(jsonResponse([]));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" />);
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));

    expect(await screen.findByRole("button", { name: "管理批次备注" })).toBeVisible();
    expect(fetchMock.mock.calls.some(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path === "/api/imports/11/notes";
    })).toBe(false);
    await user.click(screen.getByRole("button", { name: "管理批次备注" }));
    expect(await screen.findByText("这个导入批次还没有备注。" )).toBeVisible();
  });

  it("restores an unfinished upload review after the page is left and reopened", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    const first = render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" />);
    await user.upload(screen.getByLabelText("CSV 文件"), new File(["sku\nA"], "经营报告.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    expect(await screen.findByRole("heading", { name: "人工确认识别结果" })).toBeVisible();

    first.unmount();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" />);

    expect(screen.getByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
    expect(screen.getByText(/经营报告\.csv · SHA-256/)).toBeVisible();
    expect(screen.getByRole("button", { name: "查看上传源表" })).toBeVisible();
    expect(fetchMock.mock.calls.filter(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path.startsWith("/api/imports?");
    })).toHaveLength(1);
  });

  it("probes restored batch identities once without repeating HEAD for field changes", async () => {
    const reviewState = initialImportReviewState("2026-08-10");
    reviewState.activeQueueId = "restored-11";
    reviewState.importQueue = [{
      assignedDate: "2026-08-10",
      encoding: "utf-8-sig",
      id: "restored-11",
      inspection: {
        encoding: "utf-8-sig",
        issue_codes: [],
        report_date: "2026-08-10",
        report_type: "business_report",
        ruleset_version: "business_report_v1",
        status: "recognized",
      },
      reportType: "business_report",
      status: "ready",
      upload: { fileName: "restored.csv", upload: { batch_id: 11 } },
    }];
    saveReviewRecovery(
      { reportDate: "2026-08-10", siteId: 3, userId: 5 },
      { materializeReason: "", noteBatchIds: [11], reviewState },
    );
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "HEAD") return Promise.resolve(new Response(null, { status: 200 }));
      throw new Error("Only the restored raw-file HEAD probe is expected.");
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" siteId={3} userId={5} />);
    expect(await screen.findByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
    await waitFor(() => expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "HEAD")).toHaveLength(1));

    await user.selectOptions(screen.getByLabelText("文件编码"), "utf-8");
    await user.clear(screen.getByLabelText("所属报告日"));
    await user.type(screen.getByLabelText("所属报告日"), "2026-08-11");
    await Promise.resolve();

    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "HEAD")).toHaveLength(1);
  });

  it("keeps a restored 409 batch visible and marks it unavailable", async () => {
    const reviewState = initialImportReviewState("2026-08-10");
    reviewState.activeQueueId = "restored-11";
    reviewState.importQueue = [{
      assignedDate: "2026-08-10",
      encoding: "utf-8-sig",
      id: "restored-11",
      inspection: {
        encoding: "utf-8-sig",
        issue_codes: [],
        report_date: "2026-08-10",
        report_type: "business_report",
        ruleset_version: "business_report_v1",
        status: "recognized",
      },
      reportType: "business_report",
      status: "ready",
      upload: { fileName: "restored.csv", upload: { batch_id: 11 } },
    }];
    saveReviewRecovery(
      { reportDate: "2026-08-10", siteId: 3, userId: 5 },
      { materializeReason: "", noteBatchIds: [11], reviewState },
    );
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(null, { status: 409 }))));

    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" siteId={3} userId={5} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("原文件暂不可用");
    expect(screen.getAllByText("restored.csv").length).toBeGreaterThan(0);
    expect(screen.getByText("原文件完整性检查未通过，当前批次暂不可用。")).toBeVisible();
  });

  it("hands off the confirmed date without losing the active import batch", async () => {
    const locationChanged = vi.fn();
    let confirmBody: Record<string, unknown> | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-09",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        confirmBody = jsonRequestBody(init);
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    const { rerender } = render(
      <ImportReviewFlow
        onPublished={vi.fn()}
        onReportDateChanged={locationChanged}
        reportDate="2026-08-10"
      />,
    );
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    const batchNotesButton = await screen.findByRole("button", { name: "管理批次备注" });
    await user.click(screen.getByRole("button", { name: "采用识别日期" }));
    await user.click(screen.getByRole("button", { name: "确认并解析" }));

    expect(await screen.findByText("已解析 2 行源数据")).toBeVisible();
    expect(confirmBody).toMatchObject({
      report_date: "2026-08-09",
      report_type: "business_report",
    });
    expect(locationChanged).toHaveBeenCalledWith({
      reportDate: "2026-08-09",
      reportType: "business_report",
    });

    rerender(
      <ImportReviewFlow
        onPublished={vi.fn()}
        onReportDateChanged={locationChanged}
        reportDate="2026-08-09"
      />,
    );
    expect(screen.getByRole("button", { name: "管理批次备注" })).toBe(batchNotesButton);
    expect(screen.getByText("已解析 2 行源数据")).toBeVisible();
  });

  it("changes the report date after parsing by creating a new immutable baseline", async () => {
    const parseBodies: Record<string, unknown>[] = [];
    const parseKeys: string[] = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "return_report",
          report_date: "2026-07-01",
          encoding: "utf-8-sig",
          ruleset_version: "return_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        parseBodies.push(jsonRequestBody(init));
        parseKeys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
        const revision = parseBodies.length;
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 30 + revision,
            parse_baseline_id: 40 + revision,
            confirmation_revision: revision,
            report_type: "return_report",
            source_row_count: 2,
          },
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-07-05" />);
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["date,sku\n2026-07-01,A"], "7月1日退货.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    await screen.findByRole("heading", { name: "人工确认识别结果" });
    await user.click(screen.getByRole("button", { name: "确认并解析" }));

    expect(await screen.findByText("已解析 2 行源数据")).toBeVisible();
    expect(screen.getByText(/当前所属日期为/)).toHaveTextContent("2026-07-05");
    await user.click(screen.getByRole("button", { name: "修改日期并重新解析" }));
    await user.click(screen.getByRole("button", { name: "采用识别日期" }));
    await user.click(screen.getByRole("button", { name: "确认并解析" }));

    expect(await screen.findByText("不可变解析基线 #42")).toBeVisible();
    expect(parseBodies).toEqual([
      expect.objectContaining({ report_date: "2026-07-05", report_type: "return_report" }),
      expect.objectContaining({ report_date: "2026-07-01", report_type: "return_report" }),
    ]);
    expect(parseKeys[1]).not.toBe(parseKeys[0]);
  });

  it("uploads multiple files independently and keeps each one behind human confirmation", async () => {
    const uploadNames: string[] = [];
    const inspectedBatches: number[] = [];
    const onBatchReviewCreated = vi.fn();
    let nextBatchId = 10;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path === "/api/imports/batch-reviews/preflight") {
        expect(jsonRequestBody(init)).toEqual({ batch_ids: [11, 12] });
        return Promise.resolve(jsonResponse({ id: 77, items: [] }, 201));
      }
      if (path.startsWith("/api/imports?")) {
        nextBatchId += 1;
        uploadNames.push(decodeURIComponent(new Headers(init?.headers).get("X-Original-Filename") ?? ""));
        return Promise.resolve(jsonResponse({
          batch_id: nextBatchId,
          raw_file_id: 20 + nextBatchId,
          sha256_hex: String(nextBatchId).repeat(64).slice(0, 64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      const match = path.match(/^\/api\/imports\/(\d+)\/inspect$/);
      if (match) {
        const batchId = Number(match[1]);
        inspectedBatches.push(batchId);
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: batchId === 11 ? "return_report" : "business_report",
          report_date: batchId === 11 ? "2026-07-01" : "2026-07-02",
          encoding: "utf-8-sig",
          ruleset_version: batchId === 11 ? "return_report_v1" : "business_report_v1",
          issue_codes: [],
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onBatchReviewCreated={onBatchReviewCreated} onPublished={vi.fn()} reportDate="2026-07-05" />);
    await user.upload(screen.getByLabelText("CSV 文件"), [
      new File(["return"], "7月1日退货.csv", { type: "text/csv" }),
      new File(["business"], "7月2日经营.csv", { type: "text/csv" }),
    ]);
    await user.click(screen.getByRole("button", { name: "保存并检查 2 份文件" }));

    expect(await screen.findByRole("heading", { name: "2 份文件 · 上传结果" })).toBeVisible();
    expect(uploadNames).toEqual(["7月1日退货.csv", "7月2日经营.csv"]);
    expect(inspectedBatches).toEqual([11, 12]);
    expect(screen.getByText(/2026-07-02 · 等待人工确认/)).toBeVisible();
    expect(screen.getByText(/2026-07-01 · 正在人工确认/)).toBeVisible();
    expect(fetchMock.mock.calls.some(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path.endsWith("/confirm-parse");
    })).toBe(false);
    await user.click(screen.getByRole("button", { name: "批量审核" }));
    await waitFor(() => expect(onBatchReviewCreated).toHaveBeenCalledWith(77));

    await user.click(screen.getByRole("button", { name: "开始审核" }));
    expect(screen.getByText(/7月2日经营\.csv · SHA-256/)).toBeVisible();
    expect(screen.getByLabelText("所属报告日")).toHaveValue("2026-07-02");
  });

  it("keeps successful batch uploads when another queue item fails inspection", async () => {
    let nextBatchId = 10;
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        nextBatchId += 1;
        return Promise.resolve(jsonResponse({
          batch_id: nextBatchId,
          raw_file_id: 20 + nextBatchId,
          sha256_hex: String(nextBatchId).repeat(64).slice(0, 64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "return_report",
          report_date: "2026-07-01",
          encoding: "utf-8-sig",
          ruleset_version: "return_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/12/inspect") {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-07-05" />);
    await user.upload(screen.getByLabelText("CSV 文件"), [
      new File(["valid"], "有效退货.csv", { type: "text/csv" }),
      new File(["saved-but-not-inspected"], "待重试经营.csv", { type: "text/csv" }),
    ]);
    await user.click(screen.getByRole("button", { name: "保存并检查 2 份文件" }));

    expect(await screen.findByText(/有效退货\.csv · SHA-256/)).toBeVisible();
    expect(screen.getByText(/失败 · 批次 #12/)).toBeVisible();
    expect(screen.getByRole("button", { name: "重新识别" })).toBeVisible();
    expect(screen.getByText(/1 份等待人工确认，其中 1 份已按文件识别日期归入对应工作日，1 份失败/)).toBeVisible();
  });

  it("shows published duplicates as read-only results and clears the handled file selection", async () => {
    const fetchMock = vi.fn((_input: string | URL | Request, init?: RequestInit) => init?.method === "HEAD" ? Promise.resolve(new Response(null, { status: 200 })) : Promise.resolve(jsonResponse({ error: {
      code: "duplicate_import", existing_batch_id: 7, message: "Already available",
      report_date: "2026-07-07", report_type: "business_report", stage: "published",
    } }, 409)));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-07-07" />);
    const input = screen.getByLabelText<HTMLInputElement>("CSV 文件");
    await user.upload(input, new File(["report"], "report.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    expect(await screen.findByText(/文件已导入并发布 · 批次 #7/)).toBeVisible();
    expect(screen.getByRole("link", { name: "查看已发布日报" })).toHaveAttribute("href", "/review/2026-07-07?report_type=business_report#main-content");
    expect(screen.queryByRole("button", { name: "继续审核" })).not.toBeInTheDocument();
    expect(screen.getByText("本次未新增该文件的导入批次，未改变已发布日报。")).toBeVisible();
    expect(input.files).toHaveLength(0);
    expect(screen.getByRole("button", { name: "保存并检查文件" })).toBeDisabled();
    expect(fetchMock.mock.calls.filter(([path]) => typeof path === "string" && path.startsWith("/api/imports?"))).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([path]) => typeof path === "string" && path.endsWith("/inspect"))).toBe(false);
  });

  it("presents a duplicate upload as an existing batch that can be continued", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          error: {
            code: "duplicate_import",
            existing_batch_id: 92,
            message: "This file is already available.",
            report_date: "2026-07-05",
            report_type: "return_report",
            request_id: "request-duplicate",
            stage: "uploaded",
            workspace_url: "/review/2026-07-05?report_type=return_report",
          },
        }, 409));
      }
      if (path === "/api/imports/92/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "return_report",
          report_date: "2026-07-05",
          encoding: "utf-8-sig",
          ruleset_version: "return_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/92/raw-file/preview?encoding=utf-8-sig&page=1&page_size=30") {
        return Promise.resolve(jsonResponse({
          batch_id: 92,
          columns: [],
          encoding: "utf-8-sig",
          page: 1,
          page_size: 30,
          rows: [],
          total_pages: 0,
          total_rows: 0,
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-16" />);
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["return"], "亚马逊物流买家退货-20260705-80534020640.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));

    expect(await screen.findByText(/2026-07-05 · 已有批次 · 已上传 · 批次 #92/)).toBeVisible();
    expect(screen.queryByText(/2026-07-05 · 失败/)).not.toBeInTheDocument();
    expect(screen.getByText(/服务器阶段：已上传/)).toBeVisible();
    expect(screen.getByRole("button", { name: "继续审核" })).toBeVisible();
    expect(screen.getByRole("button", { name: "清空页面队列" })).toBeVisible();
    expect(screen.getByText(/不会删除服务器上的原始文件或导入批次/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "继续审核" }));
    expect(await screen.findByRole("heading", { name: "人工确认识别结果" })).toBeVisible();
    expect(screen.getByLabelText("所属报告日")).toHaveValue("2026-07-05");
  });

  it("completes upload, human parse confirmation, draft validation and publication", async () => {
    let ready = false;
    let validated = false;
    const completed = vi.fn();
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        expect(new Headers(init?.headers).get("X-Original-Filename")).toBe(
          encodeURIComponent("经营报告.csv"),
        );
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-09",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      if (path.startsWith("/api/versions?")) return Promise.resolve(jsonResponse([]));
      if (path === "/api/datasets/materialize") {
        const body = jsonRequestBody(init);
        expect(body).toMatchObject({
          batch_id: 11,
          parse_baseline_id: 32,
          report_date: "2026-08-10",
          strategy: "merge",
        });
        return Promise.resolve(jsonResponse({
          operation_token: "11111111-1111-4111-8111-111111111111",
          dataset_id: 41,
          version_id: 51,
          version_no: 1,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [],
          source_dataset_id: null,
          source_version_id: null,
        }, 201));
      }
      if (path === "/api/drafts/51" && init?.method !== "POST") {
        return Promise.resolve(jsonResponse({ ...draftHead, status: ready ? "ready_for_publish" : "draft", review_revision: ready ? 1 : 0 }));
      }
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace(
          { ...draftHead, status: ready ? "ready_for_publish" : "draft", review_revision: ready ? 1 : 0 },
          validated ? validation : null,
        )));
      }
      if (path === "/api/validation-runs/51") {
        validated = true;
        return Promise.resolve(jsonResponse(validation));
      }
      if (path === "/api/drafts/51/mark-ready") {
        ready = true;
        return Promise.resolve(jsonResponse({ result: { status: "ready_for_publish" } }));
      }
      if (path === "/api/datasets/41/publish") {
        const body = jsonRequestBody(init) as { confirmation?: { row_count?: number } };
        expect(body.confirmation?.row_count).toBe(2);
        return Promise.resolve(jsonResponse({
          operation_token: "22222222-2222-4222-8222-222222222222",
          command_id: 71,
          command_type: "publish",
          transitions: [],
          completed_at: "2026-08-10T03:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    const firstRender = render(<ImportReviewFlow onPublished={completed} reportDate="2026-08-10" />);

    const file = new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("CSV 文件"), file);
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(await screen.findByText("识别日期与所选报告日不同")).toBeVisible();
    expect(screen.getByText("2026-08-09")).toBeVisible();
    expect(screen.getByRole("link", { name: "下载原始 CSV" })).toHaveAttribute(
      "href",
      "/api/imports/11/raw-file",
    );
    await user.click(screen.getByRole("button", { name: "确认并解析" }));

    expect(await screen.findByText("已解析 2 行源数据")).toBeVisible();
    await user.type(screen.getByLabelText("生成草稿原因"), "导入并核对 8 月 10 日经营报告");
    await user.click(screen.getByRole("button", { name: "生成审核草稿" }));

    expect(await screen.findByRole("heading", { name: "草稿审核 · v1" })).toBeVisible();
    const publicationStep = within(screen.getByRole("list", { name: "导入证据链" }))
      .getByText("发布版本")
      .closest("li");
    expect(publicationStep).not.toHaveClass("custody-chain__step--reached");
    await user.click(screen.getByRole("button", { name: "运行草稿校验" }));
    expect(await screen.findByText("阻断项 0")).toBeVisible();

    await user.type(screen.getByLabelText("审核确认说明"), "已逐项核对原表、行数和合计");
    await user.click(screen.getByRole("button", { name: "确认结果并标记待发布" }));

    await user.click(await screen.findByRole("button", { name: "打开发布确认" }));
    const dialog = screen.getByRole("dialog", { name: "发布确认" });
    expect(within(dialog).getByText("2026-08-10")).toBeVisible();
    expect(within(dialog).getByText("2 行")).toBeVisible();
    await user.type(within(dialog).getByLabelText("发布说明"), "审核完成，发布当日经营报告");
    await user.click(within(dialog).getByRole("button", { name: "确认发布" }));

    await waitFor(() => expect(completed).toHaveBeenCalledWith(expect.objectContaining({ command_id: 71 })));
    expect(await screen.findByText("版本 v1 已发布")).toBeVisible();
    expect(publicationStep).toHaveAttribute("aria-current", "step");

    await waitFor(() => expect(window.sessionStorage.getItem(reviewRecoveryKey({ reportDate: "2026-08-10", siteId: 0, userId: 0 }))).toContain('"status":"completed"'));
    firstRender.unmount();
    render(<ImportReviewFlow onPublished={completed} reportDate="2026-08-10" />);
    expect(screen.getByRole("heading", { name: "这份文件已经进入当前发布版本" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "生成审核草稿" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "完成本次批量" })).toBeVisible();
  });

  it("restores an administrator published move from the review workspace after refresh", async () => {
    const moveWorkspace = {
      ...reviewWorkspace(
        {
          ...draftHead,
          status: "ready_for_publish",
          review_revision: 1,
        },
        validation,
      ),
      publication_mode: "published_move",
      published_move: {
        revision_operation_token: "77777777-7777-4777-8777-777777777777",
        source_dataset_id: 40,
        source_report_date: "2026-08-09",
        source_publication: {
          version_id: 49,
          published_at: "2026-08-09T03:00:00Z",
        },
        target_publication: {
          version_id: 48,
          published_at: "2026-08-08T03:00:00Z",
        },
      },
    } satisfies ReviewWorkspace;
    const completed = vi.fn();
    const finalizeBodies: Record<string, unknown>[] = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(moveWorkspace));
      }
      if (path === "/api/admin/published-moves/77777777-7777-4777-8777-777777777777/finalize" && init?.method === "POST") {
        finalizeBodies.push(jsonRequestBody(init));
        return Promise.resolve(jsonResponse({
          operation_token: "88888888-8888-4888-8888-888888888888",
          command_id: 72,
          command_type: "move",
          transitions: [],
          completed_at: "2026-08-10T04:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <ImportReviewFlow
        canFinalizePublishedMove
        initialVersionId={51}
        onPublished={completed}
        reportDate="2026-08-10"
      />,
    );

    expect(await screen.findByRole("button", { name: "管理批次备注" })).toBeVisible();
    await user.click(await screen.findByRole("button", { name: "打开跨日期生效确认" }));
    const dialog = screen.getByRole("dialog", { name: "跨日期生效确认" });
    await user.type(within(dialog).getByLabelText("发布说明"), "刷新后恢复并完成跨日期生效");
    await user.click(within(dialog).getByRole("button", { name: "确认跨日期生效" }));

    await waitFor(() => expect(completed).toHaveBeenCalledWith(expect.objectContaining({ command_id: 72 })));
    expect(finalizeBodies).toHaveLength(1);
    expect(finalizeBodies[0]).toMatchObject({
      source_dataset_id: 40,
      expected_source_publication: {
        version_id: 49,
        published_at: "2026-08-09T03:00:00Z",
      },
      target_dataset_id: 41,
      expected_target_publication: {
        version_id: 48,
        published_at: "2026-08-08T03:00:00Z",
      },
    });
    expect(fetchMock.mock.calls.some(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path.startsWith("/api/versions?");
    })).toBe(false);
  });

  it("previews a published target, cancels without writing, and sends the selected replace strategy", async () => {
    const materializeBodies: Record<string, unknown>[] = [];
    const publication = targetVersion();
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      if (path.startsWith("/api/versions?report_date=2026-08-10")) {
        return Promise.resolve(jsonResponse([publication]));
      }
      if (path === "/api/datasets/materialize") {
        materializeBodies.push(jsonRequestBody(init));
        return Promise.resolve(jsonResponse({
          operation_token: "44444444-4444-4444-8444-444444444444",
          dataset_id: 42,
          version_id: 52,
          version_no: 5,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [],
          source_dataset_id: 42,
          source_version_id: 62,
        }, 201));
      }
      if (path === "/api/drafts/52" && init?.method !== "POST") {
        return Promise.resolve(jsonResponse({
          ...draftHead,
          dataset_id: 42,
          version_id: 52,
          version_no: 5,
        }));
      }
      if (path.startsWith("/api/drafts/52/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace({
          ...draftHead,
          dataset_id: 42,
          version_id: 52,
          version_no: 5,
        })));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" />);
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    await screen.findByRole("heading", { name: "人工确认识别结果" });
    await user.click(screen.getByRole("button", { name: "确认并解析" }));
    await screen.findByText("已解析 2 行源数据");
    const materializeReason = screen.getByLabelText("生成草稿原因");
    await user.type(materializeReason, "按人工选择处理已有发布版本");

    await user.click(screen.getByRole("button", { name: "生成审核草稿" }));
    expect(await screen.findByText("发布版本 v4")).toBeVisible();
    expect(screen.getByText(/同一业务键在两侧都出现/)).toBeVisible();
    expect(materializeBodies).toHaveLength(0);

    await user.click(screen.getByLabelText("取消，不生成草稿"));
    await user.clear(materializeReason);
    expect(screen.getByRole("button", { name: "确认取消" })).toBeDisabled();
    await user.type(materializeReason, "取消本次生成，不改变目标数据");
    await user.click(screen.getByRole("button", { name: "确认取消" }));
    expect(await screen.findByText(/没有写入或覆盖目标日期/)).toBeVisible();
    expect(materializeBodies).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "生成审核草稿" }));
    await screen.findByText("发布版本 v4");
    await user.click(screen.getByLabelText("替换当前发布版本"));
    await user.click(screen.getByRole("button", { name: "按所选方式生成草稿" }));

    expect(await screen.findByRole("heading", { name: "草稿审核 · v5" })).toBeVisible();
    expect(materializeBodies).toHaveLength(1);
    expect(materializeBodies[0]).toMatchObject({
      expected_active_draft: null,
      expected_publication_version_id: 62,
      merge_decisions: [],
      strategy: "replace",
    });
  });

  it("lets an administrator explicitly replace an active draft with the new parsed baseline", async () => {
    const publication = targetVersion();
    const activeDraft = targetVersion({
      data_revision: 7,
      draft_pointed_at: "2026-08-10T02:30:00Z",
      is_active_draft: true,
      is_current_publication: false,
      published_at: null,
      review_revision: 3,
      sealed_at: null,
      status: "draft",
      version_id: 63,
      version_no: 5,
    });
    const forceRebuildBodies: Record<string, unknown>[] = [];
    const forceRebuildKeys: Array<string | null> = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/imports?")) {
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      if (path.startsWith("/api/versions?report_date=2026-08-10")) {
        return Promise.resolve(jsonResponse([activeDraft, publication]));
      }
      if (path === "/api/admin/drafts/63/force-rebuild" && init?.method === "POST") {
        forceRebuildBodies.push(jsonRequestBody(init));
        forceRebuildKeys.push(new Headers(init.headers).get("Idempotency-Key"));
        if (forceRebuildBodies.length === 1) {
          return Promise.resolve(jsonResponse({
            error: {
              code: "result_unknown",
              message: "重建结果暂时无法确认",
              request_id: "force-rebuild-1",
            },
          }, 503));
        }
        return Promise.resolve(jsonResponse({
          operation_token: "55555555-5555-4555-8555-555555555555",
          dataset_id: 42,
          version_id: 64,
          version_no: 6,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [63],
          source_dataset_id: 42,
          source_version_id: 62,
        }, 201));
      }
      if (path === "/api/drafts/64" && init?.method !== "POST") {
        return Promise.resolve(jsonResponse({
          ...draftHead,
          dataset_id: 42,
          version_id: 64,
          version_no: 6,
        }));
      }
      if (path.startsWith("/api/drafts/64/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace({
          ...draftHead,
          dataset_id: 42,
          version_id: 64,
          version_no: 6,
        })));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    const view = render(
      <ImportReviewFlow
        onPublished={vi.fn()}
        reportDate="2026-08-10"
      />,
    );
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    await screen.findByRole("heading", { name: "人工确认识别结果" });
    await user.click(screen.getByRole("button", { name: "确认并解析" }));
    await screen.findByText("已解析 2 行源数据");
    await user.type(
      screen.getByLabelText("生成草稿原因"),
      "目标活动草稿录入错误，按新原表重建",
    );
    await user.click(screen.getByRole("button", { name: "生成审核草稿" }));

    expect(await screen.findByText("活动草稿 v5")).toBeVisible();
    expect(screen.getByLabelText("替换当前发布版本")).toBeDisabled();
    expect(screen.queryByLabelText("管理员强制重建活动草稿")).not.toBeInTheDocument();
    view.rerender(
      <ImportReviewFlow
        canForceRebuild
        onPublished={vi.fn()}
        reportDate="2026-08-10"
      />,
    );
    await user.click(screen.getByLabelText("管理员强制重建活动草稿"));
    const submit = screen.getByRole("button", { name: "强制重建审核草稿" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByLabelText("确认废弃目标活动草稿并保留审计历史"));
    await user.click(submit);
    expect(await screen.findByText("重建结果暂时无法确认")).toBeVisible();
    await user.click(submit);

    expect(await screen.findByRole("heading", { name: "草稿审核 · v6" })).toBeVisible();
    const expectedBody = {
      batch_id: 11,
      expected_active_draft: {
        data_revision: 7,
        review_revision: 3,
        version_id: 63,
      },
      expected_publication_version_id: 62,
      parse_baseline_id: 32,
      reason: "目标活动草稿录入错误，按新原表重建",
      report_date: "2026-08-10",
    };
    expect(forceRebuildBodies).toEqual([expectedBody, expectedBody]);
    expect(forceRebuildKeys[0]).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i,
    );
    expect(forceRebuildKeys[1]).toBe(forceRebuildKeys[0]);
    expect(fetchMock.mock.calls.some(([input]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path === "/api/datasets/materialize";
    })).toBe(false);
  });

  it("keeps a failed validation away from the publication gate", async () => {
    const failedValidation = {
      ...validation,
      result: "failed",
      summary: {
        ...validation.summary,
        stages: {
          ...validation.summary.stages,
          parse_fidelity: {
            ...validation.summary.stages.parse_fidelity,
            blocking_count: 1,
          },
        },
      },
    } satisfies ValidationRun;
    let validationRan = false;
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace(draftHead, validationRan ? failedValidation : null)));
      }
      if (path === "/api/validation-runs/51") {
        validationRan = true;
        return Promise.resolve(jsonResponse(failedValidation));
      }
      throw new Error(`Unhandled request: ${path}`);
    }));

    const user = userEvent.setup();
    render(
      <ImportReviewFlow
        initialDraft={{
          head: draftHead,
          publicationMode: "ordinary",
          publishedMove: null,
          reportDate: "2026-08-10",
          reportType: "business_report",
          rulesetVersion: "business_report_v1",
        }}
        onPublished={vi.fn()}
        reportDate="2026-08-10"
      />,
    );

    await user.click(screen.getByRole("button", { name: "运行草稿校验" }));
    expect(await screen.findByText("阻断项 1")).toBeVisible();
    expect(screen.getByText("先修正阻断项，再重新运行校验。")).toBeVisible();
    expect(screen.queryByRole("button", { name: "确认结果并标记待发布" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开发布确认" })).not.toBeInTheDocument();
  });

  it("moves an unpublished draft only after checking the target date", async () => {
    const dateChanged = vi.fn();
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace()));
      }
      if (path.startsWith("/api/versions?report_date=2026-08-11")) {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/drafts/51/reassign-date") {
        expect(jsonRequestBody(init)).toMatchObject({
          source_dataset_id: 41,
          target_report_date: "2026-08-11",
          target: { target_kind: "empty", expected_dataset_id: null },
        });
        return Promise.resolve(jsonResponse({
          operation_token: "33333333-3333-4333-8333-333333333333",
          dataset_id: 42,
          version_id: 52,
          version_no: 1,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [51],
          source_dataset_id: 41,
          source_version_id: 51,
        }));
      }
      if (path.startsWith("/api/drafts/52/review-workspace")) {
        return Promise.resolve(jsonResponse(reviewWorkspace({
          ...draftHead,
          dataset_id: 42,
          version_id: 52,
          pointed_at: "2026-08-10T04:00:00Z",
        })));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(
      <ImportReviewFlow
        initialDraft={{
          head: draftHead,
          publicationMode: "ordinary",
          publishedMove: null,
          reportDate: "2026-08-10",
          reportType: "business_report",
          rulesetVersion: "business_report_v1",
        }}
        onPublished={vi.fn()}
        onReportDateChanged={dateChanged}
        reportDate="2026-08-10"
      />,
    );

    await user.click(screen.getByText("调整草稿日期"));
    await user.clear(screen.getByLabelText("目标报告日"));
    await user.type(screen.getByLabelText("目标报告日"), "2026-08-11");
    await user.type(screen.getByLabelText("移动原因"), "原表实际属于次日");
    await user.click(screen.getByRole("button", { name: "检查目标日期" }));

    expect(await screen.findByText(/草稿已移动到 2026-08-11/)).toBeVisible();
    expect(dateChanged).toHaveBeenCalledWith({
      reportDate: "2026-08-11",
      reportType: "business_report",
      versionId: 52,
    });
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/drafts/51/review-workspace"),
      expect.anything(),
    );
  });

  it("reuses the parse UUID after network loss and replaces it when parse input changes", async () => {
    const parseKeys: string[] = [];
    const parseBodies: Record<string, unknown>[] = [];
    const nonIdempotentKeys: Array<string | null> = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const headers = new Headers(init?.headers);
      if (path.startsWith("/api/imports?")) {
        nonIdempotentKeys.push(headers.get("Idempotency-Key"));
        return Promise.resolve(jsonResponse({
          batch_id: 11,
          raw_file_id: 21,
          sha256_hex: "c".repeat(64),
          content_reused: false,
          duplicate: false,
        }, 201));
      }
      if (path === "/api/imports/11/inspect") {
        nonIdempotentKeys.push(headers.get("Idempotency-Key"));
        return Promise.resolve(jsonResponse({
          status: "recognized",
          report_type: "business_report",
          report_date: "2026-08-10",
          encoding: "utf-8-sig",
          ruleset_version: "business_report_v1",
          issue_codes: [],
        }));
      }
      if (path === "/api/imports/11/confirm-parse") {
        parseKeys.push(headers.get("Idempotency-Key") ?? "");
        parseBodies.push(jsonRequestBody(init));
        if (parseKeys.length <= 2) return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(jsonResponse({
          result: {
            batch_id: 11,
            parse_attempt_id: 31,
            parse_baseline_id: 32,
            confirmation_revision: 1,
            report_type: "business_report",
            source_row_count: 2,
          },
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<ImportReviewFlow onPublished={vi.fn()} reportDate="2026-08-10" />);
    await user.upload(
      screen.getByLabelText("CSV 文件"),
      new File(["sku,sales\nA,42.50"], "经营报告.csv", { type: "text/csv" }),
    );
    await user.click(screen.getByRole("button", { name: "保存并检查文件" }));
    await screen.findByRole("heading", { name: "人工确认识别结果" });

    await user.click(screen.getByRole("button", { name: "确认并解析" }));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "确认并解析" }));
    await waitFor(() => expect(parseKeys).toHaveLength(2));

    expect(parseKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(parseKeys[1]).toBe(parseKeys[0]);
    expect(parseBodies[1]).toEqual(parseBodies[0]);

    await user.selectOptions(screen.getByLabelText("文件编码"), "utf-8");
    await user.click(screen.getByRole("button", { name: "确认并解析" }));
    expect(await screen.findByText("已解析 2 行源数据")).toBeVisible();

    expect(parseKeys[2]).not.toBe(parseKeys[1]);
    expect(parseBodies[2]).toMatchObject({ encoding: "utf-8" });
    expect(nonIdempotentKeys).toEqual([null, null]);
  });
});
