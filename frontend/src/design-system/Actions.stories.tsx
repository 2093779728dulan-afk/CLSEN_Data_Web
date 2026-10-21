import { RefreshCw, Save } from "lucide-react";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { Button } from "./Button";
import { StatusBadge } from "./StatusBadge";
import { StatusMessage } from "./StatusMessage";
import { Checkbox } from "./Checkbox";
import { Input } from "./Input";
import { FormField } from "./FormField";

function SaveFeedbackExample() {
  const [saving, setSaving] = useState(false);
  const [fail, setFail] = useState(false);
  const [value, setValue] = useState("示例审核名称");
  const [result, setResult] = useState<"success" | "failure">();
  async function save() {
    setSaving(true); setResult(undefined);
    // Fictional latency in the story only; production awaits the actual request.
    await new Promise(resolve => setTimeout(resolve, 800));
    setResult(fail ? "failure" : "success"); setSaving(false);
  }
  return <div className="storybook-stack">
    <p>复用按钮、表单和反馈组件。此样板仅演示，不写入真实数据。</p>
    <FormField label="审核名称"><Input disabled={saving} onChange={event => { setValue(event.target.value); setResult(undefined); }} value={value} /></FormField>
    <Checkbox checked={fail} disabled={saving} label="模拟本次保存失败" onChange={event => setFail(event.target.checked)} />
    <div className="storybook-row"><Button icon={<Save />} loading={saving} loadingLabel="正在保存修改" onClick={() => void save()} variant="primary">保存修改</Button></div>
    {saving && <StatusMessage kind="info" title="正在保存修改">请稍候，输入内容保留。</StatusMessage>}
    {result === "success" && <StatusMessage kind="success" title="修改已保存">示例结果：{value}</StatusMessage>}
    {result === "failure" && <StatusMessage kind="danger" title="保存失败">输入内容已保留。关闭失败模拟后，可以再次点击保存修改。</StatusMessage>}
  </div>;
}

export const SaveFeedback: Story = { render: () => <SaveFeedbackExample /> };

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
