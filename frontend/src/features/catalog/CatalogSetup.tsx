import { useEffect, useRef, useState, type FormEvent } from "react";
import { commandApi, requestApi, StableOperationKeyStore } from "../../api/client";
import { CatalogSetupView } from "./CatalogSetupView";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import type { AnalyticsReadiness, CatalogScopeStatusResponse, ReturnInitializationPreview, ReturnDedupStagingResponse } from "../../api/generated";

export function CatalogSetup({ editable = false, onGenerationReady }: { editable?: boolean; onGenerationReady?: (ready: boolean) => void }) {
  const { generation } = useAuthzGeneration();
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<{ generation: typeof generation; readiness: AnalyticsReadiness; scope: CatalogScopeStatusResponse }>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState("");
  const [name, setName] = useState("");
  const [reason, setReason] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);
  const [preview, setPreview] = useState<ReturnInitializationPreview>();
  const [progress, setProgress] = useState<string>();
  const keys = useRef(new StableOperationKeyStore());
  const active = useRef(0);
  useEffect(() => {
    keys.current = new StableOperationKeyStore();
    setPreview(undefined); setProgress(undefined);
    setAccount(""); setName(""); setReason(""); setAcknowledged(false);
  }, [generation]);
  useEffect(() => {
    const ticket = ++active.current;
    const controller = new AbortController();
    setPreview(undefined); setState(undefined); setError(undefined); setBusy(false); onGenerationReady?.(false);
    void Promise.all([
      requestApi<AnalyticsReadiness>("/api/dashboard/style-readiness", { signal: controller.signal }),
      requestApi<CatalogScopeStatusResponse>("/api/catalog/source-scope", { signal: controller.signal }),
    ]).then(([readiness, scope]) => {
      if (active.current === ticket) {
        setState({ generation, readiness, scope });
        onGenerationReady?.(scope.status === "confirmed" && readiness.return_snapshot_present && readiness.published_reports > 0);
      }
    }).catch(() => { if (!controller.signal.aborted && active.current === ticket) setError("无法读取初始化状态，请刷新；不会据此生成或批准商品。"); });
    return () => { active.current = ticket + 1; controller.abort(); };
  }, [generation, refresh, onGenerationReady]);
  const current = state?.generation === generation ? state : undefined;
  const confirm = async (event: FormEvent) => {
    event.preventDefault();
    if (!current?.scope.permissions.can_confirm || !acknowledged || busy) return;
    const ticket = active.current;
    const path = "/api/catalog/source-scope/confirm";
    const body = { expected_site_config_revision: current.scope.site_config_revision, seller_account_scope_key: account.trim(), seller_account_display_name: name.trim(), marketplace_scope_code: "amazon_us", reason: reason.trim() };
    const token = keys.current.forCommand("scope", path, body);
    setBusy(true); setError(undefined);
    try {
      await commandApi<CatalogScopeStatusResponse>(path, { ...body, operation_token: token }, token);
      keys.current.complete("scope", token);
      if (active.current === ticket) { setAcknowledged(false); setRefresh(value => value + 1); }
    } catch {
      if (active.current === ticket) setError("来源范围确认未完成。请先刷新核对是否已生效；相同内容再次提交会沿用操作编号。请勿填写另一账号绕过冲突。");
    } finally { if (active.current === ticket) setBusy(false); }
  };
  const monitorInitialization = async (jobId: number, ticket: number) => {
    const deadline = Date.now() + 120_000;
    while (active.current === ticket && Date.now() < deadline) {
      const job = await requestApi<ReturnDedupStagingResponse>(`/api/publications/return-dedup-staging/${jobId}`);
      if (active.current !== ticket) return;
      if (job.status === "ready") {
        setPreview(undefined); setProgress("首次退货快照已建立。请继续生成商品候选，审核映射后批准。");
        setRefresh(value => value + 1); return;
      }
      if (job.status !== "building") throw new Error("initialization_not_ready");
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    if (active.current === ticket) setProgress("任务仍在后台处理中。请稍后刷新准备状态；再次准备将查询原任务，不会重复初始化。");
  };
  const prepareInitialization = async () => {
    const ticket = active.current;
    setBusy(true); setError(undefined); setProgress(undefined); setPreview(undefined);
    try {
      const result = await requestApi<ReturnInitializationPreview>("/api/publications/return-initialization");
      if (active.current !== ticket) return;
      if (result.existing_job_id != null) {
        setProgress("正在查询已有初始化任务…");
        await monitorInitialization(result.existing_job_id, ticket);
      } else setPreview(result);
    } catch { if (active.current === ticket) setError("无法准备首次快照。请刷新核对来源与已发布退货报表；不会将缺报当作零退货。"); }
    finally { if (active.current === ticket) setBusy(false); }
  };
  const initialize = async () => {
    if (!preview || busy) return;
    const ticket = active.current;
    const path = "/api/publications/return-initialization";
    const body = { dataset_id: preview.dataset_id, proposed_version_id: preview.proposed_version_id,
      expected_publication_revision: preview.expected_publication_revision,
      expected_dedup_publication_revision: preview.expected_dedup_publication_revision,
      initialization_revision: preview.initialization_revision, expected_set_digest: preview.expected_set_digest };
    const token = keys.current.forCommand("return-initialization", path, body);
    setBusy(true); setError(undefined); setProgress("正在建立首次退货快照…");
    try {
      const job = await commandApi<ReturnDedupStagingResponse>(path, { ...body, operation_token: token }, token);
      if (active.current === ticket) await monitorInitialization(job.job_id, ticket);
    } catch { if (active.current === ticket) { setProgress(undefined); setError("首次快照尚未完成。来源或报表可能发生变化，请刷新核对；相同提交沿用操作编号，不会重复发布日报。"); } }
    finally { if (active.current === ticket) setBusy(false); }
  };
  return <CatalogSetupView current={current} editable={editable} busy={busy} error={error} progress={progress} preview={preview}
    fields={{ account, name, reason, acknowledged }}
    onFieldsChange={changes => { if (changes.account !== undefined) setAccount(changes.account); if (changes.name !== undefined) setName(changes.name); if (changes.reason !== undefined) setReason(changes.reason); if (changes.acknowledged !== undefined) setAcknowledged(changes.acknowledged); }}
    onConfirm={event => void confirm(event)} onPrepare={() => void prepareInitialization()} onInitialize={() => void initialize()} onRefresh={() => setRefresh(value => value + 1)} />;
}
