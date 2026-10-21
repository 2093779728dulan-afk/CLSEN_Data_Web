import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button, EmptyState, ErrorState, Skeleton, Table, Toast, ToastProvider } from "./index";

const meta = {
  title: "Design System/Feedback and data",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

function ToastGallery() {
  const [visible, setVisible] = useState({ danger: true, info: true, success: true, warning: true });
  const restore = () => setVisible({ danger: true, info: true, success: true, warning: true });
  return <div className="storybook-stack">
    <Button onClick={restore}>重新显示全部通知</Button>
    <p>通知显示在视口右下角；可逐条关闭或向右滑动。</p>
    <ToastProvider>
      <Toast kind="info" onOpenChange={(open) => setVisible((value) => ({ ...value, info: open }))} open={visible.info} title="正在同步">系统正在读取最新发布版本。</Toast>
      <Toast kind="success" onOpenChange={(open) => setVisible((value) => ({ ...value, success: open }))} open={visible.success} title="发布成功">版本 18 已进入当前经营看板。</Toast>
      <Toast kind="warning" onOpenChange={(open) => setVisible((value) => ({ ...value, warning: open }))} open={visible.warning} title="仍有待办">3 个商品需要人工确认。</Toast>
      <Toast action={{ label: "重新读取", onSelect: () => undefined }} duration={Infinity} kind="danger" onOpenChange={(open) => setVisible((value) => ({ ...value, danger: open }))} open={visible.danger} title="读取失败">无法连接 API，请确认服务状态。</Toast>
    </ToastProvider>
  </div>;
}

export const ToastKinds: Story = {
  render: () => <ToastGallery />,
};

export const LoadingEmptyAndError: Story = {
  render: () => <div className="storybook-state-grid">
    <section aria-busy="true" className="storybook-state-card">
      <h3>正在读取发布记录</h3>
      <Skeleton lines={4} />
    </section>
    <EmptyState action={<Button variant="primary">导入来源文件</Button>} description="导入并审核经营报告后，发布版本会显示在这里。" title="暂无发布记录" />
    <ErrorState action={<Button>重新读取</Button>} description="无法连接 API。已保留当前筛选条件，请检查服务后重试。" title="总表读取失败" />
  </div>,
};

export const BasicTable: Story = {
  render: () => <div className="storybook-narrow-table">
    <Table description="经营值仅来自当前发布版本，表格可独立横向滚动。" title="最近发布记录">
      <thead><tr><th>报告日</th><th>站点</th><th>状态</th><th>收入</th><th>负责人</th></tr></thead>
      <tbody>
        <tr><td>2026-09-07</td><td>Amazon US</td><td>已发布</td><td>$18,240.52</td><td>项目负责人管理员</td></tr>
        <tr><td>2026-09-06</td><td>Amazon US</td><td>等待审核</td><td>$16,908.30</td><td>TCJ</td></tr>
      </tbody>
    </Table>
  </div>,
};
