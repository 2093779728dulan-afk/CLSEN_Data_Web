import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import type { saveCatalogMutations as SaveCatalogMutations } from "./catalogApi";
import { CatalogImportSectionTable } from "./CatalogImportSectionTable";

describe("CatalogImportSectionTable", () => {
  it("does not mount row editors until their category is opened", () => {
    const props = { importId: 4, onSaved: vi.fn(), rows: [{ payload: { style_code: "DEMO", standard_name: null, status: "active" }, projection_state: "included" as const, row_key: "demo", row_origin: "system" as const, section: "styles" as const }], section: "styles" as const, workflowRevision: 3 };
    const view = render(<CatalogImportSectionTable {...props} active={false} />);
    expect(screen.queryByLabelText("demo standard_name")).not.toBeInTheDocument();
    view.rerender(<CatalogImportSectionTable {...props} active />);
    expect(screen.getByLabelText("demo standard_name")).toBeInTheDocument();
  });

  it("keeps draft values and manual candidate mode while a hidden category ignores changed filters", async () => {
    const saveMutations = vi.fn<typeof SaveCatalogMutations>().mockResolvedValue({ workflow_revision: 4 });
    const onDraftCountChange = vi.fn();
    const props = { importId: 4, onSaved: vi.fn().mockResolvedValue(undefined), onDraftCountChange, saveMutations, options: { demo: { standard_name: [{ value: "原名称", label: "原名称" }] } }, rows: [{ payload: { standard_name: "原名称", style_code: "DEMO", status: "active" }, projection_state: "included" as const, row_key: "demo", row_origin: "system" as const, section: "styles" as const }], section: "styles" as const, workflowRevision: 3 };
    const view = render(<CatalogImportSectionTable {...props} active />);
    fireEvent.change(screen.getByLabelText("demo standard_name"), { target: { value: "__manual__" } });
    const editor = screen.getByRole("textbox", { name: "demo standard_name" });
    fireEvent.change(screen.getByLabelText("demo change_reason"), { target: { value: "保留此修改" } });
    view.rerender(<CatalogImportSectionTable {...props} active={false} onlyPending query="其他分类的筛选" />);
    expect(screen.getByRole("textbox", { name: "demo standard_name" })).toBe(editor);
    expect(onDraftCountChange).toHaveBeenLastCalledWith("styles", 1);
    view.rerender(<CatalogImportSectionTable {...props} active />);
    expect(screen.getByRole("textbox", { name: "demo standard_name" })).toBe(editor);
    expect(screen.getByLabelText("demo change_reason")).toHaveValue("保留此修改");
    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(saveMutations).toHaveBeenCalledOnce());
    expect(saveMutations.mock.calls[0]?.[2][0]?.payload).toMatchObject({ standard_name: "原名称", change_reason: "保留此修改" });
  });

  it("leaves composition and ordinary Enter untouched; Escape resets only the current field", async () => {
    const saveMutations = vi.fn<typeof SaveCatalogMutations>().mockResolvedValue({ workflow_revision: 4 });
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} saveMutations={saveMutations} rows={[{
      payload: { standard_name: "原名称", style_code: "DEMO", change_reason: null, status: "active" },
      projection_state: "included", row_key: "demo", row_origin: "system", section: "styles",
    }]} section="styles" workflowRevision={3} />);
    const name = screen.getByLabelText("demo standard_name");
    const reason = screen.getByLabelText("demo change_reason");
    fireEvent.change(name, { target: { value: "中文输入中的名称" } });
    fireEvent.change(reason, { target: { value: "保留此字段" } });
    expect(fireEvent.keyDown(name, { key: "Enter" })).toBe(true);
    expect(fireEvent.keyDown(name, { key: "ArrowDown" })).toBe(true);
    fireEvent.keyDown(name, { key: "Escape", isComposing: true });
    fireEvent.keyDown(name, { key: "Enter", ctrlKey: true, isComposing: true });
    expect(name).toHaveValue("中文输入中的名称");
    expect(saveMutations).not.toHaveBeenCalled();
    fireEvent.keyDown(name, { key: "Escape" });
    expect(name).toHaveValue("原名称");
    expect(reason).toHaveValue("保留此字段");
    fireEvent.keyDown(reason, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(saveMutations).toHaveBeenCalledOnce());
    expect(saveMutations.mock.calls[0]?.[2][0]?.payload).toMatchObject({ standard_name: "原名称", change_reason: "保留此字段" });
  });
  it("previews the exact before and after values, including edits hidden by search", async () => {
    const saveMutations = vi.fn().mockResolvedValue({ workflow_revision: 4 });
    const row = { payload: { standard_name: "旧名称", style_code: "DEMO", status: "active" }, projection_state: "included" as const, row_key: "demo", row_origin: "system" as const, section: "styles" as const };
    const props = { importId: 4, onSaved: vi.fn().mockResolvedValue(undefined), saveMutations, rows: [row], section: "styles" as const, workflowRevision: 3 };
    const view = render(<CatalogImportSectionTable {...props} />);
    fireEvent.change(screen.getByLabelText("demo standard_name"), { target: { value: "新名称" } });
    view.rerender(<CatalogImportSectionTable {...props} query="无匹配内容" />);
    const summary = screen.getByText("核对本次修改 · 1 行（含筛选隐藏的修改）");
    fireEvent.click(summary);
    expect(screen.getByText("旧名称", { selector: "del" })).toBeInTheDocument();
    expect(screen.getByText("新名称", { selector: "ins" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "保存当前分类修改（1行）" }));
    await waitFor(() => expect(saveMutations).toHaveBeenCalledWith(4, 3, expect.any(Array)));
    expect(JSON.stringify(saveMutations.mock.calls)).toContain('"standard_name":"新名称"');
    expect(screen.queryByText("核对本次修改 · 1 行（含筛选隐藏的修改）")).not.toBeInTheDocument();
  });
  it("does not overwrite a changed server row with a stale local draft", async () => {
    const saveMutations = vi.fn().mockResolvedValue({ workflow_revision: 5 });
    const row = { payload: { standard_name: "原名", style_code: "DEMO", status: "active" }, projection_state: "included" as const, row_key: "demo", row_origin: "system" as const, section: "styles" as const };
    const props = { importId: 4, onSaved: vi.fn().mockResolvedValue(undefined), saveMutations, section: "styles" as const };
    const view = render(<CatalogImportSectionTable {...props} rows={[row]} workflowRevision={3} />);
    fireEvent.change(screen.getByLabelText("demo standard_name"), { target: { value: "本地修改" } });
    view.rerender(<CatalogImportSectionTable {...props} rows={[{ ...row, payload: { ...row.payload, standard_name: "他人修改" } }]} workflowRevision={4} />);
    fireEvent.click(screen.getByRole("button", { name: "保存当前分类修改（1行）" }));
    expect(saveMutations).not.toHaveBeenCalled();
    expect(screen.getByLabelText("demo standard_name")).toHaveValue("本地修改");
    fireEvent.click(screen.getByRole("button", { name: "放弃该行旧修改" }));
    expect(screen.getByLabelText("demo standard_name")).toHaveValue("他人修改");
    fireEvent.change(screen.getByLabelText("demo standard_name"), { target: { value: "重新核对后修改" } });
    fireEvent.click(screen.getByRole("button", { name: "保存当前分类修改（1行）" }));
    await waitFor(() => expect(saveMutations).toHaveBeenCalledWith(4, 4, expect.any(Array)));
  });

  it("submits only once while a save is awaiting acknowledgment", async () => {
    let finish: ((value: { workflow_revision: number }) => void) | undefined;
    const saveMutations = vi.fn(() => new Promise<{ workflow_revision: number }>(resolve => { finish = resolve; }));
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} saveMutations={saveMutations} rows={[{ payload: { standard_name: "", style_code: "DEMO" }, projection_state: "included", row_key: "demo", row_origin: "system", section: "styles" }]} section="styles" workflowRevision={3} />);
    fireEvent.change(screen.getByLabelText("demo standard_name"), { target: { value: "示例名称" } });
    const button = screen.getByRole("button", { name: "保存当前分类修改（1行）" });
    fireEvent.click(button); fireEvent.click(button);
    expect(saveMutations).toHaveBeenCalledOnce();
    expect(screen.getByLabelText("demo standard_name")).toBeDisabled();
    finish?.({ workflow_revision: 4 });
    await waitFor(() => expect(screen.getByText("草稿保存完成")).toBeVisible());
  });
  it("preserves the selected candidate for manual editing, including empty and matching values", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 4 } }), { status: 200 })));
    vi.stubGlobal("fetch", fetchMock);
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} options={{
      "style-row": { standard_name: [{ label: "报告名称", source: "经营报告", value: "报告名称" }] },
    }} rows={[{
      payload: { standard_name: "报告名称", style_code: "100", status: "active" },
      projection_state: "included", row_key: "style-row", row_origin: "system", section: "styles",
    }]} section="styles" workflowRevision={3} />);
    fireEvent.change(screen.getByRole("combobox", { name: "style-row standard_name" }), { target: { value: "__manual__" } });
    expect(screen.getByRole("textbox", { name: "style-row standard_name" })).toHaveValue("报告名称");
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox", { name: "style-row standard_name" }).tagName).toBe("TEXTAREA");
    fireEvent.click(screen.getByRole("button", { name: "清空标准商品名称" }));
    expect(screen.getByRole("textbox", { name: "style-row standard_name" })).toHaveValue("");
    expect(screen.getByRole("textbox", { name: "style-row standard_name" })).toHaveFocus();
    expect(fetchMock).not.toHaveBeenCalled();
    for (const value of ["", "报告名称", "报告名称修订"]) {
      fireEvent.change(screen.getByRole("textbox", { name: "style-row standard_name" }), { target: { value } });
      expect(screen.getByRole("textbox", { name: "style-row standard_name" })).toHaveValue(value);
    }
    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    expect(JSON.stringify(fetchMock.mock.calls)).toContain("报告名称修订");
    fireEvent.click(screen.getByRole("button", { name: "从报告候选中选择 标准商品名称" }));
    expect(screen.getByRole("combobox", { name: "style-row standard_name" })).toHaveValue("报告名称");
    expect(screen.getByText("报告名称", { selector: "p" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "清空标准商品名称" }));
    expect(screen.getByRole("textbox", { name: "style-row standard_name" })).toHaveValue("");
    expect(fetchMock).toHaveBeenCalledOnce();
  });
  it("renders approved or noneditable rows without mutation controls", () => {
    render(<CatalogImportSectionTable canEdit={false} importId={4} onSaved={vi.fn()} rows={[{ payload: { standard_name: "已批准商品", style_code: "100" }, projection_state: "included", row_key: "style-row", row_origin: "system", section: "styles" }]} section="styles" workflowRevision={3} />);
    expect(screen.getByText("已批准商品")).toBeVisible();
    expect(screen.queryByRole("button", { name: "保存此行" })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });
  it("labels approved SKU fields and displays the persisted status in Chinese", () => {
    render(<CatalogImportSectionTable canEdit={false} importId={4} onSaved={vi.fn()} rows={[{
      payload: { internal_display_sku: "100-NAVY-L", standard_color: "NAVY", standard_size: "L", status: "enabled" },
      projection_state: "included", row_key: "sku-row", row_origin: "system", section: "skus",
    }]} section="skus" workflowRevision={3} />);
    for (const label of ["内部展示 SKU", "标准颜色", "标准尺码", "状态", "修改说明"]) expect(screen.getByText(label, { selector: "span" })).toBeVisible();
    expect(screen.getByText("启用")).toBeVisible();
    expect(screen.queryByText("enabled")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "保存此行" })).not.toBeInTheDocument();
  });
  beforeEach(() => setSessionCsrfToken("csrf"));
  afterEach(() => { setSessionCsrfToken(undefined); vi.unstubAllGlobals(); });
  it("saves one style mutation atomically with the current revision", async () => {
    const captured: RequestInit[] = [];
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      void input;
      captured.push(init ?? {});
      return Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 3 } }), { status: 200 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} rows={[{
      payload: { change_reason: null, standard_name: "旧名", status: "active", style_code: "A" },
      projection_state: "included", row_key: "style-row", row_origin: "system", section: "styles",
    }]} section="styles" workflowRevision={2} />);
    fireEvent.change(screen.getByLabelText("style-row standard_name"), { target: { value: "标准名称" } });
    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const init = captured[0];
    if (typeof init?.body !== "string") throw new Error("Expected a JSON command body.");
    const body = JSON.parse(init.body) as Record<string, unknown>;
    expect(body.expected_workflow_revision).toBe(2);
    expect(JSON.stringify(body)).toContain("标准名称");
  });

  it("addresses mapping mutations by decision group", async () => {
    let commandBody: Record<string, unknown> | undefined;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (typeof init?.body !== "string") throw new Error("Expected a JSON command body.");
      commandBody = JSON.parse(init.body) as Record<string, unknown>;
      return Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 4 } }), { status: 200 }));
    }));
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} rows={[{
      payload: {
        change_reason: null,
        exclusion_reason: null,
        identity_decision: "mapped",
        target_sku_row_key: "sku-row",
      },
      projection_state: "included", row_key: "mapping-row", row_origin: "system", section: "mappings",
    }]} section="mappings" workflowRevision={3} />);
    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(commandBody).toBeDefined());
    const mutations = commandBody?.mutations as Array<Record<string, unknown>>;
    expect(mutations[0]).toMatchObject({
      decision_group_key: "mapping-row",
      row_key: null,
      type: "map_seller_sku",
    });
  });

  it("keeps the row locked until the refreshed projection is loaded", async () => {
    let finishReload: (() => void) | undefined;
    const onSaved = vi.fn(() => new Promise<void>((resolve) => { finishReload = resolve; }));
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(
      new Response(JSON.stringify({ safe_result: { workflow_revision: 3 } }), { status: 200 }),
    )));
    render(<CatalogImportSectionTable importId={4} onSaved={onSaved} rows={[{
      payload: { change_reason: null, standard_name: "旧名", status: "active", style_code: "A" },
      projection_state: "included", row_key: "style-row", row_origin: "system", section: "styles",
    }]} section="styles" workflowRevision={2} />);

    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(3));
    expect(screen.getByRole("button", { name: "保存此行" })).toBeDisabled();

    finishReload?.();
    await waitFor(() => expect(screen.getByRole("button", { name: "保存此行" })).toBeEnabled());
  });

  it("shows report-derived choices instead of exposing a target row key", () => {
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} options={{
      "mapping-row": { target_sku_row_key: [{ label: "2201 · Black · M", source: "经营报告", value: "sku-row" }] },
    }} rows={[{
      payload: { change_reason: null, exclusion_reason: null, identity_decision: null, seller_sku_preview: "2201-Black-M", target_sku_row_key: "sku-row" },
      projection_state: "included", row_key: "mapping-row", row_origin: "system", section: "mappings",
    }]} section="mappings" workflowRevision={3} />);
    fireEvent.click(screen.getByRole("radio", { name: "纳入目录" }));
    expect(screen.getByRole("option", { name: "2201 · Black · M" })).toBeVisible();
    expect(screen.getByText("2201 · Black · M", { selector: "p" })).toBeVisible();
    expect(screen.queryByText("mapping-row")).not.toBeInTheDocument();
  });
  it("retains target and exclusion inputs when switching decisions and saves by stable identity", async () => {
    const saveMutations = vi.fn<typeof SaveCatalogMutations>().mockResolvedValue({ workflow_revision: 4 });
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn().mockResolvedValue(undefined)} saveMutations={saveMutations} options={{
      "mapping-row": { target_sku_row_key: [{ label: "2201 · Black · M", value: "sku-row" }] },
    }} rows={[{
      payload: { identity_decision: "mapped", target_sku_row_key: "sku-row", seller_sku_preview: "2201-Black-M", exclusion_reason: null },
      projection_state: "included", row_key: "mapping-row", row_origin: "system", section: "mappings",
    }]} section="mappings" workflowRevision={3} />);
    fireEvent.click(screen.getByRole("radio", { name: "排除" }));
    expect(screen.queryByRole("combobox", { name: "mapping-row target_sku_row_key" })).not.toBeInTheDocument();
    fireEvent.change(screen.getByRole("textbox", { name: "mapping-row exclusion_reason" }), { target: { value: "来源待核对" } });
    fireEvent.click(screen.getByRole("radio", { name: "纳入目录" }));
    expect(screen.getByRole("combobox", { name: "mapping-row target_sku_row_key" })).toHaveValue("sku-row");
    expect(screen.queryByRole("textbox", { name: "mapping-row exclusion_reason" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("radio", { name: "排除" }));
    expect(screen.getByRole("textbox", { name: "mapping-row exclusion_reason" })).toHaveValue("来源待核对");
    fireEvent.click(screen.getByRole("button", { name: "保存此行" }));
    await waitFor(() => expect(saveMutations).toHaveBeenCalledOnce());
    expect(saveMutations.mock.calls[0]?.slice(0, 2)).toEqual([4, 3]);
    const mutation = saveMutations.mock.calls[0]?.[2][0];
    expect(mutation).toMatchObject({ type: "exclude_seller_sku", decision_group_key: "mapping-row", row_key: null });
    expect(mutation?.payload).toMatchObject({ target_sku_row_key: "sku-row", exclusion_reason: "来源待核对" });
  });
  it("keeps invalid conditional fields visible alongside the selected decision", () => {
    render(<CatalogImportSectionTable importId={4} onSaved={vi.fn()} issues={[{ section: "mappings", severity: "blocking", row_key: "mapping-row", field: "target_sku_row_key", reason_code: "required" }]} rows={[{
      payload: { identity_decision: "excluded", target_sku_row_key: null, exclusion_reason: "重复来源" },
      projection_state: "included", row_key: "mapping-row", row_origin: "system", section: "mappings",
    }]} section="mappings" workflowRevision={3} />);
    expect(screen.getByRole("textbox", { name: "mapping-row target_sku_row_key" })).toBeVisible();
    expect(screen.getByRole("radio", { name: "排除" })).toBeChecked();
  });
});
