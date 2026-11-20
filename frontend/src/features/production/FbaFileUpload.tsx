import { useEffect, useRef, useState } from "react";
import { ApiRequestError, requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, Input, StatusMessage } from "../../design-system";
import type { FbaBatch, FbaMapping } from "./fbaTypes";
import type { OverviewGuard } from "./stockOverview";
import styles from "./FbaWorkspace.module.css";

type Result = FbaBatch | { identities: FbaMapping[]; sha256: string; source_id: string; report_source_scope_id: string; stock_effect: false; snapshot_on?: string; available_units?: string; transit_units?: string; missing_skus?: number; excluded_rows?: {source_row:string;seller_sku:string;reason:string}[] };
export function FbaFileUpload({ path, identity = false, label, compact = false, disabled, saved, onGuardChange }: { path: string; identity?: boolean; label: string; compact?: boolean; disabled?: boolean; saved: (result: Result) => void; onGuardChange?: (guard: OverviewGuard) => void }) {
  const [file, setFile] = useState<File>(); const [busy, setBusy] = useState(false); const [unknown, setUnknown] = useState(false); const [error, setError] = useState("");
  const pending = useRef<{ file: File; key: string } | undefined>(undefined); const active = useRef(true); const { generation, registerSensitivePurge, purgeSensitiveState } = useAuthzGeneration(); const auth = useRef(generation); auth.current = generation;
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => registerSensitivePurge(() => { pending.current = undefined; setFile(undefined); setUnknown(false); setError(""); }), [registerSensitivePurge]);
  useEffect(() => { onGuardChange?.({dirty:!!file,busy,unknown}); }, [file,busy,unknown,onGuardChange]);
  useEffect(() => () => onGuardChange?.({dirty:false,busy:false,unknown:false}), [onGuardChange]);
  async function submit(query = false) {
    if (!file || busy) return;
    const operation = pending.current ?? { file, key: crypto.randomUUID() }; pending.current = operation; const version = auth.current; setBusy(true); setError("");
    try {
      const result = query ? await requestApi<Result>(`/api/production/commands/${operation.key}`) : await writeApi<Result>(path, { rawBody: operation.file, operationKey: operation.key, headers: { "Content-Type": identity || operation.file.name.endsWith(".csv") ? "text/csv" : "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "X-Original-Filename": encodeURIComponent(operation.file.name) } });
      if (active.current && version === auth.current) { pending.current = undefined; setUnknown(false); if(onGuardChange) setFile(undefined); saved(result); }
    } catch (reason) {
      if (!active.current || version !== auth.current) return;
      if (reason instanceof ApiRequestError && (reason.status === 401 || reason.status === 403)) { purgeSensitiveState(); return; }
      const uncertain = !identity && (query || !(reason instanceof ApiRequestError) || reason.status >= 500); setUnknown(uncertain); if (!uncertain) pending.current = undefined;
      setError(reason instanceof Error ? reason.message : "文件处理尚未完成。");
    } finally { if (active.current && version === auth.current) setBusy(false); }
  }
  return <div className={compact ? styles.uploadCompact : styles.workspace}>
    {error && <StatusMessage kind={unknown ? "warning" : "danger"} title={unknown ? "上传结果待核实" : "文件处理未完成"}>{error}{unknown && <div className={styles.actions}><Button disabled={busy} onClick={() => void submit(true)} variant="secondary">查询原上传结果</Button><Button disabled={busy} onClick={() => void submit()} variant="secondary">重发原上传</Button></div>}</StatusMessage>}
    <FormField label={label}><Input type="file" accept={identity ? ".csv" : path.includes("reimport") ? ".xlsx" : ".csv"} disabled={disabled || busy || unknown} onChange={event => { setFile(event.target.files?.[0]); pending.current = undefined; setError(""); }} /></FormField>
    <div className={styles.actions}><Button variant="secondary" disabled={!file || disabled || busy || unknown} onClick={() => void submit()}>{busy ? "正在处理文件…" : path.includes("snapshot-preview") ? "读取库存快照" : identity ? "读取商品资料" : path.includes("reimport") ? "回导核对明细" : compact ? "导入收货表" : "上传并预览接收明细"}</Button>{!compact&&!path.includes("snapshot-preview")&&<span className={styles.note}>读取、预览与保存草稿均不产生库存变动。</span>}</div>
  </div>;
}
