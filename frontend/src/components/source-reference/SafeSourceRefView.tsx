import { Fingerprint } from "lucide-react";
import { StatusBadge } from "../../design-system";
import styles from "./SafeSourceRefView.module.css";

export type SafeSourceRef = {
  digest: string;
  is_truncated: boolean;
  is_unsafe: boolean;
  preview: string;
  source_ref_id: string;
};

export function SafeSourceRefView({ source }: { source: SafeSourceRef }) {
  const suffix = source.digest.replace(/^sha256:/, "").slice(-8);
  const containsStructuralCharacter = /[<>&"']/u.test(source.preview);
  const preview = containsStructuralCharacter ? "[含危险字符的来源]" : source.preview;
  return (
    <span className={`safe-source-ref ${styles.reference}`}>
      <span className={styles.preview}>{preview}</span>
      <span className={styles.digest}><Fingerprint aria-hidden="true" /><code aria-label="来源摘要后八位">{suffix}</code></span>
      {(source.is_unsafe || containsStructuralCharacter) && <StatusBadge tone="warn" label="含危险字符" />}
      {source.is_truncated && <StatusBadge tone="quiet" label="已截断" />}
    </span>
  );
}
