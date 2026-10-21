import { useEffect, useState } from "react";
import { Button } from "../../design-system";

import { requestApi } from "../../api/client";
import { SafeSourceRefView, type SafeSourceRef } from "../../components/source-reference/SafeSourceRefView";
import { useSensitiveReveal } from "../../components/source-reference/useSensitiveReveal";

function RevealRow({ importId, source, workflowRevision }: { importId: number; source: SafeSourceRef; workflowRevision: number }) {
  const reveal = useSensitiveReveal(["catalog-draft", importId, workflowRevision, source.source_ref_id]);
  const [error, setError] = useState<string>();
  const load = async () => {
    setError(undefined);
    try {
      await reveal.load((signal) => requestApi(
        `/api/catalog/imports/${importId}/source-identifiers/${source.source_ref_id}?workflow_revision=${workflowRevision}`,
        { signal },
      ));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法 reveal 来源。"); }
  };
  return <li className="catalog-source-item"><div className="catalog-source-item__preview"><span className="catalog-source-id">来源 #{source.source_ref_id}</span><SafeSourceRefView source={source} /></div><Button onClick={() => void load()} variant="secondary">查看完整标识</Button>{reveal.decoded && <div className="catalog-source-item__revealed"><output>{reveal.decoded}</output><Button onClick={() => void reveal.copy()}>复制</Button></div>}{error && <span className="form-error" role="alert">{error}</span>}</li>;
}

export function CatalogEvidencePanel({ importId, workflowRevision }: { importId: number; workflowRevision: number }) {
  const [items, setItems] = useState<SafeSourceRef[]>([]);
  useEffect(() => {
    void requestApi<{ items: SafeSourceRef[] }>(`/api/catalog/evidence?import_id=${importId}&page_size=50`).then((value) => setItems(value.items));
  }, [importId]);
  return <section className="catalog-source-evidence" aria-label="安全来源证据"><div className="catalog-source-evidence__heading"><p>默认展示安全预览与摘要；查看完整标识时会单独校验权限。</p><span>当前加载 {items.length} 条 · 最多 50 条</span></div><ul className="catalog-source-evidence__list">{items.map((item) => <RevealRow importId={importId} key={item.source_ref_id} source={item} workflowRevision={workflowRevision} />)}</ul></section>;
}
