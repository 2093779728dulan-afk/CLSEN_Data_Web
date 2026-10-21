import { catalogReadError } from "./catalogReadError";
import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { ApiRequestError, createOperationKey } from "../../api/client";
import {
  createCatalogExport,
  createImportFromExport,
  getCatalogExport,
  getLatestCatalogExport,
  resumeCatalogExport,
  uploadCatalogWorkbook,
  type CatalogExportStatus,
} from "./catalogApi";
import { exportViewState } from "./catalogState";
import { nextCatalogPath } from "./catalogTypes";

import { useCatalogNavigation } from "./CatalogNavigationContext";

const PHASE_LABELS: Record<CatalogExportStatus["execution_phase"], string> = {
  awaiting_manual_recovery: "等待人工恢复",
  completed: "生成完成",
  failed: "生成失败",
  materializing: "正在生成工作簿",
  retry_scheduled: "等待自动重试",
  waiting_for_worker: "等待 Worker",
};

export function CatalogExportPanel({
  catalogPublicationRevision,
  initialExport,
  generationReady = true,
}: {
  catalogPublicationRevision: number;
  initialExport?: CatalogExportStatus;
  generationReady?: boolean;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const { setReviewReturn } = useCatalogNavigation();
  const [current, setCurrent] = useState<CatalogExportStatus | undefined>(initialExport);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [selectedFile, setSelectedFile] = useState<File>();
  const uploadToken = useRef<string | undefined>(undefined);
  const stale = current !== undefined && current.catalog_publication_revision !== catalogPublicationRevision;
  const state = exportViewState(current);
  const phaseLabel = current ? PHASE_LABELS[current.execution_phase] : "尚未生成";

  useEffect(() => {
    if (initialExport !== undefined) return;
    void getLatestCatalogExport().then(setCurrent).catch(() => undefined);
  }, [initialExport]);

  useEffect(() => {
    if (state.kind !== "building") return;
    const timer = window.setInterval(() => {
      void getCatalogExport(state.export.export_id).then(setCurrent).catch(() => undefined);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state]);

  const create = async () => {
    if (!generationReady || busy) return;
    setBusy(true); setError(undefined);
    try { setCurrent(await createCatalogExport(catalogPublicationRevision)); }
    catch (reason) { setError(reason instanceof ApiRequestError && reason.code === "catalog_snapshot_unavailable" ? "暂时无法生成候选。请先确认来源报告已发布，并检查来源账号范围与快照配置；不要重复上传未发布的来源。" : catalogReadError(reason, "无法创建目录导出，请刷新核对状态。").message); }
    finally { setBusy(false); }
  };

  const startOnline = async () => {
    if (stale || (state.kind !== "ready" && state.kind !== "capacity")) return;
    setBusy(true); setError(undefined);
    try {
      const imported = await createImportFromExport(
        state.export.export_id,
        state.export.catalog_publication_revision,
      );
      setReviewReturn(new URLSearchParams(location.search).get("return_to") ?? "/catalog/maintenance");
      void navigate(nextCatalogPath(imported.import_id));
    } catch (reason) {
      setError(catalogReadError(reason, "无法建立在线审核草稿，请刷新核对状态。").message);
    } finally { setBusy(false); }
  };

  const upload = async () => {
    if (!selectedFile) return;
    setBusy(true); setError(undefined);
    try {
      const imported = await uploadCatalogWorkbook(
        selectedFile,
        uploadToken.current ??= createOperationKey(),
      );
      setReviewReturn("/catalog/maintenance");
      void navigate(nextCatalogPath(imported.catalog_import_id));
    } catch (reason) {
      setError(reason instanceof ApiRequestError && reason.code === "catalog_workbook_unsafe"
        ? "工作簿格式未通过检查。请保留六张工作表、生成信息和表头，不添加公式、外部链接或隐藏内容；仍失败时请保留文件供排查。"
        : reason instanceof ApiRequestError && reason.code === "catalog_text_cell_numeric" ? reason.message
        : reason instanceof ApiRequestError ? `上传未完成（${reason.code}）。请保留文件并反馈此错误代码。` : "无法上传目录工作簿，请检查连接后重试。");
    } finally { setBusy(false); }
  };

  const resume = async () => {
    if (state.kind !== "failed" || !state.export.permissions.can_resume) return;
    setBusy(true); setError(undefined);
    try { setCurrent(await resumeCatalogExport(state.export.export_id, state.export.job_revision)); }
    catch (reason) { setError(catalogReadError(reason, "无法恢复目录生成，请刷新核对状态。").message); }
    finally { setBusy(false); }
  };

  return (
    <section className="catalog-panel catalog-workbook" aria-labelledby="catalog-export-heading">
      <div className="catalog-panel__heading"><div><p className="section-kicker">初始化与批量修订</p><h2 id="catalog-export-heading">目录工作簿</h2><p className="catalog-master__intro">按顺序生成候选、选择审核方式，再到审核页校验并批准。生成成功不等于已经批准。</p></div><span className="catalog-status">{phaseLabel}</span></div>
      {!generationReady && <p role="status">生成候选前，请先完成上方来源确认与首次退货快照初始化，然后刷新准备状态。</p>}
      {stale && <p className="catalog-issues" role="status">这份候选基于旧目录发布修订 {current?.catalog_publication_revision}，当前已是 {catalogPublicationRevision}。请重新生成候选；旧 XLSX 不可覆盖新版本。</p>}
      <div className="catalog-workbook__steps">
        <article className={`catalog-workbook-step ${state.kind === "idle" || state.kind === "building" || state.kind === "failed" ? "is-current" : "is-complete"}`}>
          <header><span>1</span><div><h3>生成候选</h3><p>基于当前已发布事实建立可审核的候选目录。</p></div></header>
          {state.kind === "idle" && <button className="catalog-action-primary" disabled={busy || !generationReady} onClick={() => void create()} type="button">生成候选</button>}
          {state.kind === "building" && <div className="catalog-job-status" role="status">
            <strong>{PHASE_LABELS[state.export.execution_phase]}</strong>
            <span>已尝试 {state.export.attempt_count} / {state.export.max_attempts} 次 · {state.export.worker_available ? "Worker 可用" : "Worker 当前不可用"}</span>
            {state.export.next_attempt_at && <span>下次重试：{new Date(state.export.next_attempt_at).toLocaleString("zh-CN")}</span>}
            <small>任务成功前不能下载候选或开始在线审核。</small>
          </div>}
          {state.kind === "failed" && <div className="catalog-job-status">
            <strong className="form-error">生成失败：{state.export.failure_reason_code}</strong>
            <span>已尝试 {state.export.attempt_count} / {state.export.max_attempts} 次</span>
            <span>{state.export.worker_available ? "Worker 可用" : "Worker 当前不可用"}</span>
            {state.export.permissions.can_resume ? <button className="catalog-action-primary" disabled={busy} onClick={() => void resume()} type="button">恢复生成</button> : <small>当前状态或权限不允许恢复，请联系管理员处理任务。</small>}
          </div>}
          {(state.kind === "ready" || state.kind === "capacity") && <div className="catalog-job-status"><strong>候选已生成，尚未批准</strong><button disabled={busy || !generationReady} onClick={() => void create()} type="button">重新生成候选</button></div>}
        </article>
        <article className={`catalog-workbook-step ${state.kind === "ready" || state.kind === "capacity" ? "is-current" : ""}`}>
          <header><span>2</span><div><h3>选择审核方式</h3><p>日常处理优先在线审核；需要批量离线修改时使用兼容 XLSX。</p></div></header>
          <div className="catalog-review-methods">
            <section><strong>在线审核（推荐）</strong><p>直接检查候选，不需要下载或重新上传。</p>{(state.kind === "ready" || state.kind === "capacity") ? <button className="catalog-action-primary" disabled={busy || stale} onClick={() => void startOnline()} type="button">开始在线审核</button> : <small>当前候选生成成功后可用。</small>}</section>
            <section><strong>兼容 XLSX</strong><p>下载当前候选，离线修改后再上传审核；支持明确版本的六表模板；请保留生成信息、表头和身份列，不添加公式。旧模板缺少分类时保持原分类。</p>{state.kind === "ready" && !stale && state.export.permissions.can_download && <a href={`/api/catalog/exports/${state.export.export_id}/file`}>下载兼容 XLSX</a>}{state.kind === "capacity" && <small>候选超过 XLSX 容量，请改用在线审核。</small>}{state.kind === "ready" && !state.export.permissions.can_download && <small>当前账号不能下载此候选。</small>}<label>上传已修改的兼容 XLSX<input accept=".xlsx" onChange={(event) => { setSelectedFile(event.target.files?.[0]); uploadToken.current = event.target.files?.[0] ? createOperationKey() : undefined; }} type="file" /></label><button disabled={!selectedFile || busy} onClick={() => void upload()} type="button">上传并进入审核</button></section>
          </div>
        </article>
        <article className="catalog-workbook-step">
          <header><span>3</span><div><h3>校验与批准</h3><p>在审核页补全字段并重新校验；只有明确批准后，新目录版本才会生效。</p></div></header>
        </article>
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
    </section>
  );
}
