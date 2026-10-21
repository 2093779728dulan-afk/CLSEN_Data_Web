import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { StatusBadge } from "./StatusBadge";

it("uses text and a hidden icon so status is not conveyed by color alone", () => {
  render(<StatusBadge label="消费者失败" tone="bad" />);

  expect(screen.getByText("消费者失败")).toBeVisible();
  expect(document.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
});
