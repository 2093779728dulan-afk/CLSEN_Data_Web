import { ArrowLeft, CheckCheck, CircleAlert, FileClock, History, LoaderCircle, Pencil, SlidersHorizontal, Upload, Undo2, ShieldCheck } from "lucide-react";
import type { Dispatch, SetStateAction } from "react";
import type { SetURLSearchParams } from "react-router-dom";
import type { SupportedEncoding, WorkbenchImportResponse } from "../../api/generated";
import type { ReportType } from "../../api/types";
import { ColumnSettingsPanel } from "../../components/data-table/ColumnSettingsPanel";
import type { DataTableSort, SortCommand } from "../../components/data-table/DataTableHeader";
import { ROW_NUMBER_WIDTH } from "../../components/data-table/columnPresentation";
import type { useColumnLayout } from "../../components/data-table/useColumnLayout";
import { Button, Checkbox, EmptyState, ErrorState, FormField, Input, LinkButton, PageHeader, Pagination, Select, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import { EditableDataGrid } from "./EditableDataGrid";
import type { CellEditorState, WorkbenchColumn, WorkbenchPage } from "./workbenchTypes";
import gridCss from "./DateWorkbenchPage.module.css";
import css from "./DateWorkbenchView.module.css";
import cellCss from "./WorkbenchCell.module.css";

export type ImportConfirmation = { encoding: SupportedEncoding; reportDate: string; reportType: ReportType };
type Props = {
  canWrite: boolean; reportDate: string; reportType: ReportType; returnTo?: string; page?: WorkbenchPage; busy: boolean; error?: string;
  editors: Record<string, CellEditorState>; searchParams: URLSearchParams; setSearchParams: SetURLSearchParams;
  importResult?: WorkbenchImportResponse; importFileName: string; confirmation?: ImportConfirmation;
  setConfirmation: Dispatch<SetStateAction<ImportConfirmation | undefined>>;
  settingsOpen: boolean; setSettingsOpen: Dispatch<SetStateAction<boolean>>;
  layout: ReturnType<typeof useColumnLayout>; sort: DataTableSort;
  onRetry: () => void; switchReport: (type: ReportType) => void; uploadFile: (file: File) => void;
  confirmImport: () => void; continueUploadedSource: () => void; startPublishedRevision: () => void;
  closeSettings: () => void; discardCellEdit: (rowId: number, column: WorkbenchColumn) => void;
  editCell: (rowId: number, column: WorkbenchColumn, input: string) => void;
  saveCell: (rowId: number, column: WorkbenchColumn, input: string, revision: number) => void;
  applySort: (command: SortCommand) => void; undo: () => void; openAdvancedPublishControls: () => void;
};

/** Shared presentation; all API ownership, revisions and operation keys stay in DateWorkbenchPage. */
export function DateWorkbenchView({ canWrite, reportDate, reportType, returnTo, page, busy, error, editors, searchParams, setSearchParams, importResult, importFileName, confirmation, setConfirmation, settingsOpen, setSettingsOpen, layout, sort, onRetry, switchReport, uploadFile, confirmImport, continueUploadedSource, startPublishedRevision, closeSettings, discardCellEdit, editCell, saveCell, applySort, undo, openAdvancedPublishControls }: Props) {
  if (!page && busy) return <main className={css["date-workbench"]} id="main-content" aria-busy="true"><p>正在加载日期表格…</p><Skeleton lines={4} /></main>;
  if (!page) return <main className={css["date-workbench"]} id="main-content"><ErrorState title="工作台读取失败" description={error ?? "工作台不可用。"} action={<Button onClick={() => onRetry()}>重新读取</Button>} /></main>;
  const pendingCount = Object.values(editors).filter((item) => item.state === "editing" || item.state === "saving").length;
  const savingCount = Object.values(editors).filter((item) => item.state === "saving").length;
  const frozenWidth = ROW_NUMBER_WIDTH + Object.keys(layout.frozenLeft).reduce((width, id) => width + (layout.widths[id] ?? 168), 0);
  // Keep room to read/edit a field when frozen identity columns fill a narrow container.
  const gridLayout = { ...layout, frozenLeft: layout.viewportWidth - frozenWidth < 180 ? {} : layout.frozenLeft };
  const reportTypeLabel = reportType === "return_report" ? "退货报告" : "经营报告";
  const recognizedTypeLabel = importResult?.report_type === "return_report" ? "退货报告" : "经营报告";
  const typeMismatch = Boolean(importResult?.report_type && importResult.report_type !== reportType);
  const failedCount = Object.values(editors).filter((item) => item.state === "failed" || item.state === "conflict").length;

  return <main className={css["date-workbench"]} id="main-content">
    <PageHeader eyebrow="日期数据 · 工作台" title={`${reportDate} 日期数据工作台`} description={page.source === "draft" ? "修改在草稿中自动保存；检查并发布后才会进入总表。" : page.source === "published" ? "当前显示已发布版本，原始字段与版本记录保持可追溯。" : "选择报表类型，导入所选日期的 CSV 文件。"}
      meta={<><StatusBadge tone={page.source === "draft" ? "warn" : "quiet"} label={page.head ? `v${page.head.version_no} · ${page.source === "draft" ? "工作草稿" : "当前发布"}` : "未导入"} /><StatusBadge tone="quiet" label={canWrite ? "数据管理" : "只读查看"} /></>}
      actions={<nav className={css.links} aria-label="日期工作台导航"><LinkButton icon={<ArrowLeft />} to={returnTo ?? `/?month=${reportDate.slice(0, 7)}`}>返回总表</LinkButton><LinkButton icon={<History />} variant="quiet" to={`/versions?report_date=${reportDate}&report_type=${reportType}`}>查看版本记录</LinkButton></nav>} />
    <nav aria-label="报表类型" className={css["workbench-tabs"]}>
      {(["business_report", "return_report"] as const).map((type) => <Button variant={type === reportType ? "secondary" : "quiet"} aria-current={type === reportType ? "page" : undefined} key={type} onClick={() => switchReport(type)} type="button">{type === "business_report" ? "经营报告" : "退货报告"}<StatusBadge tone="quiet" label={({ empty: "未导入", draft: "工作草稿", published: "已发布" })[page.tabs.find((tab) => tab.report_type === type)?.source ?? "empty"]} /></Button>)}
    </nav>
    <section aria-label="表格筛选与布局" className={css["workbench-filters"]}>
      <Input key={searchParams.get("search") ?? ""} aria-label="搜索表格" defaultValue={searchParams.get("search") ?? ""} onKeyDown={(event) => { if (event.key === "Enter") { const next = new URLSearchParams(searchParams); const value = event.currentTarget.value.trim(); if (value) next.set("search", value); else next.delete("search"); next.set("page", "1"); setSearchParams(next); } }} placeholder="搜索当前表格，按 Enter" />
      <Checkbox label="只看修改" checked={searchParams.get("changed_only") === "true"} onChange={(event) => { const next = new URLSearchParams(searchParams); if (event.target.checked) next.set("changed_only", "true"); else next.delete("changed_only"); next.set("page", "1"); setSearchParams(next); }} />

      {page.source !== "empty" && <Button icon={<SlidersHorizontal />} variant="quiet" aria-controls="workbench-column-settings" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((current) => !current)} id="workbench-settings-trigger" type="button">列设置</Button>}
    </section>
    {error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
    {page.source === "draft" && <div className={css["workbench-save-state"]} role="status" aria-live="polite" aria-atomic="true"><span className={failedCount ? css.saveError : undefined}>{failedCount ? <CircleAlert aria-hidden="true" /> : <>{savingCount ? <LoaderCircle aria-hidden="true" className={cellCss.spin} /> : pendingCount ? <Pencil aria-hidden="true" /> : <CheckCheck aria-hidden="true" />}</>}</span><span>{failedCount ? `${failedCount} 个单元格未保存` : pendingCount ? [savingCount ? `${savingCount} 个正在保存` : "", pendingCount > savingCount ? `${pendingCount - savingCount} 个待保存` : ""].filter(Boolean).join(" · ") : busy ? "处理中…" : "服务器已同步"}</span><small>{failedCount ? "保留了你的输入。请修改或重新提交错误单元格，再继续检查。" : "Enter 或离开单元格保存 · Escape 放弃本次输入"}</small></div>}
    {typeMismatch && <section className={css["workbench-import-status"]} role="alert"><div><strong>文件类型与当前入口不一致</strong><p>所选文件：{importFileName}</p><p>当前选择的是{reportTypeLabel}，文件内容识别为{recognizedTypeLabel}。这份文件不会补齐{reportTypeLabel}，也不会自动发布。</p><p>请重新选择{reportTypeLabel} CSV；如果确实要处理{recognizedTypeLabel}，请按该类型继续审核。文件夹名称不会改变报表类型。</p></div>{canWrite && <label className={css["workbench-upload-button"]}>重新选择{reportTypeLabel} CSV<input accept=".csv,text/csv" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadFile(file); event.currentTarget.value = ""; }} type="file" /></label>}</section>}
    {importResult?.status === "confirmation_required" && confirmation && <section className={css["workbench-import-status"] + " " + css["workbench-import-confirm"]} aria-label="确认文件识别结果"><div><strong>请确认文件归属</strong><p>{importResult.issue_codes.length ? importResult.issue_codes.map((code) => code === "selected_type_conflict" ? "文件类型与所选报表不一致" : code === "selected_date_conflict" ? "文件日期与所选日期不一致" : code).join("、") : "系统还需要你确认日期、类型和编码。"}</p></div><FormField label="日期"><Input onChange={(event) => setConfirmation((current) => current ? { ...current, reportDate: event.target.value } : current)} type="date" value={confirmation.reportDate} /></FormField><FormField label="类型"><Select onChange={(event) => setConfirmation((current) => current ? { ...current, reportType: event.target.value as ReportType } : current)} value={confirmation.reportType}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></Select></FormField><FormField label="编码"><Select onChange={(event) => setConfirmation((current) => current ? { ...current, encoding: event.target.value as SupportedEncoding } : current)} value={confirmation.encoding}><option value="utf-8-sig">UTF-8 BOM</option><option value="utf-8">UTF-8</option><option value="windows-1252">Windows-1252</option></Select></FormField><Button disabled={busy} onClick={() => void confirmImport()} type="button">{typeMismatch ? `按${confirmation.reportType === "return_report" ? "退货报告" : "经营报告"}继续` : "确认并生成表格"}</Button></section>}
    {importResult && (importResult.duplicate || importResult.status === "duplicate" || importResult.status === "conflict_required" || importResult.status === "failed" || importResult.status === "processing") && <section className={css["workbench-import-status"]} role="status"><div><strong>{importResult.duplicate || importResult.status === "duplicate" ? "该文件已存在，可重新用于审核" : importResult.status === "conflict_required" ? "新文件已保存，尚未替换当前表格" : "文件尚未生成可用表格"}</strong><p>文件批次 #{importResult.batch_id} · {importResult.report_date ?? reportDate}。下方仍是当前版本，不是本次文件的预览。</p><p>{importResult.status === "failed" ? importResult.message : "请核对这份原始文件，再选择替换或合并；已发布版本和审核历史会保留。"}</p></div><Button disabled={busy} onClick={continueUploadedSource} type="button">{typeMismatch ? `按${recognizedTypeLabel}继续审核` : "核对文件并继续审核"}</Button></section>}
    {page.source === "empty" ? <div className={css["workbench-empty"]}><EmptyState icon={<Upload />} title="这个报表日还没有数据" description={canWrite ? "上传 CSV 后会自动识别并直接打开表格。" : "当前没有可读取的已发布表格。"} action={canWrite ? <label className={css["workbench-upload-button"]}>{busy ? "正在识别并生成表格…" : "选择 CSV 文件"}<input accept=".csv,text/csv" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadFile(file); event.currentTarget.value = ""; }} type="file" /></label> : undefined} />{canWrite && <p>当前选择：{reportTypeLabel}。文件类型不一致时会先提示，未经确认不会生成另一类报表。</p>}</div> : <>
      {page.source === "published" && canWrite && <StatusMessage kind="info" title="当前显示已发布版本" action={<Button icon={<FileClock />} loading={busy} onClick={() => void startPublishedRevision()} type="button">开始修改</Button>}>修改前会创建修订草稿，已发布版本会保留。</StatusMessage>}
      {settingsOpen && <ColumnSettingsPanel columns={page.columns} id="workbench-column-settings" layout={layout} onChange={() => undefined} onClose={closeSettings} />}
      <div className={gridCss["workbench-grid-wrap"] + " " + css.grid} role="region" aria-label="日期工作台数据表格，可横向滚动" tabIndex={0} ref={layout.containerRef}><EditableDataGrid editors={editors} layout={gridLayout} onDiscardCell={discardCellEdit} onEditCell={editCell} onSaveCell={(rowId, column, input, revision) => { void saveCell(rowId, column, input, revision); }} onSort={applySort} page={page} sort={sort} /></div>
      <Pagination itemLabel="数据行" loading={busy} page={page.pagination.page} totalItems={page.pagination.total_rows} totalPages={page.pagination.total_pages} onPageChange={(value) => { const next = new URLSearchParams(searchParams); next.set("page", String(value)); setSearchParams(next); }} />
      <footer className={css["workbench-action-bar"]}><div className={css.footerCopy}><ShieldCheck aria-hidden="true" /><span>{page.source === "draft" ? "草稿自动保存，但不会进入总表；检查并发布后才会显示" : canWrite ? "需要调整数据时，先开始修改；检查与发布在审核页完成。" : "当前为只读发布数据，筛选和列设置不会修改报表。"}</span></div><div><Button icon={<Undo2 />} disabled={!page.permissions.can_undo || busy} onClick={() => void undo()} type="button">撤销上次修改</Button><Button disabled={!page.permissions.can_validate || busy || pendingCount > 0 || failedCount > 0} onClick={openAdvancedPublishControls} type="button">运行检查</Button><Button variant="primary" disabled={!page.permissions.can_publish || busy || pendingCount > 0 || failedCount > 0} onClick={openAdvancedPublishControls} type="button">前往发布</Button></div></footer>
    </>}
  </main>;
}
