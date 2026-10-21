import { useId } from "react";
import { ArrowRight, Clock3 } from "lucide-react";
import { useLocation } from "react-router-dom";
import { LinkButton, StatusBadge } from "../../design-system";
import styles from "./CatalogPendingItems.module.css";

import type { CatalogPendingItem } from "./catalogApi";

import { useCatalogNavigation } from "./CatalogNavigationContext";

const STATUS_LABELS: Record<CatalogPendingItem["status"], string> = {
  needs_attention: "待确认",
  validated: "已校验",
  ready_for_approval: "待批准",
};

export function CatalogPendingItems({ canReview, items }: { canReview: boolean; items: CatalogPendingItem[] }) {
  const titleId = useId();
  const location = useLocation();
  const { setReviewReturn } = useCatalogNavigation();
  if (items.length === 0) return null;
  return <section aria-labelledby={titleId} className={styles.panel}>
    <div className={styles.heading}>
      <div><p className={styles.kicker}><Clock3 aria-hidden="true" />待处理项</p><h3 id={titleId}>新变体与 Seller SKU 候选</h3><p>这些内容仍在草稿中，批准后才会写入当前商品主档。</p></div>
      <StatusBadge tone="quiet" label={`${items.length} 个审核批次`} />
    </div>
    <ul>
      {items.map((item) => <li key={item.import_id} aria-label={`审核批次 #${item.import_id}`} className={styles.item}>
        <header className={styles.itemHeading}><strong>审核批次 #{item.import_id}</strong><StatusBadge tone={item.status === "needs_attention" ? "warn" : "quiet"} label={STATUS_LABELS[item.status]} /></header>
        <div className={styles.counts}><span>新增变体 <strong>{item.variant_count}</strong></span><span>Seller SKU <strong>{item.seller_sku_count}</strong></span><span>审核修订 <strong>{item.workflow_revision}</strong></span></div>
        <div className={styles.previews}><span>Seller SKU 预览</span>{item.seller_sku_previews.length > 0 ? <ul>{item.seller_sku_previews.map((preview, index) => <li key={index}><code>{preview}</code></li>)}</ul> : <p>当前批次未提供 Seller SKU 预览。</p>}</div>
        <footer>{canReview ? <LinkButton icon={<ArrowRight />} onClick={() => setReviewReturn(location.pathname)} to={item.review_path}>进入审核</LinkButton> : <span className={styles.readonly}>由数据管理员确认</span>}</footer>
      </li>)}
    </ul>
  </section>;
}
