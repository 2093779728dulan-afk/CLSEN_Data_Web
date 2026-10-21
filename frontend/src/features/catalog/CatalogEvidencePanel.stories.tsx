import type { Meta, StoryObj } from "@storybook/react-vite";
import { useCallback, useRef, useState } from "react";
import { ApiRequestError } from "../../api/client";
import { AuthzGenerationProvider } from "../../app/AuthzGenerationContext";
import { Button } from "../../design-system";
import { CatalogEvidencePanel } from "./CatalogEvidencePanel";
import "./CatalogWorkspace.css";

type Scenario = "reference" | "empty" | "loading" | "read-failure" | "revealing" | "reveal-failure" | "revealed" | "long-preview" | "boundary-change" | "long-identifier";
const sources = [
  { source_ref_id: "3", preview: "DEMO-01-Blue-M", digest: `sha256:${"a".repeat(64)}`, is_truncated: false, is_unsafe: false },
  { source_ref_id: "4", preview: "<script>fictional-source</script>", digest: `sha256:${"b".repeat(64)}`, is_truncated: true, is_unsafe: true },
];
function Sample({ scenario = "reference" }: { scenario?: Scenario }) {
  const [principal, setPrincipal] = useState(88);
  const readFailed = useRef(false); const revealFailed = useRef(false);
  const loadSources = useCallback(async () => {
    if (scenario === "loading") return new Promise<{ items: typeof sources }>(() => {});
    await new Promise(resolve => setTimeout(resolve, 200));
    if (scenario === "read-failure" && !readFailed.current) { readFailed.current = true; throw new Error("示例：来源证据暂时不可用，请显式重新读取。"); }
    return { items: scenario === "empty" ? [] : scenario === "long-preview" ? [{ ...sources[0]!, preview: "DEMO-虚构来源-".repeat(18), is_truncated: true }, sources[1]!] : sources };
  }, [scenario]);
  const loadIdentifier = useCallback(async () => {
    if (scenario === "revealing") return new Promise<{ code_points: string; utf8_base64url: string }>(() => {});
    await new Promise(resolve => setTimeout(resolve, 250));
    if (scenario === "reveal-failure" && !revealFailed.current) { revealFailed.current = true; throw new ApiRequestError(403, "catalog_source_identifier_forbidden", "示例：完整来源查看权限未通过，安全预览仍保留。"); }
    const raw = scenario === "long-identifier" ? "DEMO-虚构完整标识-".repeat(35) : "虚构来源 DEMO-01-Blue-M <仅示例>\n第二行";
    return { code_points: Array.from(raw).map(char => `U+${char.codePointAt(0)!.toString(16).toUpperCase()}`).join(" "), utf8_base64url: btoa(String.fromCharCode(...new TextEncoder().encode(raw))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "") };
  }, [scenario]);
  return <AuthzGenerationProvider boundary={{ principalId: principal, roles: ["data_manager"], siteId: 1, siteConfigVersionId: 1 }} onRevoked={() => undefined}><main className="catalog-workspace" id="main-content">
    <CatalogEvidencePanel importId={42} workflowRevision={3} loadSources={loadSources} loadIdentifier={loadIdentifier} />
    {scenario === "boundary-change" && <Button onClick={() => setPrincipal(value => value + 1)}>模拟权限变化</Button>}
    <p>全部来源、摘要与完整标识均为虚构示例，不请求实际 API；查看后可复制或隐藏，刷新重置样板。不要输入真实标识。</p>
  </main></AuthzGenerationProvider>;
}
const meta = { title: "Patterns/Catalog Source Evidence", component: Sample, parameters: { layout: "fullscreen" } } satisfies Meta<typeof Sample>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Revealing: Story = { args: { scenario: "revealing" } };
export const RevealFailure: Story = { args: { scenario: "reveal-failure" } };
export const Revealed: Story = { args: { scenario: "revealed" } };
export const LongPreview: Story = { args: { scenario: "long-preview" } };
export const BoundaryChange: Story = { args: { scenario: "boundary-change" } };
export const LongIdentifier: Story = { args: { scenario: "long-identifier" } };
