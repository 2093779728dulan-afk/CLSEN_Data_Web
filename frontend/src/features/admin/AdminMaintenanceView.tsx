import type { MaintenanceStatusResponse } from "../../api/generated";
import { Button, EmptyState, Skeleton, StatusBadge, StatusMessage, type StatusTone } from "../../design-system";
import { WorkerObservabilityPanel } from "./WorkerObservabilityPanel";
import css from "./AdminMaintenanceView.module.css";

type Props = {
  status?: MaintenanceStatusResponse;
  pageRefreshedAt?: Date;
  refreshing: boolean;
  refreshError: string | null;
  onRefresh: () => void;
};
const labels = { running: "执行中", sealed: "已封存", succeeded: "成功", failed: "失败" };
function tone(status: keyof typeof labels): StatusTone { return status === "succeeded" ? "good" : status === "failed" ? "bad" : "quiet"; }
function timestamp(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", hour12: false, timeStyle: "short" }).format(date);
}

export function AdminMaintenanceView({ status, pageRefreshedAt, refreshing, refreshError, onRefresh }: Props) {
  if (!status) return <section aria-label="备份与后台任务" className={css.workspace} aria-busy={refreshing}>
    <header className={css.heading}><h2>备份与后台任务</h2><StatusBadge label="只读状态" tone="quiet" /></header>
    {refreshing ? <div role="status" aria-label="正在载入维护与 Worker 状态" className={css.loading}><Skeleton height={90} /><Skeleton height={180} /><Skeleton height={90} /></div>
      : <StatusMessage kind={refreshError ? "danger" : "info"} title={refreshError ? "维护状态读取失败" : "维护状态尚未载入"} action={<Button onClick={onRefresh} variant="secondary">重新读取维护状态</Button>}>{refreshError ?? "读取成功后可查看 Worker、备份和恢复记录。"}</StatusMessage>}
  </section>;
  return <section aria-label="备份与后台任务" className={css.workspace}>
    <div className={css.worker}><WorkerObservabilityPanel status={status} pageRefreshedAt={pageRefreshedAt ?? new Date(status.observed_at)} refreshing={refreshing} refreshError={refreshError} onRefresh={onRefresh} /></div>
    <section aria-labelledby="maintenance-summary-title" className={css.backups}>
      <header className={css.heading}><div><h3 id="maintenance-summary-title">备份与后台任务</h3><p>状态只读 · 操作留在本机</p></div><StatusBadge label="保留独立恢复验证" tone="quiet" /></header>
      <div className={css.metrics}>
        <article><span>写屏障</span><strong>{status.write_lock.held ? "维护中" : "空闲"}</strong><small>{status.write_lock.held ? `已连续观测 ${Math.round(status.write_lock.observed_seconds)} 秒` : "当前未持有写屏障"}</small>{status.write_lock.warning && <StatusBadge tone="warn" label="持续持有，请核对" />}</article>
        <article><span>后台任务</span><strong>{status.outbox.pending + status.outbox.processing}</strong><small>待处理 {status.outbox.pending} · 失败 {status.outbox.failed}</small></article>
        <article><span>成功备份</span><strong>{status.backups.filter(item => item.status === "succeeded").length}</strong><small>仅统计已返回的最近备份</small></article>
        <article><span>恢复演练</span><strong>{status.restores.filter(item => item.status === "succeeded").length}</strong><small>仅统计成功恢复记录</small></article>
      </div>
      <p className={css.hint}>页面只展示状态和不可逆标识。创建备份、密钥轮换和隔离恢复仍通过本机受保护脚本执行，不会把数据库凭据或密钥传到浏览器。</p>
      <div className={css.history}>
        <section aria-label="最近备份"><h4>最近备份</h4>{status.backups.length ? <ol className={css.records}>{status.backups.map(item => <li key={item.id}><article aria-label={`备份 ${item.id}`}>
          <header><StatusBadge label={labels[item.status]} tone={tone(item.status)} /><code>{item.backup_uuid.slice(0, 12)}</code></header>
          <time dateTime={item.completed_at ?? item.started_at}>{timestamp(item.completed_at ?? item.started_at)}</time>
          <p>{item.raw_file_count} 个原始对象 · {item.publication_count} 个发布指针 · schema {item.schema_revision}</p>
          {item.failure_code && <p className={css.failure}>失败原因：{item.failure_code}</p>}
          <p className={css.verification}>{item.restore_verified_at ? `已恢复验证 ${timestamp(item.restore_verified_at)}` : "尚未恢复演练"}</p>
        </article></li>)}</ol> : <EmptyState title="尚无备份记录" description="运行本机备份脚本后，记录会显示在这里。" />}</section>
        <section aria-label="最近恢复验证"><h4>最近恢复验证</h4>{status.restores.length ? <ol className={css.records}>{status.restores.map(item => <li key={item.id}><article aria-label={`恢复验证 ${item.id}`}>
          <header><StatusBadge label={labels[item.status]} tone={tone(item.status)} /><code>{item.verification_uuid.slice(0, 12)}</code></header>
          <time dateTime={item.completed_at ?? item.started_at}>{timestamp(item.completed_at ?? item.started_at)}</time>
          <p>隔离目标：{item.target_database_name}</p>{item.failure_code && <p className={css.failure}>失败原因：{item.failure_code}</p>}
        </article></li>)}</ol> : <EmptyState title="尚无恢复验证记录" description="完成隔离恢复演练后，结果会显示在这里；备份成功本身不能证明恢复已通过。" />}</section>
      </div>
    </section>
  </section>;
}
