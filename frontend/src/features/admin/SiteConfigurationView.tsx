import type { FormEvent } from "react";
import { Plus } from "lucide-react";
import type { SiteConfigVersionResponse } from "../../api/generated";
import { Button, EmptyState, FormField, Input, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import css from "./SiteConfigurationView.module.css";

export type SiteFormState = {
  changeReason: string;
  currencyCode: string;
  effectiveAt: string;
  reportingTimezone: string;
  siteId: string;
  sourceTimezone: string;
};

function timestamp(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "short", hour12: false }).format(date);
}

export type SiteConfigurationViewProps = {
  configs: SiteConfigVersionResponse[];
  currentConfig?: SiteConfigVersionResponse;
  initialLoading: boolean;
  loadFailed: boolean;
  busy: boolean;
  error?: string;
  notice?: string;
  showCreate: boolean;
  form: SiteFormState;
  onRetry: () => void;
  onBeginCreate: () => void;
  onCancel: () => void;
  onChange: (changes: Partial<SiteFormState>) => void;
  onCreate: (event: FormEvent) => void;
};

export function SiteConfigurationView({ configs, currentConfig, initialLoading, loadFailed, busy, error, notice, showCreate, form, onRetry, onBeginCreate, onCancel, onChange, onCreate }: SiteConfigurationViewProps) {
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return <section className={css.workspace} aria-labelledby="admin-site-title">
    <header className={css.heading}>
      <div><p className={css.kicker}>报告口径 · 版本管理</p><h2 id="admin-site-title">站点配置版本</h2><p>保存新版本后更新当前配置，旧版本与变更原因保留。</p></div>
      <Button icon={<Plus />} disabled={initialLoading || loadFailed || busy || showCreate} onClick={onBeginCreate}>新建配置版本</Button>
    </header>
    {error && <StatusMessage kind="danger" title={loadFailed ? "站点配置读取未完成" : "配置版本未创建"}
      action={loadFailed ? <Button onClick={onRetry}>重新载入管理资料</Button> : undefined}>{error}</StatusMessage>}
    {notice && <StatusMessage kind="success" title="站点配置操作结果">{notice}</StatusMessage>}
    {initialLoading ? <div role="status" aria-label="正在载入站点配置"><Skeleton lines={4} /></div> : !loadFailed && <>
      {currentConfig && <article aria-label={`当前站点配置 ${currentConfig.site_code}`} className={css.current}>
        <header><div><StatusBadge label="当前配置" tone="good" /><h3>{currentConfig.site_display_name} <span>v{currentConfig.version_number}</span></h3><code>{currentConfig.site_code} · 站点 #{currentConfig.site_id}</code></div><time dateTime={currentConfig.effective_at}>生效于 {timestamp(currentConfig.effective_at)}</time></header>
        <dl className={css.rules}>
          <div><dt>源时区</dt><dd>{currentConfig.source_timezone}<small>解释来源文件中的时间。</small></dd></div>
          <div><dt>统计时区</dt><dd>{currentConfig.reporting_timezone}<small>决定报告日期的统计口径。</small></dd></div>
          <div><dt>币种</dt><dd>{currentConfig.currency_code}<small>站点配置中保存的币种。</small></dd></div>
        </dl>
      </article>}
      {showCreate && <form className={css.createForm} aria-label="创建站点配置版本" onSubmit={onCreate}>
        <header><h3>创建站点配置版本</h3><p>修改报告口径前，请核对站点、生效时间并填写变更原因。</p></header>
        <fieldset disabled={busy} className={css.fields}>
          <legend className={css.srOnly}>新配置版本</legend>
          <FormField label="站点 ID" required hint="沿用站点的固定编号。"><Input type="number" min={1} required value={form.siteId} onChange={event => onChange({ siteId: event.target.value })} /></FormField>
          <FormField label="币种" required hint="使用 3 位币种代码，例如 USD。"><Input minLength={3} maxLength={3} required value={form.currencyCode} onChange={event => onChange({ currencyCode: event.target.value })} /></FormField>
          <FormField label="生效时间（本机时区）" required hint={`按本机时区 ${localTimezone} 输入。`}><Input type="datetime-local" required value={form.effectiveAt} onChange={event => onChange({ effectiveAt: event.target.value })} /></FormField>
          <FormField label="源时区" required hint="使用 IANA 时区名称，例如 America/Los_Angeles。"><Input required value={form.sourceTimezone} onChange={event => onChange({ sourceTimezone: event.target.value })} /></FormField>
          <FormField label="统计时区" required hint="调整后会改变报告日的统计口径。"><Input required value={form.reportingTimezone} onChange={event => onChange({ reportingTimezone: event.target.value })} /></FormField>
          <FormField className={css.reason} label="变更原因" required><textarea required rows={3} value={form.changeReason} onChange={event => onChange({ changeReason: event.target.value })} /></FormField>
        </fieldset>
        <div className={css.actions}><Button variant="quiet" disabled={busy} onClick={onCancel}>取消</Button><Button type="submit" variant="primary" loading={busy} loadingLabel="正在创建配置版本…">创建配置版本</Button></div>
      </form>}
      <section aria-labelledby="admin-site-history-title" className={css.history}>
        <header className={css.historyHeading}><div><h3 id="admin-site-history-title">版本历史</h3><p>保留每个站点的配置、原因及生效时间。</p></div><StatusBadge label={`${configs.length} 个版本`} tone="quiet" /></header>
        {configs.length === 0 ? <EmptyState title="还没有站点配置版本" description="创建第一个版本，设置源时区、统计时区和币种。" /> :
          <Table aria-label="站点配置版本历史" className={css.ledger} role="table"><thead role="rowgroup"><tr role="row">
            <th role="columnheader" scope="col">站点 / 版本</th><th role="columnheader" scope="col">时间口径</th><th role="columnheader" scope="col">币种</th><th role="columnheader" scope="col">生效 / 创建时间</th><th role="columnheader" scope="col">变更原因</th>
          </tr></thead><tbody role="rowgroup">{configs.map(config => <tr role="row" key={config.id}>
            <td role="cell"><div className={css.identity}><strong>{config.site_display_name} · v{config.version_number}</strong><code>{config.site_code} · #{config.site_id}</code><StatusBadge label={config.is_current ? "当前版本" : "历史版本"} tone={config.is_current ? "good" : "quiet"} /></div></td>
            <td role="cell"><div className={css.times}><span>源 · {config.source_timezone}</span><span>统计 · {config.reporting_timezone}</span></div></td>
            <td role="cell"><span className={css.mobileLabel} aria-hidden="true">币种 · </span>{config.currency_code}</td>
            <td role="cell"><div className={css.times}><time dateTime={config.effective_at}>生效 · {timestamp(config.effective_at)}</time><time dateTime={config.created_at}>创建 · {timestamp(config.created_at)}</time></div></td>
            <td role="cell"><span className={css.mobileLabel} aria-hidden="true">变更原因 · </span>{config.change_reason ?? "未填写变更原因"}</td>
          </tr>)}</tbody></Table>}
      </section>
    </>}
  </section>;
}
