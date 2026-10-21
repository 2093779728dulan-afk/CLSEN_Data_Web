import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { EmptyState } from "./EmptyState";
import { ErrorState } from "./ErrorState";
import { Skeleton } from "./Skeleton";
import { Table } from "./Table";
import { Toast, ToastProvider } from "./Toast";

describe("feedback and data-state components", () => {
  it("announces errors and exposes recovery without alerting for empty results", () => {
    render(<>
      <EmptyState title="暂无发布记录" description="调整筛选条件后重试" />
      <ErrorState title="读取失败" description="无法连接 API" action={<button>重新读取</button>} />
    </>);

    expect(screen.getByRole("alert")).toHaveTextContent("无法连接 API");
    expect(screen.getByRole("button", { name: "重新读取" })).toBeVisible();
    expect(screen.getByText("暂无发布记录").closest("section")).not.toHaveAttribute("role", "alert");
  });

  it("renders a named scrollable table and hides skeleton decoration", () => {
    render(<>
      <Table title="发布记录" description="最近 30 天">
        <thead><tr><th>报告日</th></tr></thead>
        <tbody><tr><td>2026-09-07</td></tr></tbody>
      </Table>
      <Skeleton lines={2} />
    </>);

    expect(screen.getByRole("table", { name: "发布记录" })).toHaveAccessibleDescription("最近 30 天");
    expect(document.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });

  it("shows toast content and runs its action", async () => {
    const onAction = vi.fn();
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Toast
          action={{ label: "查看记录", onSelect: onAction }}
          kind="success"
          onOpenChange={() => undefined}
          open
          title="发布成功"
        >
          已生成版本 18
        </Toast>
      </ToastProvider>,
    );

    expect(screen.getByText("发布成功")).toBeVisible();
    expect(screen.getByText("已生成版本 18")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "查看记录" }));
    expect(onAction).toHaveBeenCalledOnce();
  });
});
