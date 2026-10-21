import {
  hasActiveSessionBoundary,
  revokeSessionBoundary,
} from "./sessionRevocation";

type ApiErrorPayload = {
  error?: {
    code?: string;
    existing_batch_id?: unknown;
    message?: string;
    report_date?: unknown;
    report_type?: unknown;
    request_id?: string;
    stage?: unknown;
    workspace_url?: unknown;
    workflow_revision?: unknown;
    parse_attempt_revision?: unknown;
    catalog_publication_revision?: unknown;
    dedup_publication_revision?: unknown;
    issues?: unknown;
  };
  detail?: unknown;
};

export type ApiErrorDetails = {
  catalog_publication_revision?: number;
  dedup_publication_revision?: number;
  existing_batch_id?: number;
  issues?: readonly SafeDecisionIssue[];
  parse_attempt_revision?: number;
  report_date?: string;
  report_type?: string;
  stage?: string;
  workspace_url?: string;
  workflow_revision?: number;
};

export type SafeDecisionIssue = {
  decision_group_key?: string;
  field?: string;
  mutation_id?: string;
  reason_code: string;
  row_key?: string;
};

export type SafeErrorField = keyof ApiErrorDetails;

const LEGACY_ERROR_FIELDS: readonly SafeErrorField[] = [
  "existing_batch_id",
  "report_date",
  "report_type",
  "stage",
  "workspace_url",
];

function safePositiveInteger(value: unknown): number | undefined {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
    ? value
    : undefined;
}

function safeIssues(value: unknown): readonly SafeDecisionIssue[] | undefined {
  if (!Array.isArray(value) || value.length > 500) return undefined;
  const result: SafeDecisionIssue[] = [];
  for (const item of value) {
    if (!item || typeof item !== "object") return undefined;
    const row = item as Record<string, unknown>;
    if (typeof row.reason_code !== "string") return undefined;
    const issue: SafeDecisionIssue = { reason_code: row.reason_code };
    for (const field of ["decision_group_key", "field", "mutation_id", "row_key"] as const) {
      if (typeof row[field] === "string") issue[field] = row[field];
    }
    result.push(issue);
  }
  return Object.freeze(result);
}

function apiErrorDetails(
  error: ApiErrorPayload["error"],
  allowedFields: readonly SafeErrorField[],
): ApiErrorDetails {
  if (!error) return {};
  const candidates: ApiErrorDetails = {
    ...(safePositiveInteger(error.catalog_publication_revision) !== undefined
      ? { catalog_publication_revision: safePositiveInteger(error.catalog_publication_revision) }
      : {}),
    ...(safePositiveInteger(error.dedup_publication_revision) !== undefined
      ? { dedup_publication_revision: safePositiveInteger(error.dedup_publication_revision) }
      : {}),
    ...(typeof error.existing_batch_id === "number" && Number.isSafeInteger(error.existing_batch_id) && error.existing_batch_id > 0
      ? { existing_batch_id: error.existing_batch_id }
      : {}),
    ...(typeof error.report_date === "string" ? { report_date: error.report_date } : {}),
    ...(typeof error.report_type === "string" ? { report_type: error.report_type } : {}),
    ...(typeof error.stage === "string" ? { stage: error.stage } : {}),
    ...(typeof error.workspace_url === "string" && error.workspace_url.startsWith("/")
      ? { workspace_url: error.workspace_url }
      : {}),
    ...(safePositiveInteger(error.workflow_revision) !== undefined
      ? { workflow_revision: safePositiveInteger(error.workflow_revision) }
      : {}),
    ...(safePositiveInteger(error.parse_attempt_revision) !== undefined
      ? { parse_attempt_revision: safePositiveInteger(error.parse_attempt_revision) }
      : {}),
    ...(safeIssues(error.issues) ? { issues: safeIssues(error.issues) } : {}),
  };
  return Object.fromEntries(
    Object.entries(candidates).filter(([key]) => allowedFields.includes(key as SafeErrorField)),
  ) as ApiErrorDetails;
}

export class ApiRequestError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details: Readonly<ApiErrorDetails>;

  constructor(
    status: number,
    code: string,
    message: string,
    requestId?: string,
    details: ApiErrorDetails = {},
  ) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.details = Object.freeze({ ...details });
  }
}

let sessionCsrfToken: string | undefined;

const UUID_V4_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function readCookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;
  const match = document.cookie
    .split(";")
    .map((item) => item.trim())
    .find((item) => item.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : undefined;
}

export function createOperationKey(): string {
  const secureCrypto = globalThis.crypto;
  if (!secureCrypto) {
    throw new Error("Secure browser randomness is unavailable.");
  }
  if (typeof secureCrypto.randomUUID === "function") {
    return secureCrypto.randomUUID();
  }
  if (typeof secureCrypto.getRandomValues !== "function") {
    throw new Error("Secure browser randomness is unavailable.");
  }
  const bytes = secureCrypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const value = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  return `${value.slice(0, 8)}-${value.slice(8, 12)}-${value.slice(12, 16)}-${value.slice(16, 20)}-${value.slice(20)}`;
}

export function isOperationKey(value: string): boolean {
  return UUID_V4_PATTERN.test(value);
}

type StableOperationKey = {
  fingerprint: string;
  operationKey: string;
};

/**
 * Keeps one idempotency key for one semantic command until the caller records
 * a successful HTTP response. A changed path or JSON body starts a new command.
 */
export class StableOperationKeyStore {
  readonly #commands = new Map<string, StableOperationKey>();

  forCommand(slot: string, path: string, body: unknown): string {
    if (!slot.trim()) throw new Error("Operation key slot must not be empty.");
    const serializedBody = JSON.stringify(body);
    if (serializedBody === undefined) {
      throw new Error("Idempotent command bodies must be JSON serializable.");
    }
    const fingerprint = `${path}\n${serializedBody}`;
    const current = this.#commands.get(slot);
    if (current?.fingerprint === fingerprint) return current.operationKey;
    const operationKey = createOperationKey();
    this.#commands.set(slot, { fingerprint, operationKey });
    return operationKey;
  }

  complete(slot: string, operationKey: string): void {
    if (this.#commands.get(slot)?.operationKey === operationKey) {
      this.#commands.delete(slot);
    }
  }

  reset(slot: string): void {
    this.#commands.delete(slot);
  }
}

export function setSessionCsrfToken(token?: string) {
  sessionCsrfToken = token;
}

export async function requestApi<T>(
  path: string,
  init?: RequestInit,
  safeErrorFields: readonly SafeErrorField[] = LEGACY_ERROR_FIELDS,
): Promise<T> {
  const response = await fetch(path, {
    credentials: "same-origin",
    ...init,
  });
  if (!response.ok) {
    if (
      response.status === 401 &&
      path !== "/api/auth/csrf" &&
      path !== "/api/auth/login" &&
      hasActiveSessionBoundary()
    ) {
      revokeSessionBoundary();
    }
    const payload = (await response.json().catch(() => ({}))) as ApiErrorPayload;
    const message =
      payload.error?.message ??
      (response.status === 409
        ? "数据已发生变化，请刷新后再试。"
        : `请求失败（${response.status}）`);
    throw new ApiRequestError(
      response.status,
      payload.error?.code ?? "request_failed",
      message,
      payload.error?.request_id,
      apiErrorDetails(payload.error, safeErrorFields),
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function commandApi<T>(
  path: string,
  body: Record<string, unknown>,
  operationKey: string,
  safeErrorFields: readonly SafeErrorField[] = [],
): Promise<T> {
  if (body.operation_token !== operationKey) {
    throw new Error("Command operation_token must match its Idempotency-Key.");
  }
  const token = sessionCsrfToken ?? readCookie("clsen_csrf");
  if (!token) {
    throw new ApiRequestError(403, "csrf_missing", "当前会话缺少写入凭据，请退出后重新登录。");
  }
  return requestApi<T>(
    path,
    {
      body: JSON.stringify(body),
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": operationKey,
        "X-CSRF-Token": token,
      },
      method: "POST",
    },
    safeErrorFields,
  );
}

export async function issueLoginCsrfToken(): Promise<string> {
  const response = await requestApi<{ csrf_token: string }>("/api/auth/csrf");
  return response.csrf_token;
}

export async function writeApi<T>(
  path: string,
  options: {
    body?: unknown;
    headers?: HeadersInit;
    idempotent?: boolean;
    method?: "POST" | "PUT" | "PATCH" | "DELETE";
    operationKey?: string;
    rawBody?: BodyInit;
    signal?: AbortSignal;
  } = {},
): Promise<T> {
  const token = sessionCsrfToken ?? readCookie("clsen_csrf");
  if (!token) {
    throw new ApiRequestError(
      403,
      "csrf_missing",
      "当前会话缺少写入凭据，请退出后重新登录。",
    );
  }
  const headers = new Headers(options.headers);
  headers.set("X-CSRF-Token", token);
  const suppliedHeader = headers.get("Idempotency-Key");
  if (options.idempotent === false) {
    if (options.operationKey !== undefined || suppliedHeader !== null) {
      throw new Error("Non-idempotent requests cannot carry an operation key.");
    }
  } else {
    if (
      suppliedHeader !== null
      && options.operationKey !== undefined
      && suppliedHeader !== options.operationKey
    ) {
      throw new Error("Conflicting idempotency keys were supplied.");
    }
    const operationKey = options.operationKey ?? suppliedHeader ?? createOperationKey();
    if (!isOperationKey(operationKey)) {
      throw new Error("Idempotency keys must be UUID v4 values.");
    }
    if (suppliedHeader === null) headers.set("Idempotency-Key", operationKey);
  }
  let body = options.rawBody;
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(options.body);
  }
  return requestApi<T>(path, {
    method: options.method ?? "POST",
    headers,
    body,
    signal: options.signal,
  });
}
