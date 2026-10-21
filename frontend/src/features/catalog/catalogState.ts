import type { CatalogExportStatus } from "./catalogApi";

export type CatalogExportViewState =
  | { kind: "idle" }
  | { export: CatalogExportStatus; kind: "building" | "capacity" | "failed" | "ready" };

export function exportViewState(value?: CatalogExportStatus): CatalogExportViewState {
  if (!value) return { kind: "idle" };
  if (value.export_status === "failed" || value.job_status === "failed") {
    return { export: value, kind: "failed" };
  }
  if (value.workbook_status === "capacity_exceeded") return { export: value, kind: "capacity" };
  if (value.export_status === "ready" && value.workbook_status === "ready") {
    return { export: value, kind: "ready" };
  }
  return { export: value, kind: "building" };
}
