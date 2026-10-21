import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { CatalogIdentityOwners, type IdentityOwners } from "./CatalogIdentityOwners";
import type { CatalogImportRow } from "./catalogTypes";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "empty" | "loading" | "read-failure" | "restore-saving" | "restore-failure" | "refresh-failure" | "restored" | "read-only" | "long-reason";
const sampleOwners: IdentityOwners = { formal: [{ style_id: 8, sku_id: 12 }], drafts: [{ import_id: 9, decision_kind: "excluded" }, { import_id: 10, decision_kind: "mapped" }], ignored: [{ catalog_version_id: 2, reason: "虚构示例：此前按非经营商品排除，需重新核对来源后决定。" }] };
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [revision, setRevision] = useState(2);
  const [row, setRow] = useState<CatalogImportRow>({ row_key: "fictional-mapping-1", row_origin: "system", projection_state: "audit_only", section: "mappings", payload: { identity_decision: scenario === "empty" ? "mapped" : "excluded", seller_sku_preview: "DEMO-01-Blue-M" } });
  const readFailed = useRef(false); const saveFailed = useRef(false); const refreshFailed = useRef(false);
  return <main className="catalog-workspace" id="main-content"><CatalogIdentityOwners importId={42} revision={revision} row={row} disabled={scenario === "read-only"}
    loadOwners={async () => {
      if (scenario === "loading") return new Promise(() => {});
      await new Promise(resolve => setTimeout(resolve, 300));
      if (scenario === "read-failure" && !readFailed.current) { readFailed.current = true; throw new Error("示例：归属读取暂时失败，请显式重试。原目录未改变。"); }
      if (scenario === "empty") return { formal: [], drafts: [], ignored: [] };
      return scenario === "long-reason" ? { ...sampleOwners, ignored: [{ catalog_version_id: 2, reason: "虚构长说明：此来源曾在历史审核中被排除。请逐项核对来源账号、站点、款式与实际变体，保留原始排除依据，并由具备对应权限的审核人决定是否恢复；恢复当前草稿不会自动改变正式目录。" }] } : sampleOwners;
    }}
    saveMutation={async () => {
      if (scenario === "restore-saving") return new Promise(() => {});
      await new Promise(resolve => setTimeout(resolve, 300));
      if (scenario === "restore-failure" && !saveFailed.current) { saveFailed.current = true; throw new Error("示例：草稿修订已变化，恢复原因已保留，请核对后重试。"); }
      return { workflow_revision: revision + 1 };
    }}
    onSaved={next => {
      if (scenario === "refresh-failure" && !refreshFailed.current) { refreshFailed.current = true; return Promise.reject(new Error("示例：恢复已保存，最新草稿读取暂时失败。")); }
      setRevision(next); setRow(current => ({ ...current, projection_state: "included", payload: { ...current.payload, identity_decision: null } }));
      return Promise.resolve();
    }} />
    <p>虚构身份与审核样板，不读取真实标识，不请求实际 API；恢复只演示草稿变化，刷新重置示例。</p>
  </main>;
}
const meta = { title: "Patterns/Catalog Identity Owners", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const RestoreSaving: Story = { args: { scenario: "restore-saving" } };
export const RestoreFailure: Story = { args: { scenario: "restore-failure" } };
export const RefreshFailure: Story = { args: { scenario: "refresh-failure" } };
export const Restored: Story = { args: { scenario: "restored" } };
export const ReadOnly: Story = { args: { scenario: "read-only" } };
export const LongReason: Story = { args: { scenario: "long-reason" } };
