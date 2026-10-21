import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setSessionCsrfToken } from "../../api/client";
import { createCatalogExport, resumeCatalogExport, uploadCatalogWorkbook } from "./catalogApi";

describe("catalog API", () => {
  beforeEach(() => setSessionCsrfToken("csrf"));
  afterEach(() => { setSessionCsrfToken(undefined); vi.unstubAllGlobals(); });

  it("uses the same UUID in command body and Idempotency-Key", async () => {
    const requests: Array<{ body: Record<string, unknown>; headers: Headers }> = [];
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      if (typeof init?.body !== "string") throw new Error("Expected a JSON command body.");
      requests.push({ body: JSON.parse(init.body) as Record<string, unknown>, headers: new Headers(init.headers) });
      return Promise.resolve(new Response(JSON.stringify({ export_id: 7, export_status: "building" }), { status: 202 }));
    }));
    await createCatalogExport(0);
    expect(requests[0]?.headers.get("Idempotency-Key")).toBe(requests[0]?.body.operation_token);
  });

  it("uploads XLSX as a raw body without multipart or JSON wrapping", async () => {
    let captured: RequestInit | undefined;
    vi.stubGlobal("fetch", vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      captured = init;
      return Promise.resolve(new Response(JSON.stringify({ catalog_import_id: 9 }), { status: 202 }));
    }));
    const file = new File(["xlsx"], "目录.xlsx");
    await uploadCatalogWorkbook(file, "11111111-1111-4111-8111-111111111111");
    expect(captured?.body).toBe(file);
    expect(new Headers(captured?.headers).get("Content-Type")).toContain("spreadsheetml.sheet");
    expect(new Headers(captured?.headers).get("Content-Type")).not.toContain("multipart");
  });

  it("resumes an export with its expected job revision and then refreshes status", async () => {
    const requests: Array<{ input: string; body?: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const requestUrl = typeof input === "string"
        ? input
        : input instanceof URL
          ? input.href
          : input.url;
      requests.push({
        input: requestUrl,
        ...(typeof init?.body === "string"
          ? { body: JSON.parse(init.body) as Record<string, unknown> }
          : {}),
      });
      const payload = init?.method === "POST"
        ? { export_id: 7, job_revision: 5, job_status: "queued" }
        : { export_id: 7, job_revision: 5, job_status: "queued" };
      return Promise.resolve(new Response(JSON.stringify(payload), { status: 200 }));
    }));

    await resumeCatalogExport(7, 4);

    expect(requests.map((request) => request.input)).toEqual([
      "/api/catalog/exports/7/resume",
      "/api/catalog/exports/7",
    ]);
    expect(requests[0]?.body?.expected_job_revision).toBe(4);
    expect(requests[0]?.body?.operation_token).toBeDefined();
  });
});
