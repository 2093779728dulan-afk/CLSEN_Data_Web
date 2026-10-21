import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { requestApi } from "../../api/client";
import { useCatalogNavigation } from "./CatalogNavigationContext";
type History = { items: { import_id: number; source_kind: string; status: string; workflow_revision: number }[]; has_next: boolean };
const labels: Record<string, string> = { approved: "已批准", draft: "草稿", ready_for_review: "待审核", in_review: "审核中", rejected: "已退回", validation_failed: "校验未通过", parsing: "解析中", parse_failed: "解析失败", needs_attention: "待补全", validated: "已校验", withdrawn: "已撤回", superseded: "已取代", uploaded: "已上传", parsed: "已解析", ready_for_approval: "待批准" };
export function CatalogImportHistory() {
  const { setReviewReturn } = useCatalogNavigation();
  const [page, setPage] = useState(1);
  const [retry, setRetry] = useState(0);
  const [result, setResult] = useState<History>();
  const [error, setError] = useState<string>();
  useEffect(() => {
    let active = true;
    setResult(undefined); setError(undefined);
    void requestApi<History>(`/api/catalog/imports?page=${page}`).then((value) => { if (active) setResult(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "读取失败"); });
    return () => { active = false; };
  }, [page, retry]);
  return <section className="catalog-panel" aria-label="已有审核批次">
    <div className="catalog-panel__heading"><div><h2>已有审核批次</h2><p>继续处理已有批次，或查看已批准结果，无需重新生成候选。</p></div><button type="button" onClick={() => setRetry(retry + 1)}>刷新批次</button></div>
    {error ? <p role="alert">{error}</p> : !result ? <p role="status">正在读取审核批次…</p> : <>
      {result.items.length === 0 ? <p>暂无审核批次，可在下方生成候选。</p> : <ul>{result.items.map((item) => <li key={item.import_id}><Link onClick={() => setReviewReturn("/catalog/maintenance")} to={`/catalog/imports/${item.import_id}`}>批次 #{item.import_id} · {item.status === "approved" ? "查看批准结果" : ["withdrawn", "superseded"].includes(item.status) ? "查看批次" : "继续审核"}</Link> · {item.source_kind === "online" ? "在线候选" : "文件导入"} · {labels[item.status] ?? item.status} · 修订 {item.workflow_revision}</li>)}</ul>}
      <div className="catalog-list-controls"><button type="button" disabled={page === 1} onClick={() => setPage(page - 1)}>上一页</button><span>第 {page} 页</span><button type="button" disabled={!result.has_next} onClick={() => setPage(page + 1)}>下一页</button></div>
    </>}
  </section>;
}


