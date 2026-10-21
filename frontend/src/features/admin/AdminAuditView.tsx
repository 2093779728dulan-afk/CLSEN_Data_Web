import type { FormEvent } from "react";
import type { AuditEventPageResponse } from "../../api/generated";
import { Button, EmptyState, FormField, Input, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import css from "./AdminAuditView.module.css";

const SENSITIVE_AUDIT_KEY = /(?:order|tracking|license|customer|message|订单|物流|牌照|客户|留言)/iu;

function safeAuditValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(safeAuditValue);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .filter(([key]) => !SENSITIVE_AUDIT_KEY.test(key))
        .map(([key, item]) => [key, safeAuditValue(item)]),
    );
  }
  return value;
}

function timestamp(value: string) {
  const instant = new Date(value);
  return Number.isNaN(instant.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium", hour12: false, timeStyle: "short",
  }).format(instant);
}

export type AdminAuditViewProps = {
  page?: AuditEventPageResponse;
  offset: number;
  pageSize: number;
  filter: string;
  appliedFilter: string;
  initialLoading: boolean;
  loadFailed: boolean;
  busy: boolean;
  error?: string;
  onFilterChange: (value: string) => void;
  onFilter: (event: FormEvent) => void;
  onPage: (offset: number) => void;
  onRetry: () => void;
};

export function AdminAuditView({ page, offset, pageSize, filter, appliedFilter, initialLoading, loadFailed, busy, error, onFilterChange, onFilter, onPage, onRetry }: AdminAuditViewProps) {
  const unavailable = initialLoading || loadFailed;
  const items = page?.items ?? [];
  return <section className={css.workspace} aria-labelledby="admin-audit-title" aria-busy={initialLoading || busy}>
    <header className={css.heading}>
      <div><h2 id="admin-audit-title">内部审计</h2><p>按时间核对管理操作、操作人和对象，保留每次变更的证据。</p></div>
      <StatusBadge tone="quiet" label="只读记录" />
    </header>
    {error && <StatusMessage kind="danger" title="审计读取未完成">{error}{!loadFailed && page && <span> 当前保留上次读取的记录，本次读取尚未更新。</span>}</StatusMessage>}
    {loadFailed && <Button onClick={onRetry} variant="secondary">重新载入管理资料</Button>}
    <form aria-label="筛选审计记录" className={css.filter} onSubmit={onFilter}>
      <FormField label="事件类型" hint="输入完整事件类型；留空查看全部。">
        <Input id="admin-audit-filter" value={filter} onChange={event => onFilterChange(event.target.value)} placeholder="例如 admin.user_updated" disabled={unavailable || busy} />
      </FormField>
      <Button type="submit" variant="primary" disabled={unavailable || busy} loading={busy}>应用筛选</Button>
    </form>
    <p className={css.privacy}>这里只展示服务端脱敏后的管理事件，不提供原始订单号、物流牌照或客户留言。</p>
    {initialLoading ? <div role="status" aria-label="正在读取审计记录" className={css.loading}><Skeleton height={80} /><Skeleton height={80} /><Skeleton height={80} /></div> : !loadFailed && <>
      <div className={css.result} role="status"><span>{appliedFilter ? <>当前事件类型 <code>{appliedFilter}</code></> : "全部事件类型"}</span><span>共 {page?.total ?? 0} 条 · 第 {Math.floor(offset / pageSize) + 1} 页</span></div>
      {items.length ? <ol className={css.ledger} aria-label="审计记录">
        {items.map(item => {
          const payload = safeAuditValue(item.redacted_payload) as Record<string, unknown>;
          return <li key={item.id}><article aria-label={`审计事件 ${item.id}`} className={css.event}>
            <header className={css.eventHeading}><div><strong>{item.event_type}</strong><p>{item.actor_username ?? "系统"}<span aria-hidden="true"> · </span><time dateTime={item.occurred_at}>{timestamp(item.occurred_at)}</time></p></div><code>#{item.id}</code></header>
            <dl className={css.identity}>
              <div><dt>对象</dt><dd>{item.object_type}{item.object_id ? ` #${item.object_id}` : ""}</dd></div>
              <div><dt>站点</dt><dd>{item.site_id ?? "—"}</dd></div>
              <div><dt>请求</dt><dd><code>{item.request_id ?? "—"}</code></dd></div>
            </dl>
            {Object.keys(payload).length > 0 && <details className={css.details}><summary>查看脱敏详情</summary><pre>{JSON.stringify(payload, null, 2)}</pre></details>}
          </article></li>;
        })}
      </ol> : <EmptyState title="当前筛选条件下没有审计记录" description="检查事件类型，或留空后重新应用筛选。" />}
      <nav aria-label="审计分页" className={css.pagination}>
        <Button disabled={busy || offset === 0} onClick={() => onPage(Math.max(0, offset - pageSize))} variant="quiet">上一页</Button>
        <span aria-current="page">第 {Math.floor(offset / pageSize) + 1} 页</span>
        <Button disabled={busy || page?.next_offset == null} onClick={() => { if (page?.next_offset != null) onPage(page.next_offset); }} variant="quiet">下一页</Button>
      </nav>
    </>}
  </section>;
}
