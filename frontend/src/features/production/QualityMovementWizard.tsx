import { Check, Info, Plus, Trash2 } from "lucide-react";
import type { ReactNode, RefObject } from "react";
import { Button, Dialog, FormField, Input, StatusMessage, Table } from "../../design-system";
import { QualityMovementFields, type QualityLine, type QualityBalance, type StockImpacts } from "./StockMovementFields";
import type { Sku } from "./types";
import { units } from "./types";
import styles from "./QualityMovementWizard.module.css";

export type QualityPreview = { preview_hash: string; impacts?: StockImpacts; changes?: { sku_id: string; quality: string; delta_units: string }[] };
type Balance = QualityBalance & { sku_id: string; warehouse_id: string; owner_id: string };
const qualityNames: Record<string, string> = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
const steps = ["选择商品", "填写状态与数量", "日期与依据", "核对并确认"];

export function QualityMovementWizard({ step, lines, skus, balances, warehouse, warehouseName, owner, ownerName, date, reason, dirty, draftId, preview, busy, unknown, feedback, formRef, lineError, quantityError, change, changeDate, changeReason, add, remove, go, advance, previewAgain, confirm, close, inventoryState, refreshInventory }: {
  step: number; lines: QualityLine[]; skus: Sku[]; balances: Balance[]; warehouse: string; warehouseName: string; owner: string; ownerName: string;
  date: string; reason: string; dirty: boolean; draftId?: string; preview?: QualityPreview; busy: boolean; unknown: boolean; feedback: ReactNode;
  inventoryState: "ready" | "loading" | "error"; refreshInventory: () => void;
  formRef: RefObject<HTMLFormElement | null>; lineError: (line: QualityLine) => string | undefined; quantityError: (line: QualityLine) => string | undefined;
  change: (index: number, key: keyof QualityLine, value: string) => void; changeDate: (value: string) => void; changeReason: (value: string) => void;
  add: () => void; remove: (index: number) => void; go: (step: number) => void; advance: () => void; previewAgain: () => void; confirm: () => void; close: () => void;
}) {
  const label = (line: QualityLine) => { const sku = skus.find(item => item.sku_id === line.sku_id); return sku?.style_code && sku.standard_color && sku.standard_size ? `${sku.style_code} · ${sku.standard_color} / ${sku.standard_size}` : sku?.label || "请选择商品"; };
  const count = (value: string) => /^[0-9]+$/.test(value) ? units(value) : value || "0";
  const total = lines.reduce((sum, line) => sum + (/^[0-9]+$/.test(line.units) ? BigInt(line.units) : 0n), 0n);
  const summaries = [lines.map(label).join("、"), lines.map(line => `${qualityNames[line.quality] || "待选择"} → ${qualityNames[line.target_quality || ""] || "待选择"}${line.units ? ` · ${count(line.units)}件` : ""}`).join("；"), date, "确认此次实际变化"];
  const confirmation = lines.length === 1 ? lines[0]!.purpose === "LOCATION" ? `确认移动${count(lines[0]!.units)}件货物库位` : `确认将${count(lines[0]!.units)}件${qualityNames[lines[0]!.quality]}转为${qualityNames[lines[0]!.target_quality || ""]}` : `确认${lines.length}项货品变化`;
  return <Dialog open onOpenChange={open => { if (!open) close(); }} title="登记质量变化" description={`${warehouseName} · ${ownerName}`} closeLabel="关闭质量登记" size="large" closeOnOutsideClick={false} dismissDisabled={busy || unknown} contentClassName={styles.dialog}>
    <form ref={formRef} className={styles.form} onSubmit={event => { event.preventDefault(); if (step < 3) advance(); }}>
      <div className={styles.layout}>
        <aside className={styles.rail}>
          <ol aria-label="登记步骤">{steps.map((title, index) => <li key={title} aria-current={step === index ? "step" : undefined} data-complete={index < step}><Button variant="quiet" disabled={busy || unknown || index > step} onClick={() => go(index)}><span className={styles.marker}>{index < step ? <Check size={16} aria-hidden="true" /> : index + 1}</span><span><strong>{title}</strong><small>{summaries[index]}</small>{index < step && <span className={styles.edit}>修改</span>}</span></Button></li>)}</ol>
          <div className={styles.context}><span>本次操作的商品</span>{lines.map((line, index) => { const sku = skus.find(item => item.sku_id === line.sku_id); return <div key={index}><strong>{sku?.style_code || sku?.code || (line.sku_id ? label(line) : "尚未选择")}</strong>{sku?.standard_color && <small>{sku.standard_color} · {sku.standard_size}</small>}</div>; })}<p>已填写 <strong>{units(total.toString())}件</strong></p></div>
        </aside>
        <main className={styles.main} aria-label="质量登记当前步骤">
          <header className={styles.stepHeader}><h2>{step === 3 ? "请核对这次质量变化" : steps[step]}</h2>{step < 2 && <Button variant="secondary" disabled={busy || unknown || inventoryState === "loading"} onClick={refreshInventory}>{inventoryState === "loading" ? "正在读取库存…" : "刷新库存"}</Button>}</header>
          <p className={styles.lead}>{step === 0 ? "核对款号、颜色和尺码，可增加同次处理的其他商品。" : step === 1 ? "只填写本次实际处理的数量；质量处理不需要库位。" : step === 2 ? "填写实际发生日期和处理依据，下一步保存草稿并生成库存预览。" : "确认前请检查以下信息和库存变化，确保无误。"}</p>
          <fieldset disabled={busy || unknown} className={styles.fields}>
            {step < 2 && <>{lines.map((line, index) => <section key={index} className={styles.line} aria-label={`变动明细${index + 1}`}>{lines.length > 1 && <h3>商品 {index + 1}</h3>}{step === 1 && <p className={styles.productName}>{label(line)}</p>}<QualityMovementFields inventoryState={inventoryState} part={step === 0 ? "product" : "change"} line={line} skus={skus} locked={false} balance={balances.find(balance => balance.sku_id === line.sku_id && balance.warehouse_id === warehouse && balance.owner_id === owner)} error={lineError(line)} quantityError={quantityError(line)} onChange={(key, value) => change(index, key, value)} />{step === 0 && lines.length > 1 && <Button variant="quiet" icon={<Trash2 />} onClick={() => remove(index)}>移除商品{index + 1}</Button>}</section>)}{step === 0 && <Button variant="secondary" icon={<Plus />} onClick={add}>增加商品</Button>}</>}
            {step === 2 && <div className={styles.evidence}><FormField label="实际发生日期" required><Input required type="date" value={date} onChange={event => changeDate(event.target.value)} /></FormField><FormField label="来源依据/更正原因" required><textarea required rows={4} maxLength={2000} value={reason} placeholder="填写检验记录、实际损坏或移库依据" onChange={event => changeReason(event.target.value)} /></FormField></div>}
            {step === 3 && <><dl className={styles.summary}><div><dt>状态变化</dt><dd>{summaries[1]}</dd></div><div><dt>商品</dt><dd>{lines.map(label).join("、")}</dd></div><div><dt>日期</dt><dd>{date}</dd></div><div><dt>变更依据</dt><dd>{reason}</dd></div></dl>
              <h3>库存变化预览</h3><p className={styles.lead}>本次只调整质量或位置，不增加或减少实际在库总量。</p>
              {preview && !dirty ? <><Table aria-label="库存变化预览"><thead><tr><th>库存项</th><th>当前</th><th>确认后</th></tr></thead><tbody>{preview.impacts?.flatMap(impact => [["实际在库", impact.on_hand_before, impact.on_hand_after], ["当前可发", impact.free_before, impact.free_after]].map(([title, before, after]) => <tr key={`${impact.sku_id}:${title}`}><th scope="row">{lines.length > 1 && <small>{skus.find(sku => sku.sku_id === impact.sku_id)?.label || impact.sku_id}<br /></small>}{title}</th><td>{before == null ? "待核" : `${units(before)}件`}</td><td data-change={before !== after}><strong>{after == null ? "缺口待处理" : `${units(after)}件`}</strong></td></tr>))}</tbody></Table>{preview.changes?.length ? <div className={styles.qualityChanges} aria-label="质量数量变化">{preview.changes.map((item, index) => <span key={index}>{lines.length > 1 ? `${skus.find(sku => sku.sku_id === item.sku_id)?.label || item.sku_id} · ` : ""}{qualityNames[item.quality] || item.quality} {BigInt(item.delta_units) > 0n ? "+" : ""}{units(item.delta_units)}件</span>)}</div> : null}<StatusMessage kind="info" title="草稿已保存，尚未改变库存">确认后才生效。返回修改后需重新保存、核对预览。</StatusMessage></> : <StatusMessage kind="info" title={busy ? "正在准备库存预览" : "尚未取得可确认的库存预览"}>草稿{draftId ? ` ${draftId}` : ""}未过账；核实预览后才能确认。</StatusMessage>}
            </>}
          </fieldset>
          {feedback}
        </main>
      </div>
      <footer className={styles.footer}><span><Info size={16} aria-hidden="true" />{step === 3 ? "确认后才改变库存，原记录保留。" : "保存草稿不改变库存。"}</span><div>{step === 0 ? <Button variant="secondary" disabled={busy || unknown} onClick={close}>取消</Button> : <Button variant="secondary" disabled={busy || unknown} onClick={() => go(step === 3 ? 1 : step - 1)}>{step === 3 ? "返回修改" : "上一步"}</Button>}{step < 3 ? <Button variant="primary" type="submit" loading={busy} disabled={unknown}>{step === 2 ? "保存草稿并核对" : "下一步"}</Button> : preview && !dirty ? <Button variant="primary" disabled={busy || unknown} onClick={confirm}>{confirmation}</Button> : <Button variant="primary" loading={busy} disabled={unknown || !draftId} onClick={previewAgain}>重新预览</Button>}</div></footer>
    </form>
  </Dialog>;
}
