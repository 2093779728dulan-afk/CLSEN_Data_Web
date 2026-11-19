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

type Pending =
  | { kind: "create"; revision: number; key: string }
  | { kind: "resume"; exportId: number; revision: number; key: string }
  | { kind: "online"; exportId: number; revision: number; key: string }
  | { kind: "upload"; file: File; key: string };

export function CatalogExportPanel({
  catalogPublicationRevision, initialExport, generationReady = true, onReview, onGuardChange,
}: {
  onReview?: (id: number) => void;
  onGuardChange?: (guard: { dirty: boolean; busy: boolean; unknown: boolean }) => void;
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
  const [pending, setPending] = useState<Pending>();
  const [unknown, setUnknown] = useState(false);
  const uploadToken = useRef<string | undefined>(undefined);
  useEffect(() => onGuardChange?.({ dirty: !!selectedFile, busy, unknown }), [selectedFile, busy, unknown, onGuardChange]);
  const stale = current !== undefined && current.catalog_publication_revision !== catalogPublicationRevision;
  const state = exportViewState(current);

  useEffect(() => {
    if (initialExport !== undefined) return;
    let active = true;
    const requestedId = Number(new URLSearchParams(location.search).get("export_id"));
    void (requestedId > 0 ? getCatalogExport(requestedId) : getLatestCatalogExport()).then(value => { if (active) setCurrent(value); }).catch(reason => { if (active) setError(catalogReadError(reason, "目录生成任务尚未读取完成，请检查连接后重试。").message); });
    return () => { active = false; };
  }, [initialExport, location.search]);

  useEffect(() => {
    if (state.kind !== "building" || unknown) return;
    const timer = window.setInterval(() => {
      void getCatalogExport(state.export.export_id).then(setCurrent).catch(reason => setError(catalogReadError(reason, "生成进度读取失败，请稍后核对原任务。").message));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [state, unknown]);

  // Preserve this command's input and key until its result is known.
  const run = async (command: Pending) => {
    if (busy) return;
    setPending(command); setBusy(true); setError(undefined);
    try {
      if (command.kind === "create") setCurrent(await createCatalogExport(command.revision, command.key));
      else if (command.kind === "resume") setCurrent(await resumeCatalogExport(command.exportId, command.revision, command.key));
      else {
        const id = command.kind === "upload"
          ? (await uploadCatalogWorkbook(command.file, command.key)).catalog_import_id
          : (await createImportFromExport(command.exportId, command.revision, command.key)).import_id;
        setSelectedFile(undefined);
        setReviewReturn(new URLSearchParams(location.search).get("return_to") ?? "/catalog/maintenance");
        if (onReview) onReview(id); else void navigate(nextCatalogPath(id));
      }
      setUnknown(false); setPending(undefined);
    } catch (reason) {
      const uncertain = !(reason instanceof ApiRequestError && reason.status < 500);
      setUnknown(uncertain);
      if (!uncertain) setPending(undefined);
      setError(uncertain ? "操作结果尚待核实，请核实原操作结果；不要重新生成或改选文件。" : (reason instanceof ApiRequestError && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : catalogReadError(reason, "操作未完成，请核对提示后重试。").message));
    } finally { setBusy(false); }
  };
  const create = () => { if (generationReady && !busy && !unknown) void run({ kind: "create", revision: catalogPublicationRevision, key: createOperationKey() }); };
  const startOnline = () => {
    if (!busy && !unknown && !stale && (state.kind === "ready" || state.kind === "capacity")) void run({ kind: "online", exportId: state.export.export_id, revision: state.export.catalog_publication_revision, key: createOperationKey() });
  };
  const upload = () => { if (selectedFile && !busy && !unknown) void run({ kind: "upload", file: selectedFile, key: uploadToken.current ??= createOperationKey() }); };
  const resume = () => {
    if (!busy && !unknown && state.kind === "failed" && state.export.permissions.can_resume) void run({ kind: "resume", exportId: state.export.export_id, revision: state.export.job_revision, key: createOperationKey() });
  };
  return <CatalogExportView current={current} catalogPublicationRevision={catalogPublicationRevision} generationReady={generationReady}
    busy={busy} unknown={unknown} onRecover={() => { if (pending) void run(pending); }} error={error} selectedFile={selectedFile}
    onCreate={create} onResume={resume} onStartOnline={startOnline} onUpload={upload} onFileChange={file => {
      if (busy || unknown) return;
      setSelectedFile(file); uploadToken.current = file ? createOperationKey() : undefined;
    }} />;
}
