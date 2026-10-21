import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Checkbox } from "./Checkbox";
import { Menu } from "./Menu";
import { Radio } from "./Radio";
import { Tabs } from "./Tabs";
import { Tooltip } from "./Tooltip";

describe("selection and navigation controls", () => {
  it("exposes native checkbox and radio names with descriptions", () => {
    render(<>
      <Checkbox description="仅影响本次筛选" label="包含缺货商品" />
      <Radio label="经营报告" name="report" value="business" />
    </>);

    expect(screen.getByRole("checkbox", { name: "包含缺货商品" })).toHaveAccessibleDescription("仅影响本次筛选");
    expect(screen.getByRole("radio", { name: "经营报告" })).toBeVisible();
  });

  it("shows tooltip content for a focusable trigger", async () => {
    const user = userEvent.setup();
    render(<Tooltip content="发布后进入经营看板"><button type="button">发布说明</button></Tooltip>);

    await user.hover(screen.getByRole("button", { name: "发布说明" }));

    expect(await screen.findByRole("tooltip")).toHaveTextContent("发布后进入经营看板");
  });

  it("changes tabs and exposes the selected panel", async () => {
    const user = userEvent.setup();
    render(<Tabs ariaLabel="总表视图" defaultValue="daily" items={[
      { content: "每日内容", label: "每日总表", value: "daily" },
      { content: "产品内容", label: "产品总表", value: "products" },
    ]} />);

    await user.click(screen.getByRole("tab", { name: "产品总表" }));

    expect(screen.getByRole("tabpanel")).toHaveTextContent("产品内容");
  });

  it("runs enabled menu actions and keeps disabled actions unavailable", async () => {
    const user = userEvent.setup();
    const reload = vi.fn();
    render(<Menu items={[
      { id: "reload", label: "重新读取", onSelect: reload },
      { disabled: true, id: "delete", label: "删除记录", onSelect: vi.fn() },
    ]} label="更多操作" />);

    await user.click(screen.getByRole("button", { name: "更多操作" }));
    expect(screen.getByRole("menuitem", { name: "删除记录" })).toHaveAttribute("data-disabled");
    await user.click(screen.getByRole("menuitem", { name: "重新读取" }));

    expect(reload).toHaveBeenCalledTimes(1);
  });
});
