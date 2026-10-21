import { Info } from "lucide-react";
import { useState } from "react";
import { Button, Dialog } from "../../design-system";
import helpCss from "./LedgerMetricHelp.module.css";

export type LedgerHelpKey = "identity" | "variants" | "units" | "sales" | "returns" | "sessions" | "conversion" | "average";
const definitions: Record<LedgerHelpKey, { title: string; source: string; formula: string; rule: string }> = {
  identity: { title: "款式", source: "所选事实口径对应的已批准商品目录。", formula: "以稳定款式身份归集已映射的 SKU；名称和款号来自商品主档。", rule: "未匹配来源不会自动归入某个款式，可在下方覆盖与对账区域查看。" },
  variants: { title: "实际变体", source: "本次查询使用的目录版本中的 SKU 成员。", formula: "SKU、颜色和尺码分别去重计数。", rule: "表示目录中的变体数量，不是期间有销量的变体数；不能用颜色数乘尺码数推算 SKU 数。" },
  units: { title: "销量", source: "已发布经营报告的订购商品件数。", formula: "按 SKU 映射到款式后求和，单位：件。", rule: "不是订单数，也没有扣除退货；无报表与观测值为零分别显示。" },
  sales: { title: "销售额与占比", source: "已发布经营报告的订购商品销售额。本次美国站试用金额为 US$。", formula: "销售额按款式汇总；占比 = 该款销售额 ÷ 当前日期、搜索和事实口径下全部匹配款式的销售额。", rule: "分母在分页前计算，不包含未映射款式的金额。分母为零或不可用时显示 —。销售额不是净收入或利润，不额外扣除退款、成本和费用。" },
  returns: { title: "本期退货量与同期退销比", source: "已发布退货报告，按 SKU 映射及适用的退货去重决策归集。", formula: "本期退货量按款式汇总；同期退销比 = 本期退货量 ÷ 本期销量。", rule: "退货可能来自此前订单，因此不是订单退货率，也不代表退款金额或利润损失。比值可能超过 100%；销量为零或指标不可计算时显示 —。" },
  sessions: { title: "会话", source: "已发布经营报告的会话字段。", formula: "按已映射款式汇总报告中的会话数。", rule: "不是去重访客数或订单数；按报告口径累加，不能理解为跨 SKU、跨天去重的人数。" },
  conversion: { title: "转化率", source: "同一范围内的经营报告销量和会话。", formula: "汇总销量 ÷ 汇总会话 × 100%，显示两位小数；不平均各行转化率。", rule: "是件数与会话的比率，不是下单人数占比。会话为零时显示分母为 0；没有可用报告时显示无报表。" },
  average: { title: "平均单价", source: "同一款式、同一查询范围的销售额和销量。", formula: "销售额 ÷ 销量，单位：US$/件，显示两位小数。", rule: "不是挂牌价或扣除退款后的净单价；销量为零或数据不可用时显示 —。" },
};

export function LedgerMetricHelp({ metric, from, to, returnBasis, factBasis, catalogVersion }: {
  metric: LedgerHelpKey; from: string; to: string; returnBasis: string; factBasis: string; catalogVersion: number;
}) {
  const [open, setOpen] = useState(false);
  const help = definitions[metric];
  return <>
    <Button variant="quiet" type="button" aria-label={`${help.title}说明`} aria-haspopup="dialog" onClick={(event) => { event.currentTarget.focus(); setOpen(true); }}><Info size={14} aria-hidden="true" /></Button>
    <Dialog open={open} onOpenChange={setOpen} contentClassName={helpCss.dialog} title={help.title} closeLabel="关闭指标说明" eyebrow="指标说明" description="了解这个数字从哪里来，以及如何使用。">
      <div className={helpCss.body}>
        <section className={helpCss.source}><h3>数据来源</h3><p>{help.source}</p></section>
        <section className={helpCss.formula}><h3>计算方式</h3><p>{help.formula}</p></section>
        <section className={helpCss.scope} aria-label="当前统计范围">
          <h3>当前范围</h3>
          <div className={helpCss.context}><span>{from} — {to}</span><span>目录 V{catalogVersion}</span><span>{factBasis === "current" ? "当前事实" : "目录快照"}</span></div>
          <p>{metric === "returns" ? `退货按${returnBasis === "event_date" ? "事件日期" : "报表日期"}筛选。同期销量仍按经营报表日期统计。` : metric === "identity" || metric === "variants" ? "身份信息取自该目录版本。" : "经营指标按报表日期统计。"}</p>
        </section>
        <section className={helpCss.rules}><h3>如何理解这个指标</h3><ul>{help.rule.split("。").filter(Boolean).map((sentence) => <li key={sentence}>{sentence}。</li>)}</ul></section>
        <aside className={helpCss.note}><Info size={16} aria-hidden="true" /><p>报告不完整时会提示“部分数据”，数值仅反映已发布数据。来源或映射错误仍需审核纠正。</p></aside>
      </div>
    </Dialog>
  </>;
}
