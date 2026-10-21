import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { ApiRequestError, StableOperationKeyStore } from "../../api/client";
import type { SupportedEncoding, WorkbenchImportResponse } from "../../api/generated";
import type { ReportType } from "../../api/types";
import { ColumnSettingsPanel } from "../../components/data-table/ColumnSettingsPanel";
import type { DataTableSort, SortCommand } from "../../components/data-table/DataTableHeader";
import { useColumnLayout } from "../../components/data-table/useColumnLayout";
import {
  confirmWorkbenchImport,
  createWorkbenchRevision,
  loadWorkbench,
  undoWorkbench,
  uploadWorkbenchImport,
  writeWorkbenchCell,
} from "./workbenchApi";
import { EditableDataGrid } from "./EditableDataGrid";
import type { CellEditorState, WorkbenchColumn, WorkbenchPage } from "./workbenchTypes";
import { cellKey } from "./workbenchTypes";
import css from "./DateWorkbenchPage.module.css";
import { ArrowLeft } from "lucide-react";
import { Button, Checkbox, ErrorState, Input, LinkButton, Pagination, Select, Skeleton } from "../../design-system";

type Props = {
  canWrite: boolean;
  reportDate: string;
  siteId: number;
  userId: number;
};

const EMPTY_COLUMNS: WorkbenchColumn[] = [];

type ImportConfirmation = {
  encoding: SupportedEncoding;
  reportDate: string;
  reportType: ReportType;
};

type LoadedPage = {
  contextKey: string;
  value: WorkbenchPage;
};

type ViewContext = {
  editorScopeKey: string;
  key: string;
  queryString: string;
  reportDate: string;
  reportType: ReportType;
  searchParamsString: string;
  sortColumnId: string | null;
};

type OwnedEditorState = CellEditorState & {
  generation: number;
};

type EditorStore = {
  scopeKey: string;
  values: Record<string, OwnedEditorState>;
};

type ActiveLoad = {
  busyOwner: number;
  controller: AbortController;
  epoch: number;
};

function reconcileEditors(current: EditorStore, scopeKey: string, nextPage: WorkbenchPage): EditorStore {
  if (current.scopeKey !== scopeKey || !nextPage.head) return { scopeKey, values: {} };
  const authoritativeValues = new Map<string, string>();
  for (const row of nextPage.rows) {
    for (const cell of row.cells) {
      authoritativeValues.set(cellKey(nextPage.head.version_id, row.row_id, cell.column_id), String(cell.current ?? ""));
    }
  }
  const values: Record<string, OwnedEditorState> = {};
  const versionPrefix = `${nextPage.head.version_id}:`;
  for (const [key, editor] of Object.entries(current.values)) {
    if (!key.startsWith(versionPrefix)) continue;
    const authoritativeValue = authoritativeValues.get(key);
    if (authoritativeValue === undefined) {
      values[key] = editor;
      continue;
    }
    if (authoritativeValue === editor.input) continue;
    if (editor.state === "editing" || editor.state === "saving" || editor.state === "failed" || editor.state === "conflict") {
      values[key] = editor;
    }
  }
  return { scopeKey, values };
}

function typedValue(column: WorkbenchColumn, input: string) {
  if (input === "") return { type: "null" as const, value: null };
  if (column.value_kind === "integer") return { type: "integer" as const, value: Number(input) };
  if (column.value_kind === "decimal") return { type: "decimal" as const, value: input };
  if (column.value_kind === "utc_datetime") return { type: "utc_datetime" as const, value: input };
  return { type: "text" as const, value: input };
}

export function DateWorkbenchPage({ canWrite, reportDate, siteId, userId }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const reportType = (searchParams.get("report_type") ?? "business_report") as ReportType;
  const [loadedPage, setLoadedPage] = useState<LoadedPage>();
  const [editorStore, setEditorStore] = useState<EditorStore>({ scopeKey: "", values: {} });
  const [contextError, setContextError] = useState<{ contextKey: string; message: string }>();
  const [busyOwners, setBusyOwners] = useState<Record<number, string>>({});
  const [importResult, setImportResult] = useState<WorkbenchImportResponse>();
  const [importFileName, setImportFileName] = useState("");
  const [confirmation, setConfirmation] = useState<ImportConfirmation>();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const operations = useRef(new StableOperationKeyStore()).current;
  const loadEpochRef = useRef(0);
  const activeLoadRef = useRef<ActiveLoad | undefined>(undefined);
  const busyOwnerSequenceRef = useRef(0);
  const editorOwnershipRef = useRef<Record<string, { generation: number; input: string; scopeKey: string }>>({});
  const sortColumnId = searchParams.get("sort_column_id");
  const sort: DataTableSort = sortColumnId ? {
    columnId: sortColumnId,
    direction: searchParams.get("direction") === "desc" ? "desc" : "asc",
  } : null;
  const query = useMemo(() => {
    const next = new URLSearchParams();
    next.set("page", searchParams.get("page") ?? "1");
    next.set("page_size", "50");
    const search = searchParams.get("search");
    if (search) next.set("search", search);
    if (searchParams.get("changed_only") === "true") next.set("changed_only", "true");
    const sortColumnId = searchParams.get("sort_column_id");
    if (sortColumnId) {
      next.set("sort_column_id", sortColumnId);
      next.set("direction", searchParams.get("direction") === "desc" ? "desc" : "asc");
    }
    return next;
  }, [searchParams]);
  const queryString = query.toString();
  const searchParamsString = searchParams.toString();
  const contextKey = `${reportDate}\n${reportType}\n${queryString}`;
  const editorScopeKey = `${reportDate}\n${reportType}`;
  const viewContext = useMemo<ViewContext>(() => ({
    editorScopeKey,
    key: contextKey,
    queryString,
    reportDate,
    reportType,
    searchParamsString,
    sortColumnId,
  }), [contextKey, editorScopeKey, queryString, reportDate, reportType, searchParamsString, sortColumnId]);
  const currentContextRef = useRef(viewContext);
  currentContextRef.current = viewContext;
  const page = loadedPage?.contextKey === contextKey ? loadedPage.value : undefined;
  const editors = editorStore.scopeKey === editorScopeKey ? editorStore.values : {};
  const error = contextError?.contextKey === contextKey ? contextError.message : undefined;
  const busy = Object.values(busyOwners).includes(contextKey);
  const layout = useColumnLayout({
    columns: page?.columns ?? EMPTY_COLUMNS,
    identity: { namespace: "workbench", reportType, siteId, userId },
  });

  const acquireBusy = useCallback((ownerContextKey: string) => {
    const owner = busyOwnerSequenceRef.current + 1;
    busyOwnerSequenceRef.current = owner;
    setBusyOwners((current) => ({ ...current, [owner]: ownerContextKey }));
    return owner;
  }, []);

  const releaseBusy = useCallback((owner: number) => {
    setBusyOwners((current) => {
      if (!(owner in current)) return current;
      const next = { ...current };
      delete next[owner];
      return next;
    });
  }, []);

  const reload = useCallback(async (target: ViewContext, options: { discardEditors?: boolean } = {}) => {
    if (currentContextRef.current.key !== target.key) return;
    const epoch = loadEpochRef.current + 1;
    loadEpochRef.current = epoch;
    const previousLoad = activeLoadRef.current;
    if (previousLoad) {
      previousLoad.controller.abort();
      releaseBusy(previousLoad.busyOwner);
    }
    const controller = new AbortController();
    const busyOwner = acquireBusy(target.key);
    activeLoadRef.current = { busyOwner, controller, epoch };
    setLoadedPage(undefined);
    setContextError(undefined);
    if (options.discardEditors) {
      editorOwnershipRef.current = {};
      setEditorStore({ scopeKey: target.editorScopeKey, values: {} });
    }
    try {
      const nextPage = await loadWorkbench(target.reportDate, target.reportType, new URLSearchParams(target.queryString), controller.signal);
      if (controller.signal.aborted || loadEpochRef.current !== epoch || currentContextRef.current.key !== target.key) return;
      if (!nextPage || !Array.isArray(nextPage.tabs) || !Array.isArray(nextPage.rows)) {
        throw new Error("服务器返回的日期工作台结构无效。");
      }
      setLoadedPage({ contextKey: target.key, value: nextPage });
      if (options.discardEditors) {
        setEditorStore({ scopeKey: target.editorScopeKey, values: {} });
      } else {
        setEditorStore((current) => reconcileEditors(current, target.editorScopeKey, nextPage));
      }
      setContextError(undefined);
    } catch (reason) {
      if (controller.signal.aborted || loadEpochRef.current !== epoch || currentContextRef.current.key !== target.key) return;
      if (reason instanceof ApiRequestError && reason.code === "invalid_sort_column" && target.sortColumnId) {
        const parameters = new URLSearchParams(target.searchParamsString);
        parameters.set("report_type", target.reportType);
        parameters.set("page", "1");
        parameters.delete("sort_column_id");
        parameters.delete("direction");
        setSearchParams(parameters);
        return;
      }
      setContextError({ contextKey: target.key, message: reason instanceof Error ? reason.message : "无法读取日期工作台。" });
    } finally {
      if (activeLoadRef.current?.epoch === epoch) {
        activeLoadRef.current = undefined;
      }
      releaseBusy(busyOwner);
    }
  }, [acquireBusy, releaseBusy, setSearchParams]);

  useEffect(() => {
    editorOwnershipRef.current = {};
    setEditorStore((current) => current.scopeKey === editorScopeKey ? current : { scopeKey: editorScopeKey, values: {} });
  }, [editorScopeKey]);

  useEffect(() => {
    void reload(viewContext);
    return () => {
      loadEpochRef.current += 1;
      const activeLoad = activeLoadRef.current;
      if (activeLoad) {
        activeLoad.controller.abort();
        releaseBusy(activeLoad.busyOwner);
        activeLoadRef.current = undefined;
      }
    };
  }, [releaseBusy, reload, viewContext]);

  const switchReport = (next: ReportType) => {
    const parameters = new URLSearchParams(searchParams);
    parameters.set("report_type", next);
    parameters.set("page", "1");
    setSearchParams(parameters);
  };

  const applySort = (command: SortCommand) => {
    const parameters = new URLSearchParams(searchParams);
    parameters.set("page", "1");
    if (command.direction === null) {
      parameters.delete("sort_column_id");
      parameters.delete("direction");
    } else {
      parameters.set("sort_column_id", command.columnId);
      parameters.set("direction", command.direction);
    }
    setSearchParams(parameters);
  };

  const closeSettings = () => {
    document.getElementById("workbench-settings-trigger")?.focus();
    setSettingsOpen(false);
  };

  const applyImportResult = async (result: WorkbenchImportResponse, origin: ViewContext) => {
    if (currentContextRef.current.key !== origin.key) return;
    setImportResult(result);
    setContextError(undefined);
    if (result.status === "confirmation_required") {
      setConfirmation({
        encoding: result.encoding ?? (origin.reportType === "business_report" ? "utf-8-sig" : "windows-1252"),
        reportDate: result.report_date ?? origin.reportDate,
        reportType: result.report_type ?? origin.reportType,
      });
      return;
    }
    setConfirmation(undefined);
    if (result.status !== "workspace_ready") return;
    if (result.workspace_url && !result.workspace_url.startsWith(`/review/${origin.reportDate}?`)) {
      void navigate(result.workspace_url);
      return;
    }
    if (result.report_type && result.report_type !== origin.reportType) {
      const parameters = new URLSearchParams(origin.searchParamsString);
      parameters.set("report_type", result.report_type);
      setSearchParams(parameters);
      return;
    }
    await reload(origin);
  };

  const uploadFile = async (file: File) => {
    const origin = viewContext;
    setImportFileName(file.name);
    const slot = `workbench-import:${file.name}:${file.size}:${file.lastModified}`;
    const fingerprint = { name: file.name, size: file.size, lastModified: file.lastModified, reportDate: origin.reportDate, reportType: origin.reportType };
    const operationKey = operations.forCommand(slot, "workbench-import", fingerprint);
    const busyOwner = acquireBusy(origin.key);
    setContextError(undefined);
    setImportResult(undefined);
    setConfirmation(undefined);
    try {
      const result = await uploadWorkbenchImport(origin.reportDate, file, operationKey, origin.reportType);
      operations.complete(slot, operationKey);
      await applyImportResult(result, origin);
    } catch (reason) {
      if (currentContextRef.current.key === origin.key) {
        setContextError({ contextKey: origin.key, message: reason instanceof Error ? reason.message : "文件上传失败，请重试。" });
      }
    } finally {
      releaseBusy(busyOwner);
    }
  };

  const continueUploadedSource = () => {
    if (!importResult) return;
    const parameters = new URLSearchParams({ batch_id: String(importResult.batch_id), report_type: importResult.report_type ?? reportType });
    void navigate(`/review-advanced/${importResult.report_date ?? reportDate}?${parameters}`, { state: { workbenchReturn: `${location.pathname}${location.search}` } });
  };

  const confirmImport = async () => {
    if (!importResult || !confirmation) return;
    const origin = viewContext;
    const slot = `workbench-import-confirm:${importResult.batch_id}`;
    const body = {
      encoding: confirmation.encoding,
      report_date: confirmation.reportDate,
      report_type: confirmation.reportType,
    };
    const operationKey = operations.forCommand(slot, "workbench-import-confirm", body);
    const busyOwner = acquireBusy(origin.key);
    setContextError(undefined);
    try {
      const result = await confirmWorkbenchImport(importResult.batch_id, body, operationKey);
      operations.complete(slot, operationKey);
      await applyImportResult(result, origin);
    } catch (reason) {
      if (currentContextRef.current.key === origin.key) {
        setContextError({ contextKey: origin.key, message: reason instanceof Error ? reason.message : "无法确认这份文件。" });
      }
    } finally {
      releaseBusy(busyOwner);
    }
  };

  const openAdvancedPublishControls = () => {
    const parameters = new URLSearchParams({ report_type: reportType });
    if (page?.head) parameters.set("version_id", String(page.head.version_id));
    void navigate(`/review-advanced/${reportDate}?${parameters}`, { state: { workbenchReturn: `${location.pathname}${location.search}` } });
  };

  const startPublishedRevision = async () => {
    if (!page?.head || page.source !== "published") return;
    const origin = viewContext;
    const slot = `revision:${origin.reportDate}:${origin.reportType}`;
    const body = { published_version_id: page.head.version_id };
    const key = operations.forCommand(slot, "revision", body);
    const busyOwner = acquireBusy(origin.key);
    try {
      await createWorkbenchRevision(origin.reportDate, origin.reportType, page.head.version_id, key);
      operations.complete(slot, key);
      await reload(origin);
    } catch (reason) {
      if (currentContextRef.current.key === origin.key) {
        setContextError({ contextKey: origin.key, message: reason instanceof Error ? reason.message : "无法创建修订草稿。" });
      }
    } finally {
      releaseBusy(busyOwner);
    }
  };

  const editCell = (rowId: number, column: WorkbenchColumn, input: string) => {
    if (!page?.head || page.source !== "draft") return;
    const keyName = cellKey(page.head.version_id, rowId, column.column_id);
    const previous = editorOwnershipRef.current[keyName];
    const generation = previous?.scopeKey === editorScopeKey ? previous.generation + 1 : 1;
    editorOwnershipRef.current[keyName] = { generation, input, scopeKey: editorScopeKey };
    setEditorStore((current) => current.scopeKey !== editorScopeKey ? current : {
      scopeKey: current.scopeKey,
      values: { ...current.values, [keyName]: { generation, input, state: "editing" } },
    });
  };

  const discardCellEdit = (rowId: number, column: WorkbenchColumn) => {
    if (!page?.head) return;
    const keyName = cellKey(page.head.version_id, rowId, column.column_id);
    delete editorOwnershipRef.current[keyName];
    setEditorStore((current) => {
      if (current.scopeKey !== editorScopeKey || !current.values[keyName]) return current;
      const values = { ...current.values };
      delete values[keyName];
      return { scopeKey: current.scopeKey, values };
    });
  };

  const saveCell = async (rowId: number, column: WorkbenchColumn, input: string, revision: number) => {
    if (!page?.head || page.source !== "draft") return;
    const origin = viewContext;
    const versionId = page.head.version_id;
    const keyName = cellKey(versionId, rowId, column.column_id);
    let ownership = editorOwnershipRef.current[keyName];
    if (!ownership || ownership.scopeKey !== origin.editorScopeKey || ownership.input !== input) {
      ownership = {
        generation: ownership?.scopeKey === origin.editorScopeKey ? ownership.generation + 1 : 1,
        input,
        scopeKey: origin.editorScopeKey,
      };
      editorOwnershipRef.current[keyName] = ownership;
    }
    const submittedGeneration = ownership.generation;
    const body = {
      head: {
        dataset_id: page.head.dataset_id,
        status: page.head.status as "draft" | "ready_for_publish",
        data_revision: page.head.data_revision,
        review_revision: page.head.review_revision,
        pointed_at: page.head.pointed_at,
      },
      value: typedValue(column, input),
      expected_cell_revision: revision,
      reason: `在日期工作台修改“${column.source_header}”`,
    };
    const operationKey = operations.forCommand(keyName, "set-cell", body);
    setEditorStore((current) => {
      if (current.scopeKey !== origin.editorScopeKey) return current;
      const editor = current.values[keyName];
      if (editor && editor.generation > submittedGeneration) return current;
      return { scopeKey: current.scopeKey, values: {
        ...current.values,
        [keyName]: { generation: submittedGeneration, input, state: "saving" },
      } };
    });
    try {
      const result = await writeWorkbenchCell(versionId, rowId, column.column_id, body, operationKey);
      operations.complete(keyName, operationKey);
      const settlementContext = currentContextRef.current;
      if (settlementContext.editorScopeKey !== origin.editorScopeKey) return;
      if (settlementContext.key === origin.key) {
        setLoadedPage((current) => {
          if (current?.contextKey !== origin.key || current.value.head?.version_id !== versionId) return current;
          return { contextKey: current.contextKey, value: {
            ...current.value,
            head: { ...current.value.head, ...result.head },
            rows: current.value.rows.map((row) => row.row_id === rowId ? {
              ...row,
              cells: row.cells.map((cell) => cell.column_id === column.column_id ? {
                ...cell,
                current: result.cell.current,
                base: result.cell.base,
                cell_revision: result.cell.cell_revision,
                changed: result.cell.changed,
              } : cell),
            } : row),
          } };
        });
      }
      const latestOwnership = editorOwnershipRef.current[keyName];
      if (latestOwnership?.scopeKey === origin.editorScopeKey && latestOwnership.generation === submittedGeneration) {
        setEditorStore((current) => {
          const editor = current.scopeKey === origin.editorScopeKey ? current.values[keyName] : undefined;
          if (!editor || editor.generation !== submittedGeneration) return current;
          return { scopeKey: current.scopeKey, values: {
            ...current.values,
            [keyName]: { generation: submittedGeneration, input, state: "saved" },
          } };
        });
      }
      if (settlementContext.key !== origin.key) await reload(settlementContext);
    } catch (reason) {
      if (currentContextRef.current.editorScopeKey !== origin.editorScopeKey) return;
      const latestOwnership = editorOwnershipRef.current[keyName];
      if (latestOwnership?.scopeKey !== origin.editorScopeKey || latestOwnership.generation !== submittedGeneration) return;
      const conflict = reason instanceof ApiRequestError && reason.status === 409;
      setEditorStore((current) => {
        const editor = current.scopeKey === origin.editorScopeKey ? current.values[keyName] : undefined;
        if (!editor || editor.generation !== submittedGeneration) return current;
        return { scopeKey: current.scopeKey, values: {
          ...current.values,
          [keyName]: {
            generation: submittedGeneration,
            input,
            message: reason instanceof Error ? reason.message : "保存失败，请重试。",
            state: conflict ? "conflict" : "failed",
          },
        } };
      });
    }
  };

  const undo = async () => {
    if (!page?.head || page.source !== "draft") return;
    const origin = viewContext;
    const body = { head: {
      dataset_id: page.head.dataset_id,
      status: page.head.status,
      data_revision: page.head.data_revision,
      review_revision: page.head.review_revision,
      pointed_at: page.head.pointed_at,
    }, reason: "从日期工作台撤销上次修改" };
    const slot = `undo:${page.head.version_id}`;
    const operationKey = operations.forCommand(slot, "undo", body);
    const busyOwner = acquireBusy(origin.key);
    try {
      await undoWorkbench(page.head.version_id, body, operationKey);
      operations.complete(slot, operationKey);
      await reload(origin, { discardEditors: true });
    } catch (reason) {
      if (currentContextRef.current.key === origin.key) {
        setContextError({ contextKey: origin.key, message: reason instanceof Error ? reason.message : "撤销失败。" });
      }
    } finally { releaseBusy(busyOwner); }
  };

  if (!page && busy) return <main className={css["date-workbench"]} id="main-content" aria-busy="true"><p>正在加载日期表格…</p><Skeleton lines={4} /></main>;
  if (!page) return <main className={css["date-workbench"]} id="main-content"><ErrorState title="工作台读取失败" description={error ?? "工作台不可用。"} action={<Button onClick={() => void reload(viewContext)}>重新读取</Button>} /></main>;
  const pendingCount = Object.values(editors).filter((item) => item.state === "editing" || item.state === "saving").length;
  const reportTypeLabel = reportType === "return_report" ? "退货报告" : "经营报告";
  const recognizedTypeLabel = importResult?.report_type === "return_report" ? "退货报告" : "经营报告";
  const typeMismatch = Boolean(importResult?.report_type && importResult.report_type !== reportType);
  const failedCount = Object.values(editors).filter((item) => item.state === "failed" || item.state === "conflict").length;

  return <main className={css["date-workbench"]} id="main-content">
    <header className={css["workbench-toolbar"]}>
      <div><LinkButton icon={<ArrowLeft />} to={`/?month=${reportDate.slice(0, 7)}`}>返回总表</LinkButton><LinkButton to={`/versions?report_date=${reportDate}&report_type=${reportType}`}>查看版本记录</LinkButton><h1>{reportDate} 日期数据工作台</h1></div>
      <div className={css["workbench-save-state"]}>{failedCount ? `${failedCount} 个单元格未保存` : pendingCount ? `${pendingCount} 个单元格待保存` : busy ? "处理中…" : "服务器已同步"}</div>
    </header>
    <nav aria-label="报表类型" className={css["workbench-tabs"]}>
      {(["business_report", "return_report"] as const).map((type) => <Button aria-current={type === reportType ? "page" : undefined} key={type} onClick={() => switchReport(type)} type="button">{type === "business_report" ? "经营报告" : "退货报告"}<small>{({ empty: "未导入", draft: "工作草稿", published: "已发布" })[page.tabs.find((tab) => tab.report_type === type)?.source ?? "empty"]}</small></Button>)}
    </nav>
    <section className={css["workbench-filters"]}>
      <Input key={searchParams.get("search") ?? ""} aria-label="搜索表格" defaultValue={searchParams.get("search") ?? ""} onKeyDown={(event) => { if (event.key === "Enter") { const next = new URLSearchParams(searchParams); const value = event.currentTarget.value.trim(); if (value) next.set("search", value); else next.delete("search"); next.set("page", "1"); setSearchParams(next); } }} placeholder="搜索当前表格，按 Enter" />
      <Checkbox label="只看修改" checked={searchParams.get("changed_only") === "true"} onChange={(event) => { const next = new URLSearchParams(searchParams); if (event.target.checked) next.set("changed_only", "true"); else next.delete("changed_only"); next.set("page", "1"); setSearchParams(next); }} />
      {page.head && <span>v{page.head.version_no} · {page.source === "draft" ? "工作草稿" : "当前发布"}</span>}
      {page.source !== "empty" && <Button aria-controls="workbench-column-settings" aria-expanded={settingsOpen} onClick={() => setSettingsOpen((current) => !current)} id="workbench-settings-trigger" type="button">列设置</Button>}
    </section>
    {error && <p className={css["workbench-error"]} role="alert">{error}</p>}
    {typeMismatch && <section className={css["workbench-import-status"]} role="alert"><div><strong>文件类型与当前入口不一致</strong><p>所选文件：{importFileName}</p><p>当前选择的是{reportTypeLabel}，文件内容识别为{recognizedTypeLabel}。这份文件不会补齐{reportTypeLabel}，也不会自动发布。</p><p>请重新选择{reportTypeLabel} CSV；如果确实要处理{recognizedTypeLabel}，请按该类型继续审核。文件夹名称不会改变报表类型。</p></div>{canWrite && <label className={css["workbench-upload-button"]}>重新选择{reportTypeLabel} CSV<input accept=".csv,text/csv" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadFile(file); event.currentTarget.value = ""; }} type="file" /></label>}</section>}
    {importResult?.status === "confirmation_required" && confirmation && <section className={css["workbench-import-status"] + " " + css["workbench-import-confirm"]} aria-label="确认文件识别结果"><div><strong>请确认文件归属</strong><p>{importResult.issue_codes.length ? importResult.issue_codes.map((code) => code === "selected_type_conflict" ? "文件类型与所选报表不一致" : code === "selected_date_conflict" ? "文件日期与所选日期不一致" : code).join("、") : "系统还需要你确认日期、类型和编码。"}</p></div><label>日期<Input onChange={(event) => setConfirmation((current) => current ? { ...current, reportDate: event.target.value } : current)} type="date" value={confirmation.reportDate} /></label><label>类型<Select onChange={(event) => setConfirmation((current) => current ? { ...current, reportType: event.target.value as ReportType } : current)} value={confirmation.reportType}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></Select></label><label>编码<Select onChange={(event) => setConfirmation((current) => current ? { ...current, encoding: event.target.value as SupportedEncoding } : current)} value={confirmation.encoding}><option value="utf-8-sig">UTF-8 BOM</option><option value="utf-8">UTF-8</option><option value="windows-1252">Windows-1252</option></Select></label><Button disabled={busy} onClick={() => void confirmImport()} type="button">{typeMismatch ? `按${confirmation.reportType === "return_report" ? "退货报告" : "经营报告"}继续` : "确认并生成表格"}</Button></section>}
    {importResult && (importResult.duplicate || importResult.status === "duplicate" || importResult.status === "conflict_required" || importResult.status === "failed" || importResult.status === "processing") && <section className={css["workbench-import-status"]} role="status"><div><strong>{importResult.duplicate || importResult.status === "duplicate" ? "该文件已存在，可重新用于审核" : importResult.status === "conflict_required" ? "新文件已保存，尚未替换当前表格" : "文件尚未生成可用表格"}</strong><p>文件批次 #{importResult.batch_id} · {importResult.report_date ?? reportDate}。下方仍是当前版本，不是本次文件的预览。</p><p>{importResult.status === "failed" ? importResult.message : "请核对这份原始文件，再选择替换或合并；已发布版本和审核历史会保留。"}</p></div><Button disabled={busy} onClick={continueUploadedSource} type="button">{typeMismatch ? `按${recognizedTypeLabel}继续审核` : "核对文件并继续审核"}</Button></section>}
    {page.source === "empty" ? <section className={css["workbench-empty"]}><h2>这个报表日还没有数据</h2><p>{canWrite ? "上传 CSV 后会自动识别并直接打开表格。" : "当前没有可读取的已发布表格。"}</p>{canWrite && <label className={css["workbench-upload-button"]}>{busy ? "正在识别并生成表格…" : "选择 CSV 文件"}<input accept=".csv,text/csv" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadFile(file); event.currentTarget.value = ""; }} type="file" /></label>} {canWrite && <small>当前选择：{reportTypeLabel}。文件类型不一致时会先提示，未经确认不会生成另一类报表。</small>}</section> : <>
      {page.source === "published" && canWrite && <div className={css["workbench-revision"]}><span>当前显示已发布版本，修改前会创建修订草稿。</span><Button disabled={busy} onClick={() => void startPublishedRevision()} type="button">开始修改</Button></div>}
      {settingsOpen && <ColumnSettingsPanel columns={page.columns} id="workbench-column-settings" layout={layout} onChange={() => undefined} onClose={closeSettings} />}
      <div className={css["workbench-grid-wrap"]} ref={layout.containerRef}><EditableDataGrid editors={editors} layout={layout} onDiscardCell={discardCellEdit} onEditCell={editCell} onSaveCell={(rowId, column, input, revision) => { void saveCell(rowId, column, input, revision); }} onSort={applySort} page={page} sort={sort} /></div>
      <Pagination itemLabel="数据行" loading={busy} page={page.pagination.page} totalItems={page.pagination.total_rows} totalPages={page.pagination.total_pages} onPageChange={(value) => { const next = new URLSearchParams(searchParams); next.set("page", String(value)); setSearchParams(next); }} />
      <footer className={css["workbench-action-bar"]}><span>草稿自动保存，但不会进入总表；检查并发布后才会显示</span><div><Button disabled={!page.permissions.can_undo || busy} onClick={() => void undo()} type="button">撤销上次修改</Button><Button disabled={!page.permissions.can_validate || busy || pendingCount > 0 || failedCount > 0} onClick={openAdvancedPublishControls} type="button">运行检查</Button><Button variant="primary" disabled={!page.permissions.can_publish || busy || pendingCount > 0 || failedCount > 0} onClick={openAdvancedPublishControls} type="button">前往发布</Button></div></footer>
    </>}
  </main>;
}
