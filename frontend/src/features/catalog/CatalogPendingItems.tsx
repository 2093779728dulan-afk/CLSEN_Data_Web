import { useId } from "react";
import { ArrowRight, Clock3 } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

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
  return <section aria-labelledby={titleId} className="catalog-pending-items">
    <div className="catalog-pending-items__heading">
      <div><p className="section-kicker">待处理项</p><h3 id={titleId}>新变体与 Seller SKU 候选</h3><p>这些内容仍在草稿中，批准后才会写入当前商品主档。</p></div>
      <span className="catalog-pending-items__count"><Clock3 aria-hidden="true" />{items.length} 个审核批次</span>
    </div>
    <ul>
      {items.map((item) => <li key={item.import_id}>
        <div><span className={`catalog-pending-status catalog-pending-status--${item.status}`}>{STATUS_LABELS[item.status]}</span><strong>审核批次 #{item.import_id}</strong><small>新增变体 {item.variant_count} · Seller SKU {item.seller_sku_count}</small></div>
        {item.seller_sku_previews.length > 0 && <p>{item.seller_sku_previews.join("、")}</p>}
        {canReview ? <Link onClick={() => setReviewReturn(location.pathname)} to={item.review_path}>进入审核<ArrowRight aria-hidden="true" /></Link> : <span className="catalog-pending-items__readonly">由数据管理员确认</span>}
      </li>)}
    </ul>
  </section>;
}
