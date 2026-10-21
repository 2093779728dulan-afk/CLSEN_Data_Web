import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import type { ImportBatchNoteResponse } from "../../api/generated";
import { BatchNotePanel } from "./BatchNotePanel";

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

const firstNote: ImportBatchNoteResponse = {
  author_user_id: 1,
  author_username: "TCJ",
  body: "原始文件第 12 行为空，已与提交人确认",
  created_at: "2026-08-10T03:05:00Z",
  import_batch_id: 11,
  note_id: 801,
  note_key: "batch-note-1",
  revision_number: 1,
  target_type: "import_batch",
  visibility: "viewer_visible",
};

describe("BatchNotePanel", () => {
  beforeEach(() => {
    setSessionCsrfToken("csrf-test-token");
  });

  afterEach(() => {
    setSessionCsrfToken(undefined);
    vi.unstubAllGlobals();
  });

  it("clears the previous batch notes and draft when switching batches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse([firstNote])));
    const user=userEvent.setup();
    const view=render(<BatchNotePanel batchId={11}/>);
    await user.click(screen.getByRole("button",{name:"管理批次备注"}));
    await screen.findByText(firstNote.body);
    await user.type(screen.getByRole("textbox",{name:"批次备注内容"}),"只属于原批次");
    view.rerender(<BatchNotePanel batchId={12}/>);
    expect(screen.queryByText(firstNote.body)).not.toBeInTheDocument();
    expect(screen.queryByDisplayValue("只属于原批次")).not.toBeInTheDocument();
    expect(screen.getByRole("button",{name:"管理批次备注"})).toHaveAttribute("aria-expanded","false");
  });

  it("loads on demand, appends a batch note, and revises an existing note", async () => {
    let notes = [firstNote];
    const createBodies: Record<string, unknown>[] = [];
    const revisionBodies: Record<string, unknown>[] = [];
    const operationKeys: Array<string | null> = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path === "/api/imports/11/notes" && (init?.method ?? "GET") === "GET") {
        return Promise.resolve(jsonResponse(notes));
      }
      if (path === "/api/imports/11/notes" && init?.method === "POST") {
        createBodies.push(jsonRequestBody(init));
        operationKeys.push(new Headers(init.headers).get("Idempotency-Key"));
        notes = [
          ...notes,
          {
            ...firstNote,
            body: "文件级核对已经完成",
            note_id: 802,
            note_key: "batch-note-2",
            visibility: "internal",
          },
        ];
        return Promise.resolve(jsonResponse({ result: { note_key: "batch-note-2" } }));
      }
      if (path === "/api/imports/11/notes/batch-note-1/revisions" && init?.method === "POST") {
        revisionBodies.push(jsonRequestBody(init));
        operationKeys.push(new Headers(init.headers).get("Idempotency-Key"));
        notes = notes.map((note) => note.note_key === "batch-note-1" ? {
          ...note,
          body: "复核后确认第 12 行为空",
          note_id: 803,
          revision_number: 2,
          visibility: "internal",
        } : note);
        return Promise.resolve(jsonResponse({ result: { note_key: "batch-note-1" } }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<BatchNotePanel batchId={11} />);

    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "管理批次备注" }));
    const panel = screen.getByRole("region", { name: "导入批次 #11 备注" });
    expect(await within(panel).findByText(firstNote.body)).toBeVisible();
    expect(within(panel).queryByText("查看人员可见")).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("批次备注可见范围")).not.toBeInTheDocument();

    await user.type(within(panel).getByLabelText("批次备注内容"), "文件级核对已经完成");
    await user.click(within(panel).getByRole("button", { name: "追加批次备注" }));

    expect(await within(panel).findByText("文件级核对已经完成")).toBeVisible();
    expect(createBodies).toEqual([{
      body: "文件级核对已经完成",
      visibility: "internal",
    }]);
    expect(within(panel).getByLabelText("批次备注内容")).toHaveValue("");

    const originalNote = within(panel).getByText(firstNote.body).closest("li");
    if (!originalNote) throw new Error("Expected the original batch note list item.");
    await user.click(within(originalNote).getByRole("button", { name: "修订备注" }));
    const revisedBody = within(originalNote).getByLabelText("修订备注 batch-note-1");
    await user.clear(revisedBody);
    await user.type(revisedBody, "复核后确认第 12 行为空");
    expect(within(originalNote).queryByLabelText("修订备注 batch-note-1 的可见范围")).not.toBeInTheDocument();
    await user.click(within(originalNote).getByRole("button", { name: "保存新修订" }));

    expect(await within(panel).findByText("复核后确认第 12 行为空")).toBeVisible();
    expect(revisionBodies).toEqual([{
      body: "复核后确认第 12 行为空",
      expected_note_id: 801,
      expected_revision_number: 1,
      visibility: "internal",
    }]);
    expect(operationKeys).toHaveLength(2);
    expect(operationKeys.every((key) => /^[0-9a-f-]{36}$/i.test(key ?? ""))).toBe(true);
  });

  it("keeps one operation key for an append retry and offers a read retry", async () => {
    let reads = 0;
    let writes = 0;
    const writeKeys: Array<string | null> = [];
    const fetchMock = vi.fn((input: string | URL | Request, init?: RequestInit) => {
      const path = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (path === "/api/imports/11/notes" && (init?.method ?? "GET") === "GET") {
        reads += 1;
        if (reads === 1) {
          return Promise.resolve(jsonResponse({
            error: { code: "temporarily_unavailable", message: "批次备注暂时无法读取" },
          }, 503));
        }
        return Promise.resolve(jsonResponse([]));
      }
      if (path === "/api/imports/11/notes" && init?.method === "POST") {
        writes += 1;
        writeKeys.push(new Headers(init.headers).get("Idempotency-Key"));
        if (writes === 1) {
          return Promise.resolve(jsonResponse({
            error: { code: "result_unknown", message: "保存结果暂时无法确认" },
          }, 503));
        }
        return Promise.resolve(jsonResponse({ result: { note_key: "batch-note-1" } }));
      }
      throw new Error(`Unhandled request: ${path}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const user = userEvent.setup();
    render(<BatchNotePanel batchId={11} />);
    await user.click(screen.getByRole("button", { name: "管理批次备注" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("批次备注暂时无法读取");
    expect(screen.getByRole("button", { name: "追加批次备注" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "重新加载批次备注" }));
    expect(await screen.findByText("这个导入批次还没有备注。" )).toBeVisible();

    await user.type(screen.getByLabelText("批次备注内容"), "网络恢复后重试同一条备注");
    await user.click(screen.getByRole("button", { name: "追加批次备注" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存结果暂时无法确认");
    await user.click(screen.getByRole("button", { name: "追加批次备注" }));

    await waitFor(() => expect(writes).toBe(2));
    expect(writeKeys[0]).toMatch(/^[0-9a-f-]{36}$/i);
    expect(writeKeys[1]).toBe(writeKeys[0]);
    expect(screen.getByLabelText("批次备注内容")).toHaveValue("");
  });
});
