import css from "./ReviewDataTable.module.css";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ReviewWorkspace } from "../../api/types";
import { ReviewDataTable } from "./ReviewDataTable";

const value = (type: "text" | "decimal", content: string) => ({ type, value: content });

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
  rows: [
    {
      row_id: 101,
      logical_row_id: "11111111-1111-4111-8111-111111111111",
      row_ordinal: 1,
      row_state: "active",
      base_row_id: 201,
      original_parsed_source_row_id: 301,
      cells: [
        { field_name: "sku", current: value("text", "A-01"), base: value("text", "A-01"), source: value("text", "A-01"), changed_from_base: false, changed_from_source: false, parent_restore_options: [], source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: value("text", "A-01") }, history: [], notes: [] },
        {
          field_name: "sales",
          current: value("decimal", "42.50"),
          base: value("decimal", "40.00"),
          source: value("decimal", "39.00"),
          changed_from_base: true,
          changed_from_source: true,
          parent_restore_options: [{ parent_version_id: 49, value: value("decimal", "40.00") }],
          source_restore_option: { source_batch_id: 11, parsed_source_row_id: 301, value: value("decimal", "39.00") },
          history: [{ id: 501, data_revision: 3, operation: "set", before: value("decimal", "40.00"), after: value("decimal", "42.50"), restored_field_change_id: null, restored_parent_version_id: null, restored_source_row_id: null, actor_user_id: 1, actor_username: "TCJ", reason: "修正录入", occurred_at: "2026-08-10T03:00:00Z" }],
          notes: [{
            note_key: "field-note-1",
            note_id: 801,
            revision_number: 1,
            target_type: "field",
            row_id: 101,
            field_name: "sales",
            visibility: "internal",
            body: "首次核对说明",
            author_user_id: 1,
            author_username: "TCJ",
            review_revision: 1,
            created_at: "2026-08-10T03:05:00Z",
          }],
        },
      ],
      history: [],
      notes: [],
    },
  ],
  version_notes: [],
  latest_full_validation: {
    id: 61,
    data_revision: 3,
    ruleset_version: "business_report_v1",
    status: "succeeded",
    result: "passed",
    data_digest: "a".repeat(64),
    summary: {
      schema_version: 1,
      report_date: "2026-08-10",
      report_type: "business_report",
      row_count: 1,
      totals: { sales: "42.50" },
      stages: {
        parse_fidelity: { data_digest: "b".repeat(64), row_count: 1, totals: { sales: "42.50" }, warning_count: 1, blocking_count: 0 },
        draft_explainability: { data_digest: "a".repeat(64), row_count: 1, totals: { sales: "42.50" }, warning_count: 0, blocking_count: 0 },
      },
    },
    started_at: "2026-08-10T03:10:00Z",
    completed_at: "2026-08-10T03:11:00Z",
    is_current: true,
    issues: [{
      id: 701,
      row_id: 101,
      severity: "warning",
      rule_code: "sales.changed",
      field_name: "sales",
      message: "销售额与源文件不同",
      source_value: "39.00",
      processed_value: "42.50",
      details: null,
      requires_note: true,
      review: { state: "open", event_id: null, event_type: null, actor_user_id: null, actor_username: null, comment: null, occurred_at: null },
      created_at: "2026-08-10T03:11:00Z",
    }],
  },
  pagination: { page: 1, page_size: 50, total_rows: 1, total_pages: 1 },
};

describe("ReviewDataTable", () => {
  it("announces source and base differences independently and keeps filter recovery local", async () => {
    const local = structuredClone(workspace);
    const cell = local.rows[0]!.cells[1]!;
    cell.source = cell.current;
    cell.changed_from_source = false;
    const onPageChange = vi.fn();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={onPageChange} onRestoreField={vi.fn()} onReviewIssue={vi.fn()} onReviseNote={vi.fn()} onSetField={vi.fn()} workspace={local} />);
    expect(screen.getByRole("button", { name: "sales，当前值 42.50，与基础版本不同" })).toHaveTextContent("版本差异");
    expect(screen.getByRole("button", { name: "管理第 1 行状态，当前 active" })).toHaveTextContent("有效");
    const user = userEvent.setup();
    await user.type(screen.getByRole("searchbox", { name: "搜索当前页" }), "not-here");
    expect(screen.getByText("当前筛选没有匹配行")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "清除当前页筛选" }));
    expect(screen.getByRole("searchbox", { name: "搜索当前页" })).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "仅看差异" })).not.toBeChecked();
    expect(onPageChange).not.toHaveBeenCalled();
  });
  it("prefills row and field audit reasons from the authenticated operator", async () => {
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={vi.fn()} onReviewIssue={vi.fn()} onReviseNote={vi.fn()} onSetField={vi.fn()} operator={{ id: 3, username: "manager", display_name: "录入审核" }} workspace={workspace} />);

    await user.click(screen.getByRole("button", { name: /sales，当前值 42.50/ }));
    const cellDrawer = screen.getByRole("dialog", { name: "字段对照" });
    expect(within(cellDrawer).getByLabelText("修改原因")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：修改第 1 行字段 sales；来源：草稿 v2 · 数据修订 r3。",
    );
    expect(within(cellDrawer).getByLabelText("恢复原因")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：恢复第 1 行字段 sales；来源：草稿 v2 · 数据修订 r3。",
    );
    await user.click(within(cellDrawer).getByRole("button", { name: "关闭字段对照" }));

    await user.click(screen.getByRole("button", { name: "新增纠错行" }));
    expect(screen.getByLabelText("新增原因")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：新增纠错行；来源：草稿 v2 · 数据修订 r3。",
    );
    await user.click(screen.getByRole("button", { name: "取消新增" }));

    await user.click(screen.getByRole("button", { name: "管理第 1 行状态，当前 active" }));
    expect(screen.getByLabelText("处理原因")).toHaveValue(
      "操作人：录入审核（manager / 用户 #3）；操作：排除第 1 行；来源：草稿 v2 · 数据修订 r3。",
    );
  });

  it("opens a source/base/current drawer and submits typed edits and all restore modes", async () => {
    const setField = vi.fn().mockResolvedValue(undefined);
    const restoreField = vi.fn().mockResolvedValue(undefined);
    const reviseNote = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={restoreField} onReviewIssue={vi.fn()} onReviseNote={reviseNote} onSetField={setField} workspace={workspace} />);

    await user.click(screen.getByRole("button", { name: /sales，当前值 42.50/ }));
    const drawer = screen.getByRole("dialog", { name: "字段对照" });
    expect(within(drawer).getByText("源文件值").nextSibling).toHaveTextContent("39.00");
    expect(within(drawer).getByText("版本基础值").nextSibling).toHaveTextContent("40.00");
    expect(within(drawer).getByText("当前草稿值").nextSibling).toHaveTextContent("42.50");
    expect(within(drawer).getByRole("button", { name: "关闭字段对照" })).toHaveFocus();

    await user.clear(within(drawer).getByLabelText("当前值"));
    await user.type(within(drawer).getByLabelText("当前值"), "44.20");
    await user.type(within(drawer).getByLabelText("修改原因"), "对照原表修正");
    await user.click(within(drawer).getByRole("button", { name: "保存字段修改" }));
    expect(setField).toHaveBeenCalledWith(expect.objectContaining({ row_id: 101 }), expect.objectContaining({ field_name: "sales" }), { type: "decimal", value: "44.20" }, "对照原表修正");

    await user.clear(within(drawer).getByLabelText("恢复原因"));
    await user.type(within(drawer).getByLabelText("恢复原因"), "撤销错误修正");
    await user.click(within(drawer).getByRole("button", { name: "撤销本次修改" }));
    await user.type(within(drawer).getByLabelText("恢复原因"), "恢复父版本口径");
    await user.click(within(drawer).getByRole("button", { name: "恢复父版本值" }));
    await user.type(within(drawer).getByLabelText("恢复原因"), "恢复原始文件记录");
    await user.click(within(drawer).getByRole("button", { name: "恢复源文件值" }));
    expect(restoreField).toHaveBeenNthCalledWith(1, expect.anything(), expect.anything(), { source_kind: "previous", field_change_id: 501 }, "撤销错误修正");
    expect(restoreField).toHaveBeenNthCalledWith(2, expect.anything(), expect.anything(), { source_kind: "parent", parent_version_id: 49 }, "恢复父版本口径");
    expect(restoreField).toHaveBeenNthCalledWith(3, expect.anything(), expect.anything(), { source_kind: "source", source_batch_id: 11, parsed_source_row_id: 301 }, "恢复原始文件记录");
    await user.click(within(drawer).getByRole("button", { name: "修订备注" }));
    const revisedBody = within(drawer).getByLabelText("修订备注 field-note-1");
    await user.clear(revisedBody);
    await user.type(revisedBody, "第二次核对后的说明");
    await user.selectOptions(within(drawer).getByLabelText("修订备注 field-note-1 的可见范围"), "viewer_visible");
    await user.click(within(drawer).getByRole("button", { name: "保存新修订" }));
    expect(reviseNote).toHaveBeenCalledWith(expect.objectContaining({ note_id: 801, revision_number: 1 }), "第二次核对后的说明", "viewer_visible");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "字段对照" })).not.toBeInTheDocument();
  });

  it("synchronizes the editor after a restored value is loaded", async () => {
    const user = userEvent.setup();
    const restoreField = vi.fn().mockResolvedValue(undefined);
    const setField = vi.fn().mockResolvedValue(undefined);
    const props = {
      busy: false,
      onAddCellNote: vi.fn(),
      onAddRow: vi.fn(),
      onAddRowNote: vi.fn(),
      onChangeRowState: vi.fn(),
      onPageChange: vi.fn(),
      onRestoreField: restoreField,
      onReviewIssue: vi.fn(),
      onReviseNote: vi.fn(),
      onSetField: setField,
    };
    const rendered = render(<ReviewDataTable {...props} workspace={workspace} />);

    await user.click(screen.getByRole("button", { name: /sales，当前值 42.50/ }));
    const drawer = screen.getByRole("dialog", { name: "字段对照" });
    await user.clear(within(drawer).getByLabelText("当前值"));
    await user.type(within(drawer).getByLabelText("当前值"), "999.00");
    await user.type(within(drawer).getByLabelText("恢复原因"), "恢复源文件值");
    await user.click(within(drawer).getByRole("button", { name: "恢复源文件值" }));

    const restoredWorkspace: ReviewWorkspace = {
      ...workspace,
      head: { ...workspace.head, data_revision: workspace.head.data_revision + 1 },
      rows: workspace.rows.map((row) => ({
        ...row,
        cells: row.cells.map((cell) => cell.field_name === "sales"
          ? { ...cell, current: value("decimal", "39.00") }
          : cell),
      })),
    };
    rendered.rerender(<ReviewDataTable {...props} workspace={restoredWorkspace} />);

    expect(within(screen.getByRole("dialog", { name: "字段对照" })).getByLabelText("当前值")).toHaveValue("39.00");
    await user.type(within(drawer).getByLabelText("修改原因"), "确认后再次调整");
    await user.click(within(drawer).getByRole("button", { name: "保存字段修改" }));
    expect(setField).toHaveBeenCalledWith(
      expect.anything(),
      expect.anything(),
      { type: "decimal", value: "39.00" },
      "确认后再次调整",
    );
  });

  it("rejects a blank integer instead of silently converting it to zero", async () => {
    const integerWorkspace: ReviewWorkspace = {
      ...workspace,
      fields: workspace.fields.map((field) => field.name === "sales"
        ? { ...field, kind: "integer", precision: 12, scale: null }
        : field),
      rows: workspace.rows.map((row) => ({
        ...row,
        cells: row.cells.map((cell) => cell.field_name === "sales"
          ? {
              ...cell,
              base: { type: "integer", value: 42 },
              current: { type: "integer", value: 42 },
              source: { type: "integer", value: 42 },
            }
          : cell),
      })),
    };
    const setField = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={vi.fn()} onReviewIssue={vi.fn()} onReviseNote={vi.fn()} onSetField={setField} workspace={integerWorkspace} />);

    await user.click(screen.getByRole("button", { name: /sales，当前值 42/ }));
    const drawer = screen.getByRole("dialog", { name: "字段对照" });
    await user.clear(within(drawer).getByLabelText("当前值"));
    await user.type(within(drawer).getByLabelText("修改原因"), "检查空白整数");
    await user.click(within(drawer).getByRole("button", { name: "保存字段修改" }));

    expect(within(drawer).getByRole("alert")).toHaveTextContent("请输入有效整数。");
    expect(setField).not.toHaveBeenCalled();
  });

  it("adds a complete correction row and excludes or restores an existing row", async () => {
    const addRow = vi.fn().mockResolvedValue(undefined);
    const changeRowState = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    const props = {
      busy: false,
      onAddCellNote: vi.fn(),
      onAddRow: addRow,
      onAddRowNote: vi.fn(),
      onChangeRowState: changeRowState,
      onPageChange: vi.fn(),
      onRestoreField: vi.fn(),
      onReviewIssue: vi.fn(),
      onReviseNote: vi.fn(),
      onSetField: vi.fn(),
    };
    const rendered = render(<ReviewDataTable {...props} workspace={workspace} />);

    await user.click(screen.getByRole("button", { name: "新增纠错行" }));
    const addDrawer = screen.getByRole("dialog", { name: "新增纠错行" });
    expect(within(addDrawer).getByRole("button", { name: "关闭新增纠错行" })).toHaveFocus();
    await user.type(within(addDrawer).getByLabelText("新增行字段 sku"), "A-02");
    await user.type(within(addDrawer).getByLabelText("新增行字段 sales"), "55.10");
    await user.type(within(addDrawer).getByLabelText("新增原因"), "补录解析器遗漏的有效行");
    await user.click(within(addDrawer).getByRole("button", { name: "保存新增行" }));
    expect(addRow).toHaveBeenCalledWith(11, {
      sales: { type: "decimal", value: "55.10" },
      sku: { type: "text", value: "A-02" },
    }, "补录解析器遗漏的有效行");

    await user.click(screen.getByRole("button", { name: "管理第 1 行状态，当前 active" }));
    const excludeDrawer = screen.getByRole("dialog", { name: "行状态操作" });
    expect(within(excludeDrawer).getByRole("button", { name: "关闭行状态操作" })).toHaveFocus();
    await user.type(within(excludeDrawer).getByLabelText("处理原因"), "重复处理行不进入发布结果");
    await user.click(within(excludeDrawer).getByRole("button", { name: "排除这一行" }));
    expect(changeRowState).toHaveBeenLastCalledWith(expect.objectContaining({ row_id: 101 }), "exclude", "重复处理行不进入发布结果");

    const excludedWorkspace: ReviewWorkspace = {
      ...workspace,
      rows: workspace.rows.map((row) => ({ ...row, row_state: "excluded" })),
    };
    rendered.rerender(<ReviewDataTable {...props} workspace={excludedWorkspace} />);
    await user.click(screen.getByRole("button", { name: "管理第 1 行状态，当前 excluded" }));
    const restoreDrawer = screen.getByRole("dialog", { name: "行状态操作" });
    await user.type(within(restoreDrawer).getByLabelText("处理原因"), "确认该行应进入当前草稿");
    await user.click(within(restoreDrawer).getByRole("button", { name: "恢复这一行" }));
    expect(changeRowState).toHaveBeenLastCalledWith(expect.objectContaining({ row_id: 101 }), "restore", "确认该行应进入当前草稿");
  });

  it("requires a comment for warning acknowledgement and exposes the review action", async () => {
    const reviewIssue = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={vi.fn()} onReviewIssue={reviewIssue} onReviseNote={vi.fn()} onSetField={vi.fn()} workspace={workspace} />);

    const issue = screen.getByRole("article", { name: /警告.*销售额与源文件不同/ });
    expect(within(issue).getByRole("button", { name: "确认警告" })).toBeDisabled();
    await user.type(within(issue).getByRole("textbox", { name: "审核说明" }), "与原表核对后确认此差异");
    await user.click(within(issue).getByRole("button", { name: "确认警告" }));
    expect(reviewIssue).toHaveBeenCalledWith(expect.objectContaining({ id: 701 }), "acknowledge", "与原表核对后确认此差异");
  });

  it("retains issue comments after a rejected review and retries explicitly", async () => {
    const reviewIssue = vi.fn().mockRejectedValueOnce(new Error("虚构响应未确认")).mockResolvedValue(undefined);
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={vi.fn()} onReviewIssue={reviewIssue} onReviseNote={vi.fn()} onSetField={vi.fn()} workspace={workspace} />);
    const issue = screen.getByRole("article", { name: /警告.*销售额与源文件不同/ });
    const input = within(issue).getByRole("textbox", { name: "审核说明" });
    await user.type(input, "保留这条审核依据");
    await user.click(within(issue).getByRole("button", { name: "确认警告" }));
    expect(await within(issue).findByRole("alert")).toHaveTextContent("虚构响应未确认");
    expect(input).toHaveValue("保留这条审核依据"); expect(reviewIssue).toHaveBeenCalledTimes(1);
    await user.click(within(issue).getByRole("button", { name: "确认警告" }));
    expect(reviewIssue).toHaveBeenCalledTimes(2);
    expect(reviewIssue.mock.calls[0]).toEqual(reviewIssue.mock.calls[1]);
    expect(within(issue).queryByRole("alert")).not.toBeInTheDocument();
  });

  it("freezes business keys and supports column focus, sorting, difference navigation, and arrow keys", async () => {
    const skuField = workspace.fields[0]!;
    const baseRow = workspace.rows[0]!;
    const asinField: ReviewWorkspace["fields"][number] = { ...skuField, name: "asin" };
    const titleField: ReviewWorkspace["fields"][number] = { ...skuField, name: "title", required_on_add: false };
    const firstRow: ReviewWorkspace["rows"][number] = {
      ...baseRow,
      cells: [
        baseRow.cells[0]!,
        { ...baseRow.cells[0]!, field_name: "asin", current: value("text", "B0FIRST"), base: value("text", "B0FIRST"), source: value("text", "B0FIRST"), source_restore_option: null },
        { ...baseRow.cells[0]!, field_name: "title", current: value("text", "First product"), base: value("text", "First product"), source: value("text", "First product"), source_restore_option: null },
        baseRow.cells[1]!,
      ],
    };
    const secondRow: ReviewWorkspace["rows"][number] = {
      ...firstRow,
      row_id: 102,
      row_ordinal: 2,
      logical_row_id: "22222222-2222-4222-8222-222222222222",
      cells: firstRow.cells.map((cell) => {
        if (cell.field_name === "sku") return { ...cell, current: value("text", "B-02"), base: value("text", "B-02"), source: value("text", "B-02") };
        if (cell.field_name === "asin") return { ...cell, current: value("text", "B0SECOND"), base: value("text", "B0SECOND"), source: value("text", "B0SECOND") };
        if (cell.field_name === "title") return { ...cell, current: value("text", "Second product"), base: value("text", "Second product"), source: value("text", "Second product") };
        return { ...cell, current: value("decimal", "10.00"), base: value("decimal", "9.00"), source: value("decimal", "9.00"), history: [] };
      }),
    };
    const expandedWorkspace: ReviewWorkspace = {
      ...workspace,
      fields: [workspace.fields[0]!, asinField, titleField, workspace.fields[1]!],
      rows: [firstRow, secondRow],
      pagination: { ...workspace.pagination, total_rows: 2 },
    };
    const user = userEvent.setup();
    render(<ReviewDataTable busy={false} onAddCellNote={vi.fn()} onAddRow={vi.fn()} onAddRowNote={vi.fn()} onChangeRowState={vi.fn()} onPageChange={vi.fn()} onRestoreField={vi.fn()} onReviewIssue={vi.fn()} onReviseNote={vi.fn()} onSetField={vi.fn()} workspace={expandedWorkspace} />);

    expect(screen.getByRole("columnheader", { name: /sku/ })).toHaveClass(css["review-table__key-field"]!);
    expect(screen.getByRole("columnheader", { name: /asin/ })).toHaveClass(css["review-table__key-field"]!);

    await user.selectOptions(screen.getByLabelText("显示字段"), "sales");
    expect(screen.queryByRole("columnheader", { name: /title/ })).not.toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /sku/ })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /asin/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "按 sales 升序排序" }));
    const bodyRows = screen.getAllByRole("row").slice(1);
    expect(within(bodyRows[0]!).getByRole("button", { name: /sku，当前值 B-02/ })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一处差异" }));
    expect(within(screen.getByRole("dialog", { name: "字段对照" })).getByText("第 2 行")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭字段对照" }));
    await user.click(screen.getByRole("button", { name: "下一处差异" }));
    expect(within(screen.getByRole("dialog", { name: "字段对照" })).getByText("第 1 行")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "关闭字段对照" }));

    const skuButton = screen.getByRole("button", { name: /sku，当前值 B-02/ });
    skuButton.focus();
    await user.keyboard("{ArrowRight}");
    expect(screen.getByRole("button", { name: /asin，当前值 B0SECOND/ })).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("button", { name: /asin，当前值 B0FIRST/ })).toHaveFocus();
  });
});
