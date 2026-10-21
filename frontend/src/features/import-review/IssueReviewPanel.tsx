import { useState } from "react";
import type { ReviewIssue } from "../../api/types";
import { Button, FormField, StatusBadge, StatusMessage } from "../../design-system";
import controlCss from "../../design-system/Control.module.css";
import styles from "./IssueReviewPanel.module.css";

type Props = {
  busy: boolean;
  issues: ReviewIssue[];
  onReviewIssue: (issue: ReviewIssue, action: "acknowledge" | "resolve" | "reopen", comment: string) => Promise<void>;
};

function unknownValue(value: unknown) {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export function IssueReviewPanel({ busy, issues, onReviewIssue }: Props) {
  const [comments, setComments] = useState<Record<number, string>>({});
  const [errors, setErrors] = useState<Record<number, string>>({});
  const [pending, setPending] = useState<number>();
  if (!issues.length) return null;
  const open = issues.filter(issue => issue.review.state === "open");
  const locked = busy || pending !== undefined;
  const submit = async (issue: ReviewIssue, action: "acknowledge" | "resolve" | "reopen", comment: string) => {
    setPending(issue.id);
    setErrors(current => ({ ...current, [issue.id]: "" }));
    try { await onReviewIssue(issue, action, comment); }
    catch (caught) { setErrors(current => ({ ...current, [issue.id]: caught instanceof Error ? caught.message : "审核提交失败，请核对后重试。" })); }
    finally { setPending(undefined); }
  };
  return <section className={styles.panel} aria-label="校验问题">
    <header className={styles.header}>
      <div><p className={styles.kicker}>校验问题</p><h3>逐项核对，留下处理依据</h3><p className={styles.hint}>确认警告或解决阻断项后，仍按原流程校验与发布。</p></div>
      <div className={styles.counts}><StatusBadge tone="quiet" label={`${open.length} 项待处理`} /><StatusBadge tone="bad" label={`${open.filter(issue => issue.severity === "blocking").length} 项阻断待处理`} /></div>
    </header>
    <div className={styles.list}>{issues.map(issue => {
      const comment = comments[issue.id] ?? "";
      const action = issue.review.state === "open"
        ? issue.severity === "warning" ? "acknowledge" : "resolve"
        : "reopen";
      const label = action === "acknowledge" ? "确认警告" : action === "resolve" ? "标记已解决" : "重新打开";
      const state = issue.review.state === "open" ? "待处理" : issue.review.state === "acknowledged" ? "已确认" : "已解决";
      const scope = [issue.row_id != null ? `行 #${issue.row_id}` : "报表级问题", issue.field_name ? `字段 ${issue.field_name}` : null].filter(Boolean).join(" · ");
      return <article key={issue.id} aria-label={`${issue.severity === "warning" ? "警告" : "阻断项"} · ${issue.message}`} className={styles.card}>
        <div className={styles.identity}><div className={styles.badges}><StatusBadge tone={issue.severity === "warning" ? "warn" : "bad"} label={issue.severity === "warning" ? "警告" : "阻断项"} /><StatusBadge tone={issue.review.state === "open" ? "quiet" : "good"} label={state} /></div><code>#{issue.id} · {issue.rule_code}</code></div>
        <h4>{issue.message}</h4><p className={styles.scope}>{scope}</p>
        <dl className={styles.comparison}><div><dt>源值</dt><dd>{unknownValue(issue.source_value)}</dd></div><div className={styles.processed}><dt>处理值</dt><dd>{unknownValue(issue.processed_value)}</dd></div></dl>
        {(issue.review.actor_username || issue.review.comment) && <div className={styles.record}><strong>上次审核{issue.review.actor_username ? ` · ${issue.review.actor_username}` : ""}</strong>{issue.review.comment && <p>{issue.review.comment}</p>}</div>}
        <FormField label="审核说明" required={issue.requires_note} hint={issue.requires_note ? "本项必须填写处理依据。" : "可补充本次处理依据。"}><textarea className={controlCss.control} disabled={locked} onChange={event => setComments(current => ({ ...current, [issue.id]: event.target.value }))} rows={2} value={comment} /></FormField>
        {errors[issue.id] && <StatusMessage kind="danger" title="审核未完成">{errors[issue.id]} 说明已保留，请核对后重试。</StatusMessage>}
        <footer className={styles.actions}><span>{action === "resolve" ? "标记解决后，请重新校验。" : action === "reopen" ? "重新打开会恢复待处理状态。" : "确认本项警告，并记录审核说明。"}</span><Button variant="secondary" disabled={locked || (issue.requires_note && !comment.trim())} loading={pending === issue.id} loadingLabel="正在提交审核" onClick={() => { void submit(issue, action, comment); }} type="button">{label}</Button></footer>
      </article>;
    })}</div>
  </section>;
}
