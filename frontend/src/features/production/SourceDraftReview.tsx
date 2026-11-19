import { useId, useRef, useState } from "react";
import { Button, Dialog } from "../../design-system";
import { compareDraftQuantity } from "./draftQuantity";
import { units } from "./types";
import styles from "./Production.module.css";

export type DraftReviewItem = { key: string; title: string; detail: string; targetId: string; actionLabel: string };

function locate(targetId: string) {
  const target = document.getElementById(targetId);
  if (!target) return;
  target.scrollIntoView?.({ block: "center", inline: "nearest" });
  target.focus({ preventScroll: true });
}

function signedUnits(value: string) { return `${BigInt(value) > 0n ? "+" : ""}${units(value)}件`; }

export function SourceDraftReview({ items, changedCount, totalDifference, disabled, onRestoreAll }: { items: DraftReviewItem[]; changedCount: number; totalDifference?: string; disabled: boolean; onRestoreAll: () => void }) {
  const headingId = useId(); const heading = useRef<HTMLHeadingElement>(null); const trigger = useRef<HTMLButtonElement>(null);
  const [restoreOpen, setRestoreOpen] = useState(false);
  return <section className={styles.panel} aria-labelledby={headingId}>
    <h2 ref={heading} id={headingId} tabIndex={-1} className={styles.reviewTarget}>待核对清单与数量修改</h2>
    <ul className={styles.reviewList}>{items.map(item => <li key={item.key}><div><strong>{item.title}</strong><p>{item.detail}</p></div><Button type="button" variant="quiet" onClick={() => locate(item.targetId)}>{item.actionLabel}</Button></li>)}</ul>
    <div className={styles.reviewChanges}><div><strong>{changedCount ? `已修改数量：${changedCount}行` : "数量与原表一致"}</strong><p>{totalDifference === undefined ? "数量填写有误，修正后再核对总差额。" : changedCount ? `合计较原表 ${signedUnits(totalDifference)}。日期、备注及归属说明单独保留。` : "原表数量保持，草稿其他资料可继续核对。"}</p></div><Button ref={trigger} type="button" variant="secondary" disabled={disabled || changedCount === 0} onClick={() => setRestoreOpen(true)}>恢复全部原数量</Button></div>
    <p className={styles.reviewHint}>修改与恢复先保留在当前输入，点击保存后才更新草稿。</p>
    <Dialog contentClassName={styles.productionDialog} open={restoreOpen} onOpenChange={setRestoreOpen} returnFocusTarget={changedCount ? trigger : heading} title="恢复全部原数量" description="仅恢复明细数量；日期、备注、核对及订单归属说明全部保留。恢复只改变当前输入，保存后才更新草稿。">
      <div className={styles.guardActions}><Button type="button" variant="secondary" onClick={() => setRestoreOpen(false)}>取消恢复</Button><Button type="button" disabled={disabled || changedCount === 0} onClick={() => { onRestoreAll(); setRestoreOpen(false); }}>确认恢复全部原数量</Button></div>
    </Dialog>
  </section>;
}

export function DraftQuantityChange({ original, current, allowZero = false, disabled, inputId, onRestore }: { original: string; current: string; allowZero?: boolean; disabled: boolean; inputId: string; onRestore: () => void }) {
  const comparison = compareDraftQuantity(original, current, allowZero);
  if (!comparison.changed) return null;
  return <div className={styles.quantityChange}>
    <small>{comparison.difference === undefined ? comparison.originalValid ? "草稿数量待修正" : "原数量待核对" : `${units(original)} → ${units(current)}件 · ${signedUnits(comparison.difference)}`}</small>
    <Button type="button" className={styles.restoreRowButton} variant="quiet" disabled={disabled || !comparison.originalValid} onClick={() => { onRestore(); locate(inputId); }}>恢复本行原数量</Button>
  </div>;
}
