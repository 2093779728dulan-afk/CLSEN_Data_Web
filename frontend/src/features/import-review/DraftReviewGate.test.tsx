import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import type { ReviewWorkspace, VersionSummary } from "../../api/types";
import { DraftReviewGate } from "./DraftReviewGate";
import type { PublishedMoveReviewContext } from "./workflowTypes";

function jsonResponse(payload: unknown) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status: 200,
  });
}

function jsonRequestBody(init?: RequestInit) {
  if (typeof init?.body !== "string") throw new Error("Expected a JSON request body.");
  return JSON.parse(init.body) as Record<string, unknown>;
}

const workspace: ReviewWorkspace = {
  head: {
    dataset_id: 41,
    version_id: 51,
    version_no: 2,
    status: "draft",
    data_revision: 3,
    review_revision: 1,
    pointed_at: "2026-08-10T02:00:00Z",
  },
  report_date: "2026-08-10",
  report_type: "business_report",
  ruleset_version: "business_report_v1",
  publication_mode: "ordinary",
  published_move: null,
  source_batches: [{ batch_id: 11 }],
  fields: [
    { name: "sku", kind: "text", nullable: false, editable: true, required_on_add: true, included_in_totals: false, max_length: 64, precision: null, scale: null, ascii_only: false },
    { name: "sales", kind: "decimal", nullable: false, editable: true, required_on_add: true, included_in_totals: true, max_length: null, precision: 12, scale: 2, ascii_only: false },
  ],
  rows: [{
    row_id: 101,
    logical_row_id: "11111111-1111-4111-8111-111111111111",
    row_ordinal: 1,
    row_state: "active",
    base_row_id: 201,
    original_parsed_source_row_id: 301,
    cells: [
      { field_name: "sku", current: { type: "text", value: "A-01" }, base: { type: "text", value: "A-01" }, source: { type: "text", value: "A-01" }, changed_from_base: false, changed_from_source: false, parent_restore_options: [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: { type: "text", value: "A-01" } }, history: [], notes: [] },
      { field_name: "sales", current: { type: "decimal", value: "42.50" }, base: { type: "decimal", value: "40.00" }, source: { type: "decimal", value: "40.00" }, changed_from_base: true, changed_from_source: true, parent_restore_options: [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: { type: "decimal", value: "40.00" } }, history: [], notes: [] },
    ],
    history: [],
    notes: [],
  }],
  version_notes: [{
    note_key: "version-note-1",
    note_id: 801,
    revision_number: 1,
    target_type: "version",
    row_id: null,
    field_name: null,
    visibility: "internal",
    body: "初次审核说明",
    author_user_id: 1,
    author_username: "TCJ",
    review_revision: 1,
    created_at: "2026-08-10T03:00:00Z",
  }],
  latest_full_validation: null,
  pagination: { page: 1, page_size: 50, total_rows: 1, total_pages: 1 },
};

function readyWorkspace(): ReviewWorkspace {
  return {
    ...workspace,
    head: {
      ...workspace.head,
      status: "ready_for_publish",
      review_revision: 2,
    },
    latest_full_validation: {
      id: 901,
      data_revision: workspace.head.data_revision,
      ruleset_version: workspace.ruleset_version,
      status: "succeeded",
      result: "passed",
      data_digest: "d".repeat(64),
      summary: {
        schema_version: 1,
        report_date: workspace.report_date,
        report_type: workspace.report_type,
        row_count: 1,
        totals: { sales: "42.50" },
        stages: {
          parse_fidelity: {
            data_digest: "a".repeat(64),
            row_count: 1,
            totals: { sales: "42.50" },
            warning_count: 0,
            blocking_count: 0,
          },
          draft_explainability: {
            data_digest: "b".repeat(64),
            row_count: 1,
            totals: { sales: "42.50" },
            warning_count: 0,
            blocking_count: 0,
          },
        },
      },
      started_at: "2026-08-10T03:30:00Z",
      completed_at: "2026-08-10T03:31:00Z",
      is_current: true,
      issues: [],
    },
  };
}

function targetVersion(overrides: Partial<VersionSummary> = {}): VersionSummary {
  return {
    created_at: "2026-08-11T01:00:00Z",
    data_revision: 2,
    dataset_id: 42,
    dedup_publication_revision: null,
    draft_pointed_at: null,
    is_active_draft: false,
    is_current_publication: true,
    published_at: "2026-08-11T02:00:00Z",
    publication_revision: null,
    report_date: "2026-08-11",
    report_type: "business_report",
    review_revision: 1,
    sealed_at: "2026-08-11T02:00:00Z",
    status: "published",
    version_id: 63,
    version_no: 2,
    ...overrides,
  };
}

const publishedMove: PublishedMoveReviewContext = {
  revision_operation_token: "11111111-1111-4111-8111-111111111111",
  source_dataset_id: 40,
  source_publication: {
    version_id: 49,
    published_at: "2026-08-09T03:00:00Z",
  },
  source_report_date: "2026-08-09",
  target_publication: {
    version_id: null,
    published_at: null,
  },
};

describe("DraftReviewGate row and note commands", () => {
  beforeEach(() => setSessionCsrfToken("csrf-test-token"));

  afterEach(() => {
    setSessionCsrfToken(undefined);
    vi.unstubAllGlobals();
  });

  it("prefills downstream publication audit text from the authenticated operator", async () => {
    const currentWorkspace = readyWorkspace();
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(currentWorkspace));
      }
      throw new Error(`Unhandled request: ${path}`);
    }));

    const user = userEvent.setup();
    render(
      <DraftReviewGate
        context={{
          head: currentWorkspace.head,
          publicationMode: "ordinary",
          publishedMove: null,
          reportDate: currentWorkspace.report_date,
          reportType: currentWorkspace.report_type,
          rulesetVersion: currentWorkspace.ruleset_version,
          publication: { version_id: null, published_at: null },
        }}
        onPublished={vi.fn()}
        operator={{ id: 3, username: "manager", display_name: "录入审核" }}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "打开发布确认" }));

    const dialog = screen.getByRole("dialog", { name: "发布确认" });
    expect(within(dialog).getByLabelText("发布说明")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：确认发布审核版本；来源：2026-08-10 经营报告 · 版本 v2 · 校验 #901。",
    );
    expect(within(dialog).getByText(/服务器将按该会话写入发布审计/)).toBeVisible();
  });

  it("explicitly discards the active draft before reopening a source batch for reparse", async () => {
    const reparseSource = vi.fn<(batchId: number) => Promise<void>>().mockResolvedValue(undefined);
    let discardBody: Record<string, unknown> | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(workspace));
      }
      if (path === "/api/drafts/51/discard") {
        discardBody = jsonRequestBody(init);
        return Promise.resolve(jsonResponse({
          operation_token: new Headers(init?.headers).get("Idempotency-Key"),
          dataset_id: 41,
          version_id: 51,
          version_no: 2,
          status: "discarded",
          data_revision: 3,
          review_revision: 1,
          superseded_version_ids: [],
          source_dataset_id: null,
          source_version_id: null,
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<DraftReviewGate context={{ head: workspace.head, publicationMode: "ordinary", publishedMove: null, reportDate: workspace.report_date, reportType: workspace.report_type, rulesetVersion: workspace.ruleset_version, publication: { version_id: null, published_at: null } }} onPublished={vi.fn()} onReparseSource={reparseSource} />);
    await screen.findByRole("heading", { name: "草稿审核 · v2" });
    await user.click(screen.getByText("重新解析或废弃草稿"));
    await user.type(screen.getByLabelText("处置原因"), "解析参数选择错误，需要从原文件重做");
    await user.click(screen.getByLabelText("我确认当前草稿将被废弃，历史记录不会删除。"));
    await user.click(screen.getByRole("button", { name: "废弃并重新解析来源文件" }));

    await waitFor(() => expect(reparseSource).toHaveBeenCalledWith(11));
    expect(discardBody).toEqual({
      dataset_id: 41,
      expected_active_draft: {
        data_revision: 3,
        review_revision: 1,
        version_id: 51,
      },
      reason: "解析参数选择错误，需要从原文件重做",
    });
  });

  it("sends generated-contract row commands and immutable note revisions", async () => {
    const writes: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) return Promise.resolve(jsonResponse(workspace));
      if (init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected a JSON request body.");
        writes.push({ path, body: JSON.parse(init.body) as Record<string, unknown> });
        return Promise.resolve(jsonResponse({ result: {} }));
      }
      throw new Error(`Unhandled request: ${path}`);
    }));

    const user = userEvent.setup();
    render(<DraftReviewGate context={{ head: workspace.head, publicationMode: "ordinary", publishedMove: null, reportDate: workspace.report_date, reportType: workspace.report_type, rulesetVersion: workspace.ruleset_version, publication: { version_id: null, published_at: null } }} onPublished={vi.fn()} />);
    expect(await screen.findByRole("heading", { name: "草稿审核 · v2" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "新增纠错行" }));
    const addDrawer = screen.getByRole("dialog", { name: "新增纠错行" });
    await user.type(within(addDrawer).getByLabelText("新增行字段 sku"), "A-02");
    await user.type(within(addDrawer).getByLabelText("新增行字段 sales"), "55.10");
    await user.type(within(addDrawer).getByLabelText("新增原因"), "补录遗漏行");
    await user.click(within(addDrawer).getByRole("button", { name: "保存新增行" }));
    await waitFor(() => expect(writes.some((write) => write.path === "/api/drafts/51/rows")).toBe(true));
    expect(writes.find((write) => write.path === "/api/drafts/51/rows")?.body).toMatchObject({
      dataset_id: 41,
      data_revision: 3,
      review_revision: 1,
      source_batch_id: 11,
      values: { sku: { type: "text", value: "A-02" }, sales: { type: "decimal", value: "55.10" } },
      reason: "补录遗漏行",
    });

    await user.click(screen.getByRole("button", { name: "管理第 1 行状态，当前 active" }));
    const stateDrawer = screen.getByRole("dialog", { name: "行状态操作" });
    await user.type(within(stateDrawer).getByLabelText("处理原因"), "排除重复行");
    await user.click(within(stateDrawer).getByRole("button", { name: "排除这一行" }));
    await waitFor(() => expect(writes.some((write) => write.path === "/api/drafts/51/rows/101/state")).toBe(true));
    expect(writes.find((write) => write.path === "/api/drafts/51/rows/101/state")?.body).toMatchObject({ operation: "exclude", reason: "排除重复行" });

    await user.click(screen.getByRole("button", { name: "管理第 1 行状态，当前 active" }));
    const noteDrawer = screen.getByRole("dialog", { name: "行状态操作" });
    await user.type(within(noteDrawer).getByLabelText("行备注内容"), "整行与原表逐列核对无误");
    await user.selectOptions(within(noteDrawer).getByLabelText("行备注可见范围"), "viewer_visible");
    await user.click(within(noteDrawer).getByRole("button", { name: "追加行备注" }));
    await waitFor(() => expect(writes.some((write) => write.path === "/api/drafts/51/notes" && write.body.target_type === "row")).toBe(true));
    expect(writes.find((write) => write.path === "/api/drafts/51/notes" && write.body.target_type === "row")?.body).toMatchObject({
      expected_review_revision: 1,
      target_type: "row",
      row_id: 101,
      field_name: null,
      body: "整行与原表逐列核对无误",
      visibility: "viewer_visible",
    });

    await user.click(screen.getByRole("button", { name: "修订备注" }));
    const revisedBody = screen.getByLabelText("修订备注 version-note-1");
    await user.clear(revisedBody);
    await user.type(revisedBody, "复核后的版本说明");
    await user.click(screen.getByRole("button", { name: "保存新修订" }));
    await waitFor(() => expect(writes.some((write) => write.path === "/api/drafts/51/notes/version-note-1/revisions")).toBe(true));
    expect(writes.find((write) => write.path === "/api/drafts/51/notes/version-note-1/revisions")?.body).toMatchObject({
      expected_note_id: 801,
      expected_revision_number: 1,
      expected_review_revision: 1,
      target_type: "version",
      body: "复核后的版本说明",
      visibility: "internal",
    });
  });

  it.each([
    {
      label: "active draft",
      mergeLabel: "合并到目标活动草稿",
      versions: [
        targetVersion({
          data_revision: 4,
          draft_pointed_at: "2026-08-11T03:00:00Z",
          is_active_draft: true,
          is_current_publication: false,
          published_at: null,
          review_revision: 3,
          sealed_at: null,
          status: "draft",
          version_id: 64,
          version_no: 3,
        }),
        targetVersion(),
      ],
    },
    {
      label: "published version",
      mergeLabel: "合并目标发布版本",
      versions: [targetVersion()],
    },
  ])("previews an $label target, cancels without writing, and sends the selected target contract", async ({ label, mergeLabel, versions }) => {
    const requestBodies: Record<string, unknown>[] = [];
    const operationKeys: string[] = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(workspace));
      }
      if (path.startsWith("/api/versions?report_date=2026-08-11")) {
        return Promise.resolve(jsonResponse(versions));
      }
      if (path.startsWith("/api/datasets/merge-preview?")) {
        return Promise.resolve(jsonResponse({
          report_type: "business_report",
          target_version_id: label === "active draft" ? 64 : 63,
          source_kind: "dataset_version",
          source_id: 51,
          conflicts: [],
        }));
      }
      if (path === "/api/drafts/51/reassign-date") {
        operationKeys.push(new Headers(init?.headers).get("Idempotency-Key") ?? "");
        const body = jsonRequestBody(init);
        requestBodies.push(body);
        const target = body.target as { strategy?: string };
        if (label === "published version" && target.strategy === "merge") {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return Promise.resolve(jsonResponse({
          operation_token: operationKeys.at(-1),
          dataset_id: 42,
          version_id: 52,
          version_no: 4,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          superseded_version_ids: [51],
          source_dataset_id: 41,
          source_version_id: 51,
        }));
      }
      if (path.startsWith("/api/drafts/52/review-workspace")) {
        return Promise.resolve(jsonResponse({
          ...workspace,
          head: {
            ...workspace.head,
            dataset_id: 42,
            version_id: 52,
            version_no: 4,
          },
          report_date: "2026-08-11",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DraftReviewGate context={{ head: workspace.head, publicationMode: "ordinary", publishedMove: null, reportDate: workspace.report_date, reportType: workspace.report_type, rulesetVersion: workspace.ruleset_version, publication: { version_id: null, published_at: null } }} onPublished={vi.fn()} />);
    await screen.findByRole("heading", { name: "草稿审核 · v2" });
    await user.click(screen.getByText("调整草稿日期"));
    await user.clear(screen.getByLabelText("目标报告日"));
    await user.type(screen.getByLabelText("目标报告日"), "2026-08-11");
    await user.type(screen.getByLabelText("移动原因"), "原表实际属于目标日期");

    await user.click(screen.getByRole("button", { name: "检查目标日期" }));
    expect(await screen.findByRole("group", { name: "目标日期已有数据，请选择处理方式" })).toBeVisible();
    expect(screen.getByLabelText(mergeLabel)).toBeVisible();
    expect(screen.getByText(/当前没有逐行决定时，服务端会阻断/)).toBeVisible();
    if (label === "active draft") {
      expect(screen.queryByLabelText("替换目标发布版本")).not.toBeInTheDocument();
    } else {
      expect(screen.getByLabelText("替换目标发布版本")).toBeVisible();
    }
    expect(requestBodies).toHaveLength(0);

    await user.click(screen.getByLabelText("取消，保留当前所属日期"));
    await user.click(screen.getByRole("button", { name: "确认取消" }));
    expect(await screen.findByText(/没有发送写请求/)).toBeVisible();
    expect(requestBodies).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "检查目标日期" }));
    await screen.findByLabelText(mergeLabel);
    await user.click(screen.getByLabelText(mergeLabel));
    await screen.findByText("没有重复业务键，可以安全保留两侧记录。");
    await user.click(screen.getByRole("button", { name: "按所选方式更改日期" }));

    if (label === "published version") {
      await screen.findByRole("alert");
      await user.click(screen.getByLabelText("替换目标发布版本"));
      await user.click(screen.getByRole("button", { name: "按所选方式更改日期" }));
    }
    await waitFor(() => expect(requestBodies).toHaveLength(label === "published version" ? 2 : 1));

    const finalBody = requestBodies.at(-1);
    if (label === "active draft") {
      expect(finalBody).toMatchObject({
        merge_decisions: [],
        target: {
          action: "merge",
          expected_active_draft: {
            data_revision: 4,
            review_revision: 3,
            version_id: 64,
          },
          expected_dataset_id: 42,
          expected_publication_version_id: 63,
          target_kind: "active_draft",
        },
      });
    } else {
      expect(finalBody).toMatchObject({
        merge_decisions: [],
        target: {
          expected_dataset_id: 42,
          expected_publication_version_id: 63,
          strategy: "replace",
          target_kind: "published",
        },
      });
      expect(operationKeys[1]).not.toBe(operationKeys[0]);
    }
  });

  it.each([
    {
      label: "ordinary publication",
      expectedPath: "/api/datasets/41/publish",
      move: undefined,
    },
    {
      label: "published-date move finalization",
      expectedPath: "/api/admin/published-moves/11111111-1111-4111-8111-111111111111/finalize",
      move: publishedMove,
    },
  ] satisfies Array<{
    label: string;
    expectedPath: string;
    move: PublishedMoveReviewContext | undefined;
  }>)("keeps a stable UUID for $label retries and resets it when the reason changes", async ({ expectedPath, move }) => {
    const currentWorkspace = {
      ...readyWorkspace(),
      publication_mode: move ? "published_move" : "ordinary",
      published_move: move ?? null,
    } satisfies ReviewWorkspace;
    const operationKeys: string[] = [];
    const requestBodies: Record<string, unknown>[] = [];
    const completed = vi.fn();
    vi.stubGlobal("fetch", vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(currentWorkspace));
      }
      if (path === expectedPath && init?.method === "POST") {
        operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
        if (typeof init.body !== "string") throw new Error("Expected publication JSON body.");
        requestBodies.push(JSON.parse(init.body) as Record<string, unknown>);
        if (operationKeys.length <= 2) return Promise.reject(new TypeError("Failed to fetch"));
        return Promise.resolve(jsonResponse({
          operation_token: operationKeys.at(-1),
          command_id: 71,
          command_type: move ? "move" : "publish",
          transitions: [],
          completed_at: "2026-08-10T04:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    }));

    const user = userEvent.setup();
    render(
      <DraftReviewGate
        canFinalizePublishedMove={move !== undefined}
        context={{
          head: currentWorkspace.head,
          publicationMode: "ordinary",
          publishedMove: null,
          reportDate: currentWorkspace.report_date,
          reportType: currentWorkspace.report_type,
          rulesetVersion: currentWorkspace.ruleset_version,
          publication: { version_id: null, published_at: null },
        }}
        onPublished={completed}
      />,
    );
    await screen.findByRole("heading", { name: "草稿审核 · v2" });
    await user.click(screen.getByRole("button", { name: move ? "打开跨日期生效确认" : "打开发布确认" }));
    const dialog = screen.getByRole("dialog", { name: move ? "跨日期生效确认" : "发布确认" });
    const reason = within(dialog).getByLabelText("发布说明");
    await user.type(reason, "第一次确认说明");

    const confirmLabel = move ? "确认跨日期生效" : "确认发布";
    await user.click(within(dialog).getByRole("button", { name: confirmLabel }));
    await within(dialog).findByRole("alert");
    await user.click(within(dialog).getByRole("button", { name: confirmLabel }));
    await waitFor(() => expect(operationKeys).toHaveLength(2));

    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).toBe(operationKeys[0]);
    expect(requestBodies[1]).toEqual(requestBodies[0]);

    await user.clear(reason);
    await user.type(reason, "修改后的确认说明");
    await user.click(within(dialog).getByRole("button", { name: confirmLabel }));
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));

    expect(operationKeys[2]).not.toBe(operationKeys[1]);
    expect(requestBodies[2]).toMatchObject({ reason: "修改后的确认说明" });
  });

  it("waits for return dedup, retries a recoverable job, and publishes with the staging token", async () => {
    const base = readyWorkspace();
    const currentWorkspace = {
      ...base,
      report_type: "return_report",
      ruleset_version: "return_report_v1",
      latest_full_validation: base.latest_full_validation && {
        ...base.latest_full_validation,
        ruleset_version: "return_report_v1",
        summary: { ...base.latest_full_validation.summary, report_type: "return_report" },
      },
    } satisfies ReviewWorkspace;
    const operationKeys: Record<string, string[]> = {};
    let statusReads = 0;
    const completed = vi.fn();
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
      (operationKeys[path] ??= []).push(key);
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(currentWorkspace));
      }
      if (path === "/api/versions?report_date=2026-08-10&report_type=return_report") {
        return Promise.resolve(jsonResponse([targetVersion({
          dataset_id: 41,
          dedup_publication_revision: 7,
          publication_revision: 3,
          report_date: "2026-08-10",
          report_type: "return_report",
          version_id: 51,
        })]));
      }
      if (path === "/api/publications/return-dedup-staging" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          command_url: `/api/publications/commands/${key}`,
          failure_reason: null,
          job_id: 91,
          job_revision: 0,
          next_job_revision: 0,
          proposed_set_digest: "a".repeat(64),
          result_snapshot_id: null,
          retry_allowed: false,
          status: "building",
          status_url: "/api/publications/return-dedup-staging/91",
        }));
      }
      if (path === "/api/publications/return-dedup-staging/91" && init?.method !== "POST") {
        statusReads += 1;
        return Promise.resolve(jsonResponse({
          command_url: "/api/publications/commands/original",
          failure_reason: statusReads === 1 ? "worker_timeout" : null,
          job_id: 91,
          job_revision: statusReads,
          next_job_revision: statusReads,
          proposed_set_digest: "a".repeat(64),
          result_snapshot_id: statusReads > 1 ? 191 : null,
          retry_allowed: statusReads === 1,
          status: statusReads === 1 ? "failed" : "ready",
          status_url: "/api/publications/return-dedup-staging/91",
        }));
      }
      if (path === "/api/publications/return-dedup-staging/91/retry" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          command_url: "/api/publications/commands/original",
          failure_reason: null,
          job_id: 91,
          job_revision: 2,
          next_job_revision: 2,
          proposed_set_digest: "a".repeat(64),
          result_snapshot_id: null,
          retry_allowed: false,
          status: "building",
          status_url: "/api/publications/return-dedup-staging/91",
        }));
      }
      if (path === "/api/datasets/41/publish" && init?.method === "POST") {
        return Promise.resolve(jsonResponse({
          operation_token: key,
          command_id: 71,
          command_type: "publish",
          transitions: [],
          completed_at: "2026-08-10T04:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<DraftReviewGate context={{
      head: currentWorkspace.head,
      publicationMode: "ordinary",
      publishedMove: null,
      reportDate: currentWorkspace.report_date,
      reportType: currentWorkspace.report_type,
      rulesetVersion: currentWorkspace.ruleset_version,
      publication: { version_id: null, published_at: null },
    }} onPublished={completed} />);
    await user.click(await screen.findByRole("button", { name: "打开发布确认" }));
    const dialog = screen.getByRole("dialog", { name: "发布确认" });
    await user.type(within(dialog).getByLabelText("发布说明"), "退货数据已核对");
    await user.click(within(dialog).getByRole("button", { name: "确认发布" }));

    expect(await within(dialog).findByText(/完成前不会切换发布指针/)).toBeVisible();
    await waitFor(() => expect(completed).toHaveBeenCalledTimes(1), { timeout: 4000 });
    const stagingKey = operationKeys["/api/publications/return-dedup-staging"]?.[0];
    expect(stagingKey).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys["/api/datasets/41/publish"]?.[0]).toBe(stagingKey);
    expect(operationKeys["/api/publications/return-dedup-staging/91/retry"]?.[0]).not.toBe(stagingKey);
  });

  it("lets a data manager finish review but never exposes ordinary publish for a published move", async () => {
    let ready = false;
    const currentWorkspace = () => {
      const reviewed = readyWorkspace();
      return {
        ...reviewed,
        head: {
          ...reviewed.head,
          status: ready ? "ready_for_publish" : "draft",
          review_revision: ready ? 2 : 1,
        },
        publication_mode: "published_move",
        published_move: null,
      } satisfies ReviewWorkspace;
    };
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path.startsWith("/api/drafts/51/review-workspace")) {
        return Promise.resolve(jsonResponse(currentWorkspace()));
      }
      if (path === "/api/drafts/51/mark-ready" && init?.method === "POST") {
        ready = true;
        return Promise.resolve(jsonResponse({ result: { status: "ready_for_publish" } }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const initialWorkspace = currentWorkspace();
    const user = userEvent.setup();
    render(
      <DraftReviewGate
        context={{
          head: initialWorkspace.head,
          publicationMode: "ordinary",
          publishedMove: null,
          reportDate: initialWorkspace.report_date,
          reportType: initialWorkspace.report_type,
          rulesetVersion: initialWorkspace.ruleset_version,
          publication: { version_id: null, published_at: null },
        }}
        onPublished={vi.fn()}
      />,
    );

    await user.type(await screen.findByLabelText("审核确认说明"), "数据已核对，提交管理员最终生效");
    await user.click(screen.getByRole("button", { name: "确认结果并标记待发布" }));
    expect(await screen.findByText("审核已完成，需管理员最终生效")).toBeVisible();
    expect(screen.queryByRole("button", { name: "打开发布确认" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开跨日期生效确认" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([input, init]) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      return path === "/api/datasets/41/publish" && init?.method === "POST";
    })).toBe(false);
  });
});
