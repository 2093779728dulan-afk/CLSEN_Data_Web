import type { Meta, StoryObj } from "@storybook/react-vite";

import { FormField } from "./FormField";
import { Input } from "./Input";
import { Select } from "./Select";

const meta = {
  title: "Design System/Form controls",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const FieldStates: Story = {
  render: () => <div className="storybook-form">
    <FormField hint="支持款号、Seller SKU、ASIN 或商品名称。" label="搜索商品">
      <Input placeholder="输入商品信息" type="search" />
    </FormField>
    <FormField label="处理状态" required>
      <Select defaultValue="review">
        <option value="all">全部状态</option>
        <option value="review">等待审核</option>
        <option value="published">已发布</option>
      </Select>
    </FormField>
    <FormField error="月份不能早于当前发布数据范围。" label="统计月份">
      <Input defaultValue="2025-01" type="month" />
    </FormField>
    <FormField hint="当前账号无权修改此字段。" label="站点">
      <Input disabled value="Amazon US · America/Los_Angeles" readOnly />
    </FormField>
    <FormField label="较长中文标签用于验证窄屏换行与信息层级">
      <Input placeholder="控件保持完整宽度和可见焦点" />
    </FormField>
  </div>,
};
