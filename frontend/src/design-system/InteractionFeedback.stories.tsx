import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Button, ClickSpark, StatusMessage } from "./index";

function Feedback() {
  const [count, setCount] = useState(0);
  return <ClickSpark><div className="storybook-stack">
    <h2>彩色点击反馈</h2>
    <p>蓝、绿、金、紫短火花。点击或键盘激活只执行一次操作；减少动态效果及高对比模式不绘制火花。</p>
    <div className="storybook-row">
      <Button variant="primary" onClick={() => setCount(value => value + 1)}>确认示例操作</Button>
      <Button onClick={() => setCount(0)}>重置计数</Button>
      <Button disabled>不可操作</Button>
      <Button loading loadingLabel="正在保存">保存修改</Button>
      <Button data-click-spark="off" onClick={() => setCount(value => value + 1)}>无火花操作</Button>
    </div>
    <StatusMessage kind="info" title={`已执行 ${count} 次`}>仅演示交互反馈，不发送 API 请求。火花不表示操作成功。</StatusMessage>
  </div></ClickSpark>;
}
const meta = { title: "Design System/Interaction Feedback", component: Feedback } satisfies Meta<typeof Feedback>;
export default meta;
type Story = StoryObj<typeof meta>;
export const ClickSparkStates: Story = {};
