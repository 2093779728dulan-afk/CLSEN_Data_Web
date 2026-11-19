import { useState } from "react";
import { Button, FormField, Input, Table } from "../../design-system";
import { type Sku, units } from "./types";
import styles from "./StockMovementFields.module.css";

export function MovementSkuSelect({ value, skus, onChange, locked, error }: {
  value: string; skus: Sku[]; onChange: (value: string) => void; locked: boolean; error?: string;
}) {
  const [query, setQuery] = useState("");
  const [color, setColor] = useState("");
  const selected = skus.find(s => s.sku_id === value);
  const matches = skus.filter(s => s.status === "active" && (!query.trim() || s.label.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())));
  const colors = [...new Set(matches.map(s => s.standard_color).filter((c): c is string => !!c))];
  const choices = matches.filter(s => !color || s.standard_color === color);
  return <>
    {!locked && <FormField label="搜索款号或 SKU" hint="搜索只缩小选项，不会自动选中商品。"><Input type="search" value={query} onChange={e => { setQuery(e.target.value); setColor(""); onChange(""); }} /></FormField>}
    {!locked && colors.length > 1 && <FormField label="筛选颜色"><select value={color} onChange={e => { setColor(e.target.value); onChange(""); }}><option value="">全部匹配颜色</option>{colors.map(c => <option key={c} value={c}>{c}</option>)}</select></FormField>}
    <FormField label="商品颜色与尺码" required error={error} hint={locked ? "已从关联记录带入；如需处理其他商品，请另建独立记录。" : value ? `已选：${selected?.label || "商品身份待核"}` : "核对款号、颜色和尺码后选择；找不到商品时先处理主档。"}>
      <select required disabled={locked} value={value} onChange={e => onChange(e.target.value)}>
        <option value="">选择商品及尺码</option>
        {selected && !choices.some(s => s.sku_id === value) && <option value={value}>{selected.label}</option>}
        {choices.map(s => <option key={s.sku_id} value={s.sku_id}>{s.label}</option>)}
      </select>
    </FormField>
  </>;
}

export type QualityLine = { sku_id: string; purpose: string; quality: string; target_quality?: string; units: string; location_from?: string; location_to?: string; counted_on?: string; evidence?: string };
export type QualityBalance = { on_hand_units?: string | null; free_available_units?: string | null; qualified_units?: string; pending_units?: string; defective_units?: string; unassessed_units?: string; held_units?: string; reserved_units?: string };
export function QualityMovementFields({ line, skus, locked, error, quantityError, balance, onChange, part = "all", inventoryState = "ready" }: {
  line: QualityLine; skus: Sku[]; locked: boolean; error?: string; quantityError?: string;
  balance?: QualityBalance; inventoryState?: "ready" | "loading" | "error";
  onChange: (key: keyof QualityLine, value: string) => void;
  part?: "all" | "product" | "change";
}) {
  const qualities = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
  const location = line.purpose === "LOCATION";
  const storedLocation = !location && !!(line.location_from || line.location_to);
  const sourceUnits = line.quality === "QUALIFIED" ? balance?.qualified_units : line.quality === "PENDING" ? balance?.pending_units : line.quality === "DEFECTIVE" ? balance?.defective_units : undefined;
  return <div className={styles.workflow}>
    {part !== "change" && <section className={styles.step} aria-label="选择本次处理商品"><h3>选择商品</h3><div className={styles.productFields}><MovementSkuSelect value={line.sku_id} skus={skus} locked={locked} error={error} onChange={value => onChange("sku_id", value)} /></div></section>}
    {line.sku_id && <CurrentStockState balance={balance} quality={line.quality} inventoryState={inventoryState} />}
    {part !== "product" && <section className={styles.step} aria-label="登记本次变化"><h3>登记变化</h3>
      <div className={styles.purposePicker} role="group" aria-label="本条处理方式">{[["QUALITY", "质量处理"], ["LOCATION", "移动库位"], ["DAMAGE", "实际损坏"]].map(([value, label]) => <Button key={value} variant={line.purpose === value ? "secondary" : "quiet"} aria-pressed={line.purpose === value} disabled={locked} onClick={() => onChange("purpose", value!)}>{label}</Button>)}</div>
      <p className={styles.hint}>{location ? "只记录同一仓库内的位置变化，货品状态和在库总数不变；不用于仓库之间调货。" : line.purpose === "DAMAGE" ? "登记有实际依据的损坏，保留证据；库存总数不变，质量和可发量按确认结果更新。" : "检验完成后，将本次数量转为合格、待检或次品。只改质量状态，不重复入库；没有划分库位无需填写位置。"}</p>
      <div className={styles.changeFields}>
        <FormField label="货品状态" required><select required disabled={!line.sku_id} value={line.quality} onChange={event => onChange("quality", event.target.value)}><option value="">选择变更前的状态</option>{Object.entries(qualities).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
        {!location && <FormField label="目标货品状态" required><select required disabled={!line.sku_id} value={line.target_quality || ""} onChange={event => onChange("target_quality", event.target.value)}><option value="">选择变更后的状态</option>{Object.entries(qualities).filter(([value]) => value !== line.quality || storedLocation).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>}
        {location && <p className={styles.sameQuality}>货品状态保持不变，不增加或减少任何质量数量。</p>}
        {(location || storedLocation) && <><FormField label="来源库位" required hint={storedLocation ? "原记录已填写库位，继续保留；仅更正质量时也请核对。" : "例如：A区1号货架；仅在已划分库位时使用。"}><Input required value={line.location_from || ""} onChange={event => onChange("location_from", event.target.value)} /></FormField><FormField label="目标库位" required><Input required value={line.location_to || ""} onChange={event => onChange("location_to", event.target.value)} /></FormField></>}
        <FormField label="本次件数" required error={quantityError} hint={line.quality ? `当前${qualities[line.quality as keyof typeof qualities] || "所选状态"}：${sourceUnits == null ? "数量待核" : `${units(sourceUnits)}件`}，填写本次实际处理数量。` : "先选择商品及变更前状态，再填写本次数量。"}><Input required inputMode="numeric" pattern="[1-9][0-9]*" disabled={!line.sku_id} value={line.units} onChange={event => onChange("units", event.target.value)} /></FormField>
      </div>
      {line.purpose === "DAMAGE" && <div className={styles.changeFields}><FormField label="实盘截止日期" required><Input required type="date" value={line.counted_on || ""} onChange={event => onChange("counted_on", event.target.value)} /></FormField><FormField label="盘点/损坏证据" required><Input required value={line.evidence || ""} onChange={event => onChange("evidence", event.target.value)} /></FormField></div>}
    </section>}
  </div>;
}

export function CurrentStockState({ balance, quality, inventoryState = "ready", selectionLabel = "本次来源" }: { balance?: QualityBalance; quality: string; inventoryState?: "ready" | "loading" | "error"; selectionLabel?: string }) {
  const qualities = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品" };
  const sourceUnits = quality === "QUALIFIED" ? balance?.qualified_units : quality === "PENDING" ? balance?.pending_units : quality === "DEFECTIVE" ? balance?.defective_units : undefined;
  const stockValue = (value: string | null | undefined) => value == null ? "待核" : `${units(value)}件`;
  return <section className={styles.currentStock} aria-label="当前库存状态"><h3>当前库存状态</h3>
      {inventoryState !== "ready" ? <p role="status">{inventoryState === "error" ? "库存读取失败，请刷新后核对；未将未知数量当作0。" : "正在读取当前库存，请稍候…"}</p> : !balance ? <p>该商品在当前仓库及货主下尚无已登记库存，数量待核，不代表0件。</p> : <>
        <dl className={styles.stockTotals}><div><dt>实际在库</dt><dd>{stockValue(balance.on_hand_units)}</dd></div><div><dt>当前可发</dt><dd>{stockValue(balance.free_available_units)}</dd></div>{Object.entries(qualities).map(([value, label]) => <div key={value} data-quality={value} data-selected={quality === value}><dt>{label}{quality === value && <small>{selectionLabel}</small>}</dt><dd>{stockValue(value === "QUALIFIED" ? balance.qualified_units : value === "PENDING" ? balance.pending_units : balance.defective_units)}</dd></div>)}</dl>
        {balance.unassessed_units != null && balance.unassessed_units !== "0" && <p className={styles.hint}>质量未核 {stockValue(balance.unassessed_units)}</p>}
        {((balance.held_units != null && balance.held_units !== "0") || (balance.reserved_units != null && balance.reserved_units !== "0")) && <p className={styles.hint}>冻结 {stockValue(balance.held_units)} · 预留 {stockValue(balance.reserved_units)}（包含在质量数量中，不重复相加）</p>}
        {quality && selectionLabel === "本次来源" && <p className={styles.sourceStock}>{sourceUnits == null ? "来源状态数量待核，请刷新库存核对。" : `当前来源：${qualities[quality as keyof typeof qualities]} ${stockValue(sourceUnits)}。`}</p>}
      </>}
      <p className={styles.hint}>同一商品、当前仓库及货主的账面库存；草稿不占用库存，最终以服务端预览和确认时复核为准。</p>
    </section>;
}
type Impact = { warehouse_id: string; sku_id: string; on_hand_before: string; on_hand_after: string; free_before: string | null; free_after: string | null };
export function StockImpact({ impacts, skuName, warehouseName, compact = false }: { impacts?: Impact[]; skuName: (id: string) => string; warehouseName: (id: string) => string; compact?: boolean }) {
  if (!impacts?.length) return null;
  const free = (value: string | null) => value === null ? "缺口待处理，暂停发货" : `${units(value)} 件`;
  if (compact) return <section aria-label="确认后的库存变化（预览）"><h3>确认后的库存变化（预览）</h3>{impacts.map(item => <Table key={`${item.warehouse_id}:${item.sku_id}`} title={impacts.length > 1 ? skuName(item.sku_id) : undefined}><thead><tr><th>库存项</th><th>变更前</th><th>本次变动</th><th>变更后</th></tr></thead><tbody>{[["实际在库", item.on_hand_before, item.on_hand_after], ["当前可发", item.free_before, item.free_after]].map(([label, before, after]) => { const delta = before == null || after == null ? undefined : BigInt(after) - BigInt(before); return <tr key={label}><th scope="row">{label}</th><td>{before == null ? "待核" : units(before)}</td><td data-direction={delta == null ? undefined : delta > 0n ? "increase" : delta < 0n ? "decrease" : "unchanged"}>{delta == null ? "待核" : `${delta > 0n ? "+" : ""}${units(delta.toString())}`}</td><td><strong>{after == null ? "待核" : units(after)}</strong></td></tr>; })}</tbody></Table>)}</section>;
  return <Table title="确认后的库存变化"><thead><tr><th>商品 / 仓库</th><th>实际在库：当前 → 确认后</th><th>自由可发：当前 → 确认后</th></tr></thead><tbody>{impacts.map(item => <tr key={`${item.warehouse_id}:${item.sku_id}`}><td>{skuName(item.sku_id)}<br />{warehouseName(item.warehouse_id)}</td><td>{units(item.on_hand_before)} → {units(item.on_hand_after)} 件</td><td>{free(item.free_before)} → {free(item.free_after)}</td></tr>)}</tbody></Table>;
}

export type StockImpacts = Impact[];
