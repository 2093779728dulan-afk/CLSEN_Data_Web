import type {
  DateWorkbenchResponse,
  SetWorkbenchCellRequest,
  WorkbenchCellMutationResponse,
  WorkbenchColumnResponse,
  WorkbenchRowResponse,
} from "../../api/generated";

export type WorkbenchPage = DateWorkbenchResponse;
export type WorkbenchColumn = WorkbenchColumnResponse;
export type DataTableReportType = "business_report" | "return_report";
export type PresentableColumn = Pick<
  WorkbenchColumnResponse,
  "column_id" | "source_header" | "standard_field_name" | "is_key" | "display_order"
>;
export type WorkbenchRow = WorkbenchRowResponse;
export type WorkbenchCellWrite = SetWorkbenchCellRequest;
export type WorkbenchCellWriteResult = WorkbenchCellMutationResponse;
export type SaveState = "clean" | "editing" | "saving" | "saved" | "failed" | "conflict";

export type CellEditorState = {
  input: string;
  message?: string;
  state: SaveState;
};

export function cellKey(versionId: number, rowId: number, columnId: string) {
  return `${versionId}:${rowId}:${columnId}`;
}
