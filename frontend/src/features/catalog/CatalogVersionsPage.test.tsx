import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, expect, it, vi } from "vitest";

import { CatalogVersionsPage } from "./CatalogVersionsPage";

afterEach(() => vi.unstubAllGlobals());
it("links an empty history to initialization", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ versions: [] }), { status: 200 }))));
  render(<MemoryRouter><CatalogVersionsPage /></MemoryRouter>);
  expect(await screen.findByRole("link", { name: "前往批量维护完成初始化" })).toHaveAttribute("href", "/catalog/maintenance");
});
it("recovers a transient error without keeping the old error visible", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(new Response(JSON.stringify({ versions: [] }), { status: 200 })));
  render(<MemoryRouter><CatalogVersionsPage /></MemoryRouter>);
  fireEvent.click(await screen.findByRole("button", { name: "重新读取" }));
  expect(await screen.findByRole("link", { name: "前往批量维护完成初始化" })).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
it("renders forward catalog history", async () => {
  vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(new Response(JSON.stringify({ versions: [{ id: 2, version_number: 2, risk: "normal", approved_at: "2026-08-21", base_catalog_version_id: 1 }] }), { status: 200 }))));
  render(<CatalogVersionsPage />);
  expect(await screen.findByText("V2")).toBeVisible();
});
