import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useNavigate } from "react-router-dom";

import type {
  UndoablePublishedMoveResponse,
  VersionSummaryResponse,
} from "../../api/generated";
import type { Principal } from "../../api/types";
import {
  VersionHistory,
  type PublishedMoveRevisionHandoff,
  type PublishedRevisionHandoff,
} from "./VersionHistory";

const admin: Principal = { id: 1, username: "tcj", display_name: "管理员", roles: ["admin"] };
const manager: Principal = { id: 2, username: "manager", display_name: "录入审核人员", roles: ["data_manager"] };
const viewer: Principal = { id: 9, username: "viewer", display_name: "查看人员", roles: ["viewer"] };

function VersionHistoryNavigationHarness({ onFilterChange }: { onFilterChange: (filter: { reportDate: string; reportType: "business_report" | "return_report" }) => void }) {
  const navigate = useNavigate();
  return <>
    <button onClick={() => void navigate(-1)} type="button">返回上一筛选</button>
    <button onClick={() => void navigate(1)} type="button">前往下一筛选</button>
    <VersionHistory initialReportDate="2026-08-01" onFilterChange={onFilterChange} principal={viewer} />
  </>;
}

const current: VersionSummaryResponse = {
  dataset_id: 41,
  version_id: 53,
  report_date: "2026-08-10",
  report_type: "business_report",
  version_no: 3,
  status: "published",
  data_revision: 2,
  review_revision: 3,
  dedup_publication_revision: null,
  created_at: "2026-08-10T01:00:00Z",
  sealed_at: "2026-08-10T03:00:00Z",
  is_current_publication: true,
  published_at: "2026-08-10T03:00:00Z",
  publication_revision: null,
  is_active_draft: false,
  draft_pointed_at: null,
};

const historical: VersionSummaryResponse = {
  ...current,
  version_id: 51,
  version_no: 1,
  created_at: "2026-08-09T01:00:00Z",
  sealed_at: "2026-08-09T03:00:00Z",
  is_current_publication: false,
  published_at: null,
};

const draft: VersionSummaryResponse = {
  ...current,
  version_id: 54,
  version_no: 4,
  status: "draft",
  sealed_at: null,
  is_current_publication: false,
  published_at: null,
  is_active_draft: true,
  draft_pointed_at: "2026-08-10T04:00:00Z",
};

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

function pathOf(input: string | URL | Request) {
  return typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
}

function detailFor(version: VersionSummaryResponse = current) {
  return {
    ...version,
    parents: [{
      dataset_id: 41,
      version_id: 51,
      report_date: "2026-08-10",
      report_type: "business_report",
      version_no: 1,
      status: "published",
      lineage_type: "base",
      lineage_ordinal: 0,
    }],
    children: [],
    viewer_visible_notes: [{
      note_key: "version-note",
      revision_number: 2,
      body: "与原表逐项核对完成",
      created_at: "2026-08-10T02:30:00Z",
    }],
  };
}

describe("VersionHistory", () => {
  beforeEach(() => {
    document.cookie = "clsen_csrf=csrf-version-token; path=/";
  });

  afterEach(() => {
    document.cookie = "clsen_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/";
    vi.unstubAllGlobals();
  });

  it("queries one date and type, filters viewer-ineligible drafts, and shows safe lineage notes", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        return Promise.resolve(jsonResponse([draft, current, historical]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<VersionHistory initialReportDate="2026-08-10" principal={viewer} />);

    expect(await screen.findByText("当前发布")).toBeVisible();
    expect(screen.getByRole("button", { name: /查看版本 v3/ })).toBeVisible();
    expect(screen.getByRole("button", { name: /查看版本 v1/ })).toBeVisible();
    expect(screen.queryByRole("button", { name: /查看版本 v4/ })).not.toBeInTheDocument();
    expect(await screen.findByText("与原表逐项核对完成")).toBeVisible();
    expect(screen.getByText("基础版本 · v1")).toBeVisible();
    expect(screen.queryByRole("button", { name: /回滚/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "创建修订" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "移动到其他日期" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "撤销跨日期移动" })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map(([input]) => pathOf(input))).not.toContain(
      "/api/admin/published-moves/undoable",
    );
    expect(screen.getByText("查看人员仅能读取已发布版本和查看人员可见备注。" )).toBeVisible();
  });

  it("initializes from the route query and follows browser history while preserving callbacks", async () => {
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path.startsWith("/api/versions?")) return Promise.resolve(jsonResponse([]));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const onFilterChange = vi.fn();
    const user = userEvent.setup();

    render(
      <MemoryRouter
        initialEntries={[
          "/versions?report_date=2026-08-09&report_type=business_report",
          "/versions?report_date=2026-08-10&report_type=return_report",
        ]}
        initialIndex={1}
      >
        <VersionHistoryNavigationHarness onFilterChange={onFilterChange} />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("heading", { name: "退货报告 · 2026-08-10" })).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/versions?report_date=2026-08-10&report_type=return_report",
      expect.anything(),
    );

    await user.click(screen.getByRole("button", { name: "返回上一筛选" }));
    expect(await screen.findByRole("heading", { name: "经营报告 · 2026-08-09" })).toBeVisible();
    await waitFor(() => expect(onFilterChange).toHaveBeenLastCalledWith({
      reportDate: "2026-08-09",
      reportType: "business_report",
    }));

    await user.click(screen.getByRole("button", { name: "前往下一筛选" }));
    expect(await screen.findByRole("heading", { name: "退货报告 · 2026-08-10" })).toBeVisible();
  });

  it("uses the server batch-review filter across dates and shows a clear task label", async () => {
    const ready = {
      ...draft,
      status: "ready_for_publish" as const,
    };
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path === "/api/versions?batch_review_run_id=81") {
        return Promise.resolve(jsonResponse([ready]));
      }
      if (path === "/api/versions/54") return Promise.resolve(jsonResponse(detailFor(ready)));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MemoryRouter initialEntries={["/versions?batch_review_run_id=81"]}>
      <VersionHistory initialReportDate="2026-08-10" principal={manager} />
    </MemoryRouter>);

    expect(await screen.findByRole("heading", { name: "批量任务 #81 · 待发布草稿" })).toBeVisible();
    expect(screen.getByText("仅显示批量任务 #81 产生且当前仍为待发布的草稿。")).toBeVisible();
    expect(screen.queryByRole("form", { name: "版本筛选" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "返回批量任务" })).toHaveAttribute("href", "/review/batch/81");
    expect(fetchMock).toHaveBeenCalledWith("/api/versions?batch_review_run_id=81", expect.anything());
  });

  it.each([
    ["管理员", admin],
    ["数据管理员", manager],
  ])("lets %s create a revision draft from the current publication", async (_label, principal) => {
    const handoff = vi.fn<(value: PublishedRevisionHandoff) => void>();
    let revisionRequest: { body: Record<string, unknown>; csrf: string; key: string } | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        return Promise.resolve(jsonResponse([current]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/admin/published-moves/undoable") return Promise.resolve(jsonResponse([]));
      if (path === "/api/datasets/41/revisions" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected revision JSON body.");
        const headers = new Headers(init.headers);
        revisionRequest = {
          body: JSON.parse(init.body) as Record<string, unknown>,
          csrf: headers.get("X-CSRF-Token") ?? "",
          key: headers.get("Idempotency-Key") ?? "",
        };
        return Promise.resolve(jsonResponse({
          completed_at: "2026-08-10T05:00:00Z",
          data_revision: 2,
          dataset_id: 41,
          operation_token: revisionRequest.key,
          result_kind: "revision_created",
          review_revision: 3,
          source_dataset_id: 41,
          source_version_id: 53,
          status: "draft",
          version_id: 54,
          version_no: 4,
        }, 201));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <VersionHistory
        initialReportDate="2026-08-10"
        onRevisionCreated={handoff}
        principal={principal}
      />,
    );

    await user.click(await screen.findByRole("button", { name: "创建修订" }));
    const dialog = screen.getByRole("dialog", { name: "创建发布修订" });
    await user.type(within(dialog).getByLabelText("修订原因"), "修正已发布数据");
    await user.click(within(dialog).getByRole("button", { name: "确认创建修订" }));

    await waitFor(() => expect(handoff).toHaveBeenCalledOnce());
    expect(revisionRequest?.body).toEqual({
      expected_publication: {
        version_id: 53,
        published_at: "2026-08-10T03:00:00Z",
      },
      reason: "修正已发布数据",
    });
    expect(revisionRequest?.csrf).toBe("csrf-version-token");
    expect(revisionRequest?.key).toMatch(/^[0-9a-f-]{36}$/i);
    const created = handoff.mock.calls[0]?.[0];
    expect(created?.command).toMatchObject({
      dataset_id: 41,
      result_kind: "revision_created",
      status: "draft",
      version_id: 54,
      version_no: 4,
    });
    expect(created?.reportDate).toBe("2026-08-10");
    expect(created?.reportType).toBe("business_report");
  });

  it("reloads the isolated history when the report type filter changes", async () => {
    const requested: string[] = [];
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      requested.push(path);
      if (path.includes("report_type=business_report")) return Promise.resolve(jsonResponse([]));
      if (path.includes("report_type=return_report")) return Promise.resolve(jsonResponse([{ ...current, report_type: "return_report" }]));
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor({ ...current, report_type: "return_report" })));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await screen.findByText("该日期的经营报告还没有版本。" );
    await user.selectOptions(screen.getByLabelText("报表类型"), "return_report");

    expect(await screen.findByText("退货报告 · 2026-08-10")).toBeVisible();
    expect(requested).toContain("/api/versions?report_date=2026-08-10&report_type=return_report");
  });

  it("does not let an older filter request replace the newest history", async () => {
    let resolveBusiness: ((response: Response) => void) | undefined;
    const businessResponse = new Promise<Response>((resolve) => {
      resolveBusiness = resolve;
    });
    const returnVersion = {
      ...current,
      report_type: "return_report" as const,
      version_id: 63,
    };
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path.includes("report_type=business_report")) return businessResponse;
      if (path.includes("report_type=return_report")) {
        return Promise.resolve(jsonResponse([returnVersion]));
      }
      if (path === "/api/versions/63") {
        return Promise.resolve(jsonResponse(detailFor(returnVersion)));
      }
      if (path === "/api/admin/published-moves/undoable") {
        return Promise.resolve(jsonResponse([]));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.selectOptions(screen.getByLabelText("报表类型"), "return_report");

    expect(await screen.findByText("退货报告 · 2026-08-10")).toBeVisible();
    resolveBusiness?.(jsonResponse([current]));

    await waitFor(() => {
      expect(screen.getByText("退货报告 · 2026-08-10")).toBeVisible();
      expect(screen.queryByText("经营报告 · 2026-08-10")).not.toBeInTheDocument();
    });
  });

  it("does not query or expose move reversal to a data manager", async () => {
    const requested: string[] = [];
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      requested.push(path);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        return Promise.resolve(jsonResponse([current]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<VersionHistory initialReportDate="2026-08-10" principal={manager} />);

    expect(await screen.findByText("与原表逐项核对完成")).toBeVisible();
    expect(requested).not.toContain("/api/admin/published-moves/undoable");
    expect(screen.queryByRole("button", { name: "撤销跨日期移动" })).not.toBeInTheDocument();
  });

  it("lets only an administrator roll the same dataset back with the current publication expectation", async () => {
    let rolledBack = false;
    let rollbackRequest: { body: Record<string, unknown>; key: string } | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path.startsWith("/api/versions?")) {
        return Promise.resolve(jsonResponse(rolledBack
          ? [{ ...historical, is_current_publication: true, published_at: "2026-08-10T04:00:00Z" }, { ...current, is_current_publication: false, published_at: null }]
          : [current, historical]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/versions/51") return Promise.resolve(jsonResponse(detailFor({ ...historical, is_current_publication: true, published_at: "2026-08-10T04:00:00Z" })));
      if (path === "/api/admin/datasets/41/rollback" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected rollback JSON body.");
        rollbackRequest = {
          body: JSON.parse(init.body) as Record<string, unknown>,
          key: new Headers(init.headers).get("Idempotency-Key") ?? "",
        };
        rolledBack = true;
        return Promise.resolve(jsonResponse({
          operation_token: rollbackRequest.key,
          command_id: 71,
          command_type: "rollback",
          transitions: [],
          completed_at: "2026-08-10T04:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.click(await screen.findByRole("button", { name: "回滚到 v1" }));
    const dialog = screen.getByRole("dialog", { name: "管理员回滚确认" });
    expect(within(dialog).getByText("只切换 2026-08-10 · 经营报告 的发布指针。" )).toBeVisible();
    await user.type(within(dialog).getByLabelText("回滚原因"), "当前发布版本录入有误，恢复已核验版本");
    await user.click(within(dialog).getByRole("button", { name: "确认回滚到 v1" }));

    expect(await screen.findByText("已回滚到 v1；其他日期和报表类型未受影响。" )).toBeVisible();
    expect(rollbackRequest?.body).toEqual({
      expected_publication: { version_id: 53, published_at: "2026-08-10T03:00:00Z" },
      target_version_id: 51,
      reason: "当前发布版本录入有误，恢复已核验版本",
    });
    expect(rollbackRequest?.key).toMatch(/^[0-9a-f-]{36}$/i);
    await waitFor(() => expect(screen.getAllByText("当前发布").length).toBeGreaterThan(0));
  });

  it("rebuilds superseded return rollback staging and waits for ready before reusing its token", async () => {
    const returnCurrent: VersionSummaryResponse = {
      ...current,
      dedup_publication_revision: 12,
      publication_revision: 8,
      report_type: "return_report",
    };
    const returnHistorical: VersionSummaryResponse = {
      ...historical,
      dedup_publication_revision: 12,
      publication_revision: 8,
      report_type: "return_report",
    };
    const stagingKeys: string[] = [];
    const rollbackKeys: string[] = [];
    const requestOrder: string[] = [];
    let stagingAttempts = 0;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
      if (path === "/api/versions?report_date=2026-08-10&report_type=return_report") {
        return Promise.resolve(jsonResponse([returnCurrent, returnHistorical]));
      }
      if (path === "/api/versions/53") {
        return Promise.resolve(jsonResponse(detailFor(returnCurrent)));
      }
      if (path === "/api/versions/51") {
        return Promise.resolve(jsonResponse(detailFor(returnHistorical)));
      }
      if (path === "/api/admin/published-moves/undoable") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/publications/return-dedup-staging" && init?.method === "POST") {
        stagingAttempts += 1;
        stagingKeys.push(key);
        requestOrder.push(`stage:${key}`);
        return Promise.resolve(jsonResponse({
          command_url: `/api/publications/commands/${key}`,
          failure_reason: null,
          job_id: 90 + stagingAttempts,
          job_revision: 0,
          next_job_revision: 0,
          proposed_set_digest: `${stagingAttempts}`.repeat(64),
          result_snapshot_id: stagingAttempts === 2 ? 192 : null,
          retry_allowed: false,
          status: stagingAttempts === 2 ? "ready" : "building",
          status_url: `/api/publications/return-dedup-staging/${90 + stagingAttempts}`,
        }));
      }
      if (path === "/api/publications/return-dedup-staging/91") {
        requestOrder.push(`poll:${stagingKeys[0]}`);
        return Promise.resolve(jsonResponse({
          command_url: `/api/publications/commands/${stagingKeys[0]}`,
          failure_reason: null,
          job_id: 91,
          job_revision: 1,
          next_job_revision: 1,
          proposed_set_digest: "1".repeat(64),
          result_snapshot_id: null,
          retry_allowed: false,
          status: "superseded",
          status_url: "/api/publications/return-dedup-staging/91",
        }));
      }
      if (path === "/api/admin/datasets/41/rollback" && init?.method === "POST") {
        rollbackKeys.push(key);
        requestOrder.push(`rollback:${key}`);
        return Promise.resolve(jsonResponse({
          command_id: 71,
          command_type: "rollback",
          completed_at: "2026-08-10T04:00:00Z",
          operation_token: key,
          transitions: [],
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <VersionHistory
        initialReportDate="2026-08-10"
        initialReportType="return_report"
        principal={admin}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "回滚到 v1" }));
    const dialog = screen.getByRole("dialog", { name: "管理员回滚确认" });
    await user.type(within(dialog).getByLabelText("回滚原因"), "退货去重结果复核后恢复历史版本");
    await user.click(within(dialog).getByRole("button", { name: "确认回滚到 v1" }));

    expect(await screen.findByText("已回滚到 v1；其他日期和报表类型未受影响。", {}, { timeout: 4000 })).toBeVisible();
    expect(stagingKeys).toHaveLength(2);
    expect(stagingKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(stagingKeys[1]).not.toBe(stagingKeys[0]);
    expect(rollbackKeys).toEqual([stagingKeys[1]]);
    expect(requestOrder).toEqual([
      `stage:${stagingKeys[0]}`,
      `poll:${stagingKeys[0]}`,
      `stage:${stagingKeys[1]}`,
      `rollback:${stagingKeys[1]}`,
    ]);
  });

  it("creates an empty-target move revision and reuses its UUID after an uncertain result", async () => {
    const handoff = vi.fn<(value: PublishedMoveRevisionHandoff) => void>();
    const operationKeys: string[] = [];
    let moveAttempts = 0;
    let moveBody: Record<string, unknown> | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        return Promise.resolve(jsonResponse([current, historical]));
      }
      if (path === "/api/versions?report_date=2026-08-11&report_type=business_report") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/admin/versions/53/move-date" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected move JSON body.");
        moveBody = JSON.parse(init.body) as Record<string, unknown>;
        operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
        moveAttempts += 1;
        if (moveAttempts === 1) {
          return Promise.resolve(jsonResponse({
            error: { code: "publication_outcome_unknown", message: "移动结果暂时无法确认", request_id: "move-1" },
          }, 503));
        }
        return Promise.resolve(jsonResponse({
          operation_token: operationKeys[1],
          result_kind: "published_move_revision_created",
          dataset_id: 42,
          version_id: 61,
          version_no: 1,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          source_dataset_id: 41,
          source_version_id: 53,
          completed_at: "2026-08-10T05:00:00Z",
        }, 201));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <VersionHistory
        initialReportDate="2026-08-10"
        onMoveRevisionCreated={handoff}
        principal={admin}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "移动到其他日期" }));
    const dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));
    expect(await within(dialog).findByText("目标日期尚无数据")).toBeVisible();
    await user.type(within(dialog).getByLabelText("移动原因"), "原报告归属日期录入错误，移动到正确日期");
    await user.click(within(dialog).getByRole("button", { name: "创建跨日期审核草稿" }));

    expect(await within(dialog).findByText("移动结果暂时无法确认")).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "创建跨日期审核草稿" }));
    expect(await screen.findByText("跨日期审核草稿 v1 已创建；来源日期继续保持发布，需审核后再最终生效。" )).toBeVisible();
    expect(operationKeys).toHaveLength(2);
    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[1]).toBe(operationKeys[0]);
    expect(moveBody).toEqual({
      source_dataset_id: 41,
      expected_source_publication: { version_id: 53, published_at: "2026-08-10T03:00:00Z" },
      target_report_date: "2026-08-11",
      target: { target_kind: "empty", dataset_id: null },
      merge_decisions: [],
      reason: "原报告归属日期录入错误，移动到正确日期",
    });
    expect(handoff).toHaveBeenCalledTimes(1);
    const created = handoff.mock.calls[0]?.[0];
    expect(created?.command.version_id).toBe(61);
    expect(created?.command.operation_token).toBe(operationKeys[0]);
    expect(created?.sourceReportDate).toBe("2026-08-10");
    expect(created?.targetReportDate).toBe("2026-08-11");
    expect(created?.reportType).toBe("business_report");
    expect(created?.sourcePublication).toEqual({ datasetId: 41, versionId: 53, publishedAt: "2026-08-10T03:00:00Z" });
    expect(created?.targetPublication).toEqual({ versionId: null, publishedAt: null });
  });

  it("keeps the move dialog open and never hands off when concurrent state changes", async () => {
    const handoff = vi.fn<(value: PublishedMoveRevisionHandoff) => void>();
    let moveAttempts = 0;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        return Promise.resolve(jsonResponse([current]));
      }
      if (path === "/api/versions?report_date=2026-08-11&report_type=business_report") {
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/admin/versions/53/move-date" && init?.method === "POST") {
        moveAttempts += 1;
        return Promise.resolve(jsonResponse({
          error: {
            code: "publication_conflict",
            message: "目标日期状态已变化",
            request_id: "move-conflict-1",
          },
        }, 409));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <VersionHistory
        initialReportDate="2026-08-10"
        onMoveRevisionCreated={handoff}
        principal={admin}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "移动到其他日期" }));
    const dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));
    await within(dialog).findByText("目标日期尚无数据");
    await user.type(within(dialog).getByLabelText("移动原因"), "将来源版本移动到正确报告日");
    await user.click(within(dialog).getByRole("button", { name: "创建跨日期审核草稿" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent("系统没有自动覆盖任何版本");
    expect(screen.getByRole("dialog", { name: "已发布数据跨日期移动" })).toBeVisible();
    expect(moveAttempts).toBe(1);
    expect(handoff).not.toHaveBeenCalled();
  });

  it("requires an explicit merge, replace, or client-side cancel decision for a published target", async () => {
    const targetPublication: VersionSummaryResponse = {
      ...current,
      dataset_id: 42,
      version_id: 63,
      version_no: 2,
      report_date: "2026-08-11",
      published_at: "2026-08-11T03:00:00Z",
    };
    const moveBodies: Record<string, unknown>[] = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") return Promise.resolve(jsonResponse([current]));
      if (path === "/api/versions?report_date=2026-08-11&report_type=business_report") return Promise.resolve(jsonResponse([targetPublication]));
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/admin/versions/53/move-date" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected move JSON body.");
        moveBodies.push(JSON.parse(init.body) as Record<string, unknown>);
        return Promise.resolve(jsonResponse({
          operation_token: new Headers(init.headers).get("Idempotency-Key"),
          result_kind: "published_move_revision_created",
          dataset_id: 42,
          version_id: 64,
          version_no: 3,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          source_dataset_id: 41,
          source_version_id: 53,
          completed_at: "2026-08-10T05:00:00Z",
        }, 201));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.click(await screen.findByRole("button", { name: "移动到其他日期" }));
    let dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));
    expect(await within(dialog).findByText("目标日期已有发布版本 v2")).toBeVisible();
    expect(within(dialog).getByLabelText("合并目标发布版本")).toBeVisible();
    expect(within(dialog).getByLabelText("替换目标发布版本")).toBeVisible();
    await user.click(within(dialog).getByLabelText("取消本次移动"));
    await user.click(within(dialog).getByRole("button", { name: "关闭且不创建移动草稿" }));
    expect(screen.queryByRole("dialog", { name: "已发布数据跨日期移动" })).not.toBeInTheDocument();
    expect(moveBodies).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "移动到其他日期" }));
    dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));
    await user.click(await within(dialog).findByLabelText("替换目标发布版本"));
    await user.type(within(dialog).getByLabelText("移动原因"), "确认使用来源版本替换目标日发布数据");
    await user.click(within(dialog).getByRole("button", { name: "创建跨日期审核草稿" }));

    await waitFor(() => expect(moveBodies).toHaveLength(1));
    expect(moveBodies[0]).toMatchObject({
      target: {
        target_kind: "published",
        dataset_id: 42,
        publication: { version_id: 63, published_at: "2026-08-11T03:00:00Z" },
        strategy: "replace",
      },
    });
  });

  it("offers safe active-draft merge, recorded cancel, and explicit force-rebuild strategies", async () => {
    const targetPublication: VersionSummaryResponse = {
      ...current,
      dataset_id: 42,
      version_id: 63,
      version_no: 2,
      report_date: "2026-08-11",
      published_at: "2026-08-11T03:00:00Z",
    };
    const targetDraft: VersionSummaryResponse = {
      ...draft,
      dataset_id: 42,
      version_id: 64,
      version_no: 3,
      report_date: "2026-08-11",
      status: "ready_for_publish",
      data_revision: 4,
      review_revision: 5,
      draft_pointed_at: "2026-08-11T04:00:00Z",
    };
    let moveBody: Record<string, unknown> | undefined;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") return Promise.resolve(jsonResponse([current]));
      if (path === "/api/versions?report_date=2026-08-11&report_type=business_report") return Promise.resolve(jsonResponse([targetDraft, targetPublication]));
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/admin/versions/53/move-date" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected move JSON body.");
        moveBody = JSON.parse(init.body) as Record<string, unknown>;
        return Promise.resolve(jsonResponse({
          operation_token: new Headers(init.headers).get("Idempotency-Key"),
          result_kind: "published_move_revision_created",
          dataset_id: 42,
          version_id: 65,
          version_no: 4,
          status: "draft",
          data_revision: 0,
          review_revision: 0,
          source_dataset_id: 41,
          source_version_id: 53,
          completed_at: "2026-08-10T05:00:00Z",
        }, 201));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.click(await screen.findByRole("button", { name: "移动到其他日期" }));
    const dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));
    expect(await within(dialog).findByText("目标日期已有活动草稿 v3")).toBeVisible();
    expect(within(dialog).getByLabelText("合并到活动草稿")).toBeVisible();
    expect(within(dialog).getByLabelText("记录取消，保留活动草稿")).toBeVisible();
    expect(within(dialog).getByLabelText("强制重建并合并目标发布")).toBeVisible();
    await user.click(within(dialog).getByLabelText("强制重建，仅保留来源版本"));
    await user.type(within(dialog).getByLabelText("移动原因"), "目标活动草稿不可继续使用，按来源发布版本重建");
    await user.click(within(dialog).getByLabelText("我确认目标活动草稿会被废弃，但审计记录会保留。"));
    await user.click(within(dialog).getByRole("button", { name: "强制重建跨日期草稿" }));

    await waitFor(() => expect(moveBody).toBeDefined());
    expect(moveBody).toMatchObject({
      target: {
        target_kind: "active_draft",
        dataset_id: 42,
        draft: {
          version_id: 64,
          status: "ready_for_publish",
          data_revision: 4,
          review_revision: 5,
          pointed_at: "2026-08-11T04:00:00Z",
        },
        publication: { version_id: 63, published_at: "2026-08-11T03:00:00Z" },
        action: "force_rebuild",
        rebuild_strategy: "replace",
      },
    });
  });

  it("blocks a historical-only target because the move API has no pointer-less dataset target contract", async () => {
    const pointerlessHistory: VersionSummaryResponse = {
      ...historical,
      dataset_id: 42,
      version_id: 60,
      report_date: "2026-08-11",
    };
    const fetchMock = vi.fn((input: string | URL | Request) => {
      const path = pathOf(input);
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") return Promise.resolve(jsonResponse([current]));
      if (path === "/api/versions?report_date=2026-08-11&report_type=business_report") return Promise.resolve(jsonResponse([pointerlessHistory]));
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.click(await screen.findByRole("button", { name: "移动到其他日期" }));
    const dialog = screen.getByRole("dialog", { name: "已发布数据跨日期移动" });
    await user.type(within(dialog).getByLabelText("目标报告日"), "2026-08-11");
    await user.click(within(dialog).getByRole("button", { name: "检查目标日期" }));

    expect(await within(dialog).findByText("目标日期只有历史版本，但没有活动草稿或当前发布指针。" )).toBeVisible();
    expect(within(dialog).getByText("当前移动 API 无法可靠表达这个目标状态，系统不会猜测或自动覆盖。" )).toBeVisible();
    expect(within(dialog).queryByRole("button", { name: /创建跨日期审核草稿|强制重建跨日期草稿/ })).not.toBeInTheDocument();
  });

  it("lets an administrator atomically undo the current move with server-provided recovery pointers", async () => {
    const candidate: UndoablePublishedMoveResponse = {
      move_command_id: 77,
      source_dataset_id: 40,
      source_report_date: "2026-08-09",
      restore_source_version_id: 47,
      source_current_publication: { version_id: null, published_at: null },
      target_dataset_id: 41,
      target_report_date: "2026-08-10",
      restore_target_version_id: 51,
      target_current_publication: {
        version_id: 53,
        published_at: "2026-08-10T03:00:00Z",
      },
      moved_target_version_id: 53,
      completed_at: "2026-08-10T03:00:00Z",
      report_type: "business_report",
    };
    const operationKeys: string[] = [];
    const requestBodies: Record<string, unknown>[] = [];
    let candidateReads = 0;
    let versionReads = 0;
    let undoAttempts = 0;
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      if (path === "/api/admin/published-moves/undoable") {
        candidateReads += 1;
        return Promise.resolve(jsonResponse(candidateReads === 1 ? [candidate] : []));
      }
      if (path === "/api/versions?report_date=2026-08-10&report_type=business_report") {
        versionReads += 1;
        return Promise.resolve(jsonResponse([current, historical]));
      }
      if (path === "/api/versions/53") return Promise.resolve(jsonResponse(detailFor()));
      if (path === "/api/versions/51") return Promise.resolve(jsonResponse(detailFor(historical)));
      if (path === "/api/admin/published-moves/77/undo" && init?.method === "POST") {
        if (typeof init.body !== "string") throw new Error("Expected undo JSON body.");
        operationKeys.push(new Headers(init.headers).get("Idempotency-Key") ?? "");
        requestBodies.push(JSON.parse(init.body) as Record<string, unknown>);
        undoAttempts += 1;
        if (undoAttempts < 3) {
          return Promise.resolve(jsonResponse({
            error: {
              code: "publication_outcome_unknown",
              message: "撤销结果暂时无法确认",
              request_id: `undo-${undoAttempts}`,
            },
          }, 503));
        }
        return Promise.resolve(jsonResponse({
          operation_token: operationKeys[2],
          command_id: 78,
          command_type: "reverse_move",
          transitions: [],
          completed_at: "2026-08-10T04:00:00Z",
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<VersionHistory initialReportDate="2026-08-10" principal={admin} />);
    await user.click(await screen.findByRole("button", { name: "撤销跨日期移动" }));
    const dialog = screen.getByRole("dialog", { name: "撤销跨日期移动确认" });
    expect(within(dialog).getByText("2026-08-09")).toBeVisible();
    expect(within(dialog).getByText("2026-08-10")).toBeVisible();
    expect(within(dialog).getByText("恢复版本 #47")).toBeVisible();
    expect(within(dialog).getByText("恢复版本 #51")).toBeVisible();
    expect(within(dialog).getByText("#77")).toBeVisible();
    const confirm = within(dialog).getByRole("button", { name: "确认撤销跨日期移动" });
    expect(confirm).toBeDisabled();

    const reason = within(dialog).getByLabelText("撤销原因");
    await user.type(reason, "原移动目标日期选择错误");
    await user.click(confirm);
    expect(await within(dialog).findByText("撤销结果暂时无法确认")).toBeVisible();

    await user.type(reason, "，复核后确认撤销");
    await user.click(confirm);
    await waitFor(() => expect(operationKeys).toHaveLength(2));
    expect(operationKeys[1]).not.toBe(operationKeys[0]);
    await user.click(confirm);

    expect(await screen.findByText("2026-08-09 ← 2026-08-10 的跨日期移动已撤销；两侧发布指针已同时恢复。" )).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "撤销跨日期移动确认" })).not.toBeInTheDocument();
    expect(operationKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(operationKeys[2]).toBe(operationKeys[1]);
    expect(requestBodies[2]).toEqual({
      source_dataset_id: 40,
      expected_source_publication: { version_id: null, published_at: null },
      restore_source_version_id: 47,
      target_dataset_id: 41,
      expected_target_publication: {
        version_id: 53,
        published_at: "2026-08-10T03:00:00Z",
      },
      restore_target_version_id: 51,
      reason: "原移动目标日期选择错误，复核后确认撤销",
    });
    expect(candidateReads).toBeGreaterThanOrEqual(2);
    expect(versionReads).toBeGreaterThanOrEqual(2);
  });

  it("waits for ready return undo staging and reuses the staging token for the final command", async () => {
    const returnCurrent: VersionSummaryResponse = {
      ...current,
      dedup_publication_revision: 15,
      publication_revision: 4,
      report_type: "return_report",
    };
    const returnHistorical: VersionSummaryResponse = {
      ...historical,
      dedup_publication_revision: 15,
      publication_revision: 4,
      report_type: "return_report",
    };
    const sourceCurrent: VersionSummaryResponse = {
      ...returnCurrent,
      dataset_id: 40,
      dedup_publication_revision: 15,
      publication_revision: 7,
      report_date: "2026-08-09",
      version_id: 47,
    };
    const candidate: UndoablePublishedMoveResponse = {
      move_command_id: 79,
      source_dataset_id: 40,
      source_report_date: "2026-08-09",
      restore_source_version_id: 47,
      source_current_publication: { version_id: null, published_at: null },
      target_dataset_id: 41,
      target_report_date: "2026-08-10",
      restore_target_version_id: 51,
      target_current_publication: {
        version_id: 53,
        published_at: "2026-08-10T03:00:00Z",
      },
      moved_target_version_id: 53,
      completed_at: "2026-08-10T03:00:00Z",
      report_type: "return_report",
    };
    const requestOrder: string[] = [];
    let candidateReads = 0;
    let stagingKey = "";
    let undoKey = "";
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = pathOf(input);
      const key = new Headers(init?.headers).get("Idempotency-Key") ?? "";
      if (path === "/api/admin/published-moves/undoable") {
        candidateReads += 1;
        return Promise.resolve(jsonResponse(candidateReads === 1 ? [candidate] : []));
      }
      if (path === "/api/versions?report_date=2026-08-10&report_type=return_report") {
        return Promise.resolve(jsonResponse([returnCurrent, returnHistorical]));
      }
      if (path === "/api/versions?report_date=2026-08-09&report_type=return_report") {
        return Promise.resolve(jsonResponse([sourceCurrent]));
      }
      if (path === "/api/versions/53") {
        return Promise.resolve(jsonResponse(detailFor(returnCurrent)));
      }
      if (path === "/api/publications/return-dedup-staging" && init?.method === "POST") {
        stagingKey = key;
        requestOrder.push(`stage:${key}`);
        return Promise.resolve(jsonResponse({
          command_url: `/api/publications/commands/${key}`,
          failure_reason: null,
          job_id: 93,
          job_revision: 0,
          next_job_revision: 0,
          proposed_set_digest: "b".repeat(64),
          result_snapshot_id: null,
          retry_allowed: false,
          status: "building",
          status_url: "/api/publications/return-dedup-staging/93",
        }));
      }
      if (path === "/api/publications/return-dedup-staging/93") {
        requestOrder.push(`poll:${stagingKey}`);
        return Promise.resolve(jsonResponse({
          command_url: `/api/publications/commands/${stagingKey}`,
          failure_reason: null,
          job_id: 93,
          job_revision: 1,
          next_job_revision: 1,
          proposed_set_digest: "b".repeat(64),
          result_snapshot_id: 193,
          retry_allowed: false,
          status: "ready",
          status_url: "/api/publications/return-dedup-staging/93",
        }));
      }
      if (path === "/api/admin/published-moves/79/undo" && init?.method === "POST") {
        undoKey = key;
        requestOrder.push(`undo:${key}`);
        return Promise.resolve(jsonResponse({
          command_id: 80,
          command_type: "reverse_move",
          completed_at: "2026-08-10T04:00:00Z",
          operation_token: key,
          transitions: [],
        }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <VersionHistory
        initialReportDate="2026-08-10"
        initialReportType="return_report"
        principal={admin}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "撤销跨日期移动" }));
    const dialog = screen.getByRole("dialog", { name: "撤销跨日期移动确认" });
    await user.type(within(dialog).getByLabelText("撤销原因"), "恢复退货移动前的两侧发布指针");
    await user.click(within(dialog).getByRole("button", { name: "确认撤销跨日期移动" }));

    expect(await screen.findByText("2026-08-09 ← 2026-08-10 的跨日期移动已撤销；两侧发布指针已同时恢复。", {}, { timeout: 4000 })).toBeVisible();
    expect(stagingKey).toMatch(/^[0-9a-f-]{36}$/i);
    expect(undoKey).toBe(stagingKey);
    expect(requestOrder).toEqual([
      `stage:${stagingKey}`,
      `poll:${stagingKey}`,
      `undo:${stagingKey}`,
    ]);
  });
});
