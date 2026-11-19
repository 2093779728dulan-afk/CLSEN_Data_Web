import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it } from "vitest";
import { ReadContent } from "./WorkbenchFields";

afterEach(cleanup);
it("restores focus lost to disabled controls after a successful refresh", async () => {
  const view = (loading: boolean) => <ReadContent loading={loading} retry={() => undefined}><button>刷新</button></ReadContent>;
  const { rerender } = render(view(false));
  const button = screen.getByRole("button", { name: "刷新" });
  await userEvent.click(button); rerender(view(true));
  expect(button).toBeDisabled();
  button.blur(); // Emulate the native browser blur missing from JSDOM's disabled fieldset.
  rerender(view(false)); expect(button).toHaveFocus();
});
it("does not steal focus moved to another region while reading", async () => {
  const view = (loading: boolean) => <><input aria-label="外部搜索" /><ReadContent loading={loading} retry={() => undefined}><button>刷新</button></ReadContent></>;
  const { rerender } = render(view(false));
  await userEvent.click(screen.getByRole("button", { name: "刷新" })); rerender(view(true));
  await userEvent.click(screen.getByLabelText("外部搜索"));
  rerender(view(false)); expect(screen.getByLabelText("外部搜索")).toHaveFocus();
});
