import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { commandApi, requestApi, StableOperationKeyStore } from "../../api/client";
import { Button } from "../../design-system";
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
  return <section className="catalog-panel" aria-label="商品分析初始化">
    <h2>商品分析准备状态</h2>
    <p>报表发布与商品主档批准是两个步骤；款式映射须审核后生效。</p>
    {error && <p role="alert">{error}</p>}
    {progress && <p role="status">{progress}</p>}
    {!current && !error && <p role="status">正在读取初始化状态…</p>}
    {current && <>
      <ul>
        <li>来源报表：{current.readiness.published_reports} 份已发布；日期范围 {current.readiness.coverage_from ?? "无"} 至 {current.readiness.coverage_to ?? "无"}（中间日期可能缺报）。</li>
        <li>经营报告：{current.readiness.published_business_reports ?? 0} 份已发布；提供销售指标与商品来源。</li>
        <li>退货报告：{current.readiness.published_return_reports ?? 0} 份已发布；提供退货事实与商品来源。缺报不等于零退货。</li>
        <li>账号来源范围：{current.scope.status === "confirmed" ? `已确认（${current.scope.seller_account_display_name}）` : "待管理员确认"}</li>
        <li>商品主档：{current.readiness.catalog_approved ? "已有批准版本" : "待生成候选、审核并批准"}</li>
        <li>退货去重快照：{current.readiness.return_snapshot_present ? "已建立，读取分析时仍会校验是否匹配最新报表" : "尚未建立"}</li>
      </ul>
      <p>处理顺序：确认来源范围 → 建立首次退货快照 → 生成商品候选 → 审核并批准 → 读取产品分析。</p>
      <p>{current.readiness.prerequisites_present ? "基础资料已建立。产品总表会进一步核对日期范围、映射和快照一致性。" : "初始化尚未完成，产品分析暂不可用；已有报表可从每日数据查看。"}</p>
      {editable && current.scope.status === "unconfirmed" && (current.scope.permissions.can_confirm ? <form onSubmit={event => void confirm(event)}>
        <h3>确认本环境的报表来源</h3>
        <p>适用站点为 Amazon 美国站。请填写这些报表所属账号的稳定标识，不要填写密码或访问密钥；本次只确认来源，不批准商品映射。</p>
        <label>来源账号标识<input required maxLength={255} value={account} onChange={event => setAccount(event.target.value)} disabled={busy} /></label>
        <label>账号显示名称<input required maxLength={128} value={name} onChange={event => setName(event.target.value)} disabled={busy} /></label>
        <label>确认依据<input required maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} disabled={busy} /></label>
        <label><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} disabled={busy} />我确认当前站点报表属于上述同一账号，理解确认后不能通过此表单改为其他账号。</label>
        <Button type="submit" disabled={busy || !acknowledged || !account.trim() || !name.trim() || !reason.trim()}>确认来源范围</Button>
      </form> : <p>请联系管理员确认来源范围；当前账号不能执行该操作。</p>)}
      {current.scope.status === "confirmed" && !current.readiness.return_snapshot_present && <div>
        <p>首次快照使用已发布退货报告，不改变日报版本、发布记录或商品映射。已发布空报告可以确认零退货；没有报告时不能按零处理。</p>
        {editable ? <>
          <Button disabled={busy || (current.readiness.published_return_reports ?? 0) === 0} onClick={() => void prepareInitialization()}>准备首次退货快照</Button>
          {preview && <div>
            <p>将使用 {preview.published_return_reports} 份退货报告，范围 {preview.coverage_from} 至 {preview.coverage_to}。经营报告将在生成商品候选时一并使用。</p>
            <Button disabled={busy} onClick={() => void initialize()}>确认建立首次快照</Button>
          </div>}
        </> : <p>请由管理员或数据管理员在商品主档维护页完成初始化。</p>}
      </div>}
      {!editable && <Link to="/catalog">查看商品主档与初始化说明</Link>}
    </>}
    <p><Link to="/">查看已发布报表</Link></p>
    <Button disabled={busy} onClick={() => setRefresh(value => value + 1)}>刷新准备状态</Button>
  </section>;
}
