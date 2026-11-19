import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { ChevronLeft, ChevronRight, CircleAlert, Download, Info, Search } from "lucide-react";
import { requestApi, writeApi } from "../../api/client";
import { RequestGate } from "../../api/requestGate";
import { revokeSessionBoundary } from "../../api/sessionRevocation";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, Dialog, FormField, Input, PageHeader, Pagination, StatusMessage, Table } from "../../design-system";
import { units } from "./types";
import { groupInventoryProducts, inventoryColor, inventoryNeeds, inventoryFocusLabels, inventorySizeQuantities, inventorySizes, prepareInventoryProducts, type InventoryFocus, type StockColor } from "./inventoryPreparation";
import { InventoryReviewDialog, type Review, type Edit, type Change } from "./InventoryReviewDialog";
import { InventoryProductMatchDialog } from "./InventoryProductMatchDialog";
import styles from "./Production.module.css";

type Quantity = { cell: string; raw: string; state: "LITERAL" | "ADDITION_REFERENCE" | "UNKNOWN" | "UNSUPPORTED"; units: string | null };
export type StockRow = {
  source_key: string; sheet: string; source_row: number; style_code: string; old_style_code: string; source_sku: string;
  color: string; color_note: string; location: string; warehouse_display?: string; location_group: "WAREHOUSE_1" | "UNCONFIRMED" | "OUTSIDE_SCOPE"; reviewed_total?: string | null; quantity_complete?: boolean;
  quantities: Partial<Record<string, Quantity>>; stock_units: string; literal_units: string; formula_units: string; unknown_cells: number;
  source_total: Quantity; notes: { cell: string; raw: string }[]; issues: string[]; sku_id: null; product_links?: Record<string, import("./InventoryReviewDialog").ProductLink>;
};
export type InventorySnapshot = {
  filename: string; source_digest: string; source_manifest_digest?: string; source_format: "xlsx" | "pasted_table" | "manual_table_v1"; source_kind?: "FICTIONAL" | "REAL_SOURCE" | "MANUAL"; organized_on: string | null; stocktaken_on: string | null; warehouse_note: string; manual_batch_id?: string;
  scope: "WAREHOUSE_1"; quantity_basis: "DECLARED_TOTAL" | "SIZE_LITERALS";
  read_only: true; posting_enabled: false; historical_shipments_deducted: false;
  summary: { source_row_count: number; row_count: number; product_count: number; warehouse_1_units: string; location_unconfirmed_units: string; literal_units: string; warehouse_1_literal_units: string; location_unconfirmed_literal_units: string; formula_units: string; unknown_cells: number; defect_literal_units: string; additional_note_rows: number };
  rows: StockRow[]; unconfirmed_rows: StockRow[]; outside_rows?: StockRow[]; cutoff_note?: string; defect_period_note: string;
  defects: { source_row: number; style_code: string; color: string; size: string; quantity: Quantity; note: string; inherited_cells: Record<string, string>; identity_unresolved: boolean; sku_id: null }[];
};
const sizes = inventorySizes;

function CellQuantity({ quantity }: { quantity?: Quantity }) {
  if (!quantity) return <span className={styles.secondary}>未记录</span>;
  if (quantity.state === "LITERAL") return <span title={quantity.cell + " · 原值 " + quantity.raw}>{units(quantity.units || "0")}</span>;
  return <span title={quantity.cell + " · 原值 " + (quantity.raw || "空白")}>{quantity.state === "ADDITION_REFERENCE" ? <>{units(quantity.units || "0")}<small className={styles.secondary}>待核公式</small></> : <span className={styles.secondary}>待核</span>}</span>;
}
function Warehouse({ row }: { row: StockRow }) {
  return <>{row.location_group === "WAREHOUSE_1" ? (row.warehouse_display !== undefined ? row.warehouse_display || "本次核对仓库（名称待补）" : "花都仓库1号") : row.location_group === "OUTSIDE_SCOPE" ? "明确不属于本仓" : row.location || "未填写仓库"}{row.location_group === "UNCONFIRMED" && <small className={styles.secondary}>归属待确认 · 未计入本仓</small>}</>;
}
function RowNeeds({ row }: { row: StockRow }) {
  const needs = inventoryNeeds(row);
  return <>{needs.length ? <ul className={styles.inventoryRowNeeds}>{needs.map(need => <li key={need}>{inventoryFocusLabels[need]}</li>)}</ul> : <small className={styles.secondary}>仍待正式商品关联</small>}{row.notes.filter(note => note.raw.includes("另有")).map(note => <p className={styles.reviewHint} key={note.cell}>{note.raw}</p>)}</>;
}

export function InventorySnapshotView({ snapshot, review, onEdit, editing = false, sourceOnly = false, onExport, exporting = false, onRefresh }: { snapshot: InventorySnapshot; review?: Review; onEdit?: (edit: Edit) => void; editing?: boolean; sourceOnly?: boolean; onExport?: (path: string) => void; exporting?: boolean; onRefresh?: () => void }) {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") || "";
  const focus = params.get("focus") === "location" ? "" : params.get("focus") || "";
  const allRows = [...snapshot.rows, ...snapshot.unconfirmed_rows, ...(snapshot.outside_rows || [])];
  const matches = (row: StockRow) => [row.style_code, row.color, row.color_note].join(" ").toLocaleLowerCase().includes(q.trim().toLocaleLowerCase()) && (!focus || inventoryNeeds(row).includes(focus as InventoryFocus));
  const pendingRows = snapshot.unconfirmed_rows.filter(matches);
  const outsideRows = (snapshot.outside_rows || []).filter(matches);
  const [checked, setChecked] = useState<string[]>([]);
  const products = groupInventoryProducts(snapshot.rows);
  const filtered = prepareInventoryProducts(products, q, focus);
  const [selected, setSelected] = useState<{ style_code: string; colors: StockColor[] }>();
  const [matchRows, setMatchRows] = useState<StockRow[]>();
  const matchTrigger = useRef<HTMLButtonElement | null>(null);
  useEffect(() => setMatchRows(undefined), [review?.review_id, review?.revision]);
  const record = params.get("record");
  useEffect(() => {
    if (!record || editing) { setSelected(undefined); return; }
    const row = [...snapshot.rows, ...snapshot.unconfirmed_rows, ...(snapshot.outside_rows || [])].find(value => value.source_key === record);
    if (!row) return;
    const product = groupInventoryProducts(snapshot.rows).find(value => value.colors.some(color => color.rows.includes(row)));
    setSelected({ style_code: row.style_code, colors: product?.colors || [{ key: row.source_key, color: inventoryColor(row), stock_units: row.stock_units, unknown_cells: row.unknown_cells, rows: [row] }] });
  }, [record, snapshot, editing]);
  const detailTrigger = useRef<HTMLButtonElement | null>(null);
  const pendingSection = useRef<HTMLDetailsElement | null>(null);
  const needs = Object.fromEntries(Object.keys(inventoryFocusLabels).map(key => [key, allRows.filter(row => inventoryNeeds(row).includes(key as InventoryFocus)).length])) as Record<InventoryFocus, number>;
  const totalPages = Math.max(1, Math.ceil(filtered.length / 6));
  const requestedPage = Number(params.get("page") || "1");
  const page = Number.isSafeInteger(requestedPage) ? Math.min(totalPages, Math.max(1, requestedPage)) : 1;
  const visible = filtered.slice((page - 1) * 6, page * 6);
  const activeProduct = visible.find(product => product.key === params.get("product")) || visible[0];
  // Preserve the source's color order for the matrix; grouping and quantities remain unchanged.
  const activeColors = activeProduct ? [...activeProduct.colors].sort((left, right) => snapshot.rows.findIndex(row => left.rows.includes(row)) - snapshot.rows.findIndex(row => right.rows.includes(row))) : [];
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    for (const obsolete of ["page", "product", "category", "pending", "location"]) next.delete(obsolete);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  }
  function openDetails(style_code: string, colors: StockColor[], trigger: HTMLButtonElement) {
    detailTrigger.current = trigger; setSelected({ style_code, colors }); const next = new URLSearchParams(params); const key = colors[0]?.rows[0]?.source_key; if (key) next.set("record", key); setParams(next, { replace: true });
  }
  const filteredUnits = filtered.reduce((sum, product) => sum + BigInt(product.stock_units), 0n).toString();
  const colorCount = products.reduce((sum, product) => sum + product.colors.length, 0);
  const declared = snapshot.quantity_basis === "DECLARED_TOTAL";
  const exportParams = new URLSearchParams({ source_digest: snapshot.source_digest });
  if (review) { exportParams.set("review_id", review.review_id); exportParams.set("revision", String(review.revision)); }
  if (sourceOnly) exportParams.set("source_only", "true");
  const exportAll = "/api/production/inventory-export?" + exportParams.toString();
  if (q) exportParams.set("q", q);
  if (focus) exportParams.set("focus", focus);
  const exportFiltered = "/api/production/inventory-export?" + exportParams.toString();
  return <div className={styles.inventoryPage}>
    <div className={styles.inventoryTop}>
      <div className={styles.inventoryHeading}><PageHeader title="产品库存" description={snapshot.source_kind === "MANUAL" ? snapshot.warehouse_note : "花都仓库1号"} actions={<a className={styles.documentExport} href={exportAll} aria-disabled={exporting} onClick={onExport ? event => { event.preventDefault(); if (!exporting) onExport(exportAll); } : undefined}><Download aria-hidden="true" />{exporting ? "正在导出…" : "导出 Excel"}</a>} /></div>
      <div className={styles.inventoryTopActions}><p className={styles.inventoryScopeNote} role="status"><CircleAlert aria-hidden="true" />{snapshot.stocktaken_on ? "盘点日期：" + snapshot.stocktaken_on : "盘点日期待确认"} · 表内数量，仅用于核对</p><Link className={styles.inventoryReturn} to="/production/stock/materials"><ChevronLeft aria-hidden="true" />返回库存资料</Link></div>
      <dl className={styles.inventoryOverview} aria-label="库存核对概况"><div><dt>本仓资料核对数量</dt><dd>{units(snapshot.summary.warehouse_1_units)}<small>件</small></dd></div><div><dt>产品款数</dt><dd>{products.length}<small>款产品</small></dd></div><div><dt>款色组合</dt><dd>{colorCount}<small>组款色</small></dd></div></dl>
    </div>
    <section className={styles.inventoryFilters} aria-label="库存筛选"><div className={styles.inventoryFilterControls}>
      <div className={styles.inventorySearch}><Search aria-hidden="true" /><FormField className={styles.inventorySearchField} label="查找款号或颜色"><Input id="inventory-search" type="search" placeholder="查找款号或颜色" value={q} onChange={event => filter("q", event.target.value)} /></FormField></div>
      <FormField className={styles.inventoryFocusField} label="待补数据"><select value={focus} onChange={event => filter("focus", event.target.value)}><option value="">全部产品</option>{Object.entries(inventoryFocusLabels).filter(([key]) => key !== "location").map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></FormField>
      {(q || focus) && <Button variant="quiet" onClick={() => { const next = new URLSearchParams(params); for (const key of ["q", "focus", "page", "product"]) next.delete(key); setParams(next, { replace: true }); }}>清除筛选</Button>}
      {(q || focus) && <a className={styles.documentExport} href={exportFiltered} aria-disabled={exporting} onClick={onExport ? event => { event.preventDefault(); if (!exporting) onExport(exportFiltered); } : undefined}><Download aria-hidden="true" />导出筛选结果</a>}
    </div>{(q || focus) && <p className={styles.inventoryFilterSummary} role="status">按款号排序 · 本仓{filtered.length}款 / {units(filteredUnits)}件 · 仓库待核{pendingRows.length}行 · 本仓之外{outsideRows.length}行{q && " · 颜色搜索保留完整产品量与全部颜色"}</p>}</section>
    {activeProduct ? <>
      <section aria-label="产品库存"><ul className={styles.inventoryCards}>{visible.map(product => <li key={product.key}><Button className={styles.inventoryCard} aria-label={"查看" + (product.style_code || "待确认款号") + "库存，" + product.colors.length + "种颜色，" + units(product.stock_units) + "件"} aria-pressed={product.key === activeProduct.key} aria-controls="inventory-product-detail" onClick={() => { const next = new URLSearchParams(params); next.set("product", product.key); setParams(next); if (window.innerWidth <= 700) document.getElementById("inventory-product-detail")?.scrollIntoView({ block: "start" }); }}><span className={styles.inventoryCardHeading}><strong>{product.style_code || "待确认款号"}</strong><small>{product.colors.length}种颜色</small></span><strong className={styles.inventoryCardUnits}>{units(product.stock_units)}<small>件</small></strong></Button></li>)}</ul>
        <div className={styles.inventoryPager}><Pagination itemLabel="产品" page={page} totalPages={totalPages} totalItems={filtered.length} onPageChange={value => { const next = new URLSearchParams(params); next.set("page", String(value)); next.delete("product"); setParams(next); }} /></div>
      </section>
      <section id="inventory-product-detail" className={styles.inventoryDetail} aria-label={(activeProduct.style_code || "待确认款号") + "颜色与尺码"}>
        <div className={styles.inventoryDetailHeading}><div><h2>{activeProduct.style_code || "待确认款号"} · 颜色与尺码</h2><p>{activeColors.length}种颜色</p></div><strong className={styles.inventoryDetailUnits}>{units(activeProduct.stock_units)}<small>件</small></strong></div>
        <div className={styles.inventoryMatrixWrap}><Table className={styles.inventoryMatrix} aria-label={(activeProduct.style_code || "待确认款号") + "颜色与尺码数量"}><thead><tr><th scope="col">颜色</th>{sizes.map(size => <th scope="col" key={size}>{size}</th>)}<th scope="col">合计（件）</th></tr></thead><tbody>{activeColors.map(color => <tr key={color.key}><th scope="row">{color.color || "待确认颜色"}</th>{inventorySizeQuantities(color).map(quantity => <td key={quantity.size}>{quantity.literal_sources > 0 ? <>{quantity.pending_sources > 0 && <small className={styles.inventoryPendingQuantity}>已知</small>}{units(quantity.known_units)}{quantity.pending_sources > 0 && <small className={styles.inventoryPendingQuantity}>另{quantity.pending_sources}条待核</small>}</> : <span className={styles.inventoryPendingQuantity}>待核</span>}</td>)}<td className={styles.inventoryMatrixTotal}>{units(color.stock_units)}</td></tr>)}</tbody></Table></div>
        <div className={styles.inventoryDetailFooter}><p><Info aria-hidden="true" />未知数量标为待核，0表示已明确为0<span className={styles.inventoryScrollHint}> · 左右滑动查看全部尺码</span></p><div className={styles.documentPageActions}>{review && <Button variant="quiet" onClick={event => { matchTrigger.current = event.currentTarget; setMatchRows(activeColors.flatMap(color => color.rows)); }}>查看商品对应</Button>}<Button className={styles.inventoryEvidenceAction} variant="quiet" onClick={event => openDetails(activeProduct.style_code, activeColors, event.currentTarget)}>查看来源依据<ChevronRight aria-hidden="true" /></Button></div></div>
      </section>
    </> : <StatusMessage kind="info" title="本仓没有符合筛选的产品">匹配的待核和本仓之外记录在下方显示，不计入本仓数量。</StatusMessage>}
    {[{ title: "仓库归属待确认", rows: pendingRows }, { title: "本仓之外", rows: outsideRows }].map(group => <details key={group.title} ref={group.title === "仓库归属待确认" ? pendingSection : undefined} open={!!q || params.get("pending") === "1"} className={styles.panel + " " + styles.inventorySupplement}><summary><strong>{group.title}</strong> · 匹配{group.rows.length}条 / {units(group.rows.reduce((sum, row) => sum + BigInt(row.stock_units), 0n).toString())}件，未计入本仓汇总</summary><p>搜索与筛选覆盖此组，不自动推断空白归属。</p>{!!group.rows.length && review?.can_manage && onEdit && <Button onClick={() => onEdit({ mode: "location", rows: group.rows.filter(row => checked.includes(row.source_key)) })} disabled={!group.rows.some(row => checked.includes(row.source_key))}>批量处理所选仓库归属</Button>}<ul className={styles.inventoryPending}>{group.rows.map(row => <li key={row.source_key}><div>{review?.can_manage && <label><input type="checkbox" checked={checked.includes(row.source_key)} onChange={event => setChecked(value => event.target.checked ? [...value, row.source_key] : value.filter(key => key !== row.source_key))} />选择{row.style_code} {inventoryColor(row)}</label>}<strong>{row.style_code || "待确认款号"} · {inventoryColor(row) || "待确认颜色"}</strong><small className={styles.secondary}><Warehouse row={row} /></small></div><strong>{units(row.stock_units)}件</strong><Button variant="quiet" onClick={event => openDetails(row.style_code, [{ key: row.source_key, color: inventoryColor(row), stock_units: row.stock_units, unknown_cells: row.unknown_cells, rows: [row] }], event.currentTarget)}>查看尺码与来源</Button>{review?.can_manage && onEdit && <Button onClick={() => onEdit({ mode: "location", rows: [row] })}>处理仓库归属</Button>}</li>)}</ul></details>)}
    <details className={styles.panel + " " + styles.inventorySupplement}><summary className={styles.inventoryPrepSummary}><h2>待补关键数据</h2><span className={styles.reviewHint}>{snapshot.stocktaken_on ? "盘点日" + snapshot.stocktaken_on : "盘点日期未确认"} · {snapshot.summary.unknown_cells}个尺码数量格待核 · 已保存{allRows.reduce((sum, row) => sum + Object.keys(row.product_links || {}).length, 0)}个尺码商品对应</span></summary>
      <ul className={styles.inventoryPreparation}>
        <li><div><strong>盘点日期与库存截止</strong><p>{snapshot.stocktaken_on ? "已记录盘点日期，仍需核对截止范围。" : "本次实际盘点日期未提供，不从文件名或整理日期推定。"} 明确起点后才能区分历史出货与后续收发。截止：{snapshot.cutoff_note || "仍待确认"}</p></div>{review?.can_manage && onEdit && <Button onClick={() => onEdit({ mode: "date", rows: [] })}>记录或更正日期与截止</Button>}</li>
        <li><div><strong>商品资料完整性</strong><p>{snapshot.rows.length}条颜色记录，商品对应按尺码保存；{needs.identity}条款色信息待核。当前款号分组只用于查看，不建立商品映射。</p></div>{needs.identity > 0 && <Button variant="quiet" onClick={() => filter("focus", "identity")}>查看款色待核</Button>}</li>
        <li><div><strong>商品对应与正式关联</strong><p>可在上方所选产品的“查看商品对应”中核对已有商品。管理人员可确认对应，经预览保存后生效；支持解除后重新核对，历史保留。</p></div></li>
        {snapshot.unconfirmed_rows.length > 0 && <li><div><strong>仓库归属</strong><p>{snapshot.source_kind === "MANUAL" ? "请按本次人工资料明确仓库范围；" : "“新仓库”已确认是花都仓库1号；其余"}{snapshot.unconfirmed_rows.length}条记录单列待确认。</p></div><Button variant="quiet" onClick={() => { if (pendingSection.current) { pendingSection.current.open = true; pendingSection.current.scrollIntoView({ block: "center" }); } }}>查看仓库待核</Button></li>}
        <li><div><strong>尺码与实物数量</strong><p>{snapshot.summary.unknown_cells}个尺码数量格待核，{needs.extra}条含公式、附加数量或合计差异。明确的0保留为0；空白和“/”保持未知。</p></div><Button variant="quiet" onClick={() => filter("focus", "quantity")}>查看数量待核</Button></li>
        <li><div><strong>货品状态与后续收发依据</strong><p>后续仍需良品、次品、待检等状态，以及真实入库、出库、退回的日期和单据。库存期初、预留和流水尚未建立。</p></div></li>
      </ul>
    </details>
    {!!snapshot.defects.length && <details className={styles.panel + " " + styles.inventorySupplement}><summary>历史次品核对 · 未计入库存</summary><p>{snapshot.defect_period_note}。是否与当前清单重叠尚未确认。</p><Table title="历史次品明细"><thead><tr><th>款号</th><th>颜色</th><th>尺码</th><th>数量</th><th>说明</th></tr></thead><tbody>{snapshot.defects.map(row => <tr key={row.source_row}><td>{row.style_code || "待确认"}</td><td>{row.color || "待确认"}</td><td>{row.size || "待核"}</td><td><CellQuantity quantity={row.quantity} /></td><td>{row.note}</td></tr>)}</tbody></Table></details>}
    {allRows.some(row => row.quantity_complete === false) && <StatusMessage kind="warning" title="部分合计未知">只展示已知数量，汇总不是完整数量，不能作为可发库存。</StatusMessage>}
    <details className={styles.panel + " " + styles.inventorySupplement}><summary>查看来源与数量口径</summary><p>{snapshot.filename} · {snapshot.organized_on ? "整理日期" + snapshot.organized_on : "整理日期未提供"}。{snapshot.warehouse_note}</p><p>数量尚不能作为库存期初或当前可发货数量，历史出货未回扣。</p><p>{declared ? "产品与颜色数量按本次表内合计汇总，已与明确尺码数字核对；合计只计一次。" : "产品与颜色数量仅汇总尺码中的明确数字，公式及附加数量仍待核。"} 仅合并同款号、同仓库中大小写不同的颜色显示，不合并近似颜色名。空白和“/”不补0。</p><p className={styles.reviewHint}>来源摘要：{snapshot.source_digest}</p></details>
    {matchRows && review && <InventoryProductMatchDialog key={review.review_id + ":" + review.revision} review={review} rows={matchRows} onClose={() => setMatchRows(undefined)} onRefresh={onRefresh} onEdit={onEdit} returnFocusTarget={matchTrigger} />}
    <Dialog contentClassName={styles.productionDialog} open={!!selected} onOpenChange={open => { if (!open) { setSelected(undefined); const next = new URLSearchParams(params); next.delete("record"); setParams(next, { replace: true }); } }} title="库存核对依据" description="查看所选产品的颜色、尺码与来源，空白和斜杠保留为待核。" size="large" returnFocusTarget={detailTrigger}>
      {selected && <div className={styles.inventoryEvidence}><dl className={styles.metadata}><div><dt>款号</dt><dd>{selected.style_code || "未提供"}</dd></div><div><dt>颜色数</dt><dd>{selected.colors.length}种</dd></div><div><dt>表内数量</dt><dd>{units(selected.colors.reduce((sum, color) => sum + BigInt(color.stock_units), 0n).toString())}件</dd></div><div><dt>正式商品关联</dt><dd>已保存{selected.colors.reduce((sum, color) => sum + color.rows.reduce((n, row) => n + Object.keys(row.product_links || {}).length, 0), 0)}个尺码对应</dd></div></dl>
        {selected.colors.map(color => <section key={color.key} className={styles.inventorySource}><h3>{color.color || "颜色待确认"} · {units(color.stock_units)}件</h3>{color.rows.map(row => <section key={row.source_key} className={styles.inventorySource}><h4>{row.sheet} · 第{row.source_row}行</h4><p><Warehouse row={row} /> · 原颜色：{inventoryColor(row) || "未填写"}</p><RowNeeds row={row} />{row.issues.map(issue => <p className={styles.reviewHint} key={issue}>{issue}</p>)}
          {review?.can_manage && onEdit && <div className={styles.actions}><Button onClick={() => { setSelected(undefined); onEdit({ mode: "location", rows: [row], returnFocusTarget: detailTrigger.current }); }}>更正仓库归属</Button><Button onClick={() => { setSelected(undefined); onEdit({ mode: "quantity", rows: [row], returnFocusTarget: detailTrigger.current }); }}>核对数量</Button></div>}
          <Table title="尺码数量依据"><thead><tr><th>尺码</th><th>已读取数量</th><th>原内容</th><th>单元格</th></tr></thead><tbody>{sizes.map(size => <tr key={size}><td>{size}</td><td><CellQuantity quantity={row.quantities[size]} /></td><td>{row.quantities[size]?.raw || "未填写"}</td><td>{row.quantities[size]?.cell || "未记录"}</td></tr>)}</tbody></Table>
          <p>本条{declared ? "表内合计" : "明确数字数量"}：{units(row.stock_units)}件。{row.formula_units !== "0" && "另有公式参考" + units(row.formula_units) + "件，未计入。"} 原合计：{row.source_total.raw || "未填写"}</p>
          <details><summary>定位来源记录</summary><p>{snapshot.filename} · {row.source_key}</p>{row.source_sku && <p>原文编码：{row.source_sku}（尚未绑定正式SKU）</p>}{row.notes.map(note => <p key={note.cell}>{note.cell} · {note.raw}</p>)}</details>
        </section>)}</section>)}
      </div>}
    </Dialog>
  </div>;
}

type Current = { review_id: string | null; source: InventorySnapshot; source_identity: string; can_manage: boolean; writes_enabled?: boolean; source_view_available?: boolean };
type History = { items: { revision: number; actor_id: string; actor_name?: string; at: string; reason: string; changes: Change[] }[]; next_before_revision: number | null };
export function InventorySnapshotPage({ sourceOnly = false }: { sourceOnly?: boolean } = {}) {
  const [params, setParams] = useSearchParams();
  const [current, setCurrent] = useState<Current>();
  const [review, setReview] = useState<Review>();
  const [fallback, setFallback] = useState<InventorySnapshot>();
  const [error, setError] = useState<string>();
  const [refresh, setRefresh] = useState(0);
  const [edit, setEdit] = useState<Edit>();
  const [history, setHistory] = useState<History>();
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const gate = useRef<RequestGate | null>(null);
  const { generation, registerSensitivePurge, purgeSensitiveState } = useAuthzGeneration();
  const id = sourceOnly ? null : params.get("review");
  useEffect(() => registerSensitivePurge(() => { gate.current?.abortAll(); setExporting(false); setCurrent(undefined); setReview(undefined); setFallback(undefined); setHistory(undefined); setEdit(undefined); setError(undefined); }), [registerSensitivePurge]);
  useEffect(() => {
    const activeGate = new RequestGate(); gate.current = activeGate;
    const ticket = activeGate.begin([refresh, id, sourceOnly], generation);
    setExporting(false); setCurrent(undefined); setReview(undefined); setFallback(undefined); setError(undefined); setHistory(undefined);
    void (async () => {
      try {
        if (sourceOnly) {
          setEdit(undefined);
          const raw = await requestApi<InventorySnapshot>("/api/production/inventory-snapshot", { signal: ticket.signal });
          if (ticket.isCurrent()) setFallback(raw);
          return;
        }
        if (id) {
          const fixed = await requestApi<Review>(`/api/production/inventory-reviews/${id}`, { signal: ticket.signal });
          if (!ticket.isCurrent()) return;
          setReview(fixed);
          if (fixed.source.source_kind === "MANUAL") return;
          try { const latest = await requestApi<Current>("/api/production/inventory-reviews/current", { signal: ticket.signal }); if (ticket.isCurrent()) setCurrent(latest); }
          catch (failure) { if (ticket.isCurrent()) setError("当前来源不可读取，仍可查看固定核对单：" + (failure instanceof Error ? failure.message : "读取未完成")); }
          return;
        }
        const value = await requestApi<Current>("/api/production/inventory-reviews/current", { signal: ticket.signal });
        if (!ticket.isCurrent()) return;
        if (value.review_id) {
          const next = new URLSearchParams(params); next.set("review", value.review_id);
          setParams(next, { replace: true });
          return;
        }
        setCurrent(value);
      } catch (reason) {
        if (!ticket.isCurrent()) return;
        setError(reason instanceof Error ? reason.message : "库存核对读取未完成。");
        if (!id && !sourceOnly) try { const raw = await requestApi<InventorySnapshot>("/api/production/inventory-snapshot", { signal: ticket.signal }); if (ticket.isCurrent()) setFallback(raw); } catch { /* Keep the original actionable error. */ }
      }
    })();
    return () => { activeGate.dispose(); if (gate.current === activeGate) gate.current = null; };
  // Filters do not change the fixed source request.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generation, refresh, id, sourceOnly]);
  async function reload() {
    if (!review) throw new Error("尚未建立核对单。");
    const ticket = gate.current!.begin([review.review_id, "reload"], generation);
    const value = await requestApi<Review>(`/api/production/inventory-reviews/${review.review_id}`, { signal: ticket.signal });
    if (!ticket.isCurrent()) throw new Error("权限或页面范围已变化。");
    setReview(value); return value;
  }
  async function start() {
    if (!current) return;
    const ticket = gate.current!.begin(["start"], generation); setBusy(true); setError(undefined);
    try {
      const value = await writeApi<Review>("/api/production/inventory-reviews", { body: { source_digest: current.source.source_digest, source_manifest_digest: current.source.source_manifest_digest }, idempotent: false, signal: ticket.signal });
      if (ticket.isCurrent()) { const next = new URLSearchParams(params); next.set("review", value.review_id); setCurrent(undefined); setParams(next); }
    } catch (failure) { if (ticket.isCurrent()) setError(failure instanceof Error ? failure.message : "开始核对未完成。"); }
    finally { if (ticket.isCurrent()) setBusy(false); }
  }
  async function loadHistory(before?: number) {
    if (!review) return;
    const ticket = gate.current!.begin(["history"], generation);
    try { const value = await requestApi<History>(`/api/production/inventory-reviews/${review.review_id}/history${before ? "?before_revision=" + before : ""}`, { signal: ticket.signal }); if (ticket.isCurrent()) setHistory(value); }
    catch (failure) { if (ticket.isCurrent()) setError(failure instanceof Error ? failure.message : "历史读取未完成。"); }
  }
  async function download(path: string) {
    if (exporting || !gate.current) return;
    const ticket = gate.current.begin(["export"], generation);
    setExporting(true); setError(undefined);
    try {
      const response = await fetch(path, { credentials: "same-origin", signal: ticket.signal });
      if (response.status === 401) { revokeSessionBoundary(); throw new Error("登录已失效，请重新登录后导出。"); }
      if (!response.ok) {
        const payload = await response.json().catch(() => ({})) as { error?: { message?: string } };
        const message = payload.error?.message;
        throw new Error(message && /[\u3400-\u9fff]/.test(message) ? message : "库存导出未完成，请刷新核对状态后重试。");
      }
      const blob = await response.blob();
      if (!ticket.isCurrent()) return;
      const filename = response.headers.get("Content-Disposition")?.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = filename ? decodeURIComponent(filename) : "库存表.xlsx";
      document.body.appendChild(link); link.click(); link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch (reason) {
      if (ticket.isCurrent()) setError(reason instanceof Error && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : "库存导出未完成，请检查连接后重试。");
    } finally { if (ticket.isCurrent()) setExporting(false); }
  }
  function openEdit(value: Edit) { const next = new URLSearchParams(params); if (value.mode === "product") next.delete("record"); else if (value.rows[0]) next.set("record", value.rows[0].source_key); setParams(next, { replace: true }); setEdit({ ...value, returnFocusTarget: value.returnFocusTarget || (document.activeElement instanceof HTMLButtonElement ? document.activeElement : null) }); }
  const snapshot = sourceOnly ? fallback : review?.effective || (!id ? current?.source || fallback : undefined);
  const needsSourceSelection = !sourceOnly && !id && !!error && error.includes("尚未配置库存快照");
  return <>
    {error && !needsSourceSelection && <StatusMessage kind="danger" title="核对未就绪或操作未完成">{error}<Button onClick={() => setRefresh(value => value + 1)}>重新读取</Button>{id && !review && <Button onClick={() => { const next = new URLSearchParams(params); next.delete("review"); next.delete("record"); setParams(next, { replace: true }); }}>返回当前来源</Button>}</StatusMessage>}
    {snapshot ? <>
      <section className={styles.panel} aria-label="资料核对状态">{snapshot.manual_batch_id && <Link to={`/production/stock/materials/${snapshot.manual_batch_id}`}>返回人工整理来源与操作历史</Link>}<p>本地演示环境 · {snapshot.source_kind === "FICTIONAL" ? "独立虚构测试资料" : snapshot.source_kind === "MANUAL" ? "人工整理来源资料" : "真实来源资料"} · 未过账</p>{snapshot.source_kind !== "MANUAL" && !sourceOnly && (current?.source_view_available || review?.source_view_available) && <Link to="/production/inventory/source">查看真实库存资料（只读）</Link>}{sourceOnly ? <><p>真实库存资料仅供查看，仓库归属、盘点日期和未知数量仍需有依据地核对。此处不保存核对决定，也不产生库存流水。</p><Link to="/production/inventory">返回库存资料核对</Link></> : review ? <><p>固定来源：{review.source.filename} · 核对单{review.review_id} · 已保存修订{review.revision}</p><p className={styles.reviewHint}>来源身份：{review.source_identity}</p>{current && current.source_identity !== review.source_identity && <StatusMessage kind="warning" title="当前来源已变化">正在查看旧核对单，决定不会套用到新资料。<Button onClick={() => { const next = new URLSearchParams(params); next.delete("review"); next.delete("record"); setParams(next); }}>查看当前来源</Button></StatusMessage>}<Button onClick={() => void loadHistory()}>查看核对历史</Button>{!review.can_manage && <p>{review.writes_enabled === false ? "此环境仅查看库存资料，资料核对写入尚未启用。" : "当前账号只读；管理者可保存核对决定。"}</p>}</> : <><p>尚未开始资料核对；读取不会自动建单。</p>{current?.can_manage && <Button disabled={busy} onClick={() => void start()}>开始资料核对</Button>}{!current?.can_manage && <p>{current?.writes_enabled === false ? "此环境仅查看库存资料，资料核对写入尚未启用。" : "当前只读；存储和管理权限具备后才能开始。"}</p>}</>}</section>
      <InventorySnapshotView snapshot={snapshot} review={sourceOnly ? undefined : review} onEdit={sourceOnly ? undefined : openEdit} editing={!sourceOnly && !!edit} sourceOnly={sourceOnly} onExport={path => void download(path)} exporting={exporting} onRefresh={() => setRefresh(value => value + 1)} />
      {!sourceOnly && history && <section className={styles.panel} aria-label="核对历史"><h2>核对历史</h2>{history.items.length === 0 && <p>修订0，尚无核对命令。</p>}{history.items.map(item => <details key={item.revision}><summary>修订{item.revision} · 操作人{item.actor_name || item.actor_id} · {item.at} · {item.reason}</summary><ul>{item.changes.filter(change => change.type === "set_product").map(change => <li key={change.source_key + change.size}>{change.source_key} · {change.size}：{change.value ? "保存对应商品规格 #" + change.value.sku_id + "（目录版本" + change.value.catalog_version_id + "）" : "解除商品对应，数量不变"}</li>)}</ul><details><summary>查看原始变更明细</summary><pre>{JSON.stringify(item.changes, null, 2)}</pre></details></details>)}{history.next_before_revision && <Button onClick={() => void loadHistory(history.next_before_revision!)}>查看更早历史</Button>}</section>}
      {!sourceOnly && edit && review && <InventoryReviewDialog key={review.review_id + generation} review={review} edit={edit} onClose={() => { setEdit(undefined); const next = new URLSearchParams(params); next.delete("record"); setParams(next, { replace: true }); }} onReload={reload} onForbidden={() => { purgeSensitiveState(); setError("权限已变化，旧编辑输入已清除；正在重新核对访问权限。"); setRefresh(value => value + 1); }} />}
    </> : needsSourceSelection ? <><PageHeader title="选择库存资料" description="当前环境没有默认库存表，请从已有资料中选择要查看的固定核对单。" /><StatusMessage kind="info" title="请选择一份库存资料">原来的库存核对界面仍然保留。<Link to="/production/stock/materials">打开库存资料记录</Link></StatusMessage></> : <><PageHeader title="库存核对" description="保留待核项，不推定真实事实。" /><StatusMessage kind="info" title={error ? "未能读取所选资料" : "正在读取库存资料…"} /></>}
  </>;
}
