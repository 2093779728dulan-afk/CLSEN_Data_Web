import { useState, type FormEvent } from "react";
import { Eye, EyeOff, FileSpreadsheet, ListChecks, LockKeyhole, Send } from "lucide-react";
import { Button, ErrorState, FormField, Input, Skeleton, StatusBadge, StatusMessage } from "../design-system";
import css from "./SessionEntryView.module.css";

type LoginProps = {
  username: string;
  password: string;
  busy: boolean;
  error?: string;
  onUsernameChange: (value: string) => void;
  onPasswordChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
};

function Brand() {
  return <div className={css.brand}><span aria-hidden="true">CL</span><div><strong>CLSEN</strong><small>每日数据核验台</small></div></div>;
}

/** Uses the existing shadcn-derived form controls and project semantic tokens. */
export function LoginView({ username, password, busy, error, onUsernameChange, onPasswordChange, onSubmit }: LoginProps) {
  const [passwordVisible, setPasswordVisible] = useState(false);
  return <main className={css.page} id="main-content">
    <div className={css.layout}>
      <section aria-labelledby="login-title" className={css.introduction}>
        <Brand /><StatusBadge label="数据审核工作台" tone="quiet" />
        <h1 id="login-title">从原表开始，确认后再发布。</h1>
        <p>使用你的系统账号进入每日数据审核与已发布看板。</p>
        <ol className={css.workflow} aria-label="数据处理流程">
          <li><FileSpreadsheet aria-hidden="true" /><div><strong>导入原表</strong><span>保留来源，按报告日期整理。</span></div></li>
          <li><ListChecks aria-hidden="true" /><div><strong>核对与确认</strong><span>处理差异，保留每次修订。</span></div></li>
          <li><Send aria-hidden="true" /><div><strong>发布后查看</strong><span>已确认的数据进入经营看板。</span></div></li>
        </ol>
      </section>
      <section aria-labelledby="login-form-title" className={css.card}>
        <header className={css.heading}><LockKeyhole aria-hidden="true" /><div><h2 id="login-form-title">登录工作台</h2><p>使用已有账号继续。</p></div></header>
        <form aria-label="登录工作台" className={css.form} onSubmit={onSubmit}>
          <fieldset disabled={busy} className={css.fields}>
            <legend className={css.srOnly}>登录信息</legend>
            <FormField label="账号" required><Input autoCapitalize="none" autoComplete="username" spellCheck={false} required value={username} onChange={event => onUsernameChange(event.target.value)} /></FormField>
            <div className={css.passwordField}>
              <FormField label="密码" required><Input id="login-password" autoComplete="current-password" required type={passwordVisible ? "text" : "password"} value={password} onChange={event => onPasswordChange(event.target.value)} /></FormField>
              <Button aria-controls="login-password" aria-pressed={passwordVisible} aria-label={passwordVisible ? "隐藏密码" : "显示密码"} icon={passwordVisible ? <EyeOff /> : <Eye />} onClick={() => setPasswordVisible(visible => !visible)} variant="quiet">{passwordVisible ? "隐藏" : "显示"}</Button>
            </div>
          </fieldset>
          {error && <StatusMessage kind="danger" title="无法登录">{error}</StatusMessage>}
          <Button loading={busy} loadingLabel="正在登录…" type="submit" variant="primary">登录工作台</Button>
        </form>
        <footer className={css.footer}><p>账号权限决定可访问的数据与操作。</p><p>无法登录或需要账号时，请联系系统管理员。</p></footer>
      </section>
    </div>
  </main>;
}

type StateProps = { message?: string; error?: string; onRetry?: () => void };
export function SessionStateView({ message = "正在连接数据核验台…", error, onRetry }: StateProps) {
  return <main className={css.page} id="main-content"><section className={`${css.card} ${css.stateCard}`} aria-label={error ? "站点配置读取状态" : "会话加载状态"}>
    <Brand />
    {error ? <ErrorState title="站点配置不可用" description={error} action={<Button onClick={onRetry} variant="primary">重新读取站点配置</Button>} />
      : <div role="status" aria-label={message} className={css.loading}><h1>{message}</h1><p>就绪后会自动进入当前页面。</p><Skeleton height={44} /><Skeleton lines={2} /></div>}
  </section></main>;
}
