import { CatalogExportView } from "./CatalogExportView";
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

  return <CatalogExportView current={current} catalogPublicationRevision={catalogPublicationRevision} generationReady={generationReady}
    busy={busy} error={error} selectedFile={selectedFile} onCreate={() => void create()} onResume={() => void resume()}
    onStartOnline={() => void startOnline()} onUpload={() => void upload()} onFileChange={file => {
      setSelectedFile(file); uploadToken.current = file ? createOperationKey() : undefined;
    }} />;
}
