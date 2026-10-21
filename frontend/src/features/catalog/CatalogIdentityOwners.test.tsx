import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { setSessionCsrfToken } from "../../api/client";
import { CatalogIdentityOwners } from "./CatalogIdentityOwners";

afterEach(() => { vi.unstubAllGlobals(); setSessionCsrfToken(undefined); });

it("requires a reason to restore an excluded identity and shows its shared owners", async () => {
  setSessionCsrfToken("csrf");
  const bodies: string[] = [];
  vi.stubGlobal("fetch", vi.fn((_url: unknown, init?: RequestInit) => {
    if (typeof init?.body === "string") bodies.push(init.body);
    return Promise.resolve(new Response(JSON.stringify(init?.method === "POST"
      ? { safe_result: { workflow_revision: 3 } }
      : { formal: [{ style_id: 8, sku_id: 12 }], drafts: [{ import_id: 9, decision_kind: "excluded" }], ignored: [{ catalog_version_id: 2, reason: "非经营商品" }] }), { status: 200 }));
  }));
  const saved = vi.fn().mockResolvedValue(undefined);
  render(<CatalogIdentityOwners importId={4} revision={2} onSaved={saved} row={{
    row_key: "mapping-1", section: "mappings", row_origin: "system", projection_state: "included",
    payload: { identity_decision: "excluded", seller_sku_preview: "100-NAVY-L" },
  }} />);
  expect(screen.getByRole("button", { name: "恢复到待审核" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "查看归属与冲突" }));
  expect(await screen.findByRole("link", { name: "商品 STYLE #8" })).toHaveAttribute("href", "/catalog/styles/8");
  expect(screen.getByRole("link", { name: "审核批次 #9" })).toHaveAttribute("href", "/catalog/imports/9");
  await userEvent.type(screen.getByLabelText("恢复审核原因"), "来源复核确认需要恢复");
  await userEvent.click(screen.getByRole("button", { name: "恢复到待审核" }));
  expect(saved).toHaveBeenCalledWith(3);
  const captured = bodies[0];
  if (captured === undefined) throw new Error("Expected a restore request body.");
  const body = JSON.parse(captured) as { expected_workflow_revision: number; mutations: unknown[] };
  expect(body.expected_workflow_revision).toBe(2);
  expect(body.mutations[0]).toMatchObject({ type: "restore_seller_sku_review", payload: { change_reason: "来源复核确认需要恢复" } });
});

it("does not resubmit an acknowledged restore when the following read fails", async () => {
  setSessionCsrfToken("csrf");
  const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ safe_result: { workflow_revision: 3 } }), { status: 200 })));
  vi.stubGlobal("fetch", fetchMock);
  const saved = vi.fn().mockRejectedValueOnce(new Error("示例最新明细暂不可用")).mockResolvedValue(undefined);
  render(<CatalogIdentityOwners importId={4} revision={2} onSaved={saved} row={{ row_key: "mapping-1", section: "mappings", row_origin: "system", projection_state: "audit_only", payload: { identity_decision: "excluded" } }} />);
  await userEvent.type(screen.getByLabelText("恢复审核原因"), "已核对来源");
  await userEvent.click(screen.getByRole("button", { name: "恢复到待审核" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("示例最新明细暂不可用");
  expect(screen.getByRole("button", { name: "恢复到待审核" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "重新读取草稿" }));
  expect(saved.mock.calls).toEqual([[3], [3]]);
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
