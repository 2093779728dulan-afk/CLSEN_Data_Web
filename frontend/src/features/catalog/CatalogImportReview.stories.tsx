import type { Meta, StoryObj } from "@storybook/react-vite";
import { fireEvent, userEvent, within } from "storybook/test";
import { useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";

import { CatalogImportReview } from "./CatalogImportReview";
import type { CatalogImportRow, CatalogImportSummary, CatalogSection } from "./catalogTypes";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "loading" | "empty" | "readonly" | "save-failure" | "refresh-failure" | "field-issues";

function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string>();
  const [imported, setImported] = useState<CatalogImportSummary>({
    issues: scenario === "field-issues" ? [{ section: "styles", row_key: "demo-style-2", field: "/standard_name", severity: "error", reason_code: "required" }] : undefined,
    base_catalog_version_id: null, catalog_publication_revision: 0, export_id: 1, failure_reason_code: null,
    has_original_file: false, import_id: 42, parse_attempt_revision: 1, source_kind: "online", status: "needs_attention",
    submitted_by_user_id: null, validation_run_id: null, workflow_revision: 3,
    permissions: { can_approve_high_risk: false, can_approve_normal: false, can_download_original: false,
      can_edit: scenario !== "readonly", can_preview: false, can_rebase: false, can_reject: false,
      can_resume: false, can_submit: false, can_validate: false, can_view: true, can_withdraw: false },
  });
  const [rows, setRows] = useState<Record<CatalogSection, CatalogImportRow[]>>({
    styles: scenario === "empty" ? [] : [
      { section: "styles", row_key: "demo-style-1", row_origin: "system", projection_state: "included", payload: { style_code: "DEMO-01", standard_name: null, status: "active", candidate_seller_sku_count: 12 } },
      { section: "styles", row_key: "demo-style-2", row_origin: "system", projection_state: "included", payload: { style_code: "DEMO-02", standard_name: null, status: "active", candidate_seller_sku_count: 8 } },
      { section: "styles", row_key: "demo-style-3", row_origin: "system", projection_state: "included", payload: { style_code: "DEMO-03", standard_name: null, status: "active", candidate_seller_sku_count: 6 } },
      { section: "styles", row_key: "demo-style-4", row_origin: "system", projection_state: "included", payload: { style_code: "DEMO-04", standard_name: "示例 · 轻量棉质衬衫", status: "active", candidate_seller_sku_count: 10 } },
    ],
    skus: scenario === "empty" ? [] : [
      { section: "skus", row_key: "demo-sku-1", row_origin: "system", projection_state: "included", payload: { style_row_key: "demo-style-1", internal_display_sku: null, standard_color: null, standard_size: null, source_color_preview: '["雾蓝"]', source_size_preview: '["M"]', status: "active" } },
      { section: "skus", row_key: "demo-sku-2", row_origin: "system", projection_state: "included", payload: { style_row_key: "demo-style-2", internal_display_sku: null, standard_color: null, standard_size: null, source_color_preview: '["暖灰"]', source_size_preview: '["L"]', status: "active" } },
    ],
    mappings: scenario === "empty" ? [] : [
      { section: "mappings", row_key: "demo-mapping-1", row_origin: "system", projection_state: "included", payload: { seller_sku_preview: "DEMO01-雾蓝-M", identity_decision: null, target_sku_row_key: null, business_occurrences: 24, return_occurrences: 2 } },
    ], exceptions: [], evidence: [],
  });
  const pending = useRef(rows);
  const committed = useRef(false);
  const committedRevision = useRef(imported.workflow_revision);
  function refresh(revision: number): Promise<void> {
    if (scenario === "refresh-failure") { setError("示例：保存后明细读取失败。"); return Promise.reject(new Error("示例明细暂时不可用。")); }
    setRows(pending.current); setImported(current => ({ ...current, workflow_revision: revision }));
    return Promise.resolve();
  }
  return <MemoryRouter><main className="catalog-workspace" id="main-content"><CatalogImportReview imported={imported} rowsBySection={rows}
    rowsLoading={scenario === "loading"} loadedSections={2} refreshing={refreshing} error={error}
    onReload={() => { setRefreshing(true); void new Promise(resolve => setTimeout(resolve, 600)).then(() => { setError(undefined); if (committed.current) { setRows(pending.current); setImported(current => ({ ...current, workflow_revision: committedRevision.current })); } setRefreshing(false); }); }}
    onSaved={refresh} onWorkflowChanged={() => Promise.resolve()}
    saveMutations={async (_id, revision, mutations) => {
      await new Promise(resolve => setTimeout(resolve, 300));
      if (scenario === "save-failure") throw new Error("示例：草稿版本冲突，请重新核对。");
      pending.current = Object.fromEntries(Object.entries(rows).map(([section, values]) => [section, values.map(row => {
        const mutation = mutations.find(value => (value.row_key ?? value.decision_group_key) === row.row_key);
        return mutation ? { ...row, payload: mutation.payload as CatalogImportRow["payload"] } : row;
      })])) as Record<CatalogSection, CatalogImportRow[]>;
      committed.current = true;
      committedRevision.current = revision + 1;
      return { workflow_revision: revision + 1 };
    }} />
  </main></MemoryRouter>;
}

const meta = { title: "Pages/Catalog Import Review", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const PendingChanges: Story = {
  args: { scenario: "reference" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Fixture setup stays idempotent when Storybook replays after hot updates.
    await fireEvent.change(canvas.getByLabelText("demo-style-1 standard_name"), { target: { value: "示例 · 雾蓝针织开衫" } });
    await fireEvent.change(canvas.getByLabelText("demo-style-2 standard_name"), { target: { value: "示例 · 暖灰直筒长裤" } });
    const summary = canvas.getByText("核对本次修改 · 2 行（含筛选隐藏的修改）");
    if (!(summary.parentElement as HTMLDetailsElement).open) await userEvent.click(summary);
  },
};
export const Loading: Story = { args: { scenario: "loading" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ReadOnly: Story = { args: { scenario: "readonly" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };

export const ValidationIssues: Story = { args: { scenario: "field-issues" } };
