import { RefreshCw, Save } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";
import { StatusMessage } from "./StatusMessage";

const meta = {
  title: "Design System/Actions and status",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const ButtonStates: Story = {
  render: () => <div className="storybook-stack">
    <div className="storybook-row">
      <Button icon={<Save />} variant="primary">保存更改</Button>
      <Button variant="secondary">查看详情</Button>
      <Button variant="danger">撤销发布</Button>
      <Button variant="quiet">暂不处理</Button>
    </div>
    <div className="storybook-row">
      <Button disabled>不可操作</Button>
      <Button icon={<RefreshCw />} loading>正在重新读取</Button>
      <Button>包含较长中文操作名称的按钮</Button>
    </div>
  </div>,
};

export const StatusStates: Story = {
  render: () => <div className="storybook-stack">
    <div className="storybook-row">
      <StatusBadge label="运行正常" tone="good" />
      <StatusBadge label="等待补齐" tone="warn" />
      <StatusBadge label="执行失败" tone="bad" />
      <StatusBadge label="暂无数据" tone="quiet" />
    </div>
    <StatusMessage kind="info" title="正在读取发布版本">数据会在读取完成后自动更新。</StatusMessage>
    <StatusMessage kind="success" title="发布完成">两个报告均已进入当前发布版本。</StatusMessage>
    <StatusMessage action={<Button>重新读取</Button>} kind="danger" title="总表读取失败">请确认 API 连接后重试。</StatusMessage>
  </div>,
};
