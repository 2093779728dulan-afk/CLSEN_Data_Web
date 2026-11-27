import { Disclosure } from "../../design-system";
import { Link } from "react-router-dom";
import { ArrowLeft, ArrowRight, FileSearch, ScanSearch } from "lucide-react";
import { Button, EmptyState, LinkButton, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import { CatalogPendingItems } from "./CatalogPendingItems";
import { CatalogReadError } from "./CatalogReadFailure";
import type { catalogReadError } from "./catalogReadError";
import type { CatalogPendingItem, CatalogStyle, CatalogUnmatchedResponse, CatalogUnmatchedItem } from "./catalogApi";
import { catalogNameDisplay } from "./catalogTypes";
import styles from "./CatalogUnmatchedView.module.css";
export type PendingStyle = { style: CatalogStyle; items: CatalogPendingItem[] };

function money(values: Array<{ currency_code: string; value: string }>): string {
  if (!values.length) return "—";
  return values.map((item) => `${item.currency_code === "USD" ? "US$" : `${item.currency_code} `}${Number(item.value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`).join(" · ");
}

export function CatalogUnmatchedView({ unmatched, pending, pendingError, onRetry, onOpenStyle, page, returnBasis, returnTo, maintenancePath, changePage, showPending = true, onSelect }: {
  onSelect?: (item: CatalogUnmatchedItem) => void; showPending?: boolean; unmatched?: CatalogUnmatchedResponse; pending?: PendingStyle[]; pendingError?: ReturnType<typeof catalogReadError>;
  onRetry: () => void; onOpenStyle: () => void; page: number; returnBasis: "report_date" | "event_date"; returnTo?: string; maintenancePath: string;
  changePage: (page: number) => void;
}) {
  const returnLink = <LinkButton variant="quiet" icon={<ArrowLeft />} to={returnTo ?? "/products"}>返回产品分析</LinkButton>;
  if (!unmatched) return <div className={styles.stack}>{returnLink}<section className={styles.loading} aria-label="待归属来源核对" aria-busy="true"><ScanSearch aria-hidden="true" /><p role="status">正在核对当前发布事实与商品归属…</p><Skeleton lines={4} /></section></div>;
  const noPublicationEvidence = unmatched.baseline.publication_refs.length === 0 && unmatched.total_items === 0 && unmatched.impact.business_fact_rows === 0 && unmatched.impact.return_fact_rows === 0;
  const futureRange = unmatched.range.from_date > unmatched.baseline.consistent_as_of.slice(0, 10);
  const pageCount = Math.max(1, Math.ceil(unmatched.total_items / unmatched.page_size));
  return <div className={styles.stack}>
    {returnLink}
    <section className={styles.panel} aria-label="待归属来源核对">
      <header className={styles.heading}><div><h2>待归属商品</h2></div><ScanSearch aria-hidden="true" /></header>
      <div className={styles.body}>{noPublicationEvidence ? <div className={styles.noEvidence} role="status"><h3>{futureRange ? "所选日期尚未到达" : "当前范围没有可用的发布依据"}</h3><p>{futureRange ? "待归属核对仅包含截至当前日期的有效发布报表。未来日期即使已经发布，也不会进入此次核对，请选择已到达的报告日期。" : "本次查询没有返回范围内发布依据或待归属事实，不能据此判断所有 SKU 已完成归属。请核对报告日期与发布状态。"}</p><LinkButton to={`/review/${unmatched.range.from_date}`}>查看该日发布状态</LinkButton></div> : <dl className={styles.metrics}><div><dt>待归属</dt><dd>{unmatched.total_items}</dd></div><div><dt>少计销量</dt><dd>{unmatched.impact.units.toLocaleString("zh-CN")} 件</dd></div><div><dt>少计销售额</dt><dd className={styles.amount}>{money(unmatched.impact.sales_by_currency)}</dd></div><div><dt>待核退货</dt><dd>{unmatched.impact.return_quantity.toLocaleString("zh-CN")} 件</dd></div></dl>}
      <Disclosure className={styles.evidence}><summary>查询依据</summary><div className={styles.baseline}><span>范围 {unmatched.range.from_date} 至 {unmatched.range.to_date}</span><span>{unmatched.baseline.catalog_version_id ? `目录记录 #${unmatched.baseline.catalog_version_id}` : "目录尚未初始化"}</span><span>当前事实 · 退货按{returnBasis === "event_date" ? "事件日期" : "报表日期"}</span></div><p>仅核对当前有效发布报表；审核批准后才计入对应商品。金额按币种分别汇总，退货量不含待去重记录。</p></Disclosure></div>
    </section>
    {unmatched.impact.unresolved_return_rows > 0 && <StatusMessage kind="warning" title="退货去重尚未完成">另有 {unmatched.impact.unresolved_return_rows} 条退货记录仍待去重判定，未计入上方退货量。</StatusMessage>}
    {!noPublicationEvidence && <section className={styles.panel} aria-label="来源清单">
      <header className={styles.heading}><div><h2>来源清单 <span className={styles.total}>{unmatched.total_items}</span></h2></div><LinkButton icon={<FileSearch />} to={maintenancePath}>多商品批量维护</LinkButton></header>
      <div className={styles.body}>{unmatched.items.length === 0 ? <EmptyState icon={<ScanSearch />} title={page > 1 && unmatched.total_items > 0 ? "本页没有来源记录" : "当前范围没有未归属来源。"} description={page > 1 && unmatched.total_items > 0 ? "可返回上一页查看来源清单；本页为空不代表全部来源已完成归属。" : undefined} /> : <ol className={styles.sources}>
        {unmatched.items.map((item) => <li className={styles.source} key={item.source_identity.seller_sku_match}>
          <div className={styles.sourceHeading}><div className={styles.identity}><strong>{item.preview}</strong><div className={styles.badges}><StatusBadge tone="quiet" label={item.report_types.map((value) => value === "business_report" ? "经营" : "退货").join(" + ")} />{item.is_truncated && <StatusBadge tone="quiet" label="预览已截断" />}{item.is_unsafe && <StatusBadge tone="warn" label="安全预览" />}</div></div><div className={styles.action}>{onSelect && <Button onClick={() => onSelect(item)}>处理本条</Button>}{item.candidate.review_path ? <LinkButton variant="quiet" icon={<ArrowRight />} to={item.candidate.review_path}>{item.candidate.status === "in_review" ? "继续审核" : "查看候选"}</LinkButton> : <StatusBadge tone="quiet" label="尚未生成候选" />}</div></div>
          <dl className={styles.facts}><div><dt>销量影响</dt><dd>{item.business.units} 件 · {money(item.business.sales_by_currency)}</dd></div><div><dt>退货影响</dt><dd>{item.returns.quantity} 件{item.returns.unresolved_rows ? ` · ${item.returns.unresolved_rows} 条待去重` : ""}</dd></div></dl>
          <Disclosure className={styles.recordDetails}><summary>来源记录</summary><dl><dt>首次 / 最近</dt><dd>{item.first_seen_date} / {item.latest_seen_date}</dd></dl></Disclosure>
        </li>)}
      </ol>}
      {(pageCount > 1 || page > 1) && <nav className={styles.pagination} aria-label="来源分页"><Button disabled={page <= 1} onClick={() => changePage(page - 1)}>上一页</Button><span>第 {page} / {pageCount} 页</span><Button disabled={page >= pageCount} onClick={() => changePage(page + 1)}>下一页</Button></nav>}</div>
    </section>}
    {showPending && <section className={styles.panel} aria-label="已有审核候选"><header className={styles.heading}><div><h2>已有审核候选</h2><p>已生效商品的候选独立列出，草稿不会改变正式目录。</p></div></header><div className={styles.body}>
      {pendingError ? <CatalogReadError failure={pendingError} onRetry={() => onRetry()} />
        : !pending ? <p role="status">正在读取已有审核候选，来源清单可以先处理。</p>
        : <><p className={styles.note}>当前有 {pending.length} 款已生效商品存在待审核候选。草稿不会改变正式目录。</p>{pending.length === 0 ? <p className={styles.note}>当前没有关联到已生效商品的审核候选。</p> : pending.map(({ style, items }) => <div className={styles.pending} key={style.style_id}><h3><Link onClick={() => onOpenStyle()} to={`/catalog/styles/${style.style_id}`}>{style.style_code} · {catalogNameDisplay(style.standard_name)}</Link></h3><CatalogPendingItems canReview items={items} /></div>)}</>}</div>
    </section>}
  </div>;
}
