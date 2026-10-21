import { useId } from "react";
import { ArrowRight, Download, FileSpreadsheet, RefreshCw, Upload } from "lucide-react";
import { Button, FormField, Input, Spinner, StatusBadge, StatusMessage } from "../../design-system";
import { exportViewState } from "./catalogState";
import type { CatalogExportStatus } from "./catalogApi";
import styles from "./CatalogExportView.module.css";

const PHASE_LABELS: Record<CatalogExportStatus["execution_phase"], string> = {
  awaiting_manual_recovery: "等待人工恢复", completed: "生成完成", failed: "生成失败",
  materializing: "正在生成工作簿", retry_scheduled: "等待自动重试", waiting_for_worker: "等待 Worker",
};

export function CatalogExportView({ current, catalogPublicationRevision, generationReady, busy, error, selectedFile, onCreate, onResume, onStartOnline, onFileChange, onUpload }: {
  current?: CatalogExportStatus; catalogPublicationRevision: number; generationReady: boolean; busy: boolean; error?: string; selectedFile?: File;
  onCreate: () => void; onResume: () => void; onStartOnline: () => void; onFileChange: (file?: File) => void; onUpload: () => void;
}) {
  const heading = useId();
  const stale = current !== undefined && current.catalog_publication_revision !== catalogPublicationRevision;
  const state = exportViewState(current);
  const ready = state.kind === "ready" || state.kind === "capacity";
  const phaseLabel = current ? PHASE_LABELS[current.execution_phase] : "尚未生成";
  return <section className={styles.panel} aria-labelledby={heading} aria-busy={busy || undefined}>
    <header className={styles.heading}><div><p className={styles.kicker}>初始化与批量修订</p><h2 id={heading}><FileSpreadsheet aria-hidden="true" />目录工作簿</h2><p>按顺序生成候选、选择审核方式，再到审核页校验并批准。生成成功不等于已经批准。</p></div><StatusBadge label={phaseLabel} tone={state.kind === "failed" ? "bad" : ready ? "good" : "quiet"} /></header>
    <div className={styles.identity}><span>当前发布修订 <strong>{catalogPublicationRevision}</strong></span>{current && <><span>候选 <strong>#{current.export_id}</strong></span><span>基于发布修订 <strong>{current.catalog_publication_revision}</strong></span></>}</div>
    {!generationReady && <StatusMessage kind="warning" title="来源准备尚未完成">生成候选前，请先完成上方来源确认与首次退货快照初始化，然后刷新准备状态。</StatusMessage>}
    {stale && <StatusMessage kind="warning" title="候选修订已过期">这份候选基于旧目录发布修订 {current?.catalog_publication_revision}，当前已是 {catalogPublicationRevision}。请重新生成候选；旧 XLSX 不可覆盖新版本。</StatusMessage>}
    <ol className={styles.steps}>
      <li className={styles.step}>
        <div className={styles.stepHeading}><span className={styles.number}>1</span><div><h3>生成候选</h3><p>基于当前已发布事实建立可审核的候选目录。</p></div></div>
        <div className={styles.body}>
          {state.kind === "idle" && <Button variant="primary" icon={<FileSpreadsheet />} disabled={busy || !generationReady} onClick={onCreate}>生成候选</Button>}
          {state.kind === "building" && <div className={styles.job} role="status"><strong><Spinner aria-hidden="true" />候选正在准备</strong><span>已尝试 {state.export.attempt_count} / {state.export.max_attempts} 次 · {state.export.worker_available ? "Worker 可用" : "Worker 当前不可用"}</span>{state.export.next_attempt_at && <span>下次重试：{new Date(state.export.next_attempt_at).toLocaleString("zh-CN")}</span>}<small>任务成功前不能下载候选或开始在线审核。</small></div>}
          {state.kind === "failed" && <div className={styles.job}><strong className={styles.failure}>生成失败：{state.export.failure_reason_code}</strong><span>已尝试 {state.export.attempt_count} / {state.export.max_attempts} 次</span><span>{state.export.worker_available ? "Worker 可用" : "Worker 当前不可用"}</span>{state.export.permissions.can_resume ? <Button icon={<RefreshCw />} disabled={busy} onClick={onResume}>恢复生成</Button> : <small>当前状态或权限不允许恢复，请联系管理员处理任务。</small>}</div>}
          {ready && <div className={styles.job}><strong>候选已生成，尚未批准</strong><Button icon={<RefreshCw />} disabled={busy || !generationReady} onClick={onCreate}>重新生成候选</Button></div>}
        </div>
      </li>
      <li className={styles.step}>
        <div className={styles.stepHeading}><span className={styles.number}>2</span><div><h3>选择审核方式</h3><p>日常处理优先在线审核；需要批量离线修改时使用兼容 XLSX。</p></div></div>
        <div className={styles.methods}>
          <section className={styles.online}><header><h4>在线审核</h4><StatusBadge tone="quiet" label="推荐" /></header><p>直接检查候选，不需要下载或重新上传。</p>{ready ? <Button variant="primary" icon={<ArrowRight />} disabled={busy || stale} onClick={onStartOnline}>开始在线审核</Button> : <small>当前候选生成成功后可用。</small>}</section>
          <section><header><h4>兼容 XLSX</h4><StatusBadge tone="quiet" label="离线修改" /></header><p>下载当前候选，离线修改后再上传审核；支持明确版本的六表模板；请保留生成信息、表头和身份列，不添加公式。旧模板缺少分类时保持原分类。</p>
            {state.kind === "ready" && !stale && state.export.permissions.can_download && <a className={styles.download} href={`/api/catalog/exports/${state.export.export_id}/file`}><Download aria-hidden="true" />下载兼容 XLSX</a>}
            {state.kind === "capacity" && <StatusMessage kind="warning" title="超出 XLSX 容量">候选超过 XLSX 容量，请改用在线审核。</StatusMessage>}
            {state.kind === "ready" && !state.export.permissions.can_download && <small>当前账号不能下载此候选。</small>}
            <div className={styles.upload}><FormField label="上传已修改的兼容 XLSX"><Input accept=".xlsx" disabled={busy} onChange={event => onFileChange(event.target.files?.[0])} type="file" /></FormField>{selectedFile && <p className={styles.selected}>已选择：<strong>{selectedFile.name}</strong></p>}<Button icon={<Upload />} disabled={!selectedFile || busy} onClick={onUpload}>上传并进入审核</Button></div>
          </section>
        </div>
      </li>
      <li className={styles.step}><div className={styles.stepHeading}><span className={styles.number}>3</span><div><h3>校验与批准</h3><p>在审核页补全字段并重新校验；只有明确批准后，新目录版本才会生效。</p></div></div></li>
    </ol>
    {busy && <div className={styles.pending} role="status"><Spinner aria-hidden="true" />正在处理操作，请等待结果…</div>}
    {error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
  </section>;
}
