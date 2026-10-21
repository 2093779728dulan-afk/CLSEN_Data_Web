import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import { CatalogImportSectionTable } from "./CatalogImportSectionTable";

describe("CatalogImportSectionTable", () => {
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
    expect(screen.getByRole("option", { name: "2201 · Black · M" })).toBeVisible();
    expect(screen.queryByText("mapping-row")).not.toBeInTheDocument();
  });
});
