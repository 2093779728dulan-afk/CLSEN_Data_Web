import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { Button } from "./Button";

it("keeps a loading action disabled and exposes its busy state", () => {
  const onClick = vi.fn();

  render(<Button loading onClick={onClick}>刷新状态</Button>);

  const button = screen.getByRole("button", { name: "刷新状态" });
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
});

it("forwards button behavior when the action is ready", () => {
  const onClick = vi.fn();

  render(<Button onClick={onClick}>刷新状态</Button>);
  screen.getByRole("button", { name: "刷新状态" }).click();

  expect(onClick).toHaveBeenCalledOnce();
});
