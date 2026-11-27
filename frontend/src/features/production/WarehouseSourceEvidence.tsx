import { Disclosure } from "../../design-system";
import { useState } from "react";
import { Input, LinkButton, Table } from "../../design-system";
import type { SourceEvidenceLine, WarehouseSource } from "./directoryTypes";
import styles from "./Production.module.css";
import evidenceStyles from "./WarehouseSourceEvidence.module.css";

const amount = (value: string | null | undefined) => value == null ? "待核" : BigInt(value).toLocaleString("zh-CN");

function EvidenceTable({ rows, label }: { rows: SourceEvidenceLine[]; label: string }) {
  const [query, setQuery] = useState("");
  const selected = rows.filter(row => [row.sku, row.reference, row.source].join(" ").toLowerCase().includes(query.trim().toLowerCase()));
  return <>
    <Input type="search" aria-label={`搜索${label}`} placeholder="搜索SKU、货件号或来源行" value={query} onChange={event => setQuery(event.target.value)} />
    <p>{selected.length} 条记录</p>
    <Table aria-label={label}>
      <thead><tr><th>SKU</th><th>数量</th><th>日期 / 货件</th><th>身份 / 来源</th></tr></thead>
      <tbody>{selected.map((row, index) => <tr key={`${row.source}:${index}`}>
        <th scope="row">{row.sku}</th><td>{amount(row.units)}</td>
        <td>{row.date || "日期待核"}<br />{row.reference || ""}</td>
        <td>{row.status}<br />{row.source}{row.asin && <><br />ASIN {row.asin}</>}{row.fnsku && <><br />FNSKU {row.fnsku}</>}</td>
      </tr>)}{!selected.length && <tr><td colSpan={4}>没有匹配记录。</td></tr>}</tbody>
    </Table>
  </>;
}

export function WarehouseSourceEvidence({ source, ledgerReady = false }: { source: WarehouseSource; ledgerReady?: boolean }) {
  const packed = (source.packings || []).reduce((sum, batch) => sum + BigInt(batch.packed_units), 0n);
  const received = (source.receipts || []).reduce((sum, row) => sum + BigInt(row.units || "0"), 0n);
  const pending = (source.packings || []).filter(batch => batch.received_units === null).reduce((sum, batch) => sum + BigInt(batch.packed_units), 0n);
  if (source.kind === "domestic") return <section className={`${styles.panel} ${evidenceStyles.panel}`} aria-label="广州盘点导入资料">
    <h2>{source.stock_date} 广州盘点来源</h2>
    <p>原表明确 {amount(source.explicit_units)} 件，目录唯一对应 {amount(source.matched_units)} 件，尚未入账资料 {amount(source.pending_units)} 件。空白和“/”保留未知。用户已确认明确数量均正常可发。</p>
    {source.deferred_units && <p>22003 的 {amount(source.deferred_units)} 件按用户要求暂缓入账，其余未对应规格继续核对商品资料。</p>}
    <Disclosure><summary>查看原表数量与待核记录</summary><EvidenceTable rows={source.rows || []} label="广州盘点来源明细" /></Disclosure>
  </section>;
  return <section className={`${styles.panel} ${evidenceStyles.panel}`} aria-label="已导入FBA装箱与验收资料">
    <h2>已导入装箱与验收资料</h2>
    <p>{source.packings?.length || 0}批装箱{amount(String(packed))}件，已确认货件接收净{amount(String(received))}件。{ledgerReady ? '已确认验收沿库存事件入账，账面余额见上方库存。' : 'FBA期初、当前在库和可售未知。'}装箱{amount(String(pending))}件的验收证据待补。四批用户已确认发出，实际发货日期与后续验收待补。</p>
    {source.packings?.map(batch => <Disclosure key={batch.filename}>
      <summary>{batch.batch_date} · {batch.boxes}箱 · 装箱{amount(batch.packed_units)}件 · 接收{amount(batch.received_units)}{batch.received_units !== null ? "件" : ""}</summary>
      <p>{batch.filename}。文件日期用于批次标签。</p>
      <p>{batch.reference_id || "验收货件证据待补"} {batch.differences.join("。")}</p>
      <EvidenceTable rows={batch.rows} label={`${batch.batch_date}装箱明细`} />
    </Disclosure>)}
    <Disclosure><summary>已确认货件接收原始流水（{source.receipts?.length || 0}条）</summary>
      <p>负数更正逐行保留，按货件关联范围核对。其余{source.excluded_receipt_rows || 0}条验收记录按用户指定范围保留在原件。</p>
      <EvidenceTable rows={source.receipts || []} label="已确认货件接收流水" />
    </Disclosure>
    {!!source.issues?.length && <Disclosure><summary>资料待核事项</summary>{source.issues.map(issue => <p key={issue}>{issue}</p>)}</Disclosure>}
    <div className={styles.actions}><LinkButton to="/home">查看库存变动总表</LinkButton></div>
  </section>;
}
