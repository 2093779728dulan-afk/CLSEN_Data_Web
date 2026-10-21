import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

import { ApiRequestError, StableOperationKeyStore } from "../../api/client";
import type { WorkbenchImportResponse } from "../../api/generated";
import type { ReportType } from "../../api/types";
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
import type { CellEditorState, WorkbenchColumn, WorkbenchPage } from "./workbenchTypes";
import { cellKey } from "./workbenchTypes";
import { DateWorkbenchView, type ImportConfirmation } from "./DateWorkbenchView";

type Props = {
  canWrite: boolean;
  reportDate: string;
  siteId: number;
  userId: number;
};

const EMPTY_COLUMNS: WorkbenchColumn[] = [];

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
            permissions: { ...current.value.permissions, can_undo: true },
            actions: current.value.actions.includes("undo") ? current.value.actions : [...current.value.actions, "undo"],
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
        setContextError(undefined);
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
        const nothingToUndo = reason instanceof ApiRequestError && reason.code === "nothing_to_undo";
        if (nothingToUndo) {
          operations.complete(slot, operationKey);
          setLoadedPage((current) => current?.contextKey === origin.key ? {
            contextKey: current.contextKey,
            value: { ...current.value,
              permissions: { ...current.value.permissions, can_undo: false },
              actions: current.value.actions.filter((action) => action !== "undo"),
            },
          } : current);
        }
        setContextError({ contextKey: origin.key, message: nothingToUndo
          ? "当前没有可撤销的修改；已撤销或被后续修改覆盖的记录不能再次撤销。"
          : reason instanceof Error ? reason.message : "撤销失败。" });
      }
    } finally { releaseBusy(busyOwner); }
  };

  const requestedReturn = (location.state as { returnTo?: unknown } | null)?.returnTo;
  const returnTo = typeof requestedReturn === "string" && requestedReturn.startsWith("/?") ? requestedReturn : undefined;
  return <DateWorkbenchView canWrite={canWrite} reportDate={reportDate} reportType={reportType} returnTo={returnTo} page={page} busy={busy} error={error} editors={editors} searchParams={searchParams} setSearchParams={setSearchParams}
    importResult={importResult} importFileName={importFileName} confirmation={confirmation} setConfirmation={setConfirmation}
    settingsOpen={settingsOpen} setSettingsOpen={setSettingsOpen} layout={layout} sort={sort}
    onRetry={() => void reload(viewContext)} switchReport={switchReport} uploadFile={(file) => void uploadFile(file)} confirmImport={() => void confirmImport()} continueUploadedSource={continueUploadedSource}
    startPublishedRevision={() => void startPublishedRevision()} closeSettings={closeSettings} discardCellEdit={discardCellEdit} editCell={editCell} saveCell={(rowId, column, input, revision) => void saveCell(rowId, column, input, revision)} applySort={applySort} undo={() => void undo()} openAdvancedPublishControls={openAdvancedPublishControls} />;
}
