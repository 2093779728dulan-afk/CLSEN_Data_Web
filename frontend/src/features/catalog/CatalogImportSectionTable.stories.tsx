import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { MemoryRouter } from "react-router-dom";
import { Button, Checkbox, FormField, Input, StatusBadge } from "../../design-system";
import { CatalogImportSectionTable } from "./CatalogImportSectionTable";
import type { CatalogImportRow, CatalogSection } from "./catalogTypes";
import type { CatalogReviewOptionIndex } from "./catalogReviewOptions";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "skus" | "mappings" | "exceptions" | "read-only" | "field-issues" | "busy" | "empty" | "filtered-empty" | "save-failure" | "refresh-failure" | "long-values";
function sampleRows(section: CatalogSection): CatalogImportRow[] {
  const payload: CatalogImportRow["payload"] = section === "skus" ? { internal_display_sku: "DEMO-NAVY-M", standard_color: "藏青", standard_size: "M", status: "active", source_color_preview: '["藏青","浅蓝"]', source_size_preview: '["M","L"]' }
    : section === "mappings" ? { seller_sku_preview: "DEMO-NAVY-M", identity_decision: null, target_sku_row_key: null, business_occurrences: 24, return_occurrences: 2 }
    : section === "exceptions" ? { seller_sku_preview: "DEMO-待确认", reason_code: "unparsed", action: null, target_sku_row_key: null, corrected_style_code: null, corrected_standard_color: null, corrected_standard_size: null, exclusion_reason: null, note: null }
    : { style_code: "DEMO-01", standard_name: "虚构报告名称", candidate_seller_sku_count: 2, status: "active", change_reason: null };
  return [0, 1].map(index => ({ section, row_key: `demo-${section}-${index + 1}`, row_origin: "system", projection_state: "included", payload: { ...payload, ...(section === "styles" && index === 1 ? { style_code: "DEMO-02", standard_name: null } : {}) } }));
}
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const section: CatalogSection = scenario === "skus" || scenario === "mappings" || scenario === "exceptions" ? scenario : "styles";
  const [rows, setRows] = useState(() => scenario === "empty" ? [] : sampleRows(section).map(row => scenario === "long-values" ? { ...row, payload: { ...row.payload, standard_name: "虚构长商品名称与版型说明".repeat(10), change_reason: "虚构说明".repeat(24) } } : row));
  const [revision, setRevision] = useState(3);
  const [query, setQuery] = useState(scenario === "filtered-empty" ? "无匹配示例" : "");
  const [onlyPending, setOnlyPending] = useState(false);
  const [count, setCount] = useState(0);
  const [writes, setWrites] = useState(0);
  const committed = useRef(rows);
  const nextRevision = useRef(3);
  const failedSave = useRef(false);
  const failedRefresh = useRef(false);
  const options: CatalogReviewOptionIndex = Object.fromEntries(rows.map((row, index) => [row.row_key,
    section === "styles" && index === 0 && scenario !== "long-values" ? { standard_name: [{ value: "虚构报告名称", label: "经营报告 · 虚构报告名称", source: "经营报告" }, { value: "虚构退货名称", label: "退货报告 · 虚构退货名称", source: "退货报告" }] }
      : section === "skus" ? { standard_color: ["藏青", "浅蓝"].map(value => ({ value, label: value })), standard_size: ["M", "L"].map(value => ({ value, label: value })) }
      : section === "mappings" || section === "exceptions" ? { target_sku_row_key: [{ value: "demo-sku-1", label: "DEMO-NAVY-M · 虚构目标变体" }] } : {},
  ]));
  return <MemoryRouter><main className="catalog-workspace" id="main-content">
    <header><h1>分类审核编辑</h1><p>虚构记录与报告候选；保存仅更新当前样板，刷新重置。</p><StatusBadge tone="quiet" label={`样板修订 ${revision} · 模拟提交 ${writes} 次 · ${count} 行未保存`} /></header>
    <FormField label="搜索当前审核项"><Input type="search" value={query} onChange={event => setQuery(event.target.value)} /></FormField>
    <Checkbox label="仅看待处理" checked={onlyPending} onChange={event => setOnlyPending(event.target.checked)} />
    {scenario === "refresh-failure" && <Button onClick={() => { setRows(committed.current); setRevision(nextRevision.current); }}>重新读取样板草稿</Button>}
    <section className="catalog-review-panel"><CatalogImportSectionTable busy={scenario === "busy"} canEdit={scenario !== "read-only"} identityBlocked importId={42} section={section} rows={rows} workflowRevision={revision} options={options} query={query} onlyPending={onlyPending}
      issues={scenario === "field-issues" ? [{ section: "styles", row_key: "demo-styles-2", severity: "error", reason_code: "required", field: "/standard_name" }] : []}
      onDraftCountChange={(_section, value) => setCount(value)}
      saveMutations={async (_id, current, mutations) => {
        setWrites(value => value + 1);
        await new Promise(resolve => setTimeout(resolve, 350));
        if (scenario === "save-failure" && !failedSave.current) { failedSave.current = true; throw new Error("虚构保存失败，请核对后显式重试。"); }
        committed.current = rows.map(row => {
          const mutation = mutations.find(value => (value.row_key ?? value.decision_group_key) === row.row_key);
          return mutation ? { ...row, payload: mutation.payload as CatalogImportRow["payload"] } : row;
        });
        nextRevision.current = current + 1;
        return { workflow_revision: current + 1 };
      }}
      onSaved={current => {
        if (scenario === "refresh-failure" && !failedRefresh.current) { failedRefresh.current = true; return Promise.reject(new Error("虚构明细读取失败。")); }
        setRows(committed.current); setRevision(current);
        return Promise.resolve();
      }} />
    </section>
  </main></MemoryRouter>;
}
const meta = { title: "Patterns/Catalog Section Editors", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Skus: Story = { args: { scenario: "skus" } };
export const Mappings: Story = { args: { scenario: "mappings" } };
export const Exceptions: Story = { args: { scenario: "exceptions" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const FieldIssues: Story = { args: { scenario: "field-issues" } };
export const Busy: Story = { args: { scenario: "busy" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const FilteredEmpty: Story = { args: { scenario: "filtered-empty" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
