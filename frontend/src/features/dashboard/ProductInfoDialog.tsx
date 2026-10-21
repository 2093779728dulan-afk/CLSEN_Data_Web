import styles from "./PublishedDashboard.module.css";
import { useEffect, useState } from "react";

import { requestApi } from "../../api/client";
import type { ProductCardResponse } from "../../api/generated";
import { Dialog } from "../../design-system";

type Props = {
  currencyCode: string;
  from: string;
  onClose: () => void;
  styleCode: string;
  to: string;
};

function currency(value: string, code: string) {
  return new Intl.NumberFormat("zh-CN", {
    currency: code,
    maximumFractionDigits: 2,
    style: "currency",
  }).format(Number(value));
}

function percent(value: string | null) {
  return value === null ? "—" : `${(Number(value) * 100).toFixed(2)}%`;
}

export function ProductInfoDialog({ currencyCode, from, onClose, styleCode, to }: Props) {
  const [data, setData] = useState<ProductCardResponse>();
  const [error, setError] = useState<string>();
  const [reload, setReload] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError(undefined);
    const query = new URLSearchParams({ from, to });
    void requestApi<ProductCardResponse>(
      `/api/dashboard/product-card/${encodeURIComponent(styleCode)}?${query}`,
      { signal: controller.signal },
    )
      .then(setData)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "无法读取商品信息。");
        }
      });
    return () => controller.abort();
  }, [from, reload, styleCode, to]);

  const trendValues = data?.trend.map((point) => Number(point.sales)) ?? [];
  const peakSales = Math.max(0, ...trendValues);
  const maximum = Math.max(1, peakSales);
  const points = data?.trend.map((point, index, all) => {
    const x = all.length <= 1 ? 150 : 12 + (index / (all.length - 1)) * 276;
    const y = 82 - (Number(point.sales) / maximum) * 68;
    return `${x},${y}`;
  }).join(" ");

  return (
    <Dialog
      closeLabel="关闭商品信息"
      description={data?.name_status === "multiple" ? "存在多个变体名称，以下保留各变体原始名称。" : undefined}
      eyebrow={`PRODUCT / ${styleCode}`}
      onOpenChange={(open) => { if (!open) onClose(); }}
      open
      size="large"
      title={data?.name_status === "available" ? data.product_name : `款号 ${styleCode}`}
    >
      {!data && !error && <p className={styles["product-dialog__loading"]} role="status">正在读取当前发布商品信息…</p>}
      {error && <div className={styles["ledger-inline-error"]} role="alert"><p>{error}</p><button onClick={() => setReload((value) => value + 1)} type="button">重试</button></div>}
      {data && <>
        <dl className={styles["product-dialog__metrics"]}>
          <div><dt>本月销售额</dt><dd>{currency(data.summary.sales, currencyCode)}</dd></div>
          <div><dt>订购数</dt><dd>{data.summary.units_ordered.toLocaleString("zh-CN")}</dd></div>
          <div><dt>会话数</dt><dd>{data.summary.sessions.toLocaleString("zh-CN")}</dd></div>
          <div><dt>转化率</dt><dd>{percent(data.summary.conversion_rate)}</dd></div>
          <div><dt>退货数</dt><dd>{data.summary.return_quantity.toLocaleString("zh-CN")}</dd></div>
          <div><dt>有数据天数</dt><dd>{data.summary.published_days} 天</dd></div>
        </dl>

        <section className={styles["product-dialog__trend"]} aria-label="每日销售额趋势">
          <header>
            <div><h3>每日销售额</h3><p>当前发布周期内的日销售变化</p></div>
            <p>峰值 <strong>{currency(String(peakSales), currencyCode)}</strong></p>
          </header>
          <div className={styles["product-dialog__chart"]}>
            <div className={styles["product-dialog__chart-scale"]} aria-hidden="true">
              <span>{currency(String(peakSales), currencyCode)}</span>
              <span>{currency("0", currencyCode)}</span>
            </div>
            <svg role="img" aria-label={`${styleCode} 每日销售额趋势，峰值 ${currency(String(peakSales), currencyCode)}`} viewBox="0 0 300 92">
              <line x1="12" x2="288" y1="14" y2="14" />
              <line x1="12" x2="288" y1="48" y2="48" />
              <line x1="12" x2="288" y1="82" y2="82" />
              {points && <polyline points={points} />}
            </svg>
          </div>
          <div className={styles["product-dialog__chart-dates"]}>
            <span>{data.trend.at(0)?.report_date ?? "—"}</span>
            <span>最近发布 {data.latest_published_date ?? data.trend.at(-1)?.report_date ?? "—"}</span>
          </div>
        </section>

        <section className={styles["product-dialog__variants"]}>
          <header><h3>全部变体</h3><span>{data.variants.length} 个 Seller SKU</span></header>
          <ul>
            {data.variants.map((variant) => <li key={variant.seller_sku}>
              <div className={styles["product-dialog__variant-heading"]}><strong>{variant.seller_sku}</strong><span>{variant.color} / {variant.size}</span></div>
              <p>{variant.product_name ?? "商品名称未维护"}</p>
              <dl>
                <div><dt>ASIN</dt><dd>{variant.asins.join(" · ") || "—"}</dd></div>
                <div><dt>FNSKU</dt><dd>{variant.fnskus.join(" · ") || "—"}</dd></div>
              </dl>
            </li>)}
          </ul>
        </section>
      </>}
    </Dialog>
  );
}
