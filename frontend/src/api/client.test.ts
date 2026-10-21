import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiRequestError,
  StableOperationKeyStore,
  createOperationKey,
  isOperationKey,
  requestApi,
  setSessionCsrfToken,
  writeApi,
} from "./client";
import {
  closeSessionBoundary,
  establishSessionBoundary,
  onSessionRevoked,
} from "./sessionRevocation";

describe("API error context", () => {
  it("keeps the safe existing-batch fields returned for duplicate imports", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      error: {
        code: "duplicate_import",
        existing_batch_id: 92,
        message: "This file is already available.",
        report_date: "2026-07-05",
        report_type: "return_report",
        request_id: "request-1",
        stage: "uploaded",
        workspace_url: "/review/2026-07-05?report_type=return_report",
      },
    }), { headers: { "Content-Type": "application/json" }, status: 409 }))));

    const error = await requestApi("/api/imports").catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiRequestError);
    expect((error as ApiRequestError).details).toEqual({
      existing_batch_id: 92,
      report_date: "2026-07-05",
      report_type: "return_report",
      stage: "uploaded",
      workspace_url: "/review/2026-07-05?report_type=return_report",
    });
  });

  it("retains only caller-allowlisted catalog counters and safe issues", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      error: {
        code: "catalog_decisions_invalid",
        issues: [{ mutation_id: "m1", reason_code: "required", raw_value: "危险" }],
        message: "invalid",
        raw_sql: "select secret",
        workflow_revision: 4,
      },
    }), { headers: { "Content-Type": "application/json" }, status: 422 }))));
    const error = await requestApi(
      "/api/catalog/imports/1/decisions",
      undefined,
      ["issues", "workflow_revision"],
    ).catch((reason: unknown) => reason) as ApiRequestError;
    expect(error.details).toEqual({
      issues: [{ mutation_id: "m1", reason_code: "required" }],
      workflow_revision: 4,
    });
    expect(JSON.stringify(error)).not.toContain("危险");
    expect(JSON.stringify(error)).not.toContain("select secret");
  });

  it("emits one revocation for concurrent authenticated 401 responses", async () => {
    const listener = vi.fn();
    const unsubscribe = onSessionRevoked(listener);
    establishSessionBoundary();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({
      error: { code: "session_invalid", message: "expired" },
    }), { headers: { "Content-Type": "application/json" }, status: 401 }))));
    await Promise.allSettled([
      requestApi("/api/catalog/styles"),
      requestApi("/api/catalog/versions"),
    ]);
    expect(listener).toHaveBeenCalledTimes(1);
    unsubscribe();
    closeSessionBoundary();
  });
});

describe("idempotent API command keys", () => {
  beforeEach(() => setSessionCsrfToken("csrf-test-token"));

  afterEach(() => {
    setSessionCsrfToken(undefined);
    vi.unstubAllGlobals();
  });

  it("reuses one UUID for the same semantic command and replaces it when input changes", () => {
    const keys = new StableOperationKeyStore();
    const path = "/api/drafts/51/mark-ready";
    const first = keys.forCommand("mark-ready", path, { reason: "checked", revision: 1 });

    expect(isOperationKey(first)).toBe(true);
    expect(keys.forCommand("mark-ready", path, { reason: "checked", revision: 1 })).toBe(first);

    const changed = keys.forCommand("mark-ready", path, { reason: "checked again", revision: 1 });
    expect(changed).not.toBe(first);
    expect(isOperationKey(changed)).toBe(true);

    keys.complete("mark-ready", first);
    expect(keys.forCommand("mark-ready", path, { reason: "checked again", revision: 1 })).toBe(changed);

    keys.complete("mark-ready", changed);
    expect(keys.forCommand("mark-ready", path, { reason: "checked again", revision: 1 })).not.toBe(changed);
  });

  it("preserves an explicit operation key and keeps non-idempotent uploads keyless", async () => {
    const requests: Headers[] = [];
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      requests.push(new Headers(init?.headers));
      return Promise.resolve(new Response(null, { status: 204 }));
    }));
    const operationKey = createOperationKey();

    await writeApi<void>("/api/drafts/51/mark-ready", {
      body: { reason: "checked" },
      operationKey,
    });
    await writeApi<void>("/api/imports?report_date=2026-08-10", {
      idempotent: false,
      rawBody: "csv-bytes",
    });

    expect(requests[0]?.get("Idempotency-Key")).toBe(operationKey);
    expect(requests[1]?.get("Idempotency-Key")).toBeNull();
  });
});
