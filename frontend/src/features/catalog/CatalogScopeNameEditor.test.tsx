import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { CatalogScopeNameEditor } from "./CatalogScopeNameEditor";

const api = vi.hoisted(() => ({ read: vi.fn(), command: vi.fn() }));
vi.mock("../../api/client", async original => ({
  ...await original<typeof import("../../api/client")>(),
  requestApi: api.read,
  commandApi: api.command,
}));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("loads the current name revision and saves an audited display-only correction", async () => {
  api.read.mockResolvedValue({ scope_id: 1, display_name: "美国站", revision: 4, can_rename: true });
  api.command.mockResolvedValue({ scope_id: 1, display_name: "广州店", revision: 5, can_rename: true });
  const saved = vi.fn();
  render(<CatalogScopeNameEditor name="美国站" saved={saved} onGuardChange={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "更正店铺名称" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: /店铺名称/ })).toBeEnabled());
  await user.clear(screen.getByRole("textbox", { name: /店铺名称/ }));
  await user.type(screen.getByRole("textbox", { name: /店铺名称/ }), "广州店");
  await user.type(screen.getByLabelText(/更正原因/), "修正名称");
  await user.click(screen.getByRole("button", { name: "保存名称" }));
  await waitFor(() => expect(saved).toHaveBeenCalledOnce());
  expect(api.command.mock.calls[0]?.[1]).toMatchObject({ scope_id: 1, expected_revision: 4, display_name: "广州店", reason: "修正名称" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("locks uncertain edits and reuses the original command when verifying the result", async () => {
  api.read.mockResolvedValue({ scope_id: 1, display_name: "广州店", revision: 0, can_rename: true });
  api.command.mockRejectedValueOnce(new TypeError("网络中断")).mockResolvedValueOnce({});
  render(<CatalogScopeNameEditor name="广州店" saved={vi.fn()} onGuardChange={vi.fn()} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "更正店铺名称" }));
  await waitFor(() => expect(screen.getByRole("textbox", { name: /店铺名称/ })).toBeEnabled());
  await user.type(screen.getByLabelText(/更正原因/), "核对显示名称");
  await user.click(screen.getByRole("button", { name: "保存名称" }));
  expect(await screen.findByRole("button", { name: "核实更名结果" })).toBeEnabled();
  expect(screen.getByRole("textbox", { name: /店铺名称/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "取消" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "核实更名结果" }));
  await waitFor(() => expect(api.command).toHaveBeenCalledTimes(2));
  expect(api.command.mock.calls[1]).toEqual(api.command.mock.calls[0]);
});
