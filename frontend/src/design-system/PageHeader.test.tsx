import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { PageHeader } from "./PageHeader";

it("renders one compact heading with its optional supporting content", () => {
  render(
    <PageHeader
      actions={<button type="button">导出</button>}
      description="查看当前已发布的数据。"
      eyebrow="发布数据"
      meta={<span>更新于今天</span>}
      title="数据总表"
    />,
  );

  expect(screen.getByRole("banner")).toHaveClass("ui-page-header");
  expect(screen.getByRole("heading", { level: 1, name: "数据总表" })).toBeVisible();
  expect(screen.getByText("发布数据")).toBeVisible();
  expect(screen.getByText("查看当前已发布的数据。")).toBeVisible();
  expect(screen.getByText("更新于今天")).toBeVisible();
  expect(screen.getByRole("button", { name: "导出" })).toBeVisible();
});

it("omits optional regions when they are not provided", () => {
  render(<PageHeader title="数据总表" />);

  expect(screen.getByRole("heading", { level: 1, name: "数据总表" })).toBeVisible();
  expect(document.querySelector(".ui-page-header__eyebrow")).toBeNull();
  expect(document.querySelector(".ui-page-header__actions")).toBeNull();
});
