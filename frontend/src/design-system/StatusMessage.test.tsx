import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { StatusMessage } from "./StatusMessage";

it("renders a textual success status with supporting content and action", () => {
  render(
    <StatusMessage action={<button type="button">查看详情</button>} kind="success" title="已保存">
      更改已同步。
    </StatusMessage>,
  );

  expect(screen.getByRole("status")).toHaveClass("ui-status", "ui-status--success");
  expect(screen.getByText("已保存")).toBeVisible();
  expect(screen.getByText("更改已同步。")).toBeVisible();
  expect(screen.getByRole("button", { name: "查看详情" })).toBeVisible();
});

it("uses an alert role for danger messages", () => {
  render(<StatusMessage kind="danger" title="保存失败" />);

  expect(screen.getByRole("alert")).toHaveTextContent("保存失败");
});
