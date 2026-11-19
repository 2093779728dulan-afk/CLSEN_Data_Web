import { ArrowRight } from "lucide-react";
import { units } from "./types";
import styles from "./ReceiptQuantityPreview.module.css";

export function ReceiptQuantityPreview({ before, added = 0n, label }: { before?: string | null; added?: bigint; label: string }) {
  if (before == null || !/^[0-9]+$/.test(before)) return <span>待核</span>;
  const after = BigInt(before) + added;
  if (added === 0n || after < 0n) return <span>{units(before)}</span>;
  return <span className={styles.preview} aria-label={`${label}已入库${units(before)}件，确认后${units(after.toString())}件`} title="确认后生效">
    <span className={styles.before}>{units(before)}</span>
    <ArrowRight size={12} aria-hidden="true" />
    <strong key={after.toString()} className={styles.after}>{units(after.toString())}</strong>
  </span>;
}
