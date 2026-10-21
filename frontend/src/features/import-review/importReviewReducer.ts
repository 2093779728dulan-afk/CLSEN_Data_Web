import type { ReportType } from "../../api/types";
import type { ImportQueueItem, ReviewEncoding } from "./workflowTypes";

export type ImportReviewState = {
  activeQueueId?: string;
  importQueue: ImportQueueItem[];
  intake: {
    assignedDate: string;
    encoding: ReviewEncoding;
    reportType: ReportType;
  };
};

export type ImportReviewAction =
  | { type: "activate"; id: string }
  | { type: "set-active"; id?: string }
  | { type: "patch-active"; changes: Partial<ImportQueueItem> }
  | { type: "replace-item"; item: ImportQueueItem }
  | { type: "replace-queue"; items: ImportQueueItem[]; activeQueueId?: string }
  | { type: "update-queue"; update: (items: ImportQueueItem[]) => ImportQueueItem[] }
  | { type: "remove-items"; ids: string[] }
  | { type: "set-intake"; changes: Partial<ImportReviewState["intake"]> }
  | { type: "reset"; reportDate: string };

export function initialImportReviewState(
  reportDate: string,
  restored?: ImportReviewState,
): ImportReviewState {
  return restored ?? {
    importQueue: [],
    intake: {
      assignedDate: reportDate,
      encoding: "utf-8-sig",
      reportType: "business_report",
    },
  };
}

export function selectActiveQueueItem(state: ImportReviewState) {
  return state.importQueue.find((item) => item.id === state.activeQueueId);
}

export function importQueueItemStage(item: ImportQueueItem | undefined) {
  if (!item) return "intake" as const;
  if (item.status === "existing") return "existing" as const;
  if (item.status === "failed") return "failed" as const;
  if (item.status === "completed") return "published" as const;
  if (item.parsed) return "parsed" as const;
  if (item.inspection) return "inspection" as const;
  return "intake" as const;
}

export function importReviewReducer(
  state: ImportReviewState,
  action: ImportReviewAction,
): ImportReviewState {
  switch (action.type) {
    case "activate":
      return state.importQueue.some((item) => item.id === action.id)
        ? { ...state, activeQueueId: action.id }
        : state;
    case "set-active":
      return action.id === undefined || state.importQueue.some((item) => item.id === action.id)
        ? { ...state, activeQueueId: action.id }
        : state;
    case "patch-active":
      if (!state.activeQueueId) return state;
      return {
        ...state,
        importQueue: state.importQueue.map((item) => (
          item.id === state.activeQueueId ? { ...item, ...action.changes } : item
        )),
      };
    case "replace-item":
      return {
        ...state,
        importQueue: state.importQueue.map((item) => (
          item.id === action.item.id ? action.item : item
        )),
      };
    case "replace-queue":
      return {
        ...state,
        activeQueueId: action.activeQueueId,
        importQueue: action.items,
      };
    case "update-queue":
      return { ...state, importQueue: action.update(state.importQueue) };
    case "remove-items": {
      const removed = new Set(action.ids);
      return {
        ...state,
        activeQueueId: state.activeQueueId && removed.has(state.activeQueueId)
          ? undefined
          : state.activeQueueId,
        importQueue: state.importQueue.filter((item) => !removed.has(item.id)),
      };
    }
    case "set-intake":
      return { ...state, intake: { ...state.intake, ...action.changes } };
    case "reset":
      return initialImportReviewState(action.reportDate);
  }
}
