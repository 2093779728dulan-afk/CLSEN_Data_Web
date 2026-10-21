import type { Meta, StoryObj } from "@storybook/react-vite";
import { SafeSourceRefView, type SafeSourceRef } from "./SafeSourceRefView";
import styles from "./SafeSourceRefView.module.css";

type Scenario = "reference" | "long-preview" | "truncated" | "unsafe" | "structural-characters" | "combined";
const base: SafeSourceRef = { source_ref_id: "fictional-source", preview: "DEMO-01-Blue-M", digest: `sha256:${"a".repeat(56)}12345678`, is_truncated: false, is_unsafe: false };
const samples: Record<Exclude<Scenario, "reference">, { label: string; source: SafeSourceRef }> = {
  "long-preview": { label: "较长来源预览", source: { ...base, preview: "DEMO-虚构商品来源-".repeat(20) } },
  truncated: { label: "截断预览", source: { ...base, preview: "DEMO-较长来源预览…", is_truncated: true } },
  unsafe: { label: "上游标记需安全处理", source: { ...base, is_unsafe: true } },
  "structural-characters": { label: "预览仍包含结构字符", source: { ...base, preview: '<script>fictional-source</script>&"', is_unsafe: false } },
  combined: { label: "安全处理与截断同时存在", source: { ...base, preview: "<fictional-source>", is_truncated: true, is_unsafe: true } },
};
function SourceReferenceStory({ scenario = "reference" }: { scenario?: Scenario }) {
  const items = scenario === "reference" ? [{ label: "普通来源预览", source: base }, samples.truncated, samples.combined] : [samples[scenario]];
  return <main className={styles.story}>
    <h1>来源预览与摘要</h1>
    <p>预览用于识别来源；指纹旁显示摘要后八位。截断与字符提示说明展示状态，不表示 SKU 有误。</p>
    <ul className={styles.samples} aria-label="来源引用示例">{items.map(item => <li className={styles.sample} key={item.label}><strong>{item.label}</strong><SafeSourceRefView source={item.source} /></li>)}</ul>
    <p>全部数据为虚构示例。这里不展示完整标识；实际页面需通过原有的查看权限校验。</p>
  </main>;
}
const meta = { title: "Patterns/Safe Source Reference", component: SourceReferenceStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof SourceReferenceStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const LongPreview: Story = { args: { scenario: "long-preview" } };
export const Truncated: Story = { args: { scenario: "truncated" } };
export const Unsafe: Story = { args: { scenario: "unsafe" } };
export const StructuralCharacters: Story = { args: { scenario: "structural-characters" } };
export const Combined: Story = { args: { scenario: "combined" } };
