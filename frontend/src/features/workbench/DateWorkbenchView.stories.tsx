import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useRef, useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import type { WorkbenchImportResponse } from "../../api/generated";
import type { DataTableSort } from "../../components/data-table/DataTableHeader";
import { useColumnLayout } from "../../components/data-table/useColumnLayout";
import { DateWorkbenchView, type ImportConfirmation as ImportConfirmationState } from "./DateWorkbenchView";
import { sampleWorkbench } from "./DateWorkbenchView.fixtures";
import { cellKey, type CellEditorState, type WorkbenchPage } from "./workbenchTypes";

type Scenario = "column-settings" | "reference" | "manager" | "draft" | "save-failure" | "empty" | "read-only-empty" | "loading" | "read-failure" | "import-confirmation" | "import-conflict" | "cell-editing" | "cell-saving" | "cell-saved" | "cell-conflict" | "cell-long-error";
const sampleImport: WorkbenchImportResponse = { batch_id: 44, dataset_id: null, duplicate: false, encoding: "utf-8-sig", issue_codes: ["selected_type_conflict"], message: null, report_date: "2026-09-12", report_type: "return_report", stage: "uploaded", status: "confirmation_required", version_id: null, workspace_url: null };
function SampleWorkbench({ scenario }: { scenario: Scenario }) {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const reportType = searchParams.get("report_type") === "return_report" ? "return_report" : "business_report";
  const canWrite = scenario !== "column-settings" && scenario !== "reference" && scenario !== "read-only-empty";
  const initialSource = scenario.includes("empty") || scenario === "import-confirmation" ? "empty" : scenario === "draft" || scenario === "save-failure" || scenario.startsWith("cell-") ? "draft" : "published";
  const [source, setSource] = useState<WorkbenchPage["source"]>(initialSource);
  const [data, setData] = useState(() => {
    const initial = sampleWorkbench(initialSource, canWrite);
    if (scenario === "cell-saved") {
      const cell = initial.rows[0]!.cells[2]!;
      cell.current = "已保存的示例名称"; cell.changed = true; cell.cell_revision = 1; initial.head!.data_revision = 1;
    }
    return initial;
  });
  const [busy, setBusy] = useState(scenario === "loading");
  const [error, setError] = useState<string | undefined>(scenario === "read-failure" ? "示例：网络暂时不可用，请重新读取所选日期与报表。" : undefined);
  const [settingsOpen, setSettingsOpen] = useState(scenario === "column-settings");
  const [importResult, setImportResult] = useState<WorkbenchImportResponse | undefined>(scenario === "import-confirmation" ? sampleImport : scenario === "import-conflict" ? { ...sampleImport, report_type: "business_report", issue_codes: [], status: "conflict_required" } : undefined);
  const [confirmation, setConfirmation] = useState<ImportConfirmationState | undefined>(scenario === "import-confirmation" ? { encoding: "utf-8-sig", reportDate: "2026-09-12", reportType: "return_report" } : undefined);
  const [importFileName, setImportFileName] = useState("sample-return.csv");
  const [editors, setEditors] = useState<Record<string, CellEditorState>>(() => {
    const state: CellEditorState["state"] | undefined = scenario === "cell-editing" ? "editing" : scenario === "cell-saving" ? "saving" : scenario === "cell-saved" ? "saved" : scenario === "cell-conflict" ? "conflict" : scenario === "save-failure" || scenario === "cell-long-error" ? "failed" : undefined;
    if (!state) return {};
    return { [cellKey(92, 93, "5e2d27a9-f565-4fc8-a8d2-cbd94d8f3594")]: { input: state === "saved" ? "已保存的示例名称" : "待保存的示例名称", state, message: scenario === "cell-conflict" ? "示例：此单元格已被另一位审核员修改，当前输入尚未保存。" : scenario === "cell-long-error" ? "示例：保存请求未得到确认。本次输入仍保留在单元格内，请核对网络状态与字段内容后重新提交。重新提交前不会标记为已保存，也不会进入已发布数据。" : scenario === "save-failure" ? "示例：连接中断，请重新提交此单元格。" : undefined } };
  });
  const timers = useRef(new Set<ReturnType<typeof setTimeout>>());
  useEffect(() => { const active = timers.current; return () => { active.forEach(clearTimeout); }; }, []);
  const allRows = data.rows;
  const query = searchParams.get("search")?.toLowerCase() ?? "";
  const rows = allRows.filter(row => (!query || row.cells.some(cell => String(cell.current).toLowerCase().includes(query))) && (searchParams.get("changed_only") !== "true" || row.cells.some(cell => cell.changed)));
  const page: WorkbenchPage = { ...data, source, report_type: reportType, rows, pagination: { ...data.pagination, total_rows: rows.length }, tabs: [{ report_type: "business_report", source: reportType === "business_report" ? source : "published" }, { report_type: "return_report", source: reportType === "return_report" ? source : "empty" }] };
  const layout = useColumnLayout({ columns: page.columns, identity: { namespace: "workbench", reportType, siteId: 999, userId: 999 } });
  const sortColumnId = searchParams.get("sort_column_id");
  const sort: DataTableSort = sortColumnId ? { columnId: sortColumnId, direction: searchParams.get("direction") === "desc" ? "desc" : "asc" } : null;
  function reset(nextSource: WorkbenchPage["source"]) { setSource(nextSource); setData(sampleWorkbench(nextSource, canWrite, reportType)); setEditors({}); }
  return <><DateWorkbenchView canWrite={canWrite} reportDate="2026-09-12" reportType={reportType} page={busy && !data.head || error ? undefined : scenario === "loading" ? undefined : page} busy={busy} error={error} editors={editors} searchParams={searchParams} setSearchParams={setSearchParams}
    importResult={importResult} importFileName={importFileName} confirmation={confirmation} setConfirmation={setConfirmation} settingsOpen={settingsOpen} setSettingsOpen={setSettingsOpen} layout={layout} sort={sort}
    onRetry={() => { setError(undefined); setBusy(false); }} switchReport={type => { setSearchParams({ report_type: type, page: "1" }); setData(sampleWorkbench(source, canWrite, type)); setEditors({}); }}
    uploadFile={file => { setImportFileName(file.name); setImportResult(sampleImport); setConfirmation({ encoding: "utf-8-sig", reportDate: "2026-09-12", reportType: "return_report" }); }}
    confirmImport={() => { setSearchParams({ report_type: confirmation!.reportType, page: "1" }); reset("draft"); setImportResult(undefined); setConfirmation(undefined); }}
    continueUploadedSource={() => { void navigate(`/review-advanced/2026-09-12?batch_id=44&report_type=${importResult?.report_type ?? reportType}`); }}
    startPublishedRevision={() => reset("draft")} closeSettings={() => { document.getElementById("workbench-settings-trigger")?.focus(); setSettingsOpen(false); }}
    editCell={(rowId, column, input) => setEditors(current => ({ ...current, [cellKey(92, rowId, column.column_id)]: { input, state: "editing" } }))}
    discardCellEdit={(rowId, column) => setEditors(current => { const next = { ...current }; delete next[cellKey(92, rowId, column.column_id)]; return next; })}
    saveCell={(rowId, column, input) => {
      const key = cellKey(92, rowId, column.column_id);
      setEditors(current => ({ ...current, [key]: { input, state: "saving" } }));
      const timer = setTimeout(() => {
        timers.current.delete(timer);
        setData(current => ({ ...current, rows: current.rows.map(row => row.row_id === rowId ? { ...row, cells: row.cells.map(cell => cell.column_id === column.column_id ? { ...cell, current: input, changed: input !== String(cell.base), cell_revision: cell.cell_revision + 1 } : cell) } : row) }));
        setEditors(current => ({ ...current, [key]: { input, state: "saved" } }));
      }, 500);
      timers.current.add(timer);
    }}
    applySort={command => {
      const next = new URLSearchParams(searchParams); next.set("page", "1");
      if (command.direction === null) { next.delete("sort_column_id"); next.delete("direction"); }
      else { next.set("sort_column_id", command.columnId); next.set("direction", command.direction); }
      setSearchParams(next);
      setData(current => ({ ...current, rows: [...current.rows].sort((a, b) => String(a.cells.find(cell => cell.column_id === command.columnId)?.current).localeCompare(String(b.cells.find(cell => cell.column_id === command.columnId)?.current)) * (command.direction === "desc" ? -1 : 1)) }));
    }} undo={() => reset("draft")} openAdvancedPublishControls={() => { void navigate(`/review-advanced/2026-09-12?report_type=${reportType}&version_id=92`); }} />
    <p>本页为虚构交互样板，可编辑与筛选；不上传文件或请求实际 API。刷新样板会重置示例修改。</p>
  </>;
}
function Destination() { const location = useLocation(); return <main><h1>虚构导航目的地</h1><p>{location.pathname}{location.search}</p><Link to="/published/2026-09-12">返回工作台样板</Link></main>; }
function ReferencePage({ scenario = "reference" }: { scenario?: Scenario }) {
  return <MemoryRouter initialEntries={['/published/2026-09-12?report_type=business_report']}><Routes><Route path="/published/:reportDate" element={<SampleWorkbench scenario={scenario} />} /><Route path="*" element={<Destination />} /></Routes></MemoryRouter>;
}
const meta = { title: "Pages/Date Workbench", component: ReferencePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ReferencePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Manager: Story = { args: { scenario: "manager" } };
export const Draft: Story = { args: { scenario: "draft" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ReadOnlyEmpty: Story = { args: { scenario: "read-only-empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const ImportConfirmation: Story = { args: { scenario: "import-confirmation" } };
export const ImportConflict: Story = { args: { scenario: "import-conflict" } };
export const CellEditing: Story = { args: { scenario: "cell-editing" } };
export const CellSaving: Story = { args: { scenario: "cell-saving" } };
export const CellSaved: Story = { args: { scenario: "cell-saved" } };
export const CellConflict: Story = { args: { scenario: "cell-conflict" } };
export const CellLongError: Story = { args: { scenario: "cell-long-error" } };

export const ColumnSettings: Story = { args: { scenario: "column-settings" } };
