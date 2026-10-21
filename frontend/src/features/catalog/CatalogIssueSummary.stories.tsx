import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { StatusMessage } from "../../design-system";
import { CatalogIssueSummary } from "./CatalogIssueSummary";
import type { CatalogRowIssue } from "./catalogTypes";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "warning" | "blocking" | "unlocatable" | "long-values" | "many-issues" | "parse-failed" | "empty" | "read-only" | "unknown-code";
const issues: CatalogRowIssue[] = [
  { section: "styles", row_key: "fictional-style:1", field: "/standard_name", severity: "error", reason_code: "required" },
  { section: "skus", row_key: "fictional-sku:2", field: "/standard_size", severity: "warning", reason_code: "required" },
  { section: "mappings", row_key: "fictional-mapping:3", field: "/identity_decision", severity: "blocking", reason_code: "identity_conflict" },
];
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [selected, setSelected] = useState<CatalogRowIssue>();
  const values = scenario === "empty" || scenario === "parse-failed" ? [] : scenario === "warning" ? [issues[1]!] : scenario === "blocking" ? [issues[2]!] : scenario === "unlocatable" ? [{ ...issues[0]!, row_key: null, field: null, reason_code: "batch_review_required" }] : scenario === "long-values" ? [{ ...issues[0]!, row_key: "fictional-long-row-".repeat(12), field: "/server_field_with_a_long_name", reason_code: "fictional_unknown_reason_".repeat(8) }] : scenario === "many-issues" ? Array.from({ length: 10 }, (_, i) => ({ ...issues[i % 3]!, row_key: `fictional-row:${i + 1}` })) : scenario === "unknown-code" ? [{ ...issues[0]!, field: "/new_server_field", reason_code: "new_server_rule", severity: "server_notice" }] : issues;
  return <main className="catalog-workspace" id="main-content">
    <CatalogIssueSummary status={scenario === "parse-failed" ? "parse_failed" : "needs_attention"} issues={values} failureReason={scenario === "parse-failed" ? "invalid_headers" : undefined} onLocate={scenario === "read-only" ? undefined : setSelected} />
    {selected && <StatusMessage kind="info" title="已选择定位目标">分类 {selected.section} · 行 {selected.row_key} · 字段 {selected.field}</StatusMessage>}
    <p>问题与行标识均为虚构示例；此处展示定位参数，实际审核页会切换分类、筛选行并聚焦字段。不发送实际 API，刷新重置样板。</p>
  </main>;
}
const meta = { title: "Patterns/Catalog Issue Summary", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Warning: Story = { args: { scenario: "warning" } };
export const Blocking: Story = { args: { scenario: "blocking" } };
export const Unlocatable: Story = { args: { scenario: "unlocatable" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const ManyIssues: Story = { args: { scenario: "many-issues" } };
export const ParseFailed: Story = { args: { scenario: "parse-failed" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const UnknownCode: Story = { args: { scenario: "unknown-code" } };
