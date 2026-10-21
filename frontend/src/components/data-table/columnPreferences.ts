import type { DataTableReportType, PresentableColumn } from "../../features/workbench/workbenchTypes";
import { clampColumnWidth, recommendedWidth } from "./columnPresentation";

export type ColumnPreferenceNamespace = "workbench" | "published-details";

export type ColumnPreferenceIdentity = {
  namespace: ColumnPreferenceNamespace;
  userId: number | string;
  siteId: number | string;
  reportType: DataTableReportType;
};

export type StoredColumnPreferences = {
  version: 1;
  order: string[];
  hidden: string[];
  widths: Record<string, number>;
};

export type ResolvedColumnPreferences = {
  orderedIds: string[];
  visibleIds: string[];
  widths: Record<string, number>;
};

const PREFERENCE_VERSION = 1;

export function preferenceKey({ namespace, userId, siteId, reportType }: ColumnPreferenceIdentity) {
  return `clsen:data-table:v${PREFERENCE_VERSION}:${namespace}:user:${userId}:site:${siteId}:report:${reportType}`;
}

function serverColumns(columns: readonly PresentableColumn[]) {
  return columns
    .map((column, index) => ({ column, index }))
    .sort((left, right) => left.column.display_order - right.column.display_order || left.index - right.index)
    .map(({ column }) => column);
}

function defaults(columns: readonly PresentableColumn[]): ResolvedColumnPreferences {
  const orderedColumns = serverColumns(columns);
  return {
    orderedIds: orderedColumns.map((column) => column.column_id),
    visibleIds: orderedColumns.map((column) => column.column_id),
    widths: Object.fromEntries(orderedColumns.map((column) => [column.column_id, recommendedWidth(column)])),
  };
}

function isStringList(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((entry) => typeof entry === "string");
}

function isNumberRecord(value: unknown): value is Record<string, number> {
  return typeof value === "object"
    && value !== null
    && !Array.isArray(value)
    && Object.values(value).every((entry) => typeof entry === "number" && Number.isFinite(entry));
}

function isStoredPreferences(value: unknown): value is StoredColumnPreferences {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const candidate = value as Partial<StoredColumnPreferences>;
  return candidate.version === PREFERENCE_VERSION
    && isStringList(candidate.order)
    && isStringList(candidate.hidden)
    && isNumberRecord(candidate.widths);
}

function uniqueExistingIds(ids: readonly string[], knownIds: ReadonlySet<string>) {
  const result: string[] = [];
  const seen = new Set<string>();
  for (const id of ids) {
    if (knownIds.has(id) && !seen.has(id)) {
      seen.add(id);
      result.push(id);
    }
  }
  return result;
}

function resolvePreferences(stored: StoredColumnPreferences, columns: readonly PresentableColumn[]): ResolvedColumnPreferences {
  const orderedColumns = serverColumns(columns);
  const knownIds = new Set(orderedColumns.map((column) => column.column_id));
  const orderedIds = uniqueExistingIds(stored.order, knownIds);

  for (const column of orderedColumns) {
    if (!orderedIds.includes(column.column_id)) {
      const insertionIndex = Math.min(Math.max(column.display_order - 1, 0), orderedIds.length);
      orderedIds.splice(insertionIndex, 0, column.column_id);
    }
  }

  const hidden = new Set(uniqueExistingIds(stored.hidden, knownIds));
  const identityIds = orderedIds.filter((id) => columns.find((column) => column.column_id === id)?.is_key);
  if (identityIds.length > 0 && identityIds.every((id) => hidden.has(id))) {
    const finalIdentityId = identityIds.at(-1);
    if (finalIdentityId) hidden.delete(finalIdentityId);
  }

  return {
    orderedIds,
    visibleIds: orderedIds.filter((id) => !hidden.has(id)),
    widths: Object.fromEntries(orderedColumns.map((column) => [
      column.column_id,
      clampColumnWidth(stored.widths[column.column_id] ?? recommendedWidth(column)),
    ])),
  };
}

export function loadColumnPreferences(key: string, columns: readonly PresentableColumn[]): ResolvedColumnPreferences {
  const fallback = defaults(columns);
  try {
    if (typeof localStorage === "undefined") return fallback;
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed: unknown = JSON.parse(raw);
    return isStoredPreferences(parsed) ? resolvePreferences(parsed, columns) : fallback;
  } catch {
    return fallback;
  }
}

export function saveColumnPreferences(key: string, preferences: StoredColumnPreferences): void {
  try {
    if (typeof localStorage !== "undefined") localStorage.setItem(key, JSON.stringify(preferences));
  } catch {
    // Local browser preferences are optional and must never affect business state.
  }
}
