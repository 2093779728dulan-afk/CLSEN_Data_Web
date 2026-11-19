import { TableImportReview } from "./TableImportReview";
import { useTableBaseline } from "./useTableBaseline";
import { withoutTableBaseline } from "./tableImportDiff";
import { useLoad } from "./useProductionApi";
import { Link } from "react-router-dom";
import { ChevronDown } from "lucide-react";
import { LinkButton, StatusBadge, Table } from "../../design-system";
import { type Document, type Kind, type Summary, type Sku, statusName, trackingName, units } from "./types";
import styles from "./Production.module.css";

/** Line breaks only format the supplied label; links and relations always use the stable IDs. */
export function ProductIdentity({ label, sku }: { label: string; sku?: Sku }) {
  const display = sku?.code || label;
  const separator = sku?.code ? -1 : display.indexOf(" · ");
  const primary = separator < 0 ? display : display.slice(0, separator);
  const secondary = separator < 0 ? undefined : display.slice(separator + 3);
  return <details className={styles.productIdentity}>
    <summary><span className={styles.productIdentityText}><strong>{primary}</strong>{secondary && <span>{secondary}</span>}</span><ChevronDown aria-hidden="true" /></summary>
    <div className={styles.productIdentityDetails}><p>{label}</p>{sku && <dl><div><dt>系统款式 ID</dt><dd>{sku.style_id || "未提供"}</dd></div><div><dt>系统 SKU ID</dt><dd>{sku.sku_id}</dd></div><div><dt>身份版本</dt><dd>{sku.catalog_version}</dd></div></dl>}</div>
  </details>;
}
function ProductStatus({ sku }: { sku: Sku }) {
  return <div className={styles.productStatus}><StatusBadge label={sku.status === "active" ? "已启用" : "已停用"} tone={sku.status === "active" ? "good" : "quiet"} />{sku.code === null && <StatusBadge label="正式SKU待补" tone="warn" />}</div>;
}
function ProductActions({ sku }: { sku: Sku }) {
  return <div className={styles.rowActions}><LinkButton to={`/production/orders?sku=${sku.sku_id}`} variant="quiet">订单</LinkButton><LinkButton to={`/production/shipments?sku=${sku.sku_id}`} variant="quiet">出货</LinkButton><LinkButton to="/production/stock" variant="quiet">库存</LinkButton></div>;
}
export function ProductionProductTable({ items }: { items: Sku[] }) {
  const empty = "商品主档尚未初始化，未使用临时名字绑定真实产品。";
  return <>
    <div className={styles.desktopList}><Table title="款式、颜色、尺码与SKU" description="每行一个商品规格。点击商品信息可查看全文、系统 ID 和身份版本。" className={styles.productTable}>
      <colgroup><col /><col className={styles.productStatusColumn} /><col className={styles.productActionsColumn} /></colgroup>
      <thead><tr><th>商品与规格</th><th>状态</th><th>查看业务</th></tr></thead>
      <tbody>{items.map(sku => <tr key={sku.sku_id}><td><ProductIdentity label={sku.label} sku={sku} /></td><td><ProductStatus sku={sku} /></td><td><ProductActions sku={sku} /></td></tr>)}{!items.length && <tr><td colSpan={3}>{empty}</td></tr>}</tbody>
    </Table></div>
    <section className={`${styles.mobileList} ${styles.productMobileList}`} aria-label="生产商品列表"><h2>商品与规格</h2><ul>{items.map(sku => <li key={sku.sku_id}><ProductIdentity label={sku.label} sku={sku} /><div className={styles.productMobileFooter}><ProductStatus sku={sku} /><ProductActions sku={sku} /></div></li>)}</ul>{!items.length && <p>{empty}</p>}</section>
  </>;
}

export function QuantityOverview({ expected, actual, difference, actualLabel = "有效累计出货", differenceLabel }: { expected?: string; actual: string; difference?: string; actualLabel?: string; differenceLabel?: string }) {
  return <dl className={`${styles.metrics} ${styles.quantityOverview}`}>{expected !== undefined && <div><dt>预计数量</dt><dd>{units(expected)}<small>件</small></dd></div>}
    <div><dt>{actualLabel}</dt><dd>{units(actual)}<small>件</small></dd></div>
    {difference !== undefined && <div><dt>{differenceLabel || (BigInt(difference) < 0n ? "超额出货差额" : "预计与出货差额")}</dt><dd>{units(difference)}<small>件</small></dd></div>}</dl>;
}
type HistoryItem = NonNullable<Document["history"]>[number];
const operationNames: Record<string, string> = { PRODUCTION_STATUS: "更新生产状态", COMPLETE_PRODUCTION: "人工确认生产完成", REOPEN_PRODUCTION: "恢复生产跟进", PRODUCTION_PROGRESS: "更新生产进度", CREATE: "创建", CREATE_CONFIRMED: "创建并确认", SHIPMENT_ALLOCATION_CHANGE: "关联出货变动", CONFIRM: "确认", DATA_CORRECTION: "录入更正", DEMAND_CHANGE: "需求变更", SHIPMENT_CORRECTION: "出货事实更正", ALLOCATION_CORRECTION: "订单归属调整", CLOSE_TRACKING: "关闭跟进", REOPEN_TRACKING: "恢复跟进", VOID: "作废", UPDATE_DRAFT: "编辑草稿", LEGACY: "历史操作（未分类）" };
function displayValue(value: unknown): string { return typeof value === "string" ? value : typeof value === "number" || typeof value === "boolean" ? String(value) : "未提供"; }
function snapshotFields(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") return {};
  const v = value as Record<string, unknown>; const result: Record<string, string> = {};
  const names: Record<string, string> = { factory_name: "生产工厂", destination: "发货目的地", business_number: "业务单号", business_date: "业务日期", status: "单据状态", notes: "备注", expected_units: "预计合计", actual_units: "有效出货合计", difference_units: "预计与出货差额", closed_units: "当前关闭量", pending_units: "待跟进量", overage_units: "超发量" };
  for (const [key, label] of Object.entries(names)) if (v[key] !== undefined && v[key] !== null) result[label] = key === "status" ? statusName[v[key] as keyof typeof statusName] || displayValue(v[key]) : displayValue(v[key]);
  if (v.production_completion_state !== undefined) result["生产完成确认"] = v.production_completion_state === "COMPLETED" ? "已完成" : "进行中";
  if (Array.isArray(v.lines)) for (const item of v.lines as Record<string, unknown>[]) {
    const label = displayValue(item.sku_label || item.sku_id || "SKU");
    for (const [key, title] of Object.entries({ production_status: "生产状态", produced_units: "累计实际生产", received_units: "累计实收入库", expected_units: "预计", tracking_state: "跟进状态", closed_units: "关闭量" })) if (item[key] !== undefined) result[`${label} · ${title}`] = key === "tracking_state" ? trackingName[item[key] as keyof typeof trackingName] || displayValue(item[key]) : displayValue(item[key]);
  }
  if (Array.isArray(v.sources)) for (const item of v.sources as Record<string, unknown>[]) {
    const label = `${displayValue(item.sku_label || item.sku_id || "SKU")} · 来源${displayValue(item.id || "")}`;
    result[`${label} · 实际件数`] = displayValue(item.actual_units || "");
    result[`${label} · 货物来源`] = item.fulfillment_mode === "PRODUCTION_DIRECT" ? "生产直发" : "仓库库存出货";
    if (item.plan_id) result[`${label} · 收发安排`] = displayValue(item.plan_id);
    if (Array.isArray(item.allocations)) for (const a of item.allocations as Record<string, unknown>[]) result[`${label} · 订单${displayValue(a.order_number || a.order_line_id)}`] = displayValue(a.units || "");
  }
  if (Array.isArray(v.cartons)) for (const box of v.cartons as Record<string, unknown>[]) {
    if (Array.isArray(box.items)) for (const item of box.items as Record<string, unknown>[]) result[`箱 ${displayValue(box.number)} · SKU ${displayValue(item.sku_id)}`] = displayValue(item.units);
  }
  return result;
}
function operationTitle(item: HistoryItem): string {
  if (item.operation_kind) return operationNames[item.operation_kind] || "历史操作（未分类）";
  const before = item.before_value as { status?: string } | null;
  const after = item.after_value as { status?: string } | null;
  if (!before && after?.status) return after.status === "CONFIRMED" ? "创建并确认" : "创建草稿";
  if (before?.status === "DRAFT" && after?.status === "CONFIRMED") return "确认";
  if (before?.status === "CONFIRMED" && after?.status === "VOID") return "作废";
  return "历史操作（未分类）";
}
export function RevisionHistory({ history }: { history: HistoryItem[] }) {
  return <section className={styles.panel}><h2>修订历史</h2>{history.map(h => {
    const before = snapshotFields(h.before_value), after = snapshotFields(h.after_value);
    const changes = Array.from(new Set([...Object.keys(before), ...Object.keys(after)])).filter(key => before[key] !== after[key]);
    return <details key={h.revision}><summary>修订{h.revision} · {operationTitle(h)} · {new Date(h.created_at).toLocaleString("zh-CN")}</summary><p>操作人员：{h.actor_name || `账号${h.actor_id}`}（ID {h.actor_id}） · 原因：{h.reason || "未记录"}{h.effective_date ? ` · 业务生效日期 ${h.effective_date}` : ""}</p><Table title={`修订${h.revision}的变化`}><thead><tr><th>内容</th><th>修改前</th><th>修改后</th></tr></thead><tbody>{changes.map(key => <tr key={key}><td>{key}</td><td>{before[key] ?? "—"}</td><td>{after[key] ?? "—"}</td></tr>)}{!changes.length && <tr><td colSpan={3}>没有可比较的数量或业务字段变化，保留本次操作记录。</td></tr>}</tbody></Table></details>;
  })}</section>;
}
function RecordIdentity({ kind, document: item }: { kind: Kind; document: Pick<Document, "id" | "system_number"> & Partial<Pick<Document, "business_number">> }) {
  return <><Link className={styles.recordLink} to={`/production/${kind}/${item.id}`}>{item.business_number || `${kind === "orders" ? "订单" : "出货单"} ${item.system_number.slice(-8)}`}</Link><details className={styles.recordNumber}><summary>查看完整系统编号</summary><span>{item.system_number}</span></details></>;
}
function DocumentStatus({ status }: { status: Document["status"] }) {
  return <StatusBadge label={statusName[status]} tone={status === "CONFIRMED" ? "good" : "quiet"} />;
}
function DocumentMetadata({ document: item }: { document: Document }) {
  return <div className={styles.documentMetadata}><span>{item.business_date || "日期未填写"}</span><span>修订 {item.revision}</span></div>;
}
function ShipmentContext({ document: item, catalog }: { document: Document; catalog: Sku[] }) {
  return <div className={styles.shipmentContext}>{item.sources?.map((source, index) => <div className={styles.shipmentSource} key={source.id ?? index}>
    <div className={styles.shipmentSourceHeading}><ProductIdentity label={source.sku_label || `SKU ${source.sku_id}（名称待核）`} sku={catalog.find(sku => sku.sku_id === source.sku_id)} /><span>{source.fulfillment_mode === "PRODUCTION_DIRECT" ? "生产直发" : "仓库出货"} · {units(source.actual_units)}件</span></div>
    <div className={styles.shipmentAllocations}>{source.allocations.map(allocation => <div className={styles.shipmentAllocation} key={allocation.order_line_id}>
      <div>{allocation.order_id ? allocation.order_number ? <RecordIdentity kind="orders" document={{ id: allocation.order_id, system_number: allocation.order_number, business_number: allocation.order_business_number }} /> : <Link className={styles.recordLink} to={`/production/orders/${allocation.order_id}`}>{allocation.order_business_number || `订单 #${allocation.order_id}`}</Link> : <span>{allocation.order_business_number || allocation.order_number || `订单行 #${allocation.order_line_id}`}</span>}</div>
      <span>分配 {units(allocation.units)}件</span>
    </div>)}{!source.allocations.length && item.dispatch_purpose !== "WAREHOUSE_DISPATCH" && <p>本来源没有生产订单分配</p>}</div>
  </div>)}{!item.sources?.length && <p className={styles.secondary}>商品明细未提供。</p>}</div>;
}
export function DocumentTable({ kind, items, filtered = false, catalog = [] }: { kind: Kind; items: Document[]; filtered?: boolean; catalog?: Sku[] }) {
  const empty = filtered ? "没有匹配当前筛选的记录。请调整条件或清空筛选。" : "暂无记录，可从上方创建单据或导入标准表格。";
  const orders = kind === "orders";
  return <><div className={styles.desktopList}><Table title={orders ? "订单记录" : "出货记录"} description={orders ? "草稿及已作废订单不计入有效汇总；跟进量按全部有效累计出货计算。" : "每张单据记录一次实际发运。已作废单据保留原登记数量，不计入有效汇总。"} className={`${styles.documentTable} ${orders ? styles.orderDocumentTable : styles.shipmentDocumentTable}`}>
    <colgroup>{orders ? <><col className={styles.orderRecordColumn} /><col className={styles.orderStateColumn} /><col /><col /><col /></> : <><col className={styles.shipmentRecordColumn} /><col className={styles.shipmentContextColumn} /><col /><col /></>}</colgroup>
    <thead><tr><th>单据信息</th><th>{orders ? "状态与跟进" : "商品与批次来源"}</th>{orders ? <><th>预计</th><th>累计已发</th><th>差额</th></> : <><th>状态</th><th>本次实际</th></>}</tr></thead>
    <tbody>{items.map(item => <tr key={item.id}><td><div className={styles.documentIdentity}><RecordIdentity kind={kind} document={item} /><DocumentMetadata document={item} /></div></td>{orders ? <><td><div className={styles.documentState}><DocumentStatus status={item.status} /><p>{item.status === "CONFIRMED" ? `${trackingName[item.tracking_state || "OPEN"]} · 待跟进 ${units(item.pending_units)}件` : "未计入有效跟进"}</p></div></td><td>{units(item.expected_units)}</td><td>{units(item.actual_units)}</td><td>{units(item.difference_units)}</td></> : <><td><ShipmentContext document={item} catalog={catalog} /></td><td><DocumentStatus status={item.status} /></td><td>{units(item.actual_units)}</td></>}</tr>)}
      {!items.length && <tr><td colSpan={orders ? 5 : 4}>{empty}</td></tr>}
    </tbody>
  </Table></div><section className={`${styles.mobileList} ${styles.documentMobileList}`} aria-label={orders ? "订单记录" : "出货记录"}><h2>{orders ? "订单记录" : "出货记录"}</h2><ul>{items.map(item => <li key={item.id}>
    <div className={styles.documentCardHeader}><div><RecordIdentity kind={kind} document={item} /><DocumentMetadata document={item} /></div><DocumentStatus status={item.status} /></div>
    {!orders && <ShipmentContext document={item} catalog={catalog} />}
    <dl>{orders && <div><dt>预计</dt><dd>{units(item.expected_units)}件</dd></div>}<div><dt>{orders ? "累计已发" : "本次实际"}</dt><dd>{units(item.actual_units)}件</dd></div>{orders && <><div><dt>差额</dt><dd>{units(item.difference_units)}件</dd></div><div><dt>{item.status === "CONFIRMED" ? trackingName[item.tracking_state || "OPEN"] : "跟进"}</dt><dd>{item.status === "CONFIRMED" ? `待跟进${units(item.pending_units)}件` : "未计入有效跟进"}</dd></div></>}</dl>
    {!orders && item.status === "VOID" && <p>已作废：保留原登记数量，不计入有效汇总。</p>}
  </li>)}</ul>{!items.length && <p>{empty}</p>}</section></>;
}
function WarehouseDispatchFacts({ document: item, catalog }: { document: Document; catalog: Sku[] }) {
  const attributed = item.sources?.some(source => source.allocations.length);
  const scope=useLoad<{scopes:{warehouse_name:string}[]}>(`/api/production/inventory/availability?${new URLSearchParams({warehouse_id:item.warehouse_id || "",owner_id:item.owner_id || ""})}`,0,!!item.warehouse_id && !!item.owner_id);
  return <section className={styles.panel} aria-label={attributed ? "仓库出货批次" : "独立仓库批次"}><h2>仓库出货明细</h2><p>来源仓库：{scope.value?.scopes[0]?.warehouse_name || "仓库名称待核"} → {item.destination || "目的地未登记"}</p>{scope.error && <p>来源仓名称读取失败；原单据和数量保留，请刷新后核对。</p>}<Table title="本批商品数量"><thead><tr><th>商品规格</th><th>本批实际数量</th>{attributed && <th>来源订单</th>}</tr></thead><tbody>{item.sources?.map((source,index)=><tr key={source.id || index}><th scope="row">{catalog.find(sku => sku.sku_id === source.sku_id)?.code || source.sku_label || `SKU ${source.sku_id}（名称待核）`}</th><td>{units(source.actual_units)}</td>{attributed && <td>{source.allocations.length?source.allocations.map(allocation=><div key={allocation.order_line_id}><Link to={`/production/orders/${allocation.order_id}`}>{allocation.order_business_number || allocation.order_number?.slice(-8) || "查看订单"}</Link> · {units(allocation.units)} 件</div>):"独立库存出货"}</td>}</tr>)}</tbody></Table></section>;
}
export function DocumentContent({ document: item, kind, catalog = [] }: { document: Document; kind: Kind; catalog?: Sku[] }) {
  const voidOrder = kind === "orders" && item.status === "VOID";
  return <><ImportedDocumentReview item={item} kind={kind}/><QuantityOverview actualLabel={kind === "shipments" ? item.status === "VOID" ? "原登记出货数量（已作废）" : "本次实际出货" : "有效累计出货"} expected={item.expected_units} actual={item.actual_units} difference={item.difference_units} />
    {voidOrder && <p className={styles.secondary}>此订单已作废。下方数量保留供历史核对，不属于当前待跟进任务。</p>}
    {kind === "orders" && !voidOrder && item.pending_units !== undefined && <FollowupQuantities pending={item.pending_units} closed={item.closed_units} overage={item.overage_units} />}
    {kind === "orders" && item.received_units !== undefined && <section className={styles.panel}><h2>生产实收入库</h2><p>累计实收 {units(item.received_units)} 件。只统计已过账且未冲销的来源分配，包含待检等实际到仓货物；不是当前可发库存，也不增加订单已发或判断生产是否完工。</p>
      <Table title="SKU累计实收"><thead><tr><th>商品</th><th>累计实收件数</th></tr></thead><tbody>{item.lines?.map(line => <tr key={line.id}><td>{line.sku_label}</td><td>{units(line.received_units)}</td></tr>)}</tbody></Table>
      {item.receipts?.length ? <Table title="关联生产入库记录"><thead><tr><th>库存单</th><th>日期／仓库</th><th>商品</th><th>分配件数／货品状态</th><th>状态</th></tr></thead><tbody>{item.receipts.map(r => <tr key={`${r.document_id}:${r.line_number}:${r.order_line_id}`}><td><Link to={`/production/stock/movements/${r.document_id}`}>库存单{r.document_id} · 明细{r.line_number}</Link></td><td>{r.business_date} · 仓库{r.warehouse_id}</td><td>{item.lines?.find(l => l.id === r.order_line_id)?.sku_label || `SKU ${r.sku_id}`}</td><td>{units(r.units)} · {({ QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "次品", UNASSESSED: "质量未核" } as Record<string, string>)[r.quality] || r.quality}</td><td>{r.status === "POSTED" ? "已过账" : "已冲销 · 不计入累计实收"}</td></tr>)}</tbody></Table> : <p>尚无已过账的关联生产实收记录；入库草稿和完工通知不计入。</p>}
    </section>}
    <dl className={styles.metadata}><div><dt>业务日期</dt><dd>{item.business_date || "未填写"}</dd></div><div><dt>业务单号</dt><dd>{item.business_number || "未填写"}</dd></div><div><dt>当前状态</dt><dd>{statusName[item.status]} · 修订 {item.revision}</dd></div><div><dt>备注</dt><dd>{withoutTableBaseline(item.notes) || "—"}</dd></div></dl>
    {kind === "shipments" && (item.cartons!=null || item.dispatch_purpose!=="WAREHOUSE_DISPATCH") && <section className={styles.panel} aria-label="目的地与装箱"><h2>目的地与装箱</h2><dl className={styles.metadata}><div><dt>本批实际目的地</dt><dd>{item.destination || "历史记录未填写"}</dd></div><div><dt>装箱情况</dt><dd>{item.cartons == null ? "历史记录未提供" : `${item.cartons.length}箱`}</dd></div></dl><p className={styles.secondary}>{item.status === "DRAFT" ? "装箱草稿尚未扣库存或计入订单已发。" : item.status === "VOID" ? "原目的地和箱明细保留供历史核对。" : "已确认本批发货，不表示目的仓已签收。"}</p>{item.cartons?.length ? <Table title="本批装箱明细"><thead><tr><th>箱号</th><th>商品规格</th><th>件数</th></tr></thead><tbody>{item.cartons.flatMap((box, index) => box.items.map((line, n) => <tr key={`${box.id || index}:${n}`}><th scope="row">{box.number}</th><td>{catalog.find(sku => sku.sku_id === line.sku_id)?.code || item.sources?.find(source => source.sku_id === line.sku_id)?.sku_label || `SKU ${line.sku_id}`}</td><td>{units(line.units)}</td></tr>))}</tbody></Table> : <p>{item.cartons == null ? "旧资料没有箱明细，不能推定为零箱。" : "尚未填写箱明细。"}</p>}</section>}
    <section className={styles.panel}><details><summary>资料来源</summary><p>{item.source_system ? `${item.source_system} · ${item.source_event_kind} · ${item.external_event_id}${item.source_batch ? ` · 批次 ${item.source_batch}` : ""}` : "未登记可靠外部来源"}</p><p>{item.manual_source_note || "未记录人工来源说明"}</p>{kind === "shipments" && <><p>{item.dispatch_purpose === "WAREHOUSE_DISPATCH" ? item.sources?.some(source=>source.allocations.length) ? "仓库出货，按已确认分配累计订单进度。" : "独立仓库批次，不改变生产订单数量。" : item.status === "VOID" ? item.stock_tracked ? `原仓库出货影响已撤销 · 仓库${item.warehouse_id}` : "原单据已作废，不影响当前库存" : item.sources?.some(source => source.fulfillment_mode !== "PRODUCTION_DIRECT") ? item.status === "DRAFT" ? `拟从仓库${item.warehouse_id}出货，草稿尚未扣库存` : `仓库出货明细已联动库存 · 仓库${item.warehouse_id}` : "全部明细为生产直发，不进入或扣减仓库库存"}</p><p>用途：{item.dispatch_purpose === "WAREHOUSE_DISPATCH" ? item.sources?.some(source=>source.allocations.length) ? "仓库出货（已关联来源订单）" : "仓库独立出货（不关联生产订单）" : item.dispatch_purpose === "LOGISTICS_TRANSFER" ? "独立仓间发运（不累计生产订单已发）" : item.dispatch_purpose === "OUTWARD_ORDER" ? item.status === "VOID" ? "原登记为订单对外发运（现已作废）" : item.status === "DRAFT" ? "拟登记订单对外发运（尚未确认交接）" : "订单对外发运（已交接）" : "用途未核对（仅演示兼容），不代表真实发运凭据"}</p></>}</details></section>
    {kind === "orders" ? <Table title="SKU预计与出货"><thead><tr><th>SKU</th><th>预计</th><th>有效累计出货</th><th>差额</th><th>跟进状态</th><th>待跟进</th></tr></thead><tbody>{item.lines?.map(line => <tr key={line.id}><td>{line.sku_label}</td><td>{units(line.expected_units)}</td><td>{units(line.actual_units)}</td><td>{units(line.difference_units)}</td><td>{voidOrder ? "已作废" : trackingName[line.tracking_state || "OPEN"]}</td><td>{voidOrder ? "不适用（已作废）" : units(line.pending_units)}</td></tr>)}</tbody></Table> : item.dispatch_purpose === "WAREHOUSE_DISPATCH" ? <WarehouseDispatchFacts document={item} catalog={catalog} /> : item.sources?.map((source, index) => <Table key={source.id ?? index} title={`${source.sku_label} · 本次 ${units(source.actual_units)} 件`} description={source.fulfillment_mode === "PRODUCTION_DIRECT" ? "生产完成后直接出货：计入订单实际已发，不影响仓库库存。" : "仓库库存出货：确认后核对并扣减当前可发库存。下方为订单分配。"}><thead><tr><th>系统订单</th><th>分配数量</th></tr></thead><tbody>{source.allocations.map(a => <tr key={a.order_line_id}><td><Link to={`/production/orders/${a.order_id}`}>{a.order_number}</Link></td><td>{units(a.units)}</td></tr>)}{!source.allocations.length && <tr><td colSpan={2}>{item.dispatch_purpose === "WAREHOUSE_DISPATCH" ? "独立仓库批次，无需分配生产订单。" : item.dispatch_purpose === "LOGISTICS_TRANSFER" ? "独立仓间发运，无生产订单分配。" : "未分配，确认前需要完成订单归属。"}</td></tr>}</tbody></Table>)}
    {kind === "shipments" && item.sources?.some(source => !!source.plan_id) && <p>关联预计出库安排：{item.sources.filter(source => !!source.plan_id).map(source => <span key={source.id}><Link to={`/production/stock/plans#plan-${source.plan_id}`}>{source.sku_label} · 安排 {source.plan_id}</Link>{" "}</span>)}</p>}
    {!!item.shipments?.length && <section className={styles.panel}><h2>关联出货</h2>{item.shipments.map(s => <p key={s.id}><Link to={`/production/shipments/${s.id}`}>{s.system_number}</Link> · {s.business_date} · {statusName[s.status]}</p>)}</section>}
    {!!item.file_sources?.length && <section className={styles.panel}><h2>文件来源</h2>{item.file_sources.map(f => <p key={f.preview_id}>{f.filename}<small className={styles.secondary}>{f.digest}</small></p>)}</section>}
    {!!item.history?.length && <RevisionHistory history={item.history} />}
  </>;
}
export function SummaryContent({ summary }: { summary: Summary }) {
  const actualLabel = summary.shipment_period_filtered ? "本期间出货" : "累计已发";
  const differenceLabel = summary.shipment_period_filtered ? "期间差额" : "累计差额";
  const basis = summary.shipment_period_filtered ? "期间差额＝预计－本期间出货，不是剩余需求。当前待跟进按全部累计出货与关闭状态计算。" : "预计量按订单日期，出货量为这些订单的全部有效累计出货；当前待跟进也按全部累计计算。差额不表示库存。";
  return <><QuantityOverview expected={summary.expected_units} actual={summary.actual_units} difference={summary.difference_units} actualLabel={summary.shipment_period_filtered ? "本期间出货" : "有效累计出货"} differenceLabel={summary.shipment_period_filtered ? "预计与本期间出货差额" : undefined} />
    {summary.shipment_period_filtered && <dl className={styles.metrics}><div><dt>全部有效累计出货</dt><dd>{units(summary.cumulative_actual_units)}<small>件</small></dd></div><div><dt>预计与全部累计出货差额</dt><dd>{units(summary.cumulative_difference_units)}<small>件</small></dd></div></dl>}
    {summary.pending_units !== undefined && <FollowupQuantities pending={summary.pending_units} closed={summary.closed_units} overage={summary.overage_units} />}
    <div className={styles.desktopList}><Table title="订单与SKU明细" description={basis} className={styles.summaryTable}>
      <colgroup><col className={styles.summaryIdentityColumn} /><col /><col /><col /><col /></colgroup>
      <thead><tr><th>订单 / 商品</th><th>预计</th><th>{actualLabel}</th><th>{differenceLabel}</th><th>待跟进</th></tr></thead>
      <tbody>{summary.items.map(line => <tr key={line.id}><td><div className={styles.summaryIdentity}><RecordIdentity kind="orders" document={{ id: line.order_id, system_number: line.order_number }} /><ProductIdentity label={line.sku_label} /></div></td><td>{units(line.expected_units)}</td><td>{units(line.actual_units)}</td><td>{units(line.difference_units)}</td><td>{units(line.pending_units)}</td></tr>)}{!summary.items.length && <tr><td colSpan={5}>当前条件下没有已确认订单。</td></tr>}</tbody>
    </Table></div>
    <section className={styles.mobileList} aria-label="订单与SKU明细"><h2>订单与SKU明细</h2><p>{basis}</p><ul>{summary.items.map(line => <li key={line.id}><RecordIdentity kind="orders" document={{ id: line.order_id, system_number: line.order_number }} /><ProductIdentity label={line.sku_label} /><dl><div><dt>预计</dt><dd>{units(line.expected_units)}件</dd></div><div><dt>{actualLabel}</dt><dd>{units(line.actual_units)}件</dd></div><div><dt>{differenceLabel}</dt><dd>{units(line.difference_units)}件</dd></div><div><dt>待跟进（全部累计）</dt><dd>{units(line.pending_units)}件</dd></div></dl></li>)}</ul>{!summary.items.length && <p>当前条件下没有已确认订单。</p>}</section>
    <div className={styles.desktopList}><Table title="SKU合计" className={`${styles.summaryTable} ${styles.skuTotalsTable}`}>
      <colgroup><col className={styles.summaryIdentityColumn} /><col /><col /><col /></colgroup>
      <thead><tr><th>商品与规格</th><th>预计</th><th>{actualLabel}</th><th>{differenceLabel}</th></tr></thead>
      <tbody>{summary.skus.map(sku => <tr key={sku.sku_id}><td><ProductIdentity label={sku.sku_label} /></td><td>{units(sku.expected_units)}</td><td>{units(sku.actual_units)}</td><td>{units(sku.difference_units)}</td></tr>)}{!summary.skus.length && <tr><td colSpan={4}>当前条件下没有SKU汇总。</td></tr>}</tbody>
    </Table></div>
    <section className={styles.mobileList} aria-label="SKU合计"><h2>SKU合计</h2><ul>{summary.skus.map(sku => <li key={sku.sku_id}><ProductIdentity label={sku.sku_label} /><dl><div><dt>预计</dt><dd>{units(sku.expected_units)}件</dd></div><div><dt>{actualLabel}</dt><dd>{units(sku.actual_units)}件</dd></div><div><dt>{differenceLabel}</dt><dd>{units(sku.difference_units)}件</dd></div></dl></li>)}</ul>{!summary.skus.length && <p>当前条件下没有SKU汇总。</p>}</section>
  </>;
}

export function FollowupQuantities({ pending, closed, overage }: { pending: string; closed?: string; overage?: string }) {
  const noExceptions = closed === "0" && overage === "0";
  return <section className={styles.followup}><dl className={styles.metrics}><div><dt>当前待跟进（全部累计）</dt><dd>{units(pending)}<small>件</small></dd></div>{!noExceptions && <><div><dt>当前关闭剩余</dt><dd>{units(closed)}<small>件</small></dd></div><div><dt>超发量（按SKU行）</dt><dd>{units(overage)}<small>件</small></dd></div></>}</dl>{noExceptions && <details><summary>关闭剩余0件 · 超发0件 · 查看口径</summary><p>关闭不改变预计与已发数量；待跟进按全部有效累计出货计算。不同SKU的不足与超发分别核对。</p></details>}</section>;
}

function ImportedDocumentReview({item,kind}:{item:Document;kind:Kind}){
  const audit=useTableBaseline(item.notes,kind==="orders"?"orders":"packing");
  const rows=kind==="orders"?[{key:"document",label:"订单信息",values:{"下单日期":item.business_date || "","业务订单号":item.business_number || ""}},...(item.lines || []).map(line=>({key:line.sku_id,label:line.sku_label,values:{"下单数量":line.expected_units}}))]:(item.sources || []).map(source=>({key:source.sku_id,label:source.sku_label || source.sku_id,values:{"出货数量":source.actual_units,"装箱分配":(item.cartons || []).flatMap(box=>box.items.filter(line=>line.sku_id===source.sku_id).map(line=>`${box.number}：${line.units}`)).sort().join("；")}}));
  return <>{audit.feedback}<TableImportReview baseline={audit.baseline} rows={rows}/></>;
}
