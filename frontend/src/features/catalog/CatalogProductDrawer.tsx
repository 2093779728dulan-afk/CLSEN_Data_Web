import { useEffect, useState } from "react";
import { ContentReveal, Dialog, EmptyState, ErrorState, Button, LinkButton, Skeleton, StatusBadge, Table } from "../../design-system";
import { getCatalogStyle, type CatalogStyle } from "./catalogApi";
import { catalogReadError } from "./catalogReadError";
import { catalogStatusDisplay } from "./catalogTypes";
import styles from "./CatalogProductDrawer.module.css";

export type CatalogStyleLoader = typeof getCatalogStyle;
type Detail = Awaited<ReturnType<CatalogStyleLoader>>;

/** Read-only quick view: no SKU reveal, evidence expansion or editing requests. */
export function CatalogProductDrawer({ item, open, onOpenChange, onOpenStyle, loadStyle = getCatalogStyle }: {
  item: CatalogStyle; open: boolean; onOpenChange: (open: boolean) => void;
  onOpenStyle: () => void; loadStyle?: CatalogStyleLoader;
}) {
  const [detail, setDetail] = useState<Detail>();
  const [failure, setFailure] = useState<ReturnType<typeof catalogReadError>>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!open) return;
    let active = true;
    void loadStyle(item.style_id).then(value => { if (active) setDetail(value); }).catch((reason: unknown) => {
      if (active) { setDetail(undefined); setFailure(catalogReadError(reason, "商品详情读取未完成，请重试。")); }
    });
    return () => { active = false; };
  }, [open, item.style_id, loadStyle, attempt]);
  const status = detail ? catalogStatusDisplay(detail.style.status) : undefined;
  const retry = () => { setFailure(undefined); setDetail(undefined); setAttempt(value => value + 1); };
  return <Dialog open={open} onOpenChange={onOpenChange} presentation="drawer" closeLabel="关闭商品快速查看" title="商品快速查看" eyebrow={item.style_code} description="快速核对基础信息和实际变体，关闭后继续当前列表。">
    <div className={styles.body}>
      {failure ? <ErrorState title="商品详情读取未完成" description={failure.message} action={failure.retry ? <Button onClick={retry}>重新读取详情</Button> : undefined} />
        : !detail ? <div role="status" aria-label="正在读取商品详情"><Skeleton lines={6} /></div>
        : <ContentReveal className={styles.details}>
          <div className={styles.identity}><StatusBadge label={status!.label} tone={status!.tone} /><h3>{detail.style.standard_name}</h3><p>{detail.style.category_name || "未分类"}</p><small>STYLE #{detail.style.style_id} · 商品修订 {detail.style.revision}</small></div>
          <dl className={styles.metrics}><div><dt>实际变体</dt><dd>{detail.style.variant_count}</dd></div><div><dt>Seller SKU</dt><dd>{detail.style.seller_sku_count}</dd></div><div><dt>来源报告</dt><dd>{detail.style.source_summary.source_report_count}</dd></div><div><dt>观察记录</dt><dd>{detail.style.source_summary.observation_count}</dd></div></dl>
          <section><h4>实际变体</h4>{detail.skus.length ? <Table className={styles.variantTable} aria-label="商品快速查看变体"><thead><tr><th scope="col">内部展示 SKU</th><th scope="col">颜色 / 尺码</th><th scope="col">状态</th></tr></thead><tbody>{detail.skus.map(sku => { const state = catalogStatusDisplay(sku.status); return <tr key={sku.sku_id}><td>{sku.internal_display_sku}</td><td>{sku.standard_color} / {sku.standard_size}</td><td><StatusBadge label={state.label} tone={state.tone} /></td></tr>; })}</tbody></Table> : <EmptyState title="暂无实际变体" description="当前商品尚未记录已确认的颜色与尺码变体。" />}</section>
          <p className={styles.note}>来源观察：{detail.style.source_summary.first_seen_date ?? "暂无日期"} 至 {detail.style.source_summary.latest_seen_date ?? "暂无日期"}。销售别名与详细来源请查看完整商品卡。</p>
        </ContentReveal>}
      <footer className={styles.footer}><Button onClick={() => onOpenChange(false)} variant="quiet">返回列表</Button>{detail && !failure && <LinkButton to={`/catalog/styles/${item.style_id}`} onClick={onOpenStyle} variant="primary">打开完整商品卡</LinkButton>}</footer>
    </div>
  </Dialog>;
}
