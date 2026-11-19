import { Check, Info, Plus, Trash2 } from "lucide-react";
import type { ReactNode, RefObject } from "react";
import { Button, Dialog, FormField, Input, StatusMessage, Table } from "../../design-system";
import { CurrentStockState, MovementSkuSelect, StockImpact, type QualityBalance } from "./StockMovementFields";
import type { QualityPreview } from "./QualityMovementWizard";
import { type Sku, units } from "./types";
import styles from "./QualityMovementWizard.module.css";
import fields from "./StockMovementFields.module.css";

export type OperationLine = { sku_id: string; quality: string; units: string; purpose: string; borrower?: string; borrow_purpose?: string; due_on?: string; loan_id?: string; evidence?: string; counted_on?: string };
export type OperationLoan = { id: string; borrower: string; outstanding_units: string; is_active?: boolean };
export function StockOperationWizard({ countEditor, importReview, mode, step, lines, skus, balanceFor, loanFor, scopeLabel, inventoryState, refreshInventory, loansReady, loansValid, date, reason, dirty, draftId, preview, busy, unknown, feedback, formRef, quantityError, change, changeDate, changeReason, add, remove, go, advance, previewAgain, confirm, close }: {
  countEditor?: ReactNode; importReview?: ReactNode; mode: "count" | "borrow" | "return"; step: number; lines: OperationLine[]; skus: Sku[]; balanceFor: (line: OperationLine) => QualityBalance | undefined; loanFor: (line: OperationLine) => OperationLoan | undefined;
  scopeLabel: string; inventoryState: "ready" | "loading" | "error"; refreshInventory: () => void; loansReady: boolean; loansValid: boolean; date: string; reason: string; dirty: boolean; draftId?: string; preview?: QualityPreview; busy: boolean; unknown: boolean; feedback: ReactNode;
  formRef: RefObject<HTMLFormElement | null>; quantityError: (line: OperationLine) => string | undefined; change: (index: number, key: keyof OperationLine, value: string) => void; changeDate: (value: string) => void; changeReason: (value: string) => void;
  add: () => void; remove: (index: number) => void; go: (step: number) => void; advance: () => void; previewAgain: () => void; confirm: () => void; close: () => void;
}) {
  const counting = mode === "count", returning = mode === "return";
  const action = counting ? "盘点" : returning ? "归还" : "借出";
  const qualities: Record<string, string> = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
  const steps = [counting ? "填写盘点明细" : returning ? "核对原借出" : "选择商品", counting ? "填写实盘总数" : `填写${action}详情`, "日期与依据", "核对并确认"];
  const label = (line: OperationLine) => { const sku = skus.find(item => item.sku_id === line.sku_id); return sku?.style_code && sku.standard_color && sku.standard_size ? `${sku.style_code} · ${sku.standard_color} / ${sku.standard_size}` : sku?.label || "请选择商品"; };
  const amount = (value: string) => /^\d+$/.test(value) ? units(value) : value || "未填";
  const summaries = [lines.map(label).join("、"), lines.map(line => `${qualities[line.quality] || "状态待选"} · ${amount(line.units)}件`).join("；"), date, `确认本次${action}`];
  return <Dialog open title={`登记${action}`} description={scopeLabel} closeLabel={`关闭${action}登记`} size="large" closeOnOutsideClick={false} dismissDisabled={busy || unknown} contentClassName={styles.dialog} onOpenChange={open => { if (!open) close(); }}>
    <form ref={formRef} className={styles.form} onSubmit={event => { event.preventDefault(); if (step < 3) advance(); }}>
      <div className={styles.layout}>
        <aside className={styles.rail}><ol aria-label="登记步骤">{steps.map((title, index) => counting && index===1 ? null : <li key={title} aria-current={step === index ? "step" : undefined} data-complete={index < step}><Button variant="quiet" disabled={busy || unknown || index > step} onClick={() => go(index)}><span className={styles.marker}>{index < step ? <Check size={16} aria-hidden="true" /> : index + 1}</span><span><strong>{title}</strong><small>{summaries[index]}</small>{index < step && <span className={styles.edit}>修改</span>}</span></Button></li>)}</ol><div className={styles.context}><span>本次操作的商品</span>{lines.map((line, index) => <div key={index}><strong>{label(line)}</strong><small>{counting ? "实盘总数" : `本次${action}`} {amount(line.units)}件</small></div>)}</div></aside>
        <main className={styles.main} aria-label={`${action}登记当前步骤`}>
          <header className={styles.stepHeader}><h2>{step === 3 ? `请核对本次${action}` : steps[step]}</h2>{step < 2 && <Button variant="secondary" disabled={busy || unknown || inventoryState === "loading"} onClick={refreshInventory}>{inventoryState === "loading" ? "正在读取库存…" : "刷新库存"}</Button>}</header>
          <p className={styles.lead}>{counting ? "填写所选状态的实盘总数，可填0；不要填写增减差额。" : returning ? "沿原借出分批归还；待检归还只增加在库，不直接增加可发。" : "借出会减少当前在库和可发，并生成未还记录；预计归还不等于当前库存。"}</p>
          <fieldset disabled={busy || unknown} className={`${styles.fields} ${fields.workflow}`}>
            {counting && step < 2 && countEditor}
            {!counting && step < 2 && <>{lines.map((line, index) => { const loan = loanFor(line); return <section className={styles.line} key={index} aria-label={`操作明细${index + 1}`}>
              {step === 0 ? <div className={fields.productFields}><MovementSkuSelect value={line.sku_id} skus={skus} locked={returning} onChange={value => change(index, "sku_id", value)} /></div> : <p className={styles.productName}>{label(line)}</p>}
              {returning && <StatusMessage kind={loan ? "info" : "warning"} title={loan ? `原借出${loan.id} · ${loan.borrower}` : loansReady ? "原借出不存在、已停用或不属于当前范围" : "正在核对原借出"}>{loan && `未还${units(loan.outstanding_units)}件；本次只登记实际收到的部分。`}</StatusMessage>}
              {line.sku_id && <CurrentStockState selectionLabel={counting ? "本次盘点" : returning ? "归还状态" : "本次来源"} balance={balanceFor(line)} quality={line.quality} inventoryState={inventoryState} />}
              {step === 1 && <div className={fields.changeFields}>
                <FormField label={counting ? "盘点货品状态" : returning ? "归还货品状态" : "借出货品状态"} required><select required value={line.quality} onChange={event => change(index, "quality", event.target.value)}><option value="">选择实际货品状态</option>{Object.entries(qualities).filter(([value]) => mode !== "borrow" || value === "QUALIFIED").map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select></FormField>
                <FormField label={counting ? "实盘总数" : `本次${action}件数`} required error={quantityError(line)} hint={counting ? "实际清点的总数，不是增减数量；0表示明确没有。" : returning ? "不能超过原借出未还量；按实物状态归还。" : "按当前可发量核对，同商品多行合计不能重复使用余额。"}><Input required inputMode="numeric" pattern={counting ? "0|[1-9][0-9]*" : "[1-9][0-9]*"} value={line.units} onChange={event => change(index, "units", event.target.value)} /></FormField>
                {mode === "borrow" && <><FormField label="实际借用人/对象" required><Input required maxLength={255} value={line.borrower || ""} onChange={event => change(index, "borrower", event.target.value)} /></FormField><FormField label="借用用途（可选）"><Input maxLength={255} value={line.borrow_purpose || ""} onChange={event => change(index, "borrow_purpose", event.target.value)} /></FormField><FormField label="约定归还日期（可留空）"><Input type="date" value={line.due_on || ""} onChange={event => change(index, "due_on", event.target.value)} /></FormField></>}
              </div>}
              {step === 0 && !returning && lines.length > 1 && <Button variant="quiet" icon={<Trash2 />} onClick={() => remove(index)}>移除商品{index + 1}</Button>}
            </section>; })}{step === 0 && !returning && <Button variant="secondary" icon={<Plus />} onClick={add}>增加商品</Button>}</>}
            {step === 2 && <div className={styles.evidence}><FormField label={counting ? "实盘截止日期" : "实际发生日期"} required hint={counting ? "本单各行以同一截止日期清点；旧盘点不能覆盖后续收发。" : undefined}><Input required type="date" value={date} onChange={event => changeDate(event.target.value)} /></FormField><FormField label="来源依据/更正原因" required><textarea required rows={3} maxLength={2000} value={reason} onChange={event => changeReason(event.target.value)} /></FormField>{counting && lines.map((line, index) => <FormField key={index} label={`盘点证据${lines.length > 1 ? index + 1 : ""}`} required hint={label(line)}><Input required maxLength={2000} value={line.evidence || ""} onChange={event => change(index, "evidence", event.target.value)} /></FormField>)}</div>}
            {step === 3 && <>{counting && importReview}<dl className={styles.summary}><div><dt>仓库及货主</dt><dd>{scopeLabel}</dd></div><div><dt>日期</dt><dd>{date}</dd></div><div><dt>依据</dt><dd>{reason}</dd></div></dl><Table title="本次操作明细"><thead><tr><th>商品</th><th>货品状态</th><th>{counting ? "实盘总数" : `本次${action}`}</th><th>{counting ? "盘点证据" : returning ? "原借出" : "借用人／归还日期"}</th></tr></thead><tbody>{lines.map((line, index) => <tr key={index}><td>{label(line)}</td><td>{qualities[line.quality]}</td><td>{amount(line.units)}件</td><td>{counting ? line.evidence : returning ? `借出${line.loan_id} · ${loanFor(line)?.borrower || "待核"}` : `${line.borrower} · ${line.due_on || "未定"}`}</td></tr>)}</tbody></Table>
              {preview && !dirty ? <><StockImpact impacts={preview.impacts} skuName={id => label(lines.find(line => line.sku_id === id) || { sku_id: id, units: "", quality: "", purpose: "" })} warehouseName={() => scopeLabel} /><StatusMessage kind="info" title="草稿已保存，尚未改变库存">核对库存影响后单独确认；返回修改后需重新保存、预览。</StatusMessage></> : <StatusMessage kind="info" title={busy ? "正在准备库存预览" : "尚未取得可确认的库存预览"}>草稿{draftId ? ` ${draftId}` : ""}未过账。核实后才能确认。</StatusMessage>}
            </>}
          </fieldset>{feedback}
        </main>
      </div>
      <footer className={styles.footer}><span><Info size={16} aria-hidden="true" />保存草稿不改变库存，确认后才生效。</span><div><Button variant="secondary" disabled={busy || unknown} onClick={step === 0 ? close : () => go(counting ? step===3 ? 2 : 0 : step === 3 ? 1 : step - 1)}>{step === 0 ? "取消" : step === 3 ? "返回修改" : "上一步"}</Button>{step < 3 ? <Button variant="primary" type="submit" loading={busy} disabled={unknown || (returning && !loansValid)}>{step === 2 ? "保存草稿并核对" : "下一步"}</Button> : preview && !dirty ? <Button variant="primary" disabled={busy || unknown} onClick={confirm}>{`确认本次${action}`}</Button> : <Button variant="primary" loading={busy} disabled={unknown || !draftId} onClick={previewAgain}>重新预览</Button>}</div></footer>
    </form>
  </Dialog>;
}
