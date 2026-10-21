import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { Checkbox, Menu, Radio, Tabs, Tooltip } from "./index";

const meta = {
  title: "Design System/Selection and navigation",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const SelectionStates: Story = {
  render: () => <div className="storybook-stack">
    <Checkbox defaultChecked description="仅影响本次筛选，不修改已发布数据。" label="包含缺货商品" />
    <Checkbox disabled label="当前账号不可更改此选项" />
    <Checkbox error="至少选择一个需要核对的数据范围。" label="包含有待审核数据但尚未形成发布版本的商品" />
    <fieldset className="storybook-fieldset">
      <legend>报告类型</legend>
      <Radio defaultChecked label="经营报告" name="report-kind" value="business" />
      <Radio label="退货报告" name="report-kind" value="returns" />
      <Radio disabled label="广告报告（暂未接入）" name="report-kind" value="ads" />
    </fieldset>
  </div>,
};

function NavigationExample() {
  const [tab, setTab] = useState("daily");
  return <div className="storybook-stack">
    <div className="storybook-row">
      <Tooltip content="发布后进入当前经营看板，历史版本仍会保留。">
        <button className="storybook-native-button" type="button">发布说明</button>
      </Tooltip>
      <Menu label="更多操作" items={[
        { id: "reload", label: "重新读取", onSelect: () => undefined },
        { disabled: true, id: "archive", label: "归档（当前不可用）", onSelect: () => undefined },
        { danger: true, id: "rollback", label: "回退当前草稿", onSelect: () => undefined },
      ]} />
    </div>
    <Tabs
      ariaLabel="总表视图"
      items={[
        { content: <p>按报告日核对数据完整度与异常。</p>, label: "每日总表", value: "daily" },
        { content: <p>按 SKU 查看指标趋势与当前发布口径。</p>, label: "产品总表", value: "products" },
        { content: <p>该视图正在准备中。</p>, disabled: true, label: "对比视图", value: "compare" },
      ]}
      onValueChange={setTab}
      value={tab}
    />
  </div>;
}

export const CompositeInteractions: Story = {
  render: () => <NavigationExample />,
};

export const NarrowAndLongChinese: Story = {
  render: () => <div className="storybook-narrow storybook-stack">
    <Checkbox description="说明信息保持可读，并与选项名称分别提供给辅助技术。" label="显示当前月份内所有尚未发布、已退回修改以及等待补充来源文件的商品记录" />
    <Tabs ariaLabel="窄屏长标签示例" items={[
      { content: <p>窄屏下标签允许稳定换行，内容区域保持完整。</p>, label: "需要人工确认的数据", value: "review" },
      { content: <p>已发布内容。</p>, label: "已经完成发布的数据", value: "published" },
    ]} />
  </div>,
};
