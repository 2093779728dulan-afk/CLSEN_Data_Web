import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef, useState } from "react";
import { ReviewDataTable } from "./ReviewDataTable";
import { issueReviewWorkspace, type IssueScenario } from "./IssueReviewPanel.fixtures";
import styles from "./IssueReviewPanel.module.css";

function IssueReview({ scenario = "reference" }: { scenario?: IssueScenario }) {
  const [workspace, setWorkspace] = useState(() => issueReviewWorkspace(scenario));
  const [busy, setBusy] = useState(false); const attempts = useRef(0);
  const reject = () => Promise.reject(new Error("本样板仅用于校验问题审核。"));
  return <main className={styles.stage}><h1>校验问题审核</h1><p>虚构数据与本地回调；从页面下方的问题卡片填写说明、确认或重新打开。</p>
    <ReviewDataTable busy={busy} workspace={workspace} onAddRow={reject} onAddRowNote={reject} onAddCellNote={reject} onChangeRowState={reject} onPageChange={() => {}} onSetField={reject} onRestoreField={reject} onReviseNote={reject}
      onReviewIssue={async (issue, action, comment) => {
        attempts.current += 1; setBusy(true);
        try {
          if (scenario === "saving") await new Promise<void>(() => {});
          if (scenario === "save-failure" && attempts.current === 1) throw new Error("示例：保存响应未确认。");
          setWorkspace(current => { const next = structuredClone(current); next.head.review_revision += 1;
            next.latest_full_validation!.issues.find(item => item.id === issue.id)!.review = {
              state: action === "acknowledge" ? "acknowledged" : action === "resolve" ? "resolved" : "open",
              actor_user_id: 88, actor_username: "fictional-reviewer", comment: comment.trim() || null, event_id: 801, event_type: action, occurred_at: "2026-08-10T04:00:00Z",
            }; return next;
          });
        } finally { setBusy(false); }
      }} />
  </main>;
}
const meta = { title: "Patterns/Issue Review", component: IssueReview, parameters: { layout: "fullscreen" } } satisfies Meta<typeof IssueReview>;
export default meta; type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Warning: Story = { args: { scenario: "warning" } };
export const Blocking: Story = { args: { scenario: "blocking" } };
export const Handled: Story = { args: { scenario: "handled" } };
export const OptionalNote: Story = { args: { scenario: "optional-note" } };
export const LongValues: Story = { args: { scenario: "long-values" } };
export const Saving: Story = { args: { scenario: "saving" } };
export const SaveFailure: Story = { args: { scenario: "save-failure" } };
