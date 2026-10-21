import { ArrowLeft, ArrowRight, CircleAlert, ListChecks, RefreshCw } from "lucide-react";
import { Button, LinkButton, StatusBadge } from "../../design-system";
import { CatalogSetup } from "./CatalogSetup";
import { catalogReadError } from "./catalogReadError";
import css from "./CatalogReadFailure.module.css";

type Props = { failure: ReturnType<typeof catalogReadError>; onRetry: () => void };

export function CatalogReadFailurePanel({ failure, onRetry }: Props) {
  const Icon = failure.setup ? ListChecks : CircleAlert;
  return <section className={css.panel} aria-label="目录读取反馈">
    <header className={css.header}>
      <span className={css.icon} aria-hidden="true"><Icon /></span>
      <div className={css.heading}><span className={css.eyebrow}>商品主档 · 读取反馈</span><h2>{failure.setup ? "待处理清单尚未就绪" : "商品主档读取未完成"}</h2></div>
      <StatusBadge tone="warn" label={failure.setup ? "前置未完成" : failure.retry ? "可手动重试" : "需要核对"} />
    </header>
    <div className={css.body}><p className={css.message} role="alert">{failure.message}</p>
      <div className={css.next}><span>下一步</span><p>{failure.setup ? "核对下方准备状态，再由有权限的维护账号完成缺失步骤。" : failure.retry ? "检查连接后，手动重新读取。" : "返回商品主档，核对当前账号权限或查询条件。"}</p></div>
    </div>
    <footer className={css.footer}>
      {failure.setup ? <LinkButton variant="primary" icon={<ArrowRight />} to="/catalog/maintenance">前往批量维护，完成初始化</LinkButton> : failure.retry ? <Button variant="primary" icon={<RefreshCw />} onClick={onRetry}>重新读取</Button> : <LinkButton icon={<ArrowLeft />} to="/catalog">返回商品主档</LinkButton>}
    </footer>
  </section>;
}

export function CatalogReadError({ failure, onRetry }: Props) {
  return <div className="catalog-stack">
    <CatalogReadFailurePanel failure={failure} onRetry={onRetry} />
    {failure.setup && <CatalogSetup />}
  </div>;
}
