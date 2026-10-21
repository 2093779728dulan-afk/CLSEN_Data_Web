import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleHelp,
  Clock3,
  RefreshCw,
  Wrench,
} from "lucide-react";

import type {
  MaintenanceStatusResponse,
  QueueStatusResponse,
  WorkerInstanceStatusResponse,
} from "../../api/generated";
import { Button, StatusBadge, type StatusTone } from "../../design-system";

type Props = {
  status: MaintenanceStatusResponse;
  pageRefreshedAt: Date;
  refreshing: boolean;
  refreshError: string | null;
  onRefresh: () => void;
};

const heartbeatLabels = {
  online: "在线",
  stale: "心跳延迟",
  offline: "离线",
  stopped: "已停止",
  unknown: "无法确认",
} as const;

const consumerLabels = {
  healthy: "消费者正常",
  failing: "消费者失败",
  unknown: "无法确认",
  not_observed: "尚未观测",
} as const;

function formatTimestamp(value: string | Date | null) {
  if (!value) return "—";
  const instant = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(instant.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    hour12: false,
    timeStyle: "medium",
  }).format(instant);
}

function Timestamp({ value }: { value: string | Date | null }) {
  if (!value) return <>—</>;
  const instant = value instanceof Date ? value : new Date(value);
  const dateTime = Number.isNaN(instant.getTime()) ? String(value) : instant.toISOString();
  return <time dateTime={dateTime}>{formatTimestamp(value)}</time>;
}

function StatusMark({ label, tone }: { label: string; tone: StatusTone }) {
  return <StatusBadge label={label} tone={tone} />;
}

function heartbeatTone(status: WorkerInstanceStatusResponse["heartbeat_status"]) {
  if (status === "online") return "good" as const;
  if (status === "stale") return "warn" as const;
  if (status === "offline") return "bad" as const;
  return "quiet" as const;
}

function consumerTone(status: QueueStatusResponse["consumer_health"]) {
  if (status === "healthy") return "good" as const;
  if (status === "failing") return "bad" as const;
  if (status === "unknown") return "warn" as const;
  return "quiet" as const;
}

function queueHeadline(queue: QueueStatusResponse) {
  if (queue.query_health === "unknown") return "查询结果无法确认";
  if (queue.unresolved_building != null && queue.unresolved_building > 0) return `未决构建 ${queue.unresolved_building}`;
  if (queue.capabilities.stuck && queue.stuck != null && queue.stuck > 0) return `卡住 ${queue.stuck}`;
  const metrics = [
    ["可执行", queue.capabilities.actionable ? queue.actionable : null],
    ["执行中", queue.capabilities.in_flight ? queue.in_flight : null],
    ["等待重试", queue.capabilities.retry_wait ? queue.retry_wait : null],
    ["失败", queue.failed],
  ] as const;
  const meaningful = metrics.filter(([, value]) => value != null && value > 0);
  return meaningful.length
    ? meaningful.map(([label, value]) => `${label} ${value}`).join(" · ")
    : "当前无待处理工作";
}

function QueueDiagnostic({ queue }: { queue: QueueStatusResponse }) {
  const unknown = queue.query_health === "unknown";
  const metrics = [
    ["可执行", queue.capabilities.actionable, queue.actionable],
    ["执行中", queue.capabilities.in_flight, queue.in_flight],
    ["等待重试", queue.capabilities.retry_wait, queue.retry_wait],
    ["过期", queue.capabilities.stale, queue.stale],
    ["卡住", queue.capabilities.stuck, queue.stuck],
    ["失败", true, queue.failed],
  ] as const;

  return (
    <div className="worker-observability__diagnostic">
      {(queue.consumer_health === "failing" || unknown) && (
        <p className="worker-observability__queue-alert">
          {unknown
            ? `查询失败 · ${queue.failure_code ?? "unknown_query_error"}`
            : `消费者连续失败 ${queue.consecutive_failures ?? 0} 次 · ${queue.failure_code ?? "consumer_unexpected_error"}`}
        </p>
      )}
      <dl className="worker-observability__diagnostic-metrics">
        {metrics.map(([label, supported, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{supported ? (unknown ? "无法确认" : (value ?? "—")) : "不适用"}</dd>
          </div>
        ))}
      </dl>
      <div className="worker-observability__queue-facts">
        <span>最早工作 <Timestamp value={queue.oldest_work_at} /></span>
        <span>最近成功 <Timestamp value={queue.last_succeeded_at} /></span>
        <span>最近失败 <Timestamp value={queue.last_failed_at} /></span>
      </div>
      {queue.native_status_counts && (
        <dl className="worker-observability__native-counts" aria-label={`${queue.queue_name} 原生状态计数`}>
          {Object.entries(queue.native_status_counts).map(([name, count]) => (
            <div key={name}><dt>{name}</dt><dd>{count}</dd></div>
          ))}
        </dl>
      )}
    </div>
  );
}

function WorkerInstance({ instance }: { instance: WorkerInstanceStatusResponse }) {
  return (
    <article className={`worker-observability__instance worker-observability__instance--${instance.heartbeat_status}`}>
      <div className="worker-observability__instance-identity">
        <strong>{instance.instance_id.slice(0, 12)}</strong>
        <span>{instance.build_id}</span>
      </div>
      <StatusMark label={heartbeatLabels[instance.heartbeat_status]} tone={heartbeatTone(instance.heartbeat_status)} />
      <span><Timestamp value={instance.last_heartbeat_at} /></span>
      <span>{instance.heartbeat_age_seconds == null ? "无法确认" : `${instance.heartbeat_age_seconds} 秒`}</span>
      <span>#{instance.heartbeat_sequence}</span>
      <details>
        <summary>查看诊断 <ChevronRight aria-hidden="true" /></summary>
        <dl>
          <div><dt>状态码</dt><dd>{instance.last_result_code ?? "—"}</dd></div>
          <div><dt>角色</dt><dd>{instance.role}</dd></div>
        </dl>
        <ul aria-label={`${instance.instance_id} 消费者状态`}>
          {instance.consumers.map((consumer) => (
            <li key={consumer.queue_name}>
              <span>{consumer.queue_name}</span>
              <StatusMark label={consumerLabels[consumer.consumer_health]} tone={consumerTone(consumer.consumer_health)} />
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}

function QueueRow({ queue }: { queue: QueueStatusResponse }) {
  const unknown = queue.query_health === "unknown";
  return (
    <article className={`worker-observability__queue worker-observability__queue--${queue.consumer_health}`}>
      <div className="worker-observability__queue-row">
        <strong>{queue.queue_name}</strong>
        <StatusMark label={unknown ? "无法确认" : consumerLabels[queue.consumer_health]} tone={unknown ? "warn" : consumerTone(queue.consumer_health)} />
        <span className="worker-observability__queue-headline">{queueHeadline(queue)}</span>
        <span><Timestamp value={queue.last_succeeded_at ?? queue.last_failed_at} /></span>
        <details>
          <summary>查看诊断 <ChevronRight aria-hidden="true" /></summary>
          <QueueDiagnostic queue={queue} />
        </details>
      </div>
    </article>
  );
}

export function WorkerObservabilityPanel({ onRefresh, pageRefreshedAt, refreshError, refreshing, status }: Props) {
  const onlineCount = status.worker.instances.filter((instance) => instance.heartbeat_status === "online").length;
  const staleCount = status.worker.instances.filter((instance) => instance.heartbeat_status === "stale").length;
  const offlineCount = status.worker.instances.filter((instance) => instance.heartbeat_status === "offline").length;
  const failingQueues = status.queues.filter((queue) => queue.consumer_health === "failing");
  const unknownQueues = status.queues.filter((queue) => queue.consumer_health === "unknown" || queue.query_health === "unknown");
  const notObservedQueues = status.queues.filter((queue) => queue.consumer_health === "not_observed");
  const workerUnavailable = status.worker.query_health === "unknown";
  const hasIncidents = status.maintenance_active || workerUnavailable || staleCount > 0 || offlineCount > 0 || failingQueues.length > 0 || unknownQueues.length > 0;
  const overallTone = offlineCount > 0 || failingQueues.length > 0
    ? "bad"
    : status.maintenance_active || workerUnavailable || staleCount > 0 || unknownQueues.length > 0
      ? "warn"
      : onlineCount > 0 ? "good" : "quiet";
  const overallLabel = overallTone === "bad" ? "存在故障" : overallTone === "warn" ? "需要关注" : overallTone === "good" ? "运行正常" : "等待首次心跳";
  const failingQueue = failingQueues[0];

  return (
    <section className="worker-observability" aria-labelledby="worker-observability-title">
      <header className="worker-observability__heading">
        <div>
          <p>RECOVERY READINESS</p>
          <h2 id="worker-observability-title">Worker 运行状态</h2>
          <span>在线仅表示最近成功写入数据库心跳</span>
        </div>
        <div className="worker-observability__refresh-action">
          <span>数据库观测 <Timestamp value={status.observed_at} /></span>
          <span>页面最后刷新 <Timestamp value={pageRefreshedAt} /></span>
          <Button icon={<RefreshCw aria-hidden="true" />} loading={refreshing} onClick={onRefresh} variant="secondary">{refreshing ? "刷新中…" : "刷新状态"}</Button>
        </div>
      </header>

      {refreshError && <p className="worker-observability__refresh-error" role="alert">状态可能已过期：{refreshError}</p>}

      <details className="worker-observability__thresholds">
        <summary>心跳阈值参考 <ChevronRight aria-hidden="true" /></summary>
        <div>
          <span><strong>{status.worker.thresholds.heartbeat_seconds}s</strong> 写入间隔</span>
          <span><strong>{status.worker.thresholds.stale_seconds}s</strong> 延迟</span>
          <span><strong>{status.worker.thresholds.offline_seconds}s</strong> 离线</span>
          <span><strong>{status.worker.thresholds.refresh_seconds}s</strong> 页面刷新</span>
        </div>
      </details>

      <div className="worker-observability__workspace">
        <div className="worker-observability__rail">
          <aside className="worker-observability__issues" aria-labelledby="worker-issues-title">
            <header><h3 id="worker-issues-title">需要处理</h3><span>{hasIncidents ? "!" : "0"}</span></header>
            <ul>
              {status.maintenance_active && <li className="worker-observability__issue worker-observability__issue--warn"><Wrench aria-hidden="true" /><div><strong>维护模式已开启</strong><span>队列与心跳状态相互独立，请结合写屏障判断可操作性。</span></div><ChevronRight aria-hidden="true" /></li>}
              {failingQueue && onlineCount > 0 && <li className="worker-observability__issue worker-observability__issue--bad"><AlertTriangle aria-hidden="true" /><div><strong>进程在线，{failingQueue.queue_name} 消费者失败</strong><span>连续失败 {failingQueue.consecutive_failures ?? 0} 次 · {failingQueue.failure_code ?? "consumer_unexpected_error"}</span></div><ChevronRight aria-hidden="true" /></li>}
              {workerUnavailable && <li className="worker-observability__issue worker-observability__issue--warn"><CircleHelp aria-hidden="true" /><div><strong>Worker 状态无法确认</strong><span>{status.worker.failure_code ?? "数据库查询未返回可用结果"}</span></div><ChevronRight aria-hidden="true" /></li>}
              {unknownQueues.map((queue) => <li className="worker-observability__issue worker-observability__issue--warn" key={queue.queue_name}><Clock3 aria-hidden="true" /><div><strong>{queue.queue_name} 无法确认</strong><span>{queue.failure_code ?? "最近观测结果不可用"}</span></div><ChevronRight aria-hidden="true" /></li>)}
              {!hasIncidents && <li className="worker-observability__issue-empty"><CheckCircle2 aria-hidden="true" /><strong>当前没有需要处理的异常</strong><span>{onlineCount > 0 ? "Worker 与队列运行平稳" : "等待首次 Worker 心跳"}</span></li>}
            </ul>
          </aside>

          <section className="worker-observability__overview" aria-labelledby="worker-overview-title">
            <h3 id="worker-overview-title">运行概览</h3>
            <div>
              <article>{overallTone === "good" ? <CheckCircle2 aria-hidden="true" /> : overallTone === "bad" ? <AlertTriangle aria-hidden="true" /> : <CircleHelp aria-hidden="true" />}<span>总体状态</span><strong>{overallLabel}</strong></article>
              <article><Clock3 aria-hidden="true" /><span>Worker 心跳</span><strong>{onlineCount} 在线</strong><small>共 {status.worker.instances.length} 个实例</small></article>
              <article><AlertTriangle aria-hidden="true" /><span>原生队列</span><strong>{failingQueues.length + unknownQueues.length} 需关注</strong><small>共 {status.queues.length} 个队列</small></article>
              <article><CircleHelp aria-hidden="true" /><span>尚未观测</span><strong>{notObservedQueues.length}</strong><small>等待消费者数据</small></article>
            </div>
          </section>
        </div>

        <div className="worker-observability__main">
          <section className="worker-observability__fleet" aria-labelledby="worker-fleet-title">
            <header><h3 id="worker-fleet-title">实例</h3><span>{onlineCount} 在线 / {status.worker.instances.length} 已记录</span></header>
            {status.worker.instances.length > 0 && <div className="worker-observability__instance-columns" aria-hidden="true"><span>实例 / 构建</span><span>状态</span><span>最后心跳</span><span>心跳延迟</span><span>序列</span><span>操作</span></div>}
            <div className="worker-observability__instances">
              {status.worker.instances.map((instance) => <WorkerInstance instance={instance} key={instance.instance_id} />)}
              {status.worker.instances.length === 0 && <p className="worker-observability__empty"><CircleHelp aria-hidden="true" /><strong>{workerUnavailable ? "Worker 状态无法确认。" : "尚未观测到 Worker 实例。"}</strong><span>收到首个数据库心跳后，实例会显示在此处。</span></p>}
            </div>
          </section>

          <section className="worker-observability__queue-section" aria-labelledby="worker-queues-title">
            <header><h3 id="worker-queues-title">原生队列</h3><span>固定四类 · 每类独立查询</span></header>
            <div className="worker-observability__queue-columns" aria-hidden="true"><span>队列名称</span><span>状态</span><span>关键指标</span><span>最近观测</span><span>操作</span></div>
            <div className="worker-observability__queues">{status.queues.map((queue) => <QueueRow key={queue.queue_name} queue={queue} />)}</div>
          </section>
        </div>
      </div>
    </section>
  );
}
