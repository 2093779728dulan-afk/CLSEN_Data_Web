import type { Meta, StoryObj } from "@storybook/react-vite";
import { useMemo, useRef, useState } from "react";
import { Button, Dialog, StatusBadge } from "../../design-system";
import { MergeDecisionMatrix, type MergeDecisionState, type MergePreviewResponse } from "./MergeDecisionMatrix";
import { mergePreview } from "./MergeDecisionMatrix.fixtures";
import styles from "./MergeDecisionMatrix.module.css";

type Scenario = "reference" | "identical" | "hidden-fields" | "return-report" | "empty" | "loading" | "read-failure" | "disabled" | "in-dialog";
function MergePage({ scenario = "reference" }: { scenario?: Scenario }) {
  const [state, setState] = useState<MergeDecisionState>({ decisions: [], ready: false });
  const [open, setOpen] = useState(true); const reads = useRef(0);
  const loadPreview = useMemo(() => async () => {
    reads.current += 1;
    if (scenario === "loading") return new Promise<MergePreviewResponse>(() => {});
    if (scenario === "read-failure" && reads.current === 1) throw new Error("示例：重复记录预览暂时不可用，未提交合并决定。");
    return mergePreview(scenario === "return-report" ? "return" : scenario === "identical" ? "identical" : scenario === "hidden-fields" ? "hidden" : scenario === "empty" ? "empty" : "business");
  }, [scenario]);
  const matrix = <MergeDecisionMatrix disabled={scenario === "disabled"} loadPreview={loadPreview} onStateChange={setState}
    operator={scenario === "in-dialog" ? undefined : { id: 88, username: "fictional.manager", display_name: "示例审核人员" }} sourceId={61} sourceKind="parse_baseline" targetVersionId={51} />;
  return <div className={styles.stage}><h1>重复记录核对</h1><p>虚构数据，处理决定保留在当前样板；不会生成真实草稿或发布。</p>
    <div aria-label="合并决定状态"><StatusBadge label={state.ready ? `已就绪：${state.decisions.length} 组决定` : "未就绪"} tone={state.ready ? "good" : "quiet"} /></div>
    {scenario === "in-dialog" ? <><Button onClick={() => setOpen(true)}>重新打开合并确认</Button><Dialog open={open} onOpenChange={setOpen} title="跨日期移动 · 合并记录" description="核对目标与来源的重复记录" size="large">{matrix}</Dialog></> : matrix}
  </div>;
}
const meta = { title: "Patterns/Merge Decision Matrix", component: MergePage, parameters: { layout: "fullscreen" } } satisfies Meta<typeof MergePage>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Identical: Story = { args: { scenario: "identical" } };
export const HiddenFields: Story = { args: { scenario: "hidden-fields" } };
export const ReturnReport: Story = { args: { scenario: "return-report" } };
export const Empty: Story = { args: { scenario: "empty" } };
export const Loading: Story = { args: { scenario: "loading" } };
export const ReadFailure: Story = { args: { scenario: "read-failure" } };
export const Disabled: Story = { args: { scenario: "disabled" } };
export const InDialog: Story = { args: { scenario: "in-dialog" } };
