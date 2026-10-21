import "./SafeSourceRefView.css";

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
    <span className="safe-source-ref">
      <span>{preview}</span>
      <code aria-label="来源摘要后八位">{suffix}</code>
      {(source.is_unsafe || containsStructuralCharacter) && <span className="safe-source-ref__badge">含危险字符</span>}
      {source.is_truncated && <span className="safe-source-ref__badge">已截断</span>}
    </span>
  );
}
