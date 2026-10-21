import { useEffect, useState } from "react";
import { Check, Copy, Eye, EyeOff, FileSearch } from "lucide-react";
import { Button, EmptyState, Skeleton, Spinner, StatusBadge, StatusMessage } from "../../design-system";

import { requestApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { SafeSourceRefView, type SafeSourceRef } from "../../components/source-reference/SafeSourceRefView";
import { useSensitiveReveal, type SensitiveReveal } from "../../components/source-reference/useSensitiveReveal";
import styles from "./CatalogEvidencePanel.module.css";

function readSources(importId: number, signal: AbortSignal) {
  return requestApi<{ items: SafeSourceRef[] }>(`/api/catalog/evidence?import_id=${importId}&page_size=50`, { signal });
}
function readIdentifier(importId: number, sourceRefId: string, workflowRevision: number, signal: AbortSignal) {
  return requestApi<SensitiveReveal>(`/api/catalog/imports/${importId}/source-identifiers/${sourceRefId}?workflow_revision=${workflowRevision}`, { signal });
}

function RevealRow({ importId, source, workflowRevision, loadIdentifier }: { importId: number; source: SafeSourceRef; workflowRevision: number; loadIdentifier: typeof readIdentifier }) {
  const reveal = useSensitiveReveal(["catalog-draft", importId, workflowRevision, source.source_ref_id]);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [copying, setCopying] = useState(false);
  const [copied, setCopied] = useState(false);
  const load = async () => {
    if (busy) return;
    setError(undefined); setBusy(true); setCopied(false);
    try {
      await reveal.load((signal) => loadIdentifier(importId, source.source_ref_id, workflowRevision, signal));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "无法查看完整标识，请重试。"); }
    finally { setBusy(false); }
  };
  const copy = async () => {
    if (copying) return;
    setError(undefined); setCopying(true); setCopied(false);
    try {
      if (await reveal.copy()) setCopied(true);
      else setError("没有可复制的完整标识，请重新查看。");
    } catch { setError("复制未完成，请允许浏览器访问剪贴板后重试。"); }
    finally { setCopying(false); }
  };
  return <li className={styles.source} aria-label={`来源 ${source.source_ref_id}`}>
    <div className={styles.sourceHeader}><span className={styles.sourceId}>来源 #{source.source_ref_id}</span><Button icon={<Eye />} loading={busy} loadingLabel="正在校验权限" disabled={busy || copying} onClick={() => void load()} variant="secondary">查看完整标识</Button></div>
    <div className={styles.preview}><SafeSourceRefView source={source} /></div>
    {reveal.decoded !== undefined && <div className={styles.revealed}><div className={styles.revealHeading}><strong>完整标识</strong><Button icon={<EyeOff />} disabled={busy || copying} onClick={() => { reveal.purge(); setCopied(false); setError(undefined); }} variant="quiet">隐藏完整标识</Button></div><output aria-label={`来源 ${source.source_ref_id} 完整标识`}>{reveal.decoded}</output><div className={styles.copyActions}><Button icon={copied ? <Check /> : <Copy />} loading={copying} loadingLabel="正在复制" disabled={busy || copying} onClick={() => void copy()}>{copied ? "已复制" : "复制完整标识"}</Button>{copied && <span role="status">已复制到剪贴板</span>}</div></div>}
    {error && <StatusMessage kind="danger" title="来源操作未完成">{error}</StatusMessage>}
  </li>;
}

export function CatalogEvidencePanel({ importId, workflowRevision, loadSources = readSources, loadIdentifier = readIdentifier }: { importId: number; workflowRevision: number; loadSources?: typeof readSources; loadIdentifier?: typeof readIdentifier }) {
  const { generation } = useAuthzGeneration();
  const [items, setItems] = useState<SafeSourceRef[]>();
  const [error, setError] = useState<string>();
  const [readAttempt, setReadAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setItems(undefined); setError(undefined);
    void loadSources(importId, controller.signal).then(value => { if (!controller.signal.aborted) setItems(value.items); }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "来源证据读取未完成。"); });
    return () => controller.abort();
  }, [importId, loadSources, readAttempt]);
  return <section className={styles.panel} aria-label="安全来源证据" aria-busy={!items && !error || undefined}>
    <header className={styles.heading}><div><h3><FileSearch aria-hidden="true" />安全来源证据</h3><p>默认展示安全预览与摘要；查看完整标识时会单独校验权限。</p></div><StatusBadge tone="quiet" label={items ? `${items.length} 条 · 最多 50 条` : "最多 50 条"} /></header>
    {error ? <StatusMessage kind="danger" title="来源证据读取未完成" action={<Button onClick={() => setReadAttempt(value => value + 1)}>重新读取来源</Button>}>{error}</StatusMessage> : !items ? <div className={styles.loading}><p role="status"><Spinner aria-hidden="true" />正在读取安全来源…</p><Skeleton lines={3} /></div> : !items.length ? <EmptyState title="暂无来源证据" description="当前批次未返回来源记录；这不表示商品审核已经完成。" /> : <ul className={styles.list}>{items.map(item => <RevealRow importId={importId} key={`${generation}:${importId}:${workflowRevision}:${item.source_ref_id}`} source={item} workflowRevision={workflowRevision} loadIdentifier={loadIdentifier} />)}</ul>}
  </section>;
}
