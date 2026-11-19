import { Navigate, Link, useLocation, useSearchParams } from "react-router-dom";
import { LinkButton, Button, PageHeader, StatusMessage  } from "../../design-system";
import { ManualTablePage } from "../manual-tables/ManualTablePage";
import type { ManualKind } from "../manual-tables/manualTablesApi";
import { ShipmentEntry } from "./ShipmentEntry";
import { SourceDraftManager } from "./SourceDraftManager";
import styles from "./Production.module.css";

const businesses = {
  orders: { title: "新增订单", label: "订单", home: "/production/orders", manual: "/production/orders/new", note: "预计需求不会增减实际库存。" },
  packing: { title: "新建出货单", label: "出货", home: "/production/shipments", manual: "/production/shipments/new", note: "核对实际发运数量，确认时按当前可发库存校验。" },
  inventory: { title: "更新库存", label: "库存", home: "/production/stock", manual: "/production/stock/movements/new?kind=ADJUST", note: "仓库表先核对差异，不会直接覆盖库存账；出货后结存不能再扣同批出货。" },
} as const;

export function ProductionImportCenter({ canWrite, records = false, business }: { canWrite: boolean; records?: boolean; business?: ManualKind }) {
  const [params, setParams] = useSearchParams();
  const { pathname } = useLocation();
  const requestedKind = params.get("kind");
  const kind = business ?? (requestedKind && Object.hasOwn(businesses, requestedKind) ? requestedKind as ManualKind : undefined);
  if (business === "packing" && !records && params.get("method") === "table") {
    const query=new URLSearchParams(params);query.set("flow","guided");query.set("purpose","WAREHOUSE_DISPATCH");return <Navigate replace to={`/production/shipments/new?${query}`}/>;
  }
  if (business === "packing" && !records && !params.get("method")) return <ShipmentEntry canWrite={canWrite} />;
  if (!records && params.get("layout") !== "raw" && (kind === "orders" || kind === "inventory")) {
    const next=new URLSearchParams(params);next.delete("method");
    if(kind==="inventory")next.set("kind","ADJUST");
    return <Navigate replace to={`${kind==="orders"?"/production/orders/new":"/production/stock/movements/new"}?${next}`}/>;
  }
  const manualEnabled = import.meta.env.VITE_MANUAL_TABLES_ENABLED === "true";
  if (!kind) return <><PageHeader title={records ? "选择要查看的业务记录" : "选择要办理的业务"} description="资料导入已归入对应业务。原资料和处理记录继续保留。" /><div className={styles.workflowQuickActions}>{Object.entries(businesses).map(([key, value]) => <Link key={key} to={`${value.home}/${records ? "materials" : "intake"}`}>{records ? `${value.label}资料记录` : value.title}</Link>)}</div></>;
  const info = businesses[kind];
  const legacy = params.get("source") === "legacy";
  const method = params.get("method") ?? (pathname.startsWith("/production/imports") ? "table" : "");
  const updateParams = (patch: Record<string, string>) => { const next = new URLSearchParams(params); for (const [key, value] of Object.entries(patch)) { if (value) next.set(key, value); else next.delete(key); } setParams(next); };
  return <div className={styles.importCenter}>
    <PageHeader title={records ? `${info.label}资料` : info.title} description={records ? "查看处理进度，继续核对，或打开已经生成的业务记录。原件和修订历史保留。" : info.note} actions={<LinkButton to={info.home}>返回{kind === "inventory" ? "库存总览" : `${info.label}记录`}</LinkButton>} />
    {records ? <>
      {kind === "inventory" ? <p className={styles.workflowNote}>已生成的库存核对单请从下方对应资料打开。<Link to="/production/inventory/source">查看已有库存原表</Link></p> : <div className={styles.actions} aria-label="记录来源"><Button aria-pressed={!legacy} onClick={() => updateParams({ source: "" })}>人工表格</Button><Button aria-pressed={legacy} onClick={() => updateParams({ source: "legacy" })}>已有旧格式资料</Button></div>}
      {legacy && kind !== "inventory" ? <SourceDraftManager canWrite={canWrite} recordsOnly initialKind={kind === "orders" ? "orders" : "shipments"} /> : canWrite && manualEnabled ? <ManualTablePage key={kind} view="records" initialKind={kind} /> : <StatusMessage kind="info" title="整理资料暂不可查看">人工整理需管理员或数据管理员账号，且当前环境已启用该功能；业务记录仍可从上方返回查看。</StatusMessage>}
    </> : !canWrite ? <StatusMessage kind="info" title="当前账号只读">可以返回业务记录查看；上传、保存和确认需管理员或数据管理员账号。</StatusMessage> : <>
      <div className={styles.intakeMethods} aria-label="录入方式"><Link className={styles.intakeMethod} to={info.manual}><strong>{kind === "inventory" ? "手工盘点调整" : "手工填写"}</strong><span>{kind === "inventory" ? "已核实具体规格的实际数量，登记盘点变动。" : "直接选择商品、填写数量和业务信息。"}</span></Link><Button className={styles.intakeMethod} variant="secondary" aria-expanded={method === "table"} aria-controls="manual-table-upload" data-selected={method === "table"} onClick={() => updateParams({ method: "table" })}><strong>从表格导入</strong><span>{kind === "inventory" ? "上传仓库库存表，先核对再继续处理。" : kind === "orders" ? "上传下单表或出货安排，生成预计订单草稿。" : "上传实际装箱单，核对后生成出货草稿。"}</span></Button></div>
      {method === "table" && <div id="manual-table-upload">
        {kind === "orders" && <div className={styles.actions}><LinkButton variant="primary" to="/production/orders/new?method=table">使用最新版下单表</LinkButton><p>读取下单日期、款号、SKU、订单数量，支持最新四列模板及原八列表。下方保留其他排版原表的人工整理。</p></div>}
        <ol className={styles.workflowSteps} aria-label="资料处理步骤"><li aria-current="step">1 上传表格</li><li>2 核对并保存</li><li>3 确认{info.label}结果</li></ol>
        {manualEnabled ? <ManualTablePage key={kind} view="upload" initialKind={kind} /> : <StatusMessage kind="info" title="此环境尚未启用人工表格整理">已有标准模板与旧格式入口继续可用。</StatusMessage>}
        <details className={styles.workflowTools}><summary>标准模板与已适配格式</summary><p>已有格式保持原规则。亚马逊官方经营、退货报告仍使用原报表入口。</p><div className={styles.actions}>{kind !== "inventory" ? <><Link to={`${info.home}/import`}>使用标准模板导入</Link><Link to={`/production/source-drafts?kind=${kind === "orders" ? "orders" : "shipments"}`}>上传已适配旧格式</Link></> : <Link to="/production/inventory/source">查看已有库存原表</Link>}</div></details>
      </div>}
      <p className={styles.workflowNote}><Link to={`${info.home}/materials`}>查看{info.label}资料记录</Link></p>
    </>}
  </div>;
}
