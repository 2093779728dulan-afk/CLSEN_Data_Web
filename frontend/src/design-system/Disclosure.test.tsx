import { createRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { Disclosure } from "./Disclosure";

it("preserves native toggling, details refs and caller toggle callbacks", async () => {
  const ref = createRef<HTMLDetailsElement>();
  const toggled = vi.fn();
  render(<Disclosure ref={ref} onToggle={event => { toggled(event.currentTarget.open); }}><summary>修订记录</summary><p>操作人员与修改前后</p></Disclosure>);
  expect(ref.current?.tagName).toBe("DETAILS");
  expect(ref.current).not.toHaveAttribute("open");
  await userEvent.click(screen.getByText("修订记录", { selector: "summary" }));
  await waitFor(() => expect(toggled).toHaveBeenCalledWith(true));
  expect(ref.current).toHaveAttribute("open");
  await userEvent.click(screen.getByText("修订记录", { selector: "summary" }));
  expect(ref.current).not.toHaveAttribute("open");
});

it("retains form input and independent nested disclosures while closed", async () => {
  const { container, rerender } = render(<Disclosure open><summary>来源依据</summary><input aria-label="说明" defaultValue="原备注"/><Disclosure><summary>完整编号</summary><p>QA-1</p></Disclosure></Disclosure>);
  await userEvent.type(screen.getByRole("textbox", {name:"说明"}), "补充");
  const outer = container.querySelector("details")!;
  const inner = outer.querySelector("details")!;
  await userEvent.click(screen.getByText("完整编号", {selector:"summary"}));
  expect(outer).toHaveAttribute("open");
  expect(inner).toHaveAttribute("open");
  rerender(<Disclosure open={false}><summary>来源依据</summary><input aria-label="说明" defaultValue="原备注"/><Disclosure><summary>完整编号</summary><p>QA-1</p></Disclosure></Disclosure>);
  expect(container.querySelector("input")).toHaveValue("原备注补充");
  expect(inner).toHaveAttribute("open");
});
