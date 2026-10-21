import { useState } from "react";
import { Button, Select } from "../../design-system";
import { SafeSourceRefView } from "../../components/source-reference/SafeSourceRefView";
import type { StyleCardResponse } from "./productAnalyticsTypes";
import { MetricValueView } from "./MetricValueView";
import { decimalStringToScaledBigInt } from "./metricFormatting";
import { averagePrice, returnSalesRatio, salesShare } from "./ledgerInsights";
import css from "./ProductAnalytics.module.css";

export function VariantReviewTable({ response }: { response: StyleCardResponse }) {
  const [color, setColor] = useState("");
  const [size, setSize] = useState("");
  const [sort, setSort] = useState<"sales" | "returns">("sales");
  const colors = [...new Set(response.variants.map(row => row.standard_color))];
  const sizes = [...new Set(response.variants.map(row => row.standard_size))];
  const selectedColor = colors.includes(color) ? color : "";
  const selectedSize = sizes.includes(size) ? size : "";
  const rows = response.variants.filter(row => (!selectedColor || row.standard_color === selectedColor) && (!selectedSize || row.standard_size === selectedSize));
  rows.sort((a, b) => {
    const left = a.metrics[sort]; const right = b.metrics[sort];
    const missing = (value: typeof left) => value.value === null || !["observed", "zero"].includes(value.value_state);
    if (missing(left) !== missing(right)) return missing(left) ? 1 : -1;
    if (!missing(left) && !missing(right)) {
      const x = sort === "sales" ? decimalStringToScaledBigInt(String(left.value), 2) : BigInt(left.value!);
      const y = sort === "sales" ? decimalStringToScaledBigInt(String(right.value), 2) : BigInt(right.value!);
      if (x !== y) return x > y ? -1 : 1;
    }
    return a.sku_id.localeCompare(b.sku_id);
  });
  const total = response.summary.metrics.sales.value;
  return <section className={css["variant-ledger"]} aria-labelledby="variant-title">
    <div className={css["analytics-section-heading"]}><div><p className={css["analytics-eyebrow"]}>VARIANT REVIEW</p><h2 id="variant-title">颜色与尺码经营明细</h2></div><p>显示 {rows.length} / {response.variants.length} 个实际 SKU</p></div>
    <div className={css["analytics-filterbar"]}>
      <Button aria-pressed={sort === "sales"} onClick={() => setSort("sales")}>变体销售贡献</Button>
      <Button aria-pressed={sort === "returns"} onClick={() => setSort("returns")}>变体退货关注</Button>
      <label>筛选颜色<Select value={selectedColor} onChange={event => setColor(event.target.value)}><option value="">全部颜色</option>{colors.map(value => <option key={value} value={value}>{value}</option>)}</Select></label>
      <label>筛选尺码<Select value={selectedSize} onChange={event => setSize(event.target.value)}><option value="">全部尺码</option>{sizes.map(value => <option key={value} value={value}>{value}</option>)}</Select></label>
      {(selectedColor || selectedSize) && <Button onClick={() => { setColor(""); setSize(""); }}>清除变体筛选</Button>}
    </div>
    <p className={css["ledger-basis"]}>按{sort === "sales" ? "销售额" : "本期退货量"}从高到低排列。占比以本款全部变体销售额为分母，颜色和尺码筛选不改变分母；此处筛选仅影响下表。退货按{response.effective_return_basis === "event_date" ? "事件日期" : "报表日期"}统计，同期退销比不是订单退货率。{response.summary.metrics.sales.is_partial && "销售报告不完整，占比仅反映已发布数据。"}</p>
    <div className={css["analytics-table-scroll"]} role="region" aria-label="实际变体指标" tabIndex={0}>
      <table className={`${css["analytics-table"]} ${css["variant-table"]}`}><thead><tr><th>展示 SKU</th><th>颜色</th><th>尺码</th><th>销量</th><th>销售额 US$ / 款内占比</th><th>平均单价 US$</th><th>本期退货量{sort === "returns" && " / 同期退销比"}</th><th>会话</th><th>转化率</th><th>来源别名</th></tr></thead>
        <tbody>{rows.map(row => <tr key={row.sku_id}>
          <th scope="row"><code>{row.internal_display_sku}</code></th><td>{row.standard_color}</td><td>{row.standard_size}</td>
          <td><MetricValueView compact kind="units" metric={row.metrics.units} /></td>
          <td><MetricValueView compact kind="sales" metric={row.metrics.sales} /><small>占比 {salesShare(row.metrics.sales, total === null ? null : String(total))}</small></td>
          <td>{averagePrice(row.metrics.sales, row.metrics.units)}{(row.metrics.sales.is_partial || row.metrics.units.is_partial) && <small>部分数据</small>}</td>
          <td><MetricValueView compact kind="returns" metric={row.metrics.returns} />{sort === "returns" && <small>同期退销比 {returnSalesRatio(row.metrics.returns, row.metrics.units)}{(row.metrics.returns.is_partial || row.metrics.units.is_partial) && " · 部分数据"}</small>}</td>
          <td><MetricValueView compact kind="sessions" metric={row.metrics.sessions} /></td><td><MetricValueView compact percentage kind="conversion" metric={row.metrics.conversion} /></td>
          <td><details><summary>{row.seller_sku_aliases.length} 个来源别名</summary>{row.seller_sku_aliases.map(alias => <SafeSourceRefView key={alias.source_ref_id} source={{digest:alias.sha256,is_truncated:alias.is_truncated,is_unsafe:alias.is_unsafe,preview:alias.preview,source_ref_id:alias.source_ref_id}} />)}</details></td>
        </tr>)}{rows.length === 0 && <tr><td colSpan={10}>没有匹配的实际变体，请调整颜色或尺码筛选。</td></tr>}</tbody>
      </table>
    </div>
  </section>;
}
