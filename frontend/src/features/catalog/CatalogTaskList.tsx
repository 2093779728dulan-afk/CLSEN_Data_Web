import { Disclosure } from "../../design-system";
import { useEffect, useRef, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { requestApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, Input, Select, StatusMessage } from "../../design-system";
import styles from "./CatalogOperations.module.css";

type Task = { task_id: string; import_id?: number; source_name: string; record_kind: string; stale?: boolean; source_kind: string; status: string; actor: string; updated_at: string; workflow_revision: number; review_path: string; scope_ids: number[] };
type Result = { items: Task[]; total_items: number; page: number; has_next: boolean; complete: boolean; group_counts?: { review_batches: number; listing_groups: number; generation_jobs: number; failed_batches: number }; baseline: { catalog_publication_revision: number } };
const states: Record<string, string> = { draft: "名称／分类草稿，待批准", queued: "等待生成", running: "生成中", failed: "生成失败，查看原恢复状态", uploaded: "已上传，等待解析", parsing: "解析中", parse_failed: "解析失败，需恢复", needs_attention: "待补全", validated: "已校验，待提交", ready_for_approval: "待批准", rejected: "已退回，需修订" };

export function CatalogTaskList({ kind }: { kind: "review" | "attention" }) {
  const [search, setSearch] = useSearchParams();
  const location = useLocation();
  const previousRevision = useRef<number | undefined>(undefined);
  const [changed, setChanged] = useState(false);
  const { registerSensitivePurge, generation } = useAuthzGeneration();
  const [result, setResult] = useState<Result>();
  const [error, setError] = useState<string>();
  const [retry, setRetry] = useState(0);
  const [scopes, setScopes] = useState<{ id: number; seller_account_display_name: string; marketplace_scope_code: string }[]>([]);
  const page = Math.max(1, Number(search.get("task_page")) || 1);
  const q = search.get("task_q") ?? "";
  const status = search.get("task_status") ?? "";
  const scope = search.get("scope_id") ?? "";
  const updatedFrom = search.get("updated_from") ?? "";
  const updatedTo = search.get("updated_to") ?? "";
  useEffect(() => registerSensitivePurge(() => { setResult(undefined); setScopes([]); setError(undefined); }), [registerSensitivePurge]);
  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams({ kind, page: String(page), page_size: "25", q });
    if (status) query.set("status", status);
    if (scope) query.set("scope_id", scope);
    if (updatedFrom) query.set("updated_from", updatedFrom);
    if (updatedTo) query.set("updated_to", updatedTo);
    setResult(undefined); setError(undefined);
    void requestApi<Result>(`/api/catalog/tasks?${query}`, { signal: controller.signal }).then(value => { if (!controller.signal.aborted) { if (previousRevision.current !== undefined && previousRevision.current !== value.baseline.catalog_publication_revision) setChanged(true); previousRevision.current = value.baseline.catalog_publication_revision; setResult(value); } }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : "任务读取未完成，请检查账号权限或连接后重试。"); });
    void requestApi<{scopes: typeof scopes}>("/api/catalog/production-sources/capabilities", { signal: controller.signal }).then(value => { if (!controller.signal.aborted) setScopes(value.scopes); }).catch(() => { /* The task response retains explicit scope IDs if labels are unavailable. */ });
    return () => controller.abort();
  }, [kind, page, q, status, scope, updatedFrom, updatedTo, retry, generation]);
  function navigate(nextPage: number) { const next = new URLSearchParams(search); next.set("task_page", String(nextPage)); setSearch(next); }
  return <section className={styles.operations} aria-label={kind === "review" ? "全部已保存审核候选" : "来源与失败待处理"}>
    <h2>{kind === "review" ? "待审核候选" : "需要继续处理"}</h2>

    <form className={styles.taskFilters} key={`${q}:${status}:${scope}:${updatedFrom}:${updatedTo}`} onSubmit={event => { event.preventDefault(); const values = new FormData(event.currentTarget); const next = new URLSearchParams(search); for (const field of ["task_q", "task_status", "scope_id", "updated_from", "updated_to"]) { const entry = values.get(field); const value = typeof entry === "string" ? entry : ""; if (value) next.set(field, value); else next.delete(field); } next.set("task_page", "1"); setSearch(next); }}>
      <FormField label="查找任务"><Input name="task_q" defaultValue={q} placeholder="款号、SKU、资料名称或批次号" /></FormField>
      <FormField label="任务状态"><Select name="task_status" defaultValue={status}><option value="">全部状态</option>{Object.entries(states).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</Select></FormField>
      <FormField label="店铺账号与站点"><Select name="scope_id" defaultValue={scope}><option value="">全部授权范围（含尚未绑定来源）</option>{scopes.map(item => <option key={item.id} value={item.id}>{item.seller_account_display_name} · {item.marketplace_scope_code}</option>)}</Select></FormField>
      <FormField label="任务更新开始日期"><Input type="date" name="updated_from" defaultValue={updatedFrom} /></FormField><FormField label="任务更新结束日期"><Input type="date" name="updated_to" defaultValue={updatedTo} /></FormField><Button type="submit">查找任务</Button>
    </form>
    {changed && <StatusMessage kind="info" title="目录版本已有更新">当前列表已按新版本重新读取，任务状态及数量可能变化。</StatusMessage>}{error ? <StatusMessage kind="danger" title="任务尚未读取完成">{error}<Button onClick={() => setRetry(value => value + 1)}>重新读取任务</Button></StatusMessage> : !result ? <p role="status">正在读取完整任务范围…</p> : <>
      {!result.complete && <StatusMessage kind="warning" title="任务尚未读取完整">请重新读取，不以当前数量判断全部任务。</StatusMessage>}{kind === "attention" && result.group_counts && <p>清单未处理 {result.group_counts.listing_groups} 组 · 解析或退回 {result.group_counts.failed_batches} 批 · 生成任务 {result.group_counts.generation_jobs} 项</p>}<p>共 {result.total_items} 条</p>
      {!result.items.length && <p>当前条件没有任务。</p>}
      <ul className={styles.history}>{result.items.map(item => <li key={item.task_id}><div><Link to={["catalog_review", "style_change"].includes(item.record_kind) ? `${item.review_path}${item.review_path.includes("?") ? "&" : "?"}return_to=${encodeURIComponent(location.pathname + location.search)}` : item.review_path}>{item.source_name} {item.import_id ? ` · 批次 ${item.import_id}` : ""}</Link><p>{item.record_kind === "listing_source" ? "原始清单 · 继续未核记录" : item.stale ? "目录已变化，需要重新核对" : states[item.status] ?? item.status} · 修订 {item.workflow_revision}</p><Disclosure><summary>记录详情</summary><p>操作账号 {item.actor} · 更新 {new Date(item.updated_at).toLocaleString("zh-CN")}</p><p>范围：{item.scope_ids.length ? item.scope_ids.map(id => scopes.find(s => s.id === id)?.seller_account_display_name ?? `账号范围#${id}`).join("、") : item.record_kind === "style_change" ? "内部商品范围，不按账号区分" : "来源账号待绑定"}</p></Disclosure></div></li>)}</ul>
      <nav aria-label="完整任务分页"><Button disabled={page <= 1} onClick={() => navigate(page - 1)}>上一页</Button><span>第 {page} 页</span><Button disabled={!result.has_next} onClick={() => navigate(page + 1)}>下一页</Button></nav>
    </>}
    <Link to="/catalog/maintenance">查看全部批次与高级维护</Link>
  </section>;
}
