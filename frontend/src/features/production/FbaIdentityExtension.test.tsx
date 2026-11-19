import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { FbaIdentityExtension } from "./FbaIdentityExtension";
import type { FbaIdentity, FbaScope } from "./fbaTypes";
import type { Sku } from "./types";

const api = vi.hoisted(() => ({ read: vi.fn(), write: vi.fn() }));
vi.mock("../../api/client", async original => ({ ...await original<typeof import("../../api/client")>(), requestApi: api.read, writeApi: api.write }));
const scope = { id: "1", warehouse_id: "3", owner_id: "1", report_source_scope_id: "1", store_evidence: "SIM store", cutoff_on: "2026-10-01", simulated: true, revision: "2" } as FbaScope;
const catalog = [{ sku_id: "11", code: "1112-Black-L", label: "1112 Black L" }] as Sku[];
const row = { source_row: 2, sku_id: "11", seller_sku: "1112-Black-L", asin: "B000000001", fnsku: "X000000001", store: "SIM store" };
beforeEach(()=>api.read.mockResolvedValue({identities:[],issues:[],store:"SIM store",catalog_version:"1:1"}));
function mount(canWrite = true, identities: FbaIdentity[] = [], skuIds?: string[], embedded = false) {
  const saved = vi.fn();
  const router = createMemoryRouter([{ path: "/", element: <FbaIdentityExtension scope={scope} identities={identities} catalog={catalog} canWrite={canWrite} saved={saved} skuIds={skuIds} embedded={embedded} /> }], { initialEntries: ["/"] });
  render(<AuthzGenerationProvider boundary={{ principalId: 1, roles: [canWrite ? "data_manager" : "viewer"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><RouterProvider router={router} /></AuthzGenerationProvider>);
  return saved;
}
async function upload(store = "SIM store") {
  api.write.mockReset();
  api.write.mockResolvedValueOnce({ identities: [{ ...row, store }], source_id: "a".repeat(64), report_source_scope_id: "1" });
  await userEvent.upload(screen.getByLabelText("FBA商品资料CSV"), new File(["SIM"], "SIM.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "读取商品资料" }));
}
it("connects the existing stable SKU only after explicit source and zero confirmation", async () => {
  const saved = mount();
  await upload();
  expect(screen.getByRole("combobox", { name: "1112-Black-L 对应商品规格" })).toHaveValue("11");
  const confirm = screen.getByRole("button", { name: "确认并启用商品" });
  expect(confirm).toBeDisabled();
  await userEvent.click(screen.getByRole("checkbox"));
  api.write.mockResolvedValueOnce({});
  await userEvent.click(confirm);
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api.write.mock.calls[1]?.[0]).toBe("/api/production/fba/commands/extend-identities");
  expect(api.write.mock.calls[1]?.[1]).toMatchObject({ body: { scope_id: "1", expected_revision: "2", identities: [row], explicit_zero_opening: true, identities_confirmed: true } });
  expect(screen.getByText("已启用 1 个规格")).toBeVisible();
});
it.each(["duplicate", "wrong-store"])("blocks %s without submitting a connection", async mode => {
  mount(true, mode === "duplicate" ? [{ sku_id: "11" } as FbaIdentity] : []);
  await upload(mode === "wrong-store" ? "OTHER" : "SIM store");
  await userEvent.click(screen.getByRole("checkbox"));
  expect(screen.getByRole("button", { name: "确认并启用商品" })).toBeDisabled();
  expect(api.write).toHaveBeenCalledTimes(1);
});
it("keeps viewers read-only", () => {
  mount(false);
  expect(screen.queryByLabelText("FBA商品资料CSV")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "确认并启用商品" })).not.toBeInTheDocument();
});

it("enables reviewed product data without asking for another CSV", async()=>{
 api.read.mockResolvedValue({identities:[row],issues:[],store:"SIM store",catalog_version:"1:1"});
 api.write.mockReset();api.write.mockResolvedValue({});
 const saved=mount();
 expect(await screen.findByText("已自动带入 1 个商品规格")).toBeVisible();
 expect(screen.getByLabelText("FBA商品资料CSV")).not.toBeVisible();
 await userEvent.click(screen.getByRole("button",{name:"启用已带入商品"}));
 await waitFor(()=>expect(saved).toHaveBeenCalledOnce());
 expect(api.write.mock.calls[0]?.[1]).toMatchObject({body:{identity_mode:"catalog",catalog_version:"1:1",identities:[row]}});
 expect(screen.getByText("已启用 1 个规格")).toBeVisible();
});

it("checks only the new products of the current shipment from a shared identity file", async () => {
  mount(true, [], ["11"], true);
  api.write.mockReset();
  api.write.mockResolvedValueOnce({ identities: [row, { ...row, sku_id: "12", seller_sku: "OTHER" }], source_id: "a".repeat(64), report_source_scope_id: "1" });
  await userEvent.upload(screen.getByLabelText("FBA商品资料CSV"), new File(["SIM"], "SIM.csv", { type: "text/csv" }));
  await userEvent.click(screen.getByRole("button", { name: "读取商品资料" }));
  expect(await screen.findByText("原资料2行，本批核对1行。")).toBeVisible();
  expect(screen.queryByText("OTHER")).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "返回验收或商品管理" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("checkbox"));
  api.write.mockResolvedValueOnce({});
  await userEvent.click(screen.getByRole("button", { name: "确认并启用商品" }));
  await waitFor(() => expect(api.write).toHaveBeenCalledTimes(2));
  expect(api.write.mock.calls[1]?.[1]).toMatchObject({ body: { identities: [row] } });
});
