import { useState } from "react";
import type { Meta, StoryObj } from "@storybook/react-vite";

import { Button } from "./Button";
import { Dialog } from "./Dialog";
import { PageHeader } from "./PageHeader";
import { Pagination } from "./Pagination";

const meta = {
  title: "Design System/Structure and navigation",
  parameters: { layout: "padded" },
} satisfies Meta;

export default meta;
type Story = StoryObj<typeof meta>;

export const Header: Story = {
  render: () => <PageHeader actions={<Button variant="primary">进入今日审核</Button>} description="按月核对日期完整度与商品表现；经营值仅来自当前发布版本。" eyebrow="当前发布口径 · 2026-09" meta="数据管理视图" title="发布数据总表" />,
};

function DialogExample() {
  const [open, setOpen] = useState(false);
  return <>
    <Button onClick={() => setOpen(true)}>打开发布确认</Button>
    <Dialog description="发布后会更新当前经营看板，原始文件和历史版本仍会保留。" eyebrow="高影响操作" onOpenChange={setOpen} open={open} title="确认发布 2026-09-07 数据？">
      <div className="storybook-dialog-content">
        <p>请确认经营报告和退货报告均已完成审核。</p>
        <div className="storybook-dialog-actions"><Button onClick={() => setOpen(false)}>取消</Button><Button onClick={() => setOpen(false)} variant="primary">确认发布</Button></div>
      </div>
    </Dialog>
  </>;
}

export const DialogInteraction: Story = {
  render: () => <DialogExample />,
};

function PaginationExample() {
  const [page, setPage] = useState(2);
  return <Pagination itemLabel="商品" onPageChange={setPage} page={page} totalItems={78} totalPages={4} />;
}

export const PaginationStates: Story = {
  render: () => <div className="storybook-stack"><PaginationExample /><Pagination itemLabel="商品" loading onPageChange={() => undefined} page={1} totalItems={78} totalPages={4} /></div>,
};
