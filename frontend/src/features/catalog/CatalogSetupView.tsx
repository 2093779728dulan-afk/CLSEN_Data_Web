import type { FormEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Database, FileCheck2, RefreshCw, ShieldCheck } from "lucide-react";
import type { AnalyticsReadiness, CatalogScopeStatusResponse, ReturnInitializationPreview } from "../../api/generated";
import { Button, Checkbox, FormField, Input, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import css from "./CatalogSetupView.module.css";

export type SourceScopeFields = { account: string; name: string; reason: string; acknowledged: boolean };
type Props = {
  current?: { readiness: AnalyticsReadiness; scope: CatalogScopeStatusResponse };
  editable: boolean;
  busy: boolean;
  error?: string;
  progress?: string;
  preview?: ReturnInitializationPreview;
  fields: SourceScopeFields;
  onFieldsChange: (changes: Partial<SourceScopeFields>) => void;
  onConfirm: (event: FormEvent<HTMLFormElement>) => void;
  onPrepare: () => void;
  onInitialize: () => void;
  onRefresh: () => void;
};

export function CatalogSetupView({ current, editable, busy, error, progress, preview, fields, onFieldsChange, onConfirm, onPrepare, onInitialize, onRefresh }: Props) {
  const readiness = current?.readiness;
  const scope = current?.scope;
  const confirmed = scope?.status === "confirmed";
  const snapshot = readiness?.return_snapshot_present;
  const currentStep = !confirmed ? 0 : !snapshot ? 1 : !readiness?.catalog_approved ? 2 : 3;
  return <section className={css.panel} aria-label="商品分析初始化" aria-busy={busy || !current && !error}>
    <header className={css.header}><div><span className={css.eyebrow}>商品主档 · 分析前置</span><h2>商品分析准备状态</h2><p>报表发布与商品主档批准是两个步骤；款式映射须审核后生效。</p></div><Button icon={<RefreshCw />} disabled={busy} onClick={onRefresh}>刷新准备状态</Button></header>
    {current && <ol className={css.steps} aria-label="准备顺序">{["确认来源范围", "建立退货快照", "审核商品主档", "读取产品分析"].map((label, index) => <li key={label} aria-current={index === currentStep ? "step" : undefined}><span>{index + 1}</span>{label}</li>)}</ol>}
    <div className={css.body}>
      {error && <div className={css.feedback}><StatusMessage kind="danger" title="准备操作未完成" action={<Button disabled={busy} onClick={onRefresh}>刷新核对状态</Button>}>{error}</StatusMessage></div>}
      {progress && <StatusMessage kind="info" title="快照任务进度">{progress}</StatusMessage>}
      {!current && !error && <div role="status" aria-label="正在读取初始化状态"><Skeleton lines={4} height={40} /><p>正在读取初始化状态…</p></div>}
      {current && readiness && scope && <>
        <div className={css.metrics} aria-label="已发布报表"><div><span>全部来源报表</span><strong>{readiness.published_reports}<small> 份</small></strong></div><div><span>经营报告</span><strong>{readiness.published_business_reports ?? 0}<small> 份</small></strong></div><div><span>退货报告</span><strong>{readiness.published_return_reports ?? 0}<small> 份</small></strong></div></div>
        <p className={css.coverage}>已发布日期范围 {readiness.coverage_from ?? "无"} 至 {readiness.coverage_to ?? "无"}；中间日期可能缺报，缺报不等于零退货。</p>
        <div className={css.readiness}>
          <article><ShieldCheck aria-hidden="true" /><div><h3>报表来源</h3><p>账号来源范围：{confirmed ? `已确认（${scope.seller_account_display_name}）` : "待管理员确认"}</p></div><StatusBadge tone={confirmed ? "good" : "warn"} label={confirmed ? "已确认" : "待确认"} /></article>
          <article><Database aria-hidden="true" /><div><h3>退货快照</h3><p>退货去重快照：{snapshot ? "已建立，读取分析时仍会校验是否匹配最新报表" : "尚未建立"}</p></div><StatusBadge tone={snapshot ? "good" : "quiet"} label={snapshot ? "已建立" : "待建立"} /></article>
          <article><FileCheck2 aria-hidden="true" /><div><h3>商品主档</h3><p>商品主档：{readiness.catalog_approved ? "已有批准版本" : "待生成候选、审核并批准"}</p></div><StatusBadge tone={readiness.catalog_approved ? "good" : "quiet"} label={readiness.catalog_approved ? "已批准" : "待审核"} /></article>
        </div>
        <StatusMessage kind={readiness.prerequisites_present ? "info" : "warning"} title={readiness.prerequisites_present ? "基础资料已建立" : "初始化尚未完成"}>{readiness.prerequisites_present ? "产品总表会进一步核对日期范围、映射和快照一致性。" : "产品分析暂不可用；已有报表可从每日数据查看。"}</StatusMessage>
        {editable && scope.status === "unconfirmed" && (scope.permissions.can_confirm ? <form className={css.form} onSubmit={onConfirm}>
          <div className={css.sectionHeading}><span>第 1 步</span><h3>确认本环境的报表来源</h3><p>适用 Amazon 美国站。填写报表所属账号的稳定标识；不要填写密码或访问密钥。本次只确认来源，不批准商品映射。</p></div>
          <fieldset disabled={busy} className={css.fields}>
            <FormField label="来源账号标识" required hint="使用稳定标识，确认后不能在此改为其他账号。"><Input required maxLength={255} value={fields.account} onChange={event => onFieldsChange({ account: event.target.value })} /></FormField>
            <FormField label="账号显示名称" required><Input required maxLength={128} value={fields.name} onChange={event => onFieldsChange({ name: event.target.value })} /></FormField>
            <FormField className={css.full} label="确认依据" required><Input required maxLength={1000} value={fields.reason} onChange={event => onFieldsChange({ reason: event.target.value })} /></FormField>
            <div className={css.full}><Checkbox label="我确认当前站点报表属于上述同一账号，理解确认后不能通过此表单改为其他账号。" checked={fields.acknowledged} onChange={event => onFieldsChange({ acknowledged: event.target.checked })} /></div>
          </fieldset>
          <footer className={css.footer}><span>确认账号范围，商品映射仍需单独审核。</span><Button variant="primary" type="submit" icon={<ShieldCheck />} loading={busy} loadingLabel="正在确认来源" disabled={!fields.acknowledged || !fields.account.trim() || !fields.name.trim() || !fields.reason.trim()}>确认来源范围</Button></footer>
        </form> : <StatusMessage kind="info" title="需要管理员确认">请联系管理员确认来源范围；当前账号不能执行该操作。</StatusMessage>)}
        {confirmed && !snapshot && <div className={css.form}>
          <div className={css.sectionHeading}><span>第 2 步</span><h3>建立首次退货快照</h3><p>使用已发布退货报告，不改变日报版本、发布记录或商品映射。已发布空报告可以确认零退货；没有报告时不能按零处理。</p></div>
          {editable ? <>
            {(readiness.published_return_reports ?? 0) === 0 && <StatusMessage kind="warning" title="尚无已发布退货报告">请先发布退货报告，再准备首次快照。</StatusMessage>}
            {preview && <div className={css.preview} role="region" aria-label="首次快照预览"><h4>请核对本次范围</h4><p>将使用 {preview.published_return_reports} 份退货报告，范围 {preview.coverage_from} 至 {preview.coverage_to}。经营报告将在生成商品候选时一并使用。</p><p className={css.trace}>数据集 #{preview.dataset_id} · 候选版本 #{preview.proposed_version_id} · 初始化修订 {preview.initialization_revision}</p><Button variant="primary" icon={<Database />} loading={busy} loadingLabel="正在建立首次快照" onClick={onInitialize}>确认建立首次快照</Button></div>}
            {<div className={css.prepare}><Button variant={preview ? "secondary" : "primary"} disabled={busy || (readiness.published_return_reports ?? 0) === 0} onClick={onPrepare}>准备首次退货快照</Button></div>}
          </> : <StatusMessage kind="info" title="需要维护账号初始化">请由管理员或数据管理员在商品主档维护页完成初始化。</StatusMessage>}
        </div>}
        {!editable && <Link className={css.link} to="/catalog">查看商品主档与初始化说明<ArrowRight size={16} aria-hidden="true" /></Link>}
      </>}
      <footer className={css.links}><Link to="/">查看已发布报表<ArrowRight size={16} aria-hidden="true" /></Link></footer>
    </div>
  </section>;
}
