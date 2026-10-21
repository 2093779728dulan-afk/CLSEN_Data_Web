import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { Link, MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { StatusMessage } from "../../design-system";
import { CatalogImportHistoryView, type CatalogHistory } from "./CatalogImportHistoryView";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "empty" | "loading" | "read-failure" | "second-page" | "archived" | "long-values" | "unknown-status";
const items: CatalogHistory["items"] = [
  { import_id: 901, source_kind: "online", status: "ready_for_approval", workflow_revision: 3 },
  { import_id: 902, source_kind: "xlsx", status: "approved", workflow_revision: 6 },
  { import_id: 903, source_kind: "xlsx", status: "parse_failed", workflow_revision: 1 },
];
function Destination() {
  const location = useLocation();
  return <StatusMessage kind="info" title="虚构批次导航"><p>目标路径：{location.pathname}。样板不读取实际批次。</p><Link to="/">返回批次列表</Link></StatusMessage>;
}
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [page, setPage] = useState(scenario === "second-page" ? 2 : 1);
  const [recovered, setRecovered] = useState(false);
  const values = scenario === "empty" ? [] : scenario === "archived" ? [{ ...items[0]!, status: "withdrawn" }, { ...items[1]!, status: "superseded" }] : scenario === "long-values" ? [{ ...items[0]!, import_id: 9007199254740991, workflow_revision: 123456 }] : scenario === "unknown-status" ? [{ ...items[0]!, status: "future_status" }] : page === 1 ? items : [{ ...items[1]!, import_id: 904 }];
  return <MemoryRouter><main className="catalog-workspace" id="main-content"><Routes><Route path="/" element={<CatalogImportHistoryView result={scenario === "loading" && !recovered || scenario === "read-failure" && !recovered ? undefined : { items: values, has_next: page === 1 && values.length > 0 }} error={scenario === "read-failure" && !recovered ? "虚构示例：连接暂时不可用，未创建或修改任何批次。" : undefined} page={page} onReload={() => setRecovered(true)} onPageChange={setPage} onOpenReview={() => undefined} />} /><Route path="*" element={<Destination />} /></Routes><p>全部批次、修订与状态为虚构示例。只更新样板内存，不请求实际 API；刷新重置。</p></main></MemoryRouter>;
}
const meta = { title: "Patterns/Catalog Import History", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const SecondPage: Story = { args: { scenario: "second-page" } };
export const Archived: Story = { args: { scenario: "archived" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const UnknownStatus: Story = { args: { scenario: "unknown-status" } };
