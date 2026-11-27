import { Disclosure } from "../../design-system";
import { ProductionConfirmDialog } from "./ProductionConfirmDialog";
import { useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ChevronRight, Factory, Pencil, Plus, Search, Warehouse } from "lucide-react";
import { Button, Dialog, FormField, Input, LinkButton, Pagination, StatusMessage, Table } from "../../design-system";
import { useLoad, useCommand, useSearchDraft } from "./useProductionApi";
import { useProductionLeave } from "./useProductionLeave";
import { ReadContent, ReadState } from "./WorkbenchFields";
import { type DirectoryRecord, type DirectoryPage, warehouseTypes, inventoryStates } from "./directoryTypes";
import { type DocumentPage, units } from "./types";
import { WarehouseCenter } from "./WarehouseCenter";
import styles from "./DirectoryWorkspace.module.css";
import { WarehouseOpeningDialog } from "./WarehouseOpening";
import { countries, FactoryRegionPicker } from "./FactoryRegionPicker";

type DirectoryKind = "factories" | "warehouses";
const base = "/api/production/";
const warehouseCountries = [
  "中国",
  "美国",
  ...countries.filter(country => country !== "中国" && country !== "美国")
    .sort((left, right) => left.localeCompare(right, "zh-Hans-CN-u-co-pinyin")),
];
function State({ record }: { record: DirectoryRecord }) {
  return <span className={`${styles.badge} ${record.status === "INACTIVE" || record.inventory_state === "NOT_CONNECTED" ? styles.mutedBadge : record.inventory_state === "READY" || !record.type ? styles.ready : styles.pending}`}>{record.status === "INACTIVE" ? "已停用" : inventoryStates[record.inventory_state || ""] || "启用"}</span>;
}
export function DirectoryWorkspace({ kind, canWrite }: { kind: DirectoryKind; canWrite: boolean }) {
  const capability = useLoad<{ directory_supported?: boolean }>(`${base}workbench`);
  if (!capability.value) return <ReadState error={capability.error} />;
  if (!capability.value.directory_supported) return <StatusMessage kind="info" title="当前服务尚未接入仓库与工厂管理">此环境不会自动升级或迁移。<Link to="/production/stock">继续使用原库存入口</Link></StatusMessage>;
  return kind === "warehouses" ? <WarehouseDirectory canWrite={canWrite} /> : <DirectoryContent canWrite={canWrite} />;
}
function DirectoryContent({ canWrite }: { canWrite: boolean }) {
  const [params, setParams] = useSearchParams(); const { directoryId } = useParams(); const navigate = useNavigate();
  const appliedQuery = params.get("q") || "";
  const [query, setQuery] = useSearchDraft(appliedQuery); const [refresh, setRefresh] = useState(0);
  const [editing, setEditing] = useState<DirectoryRecord | "new">(); const [notice, setNotice] = useState(""); const trigger = useRef<HTMLButtonElement>(null);
  const list = useLoad<DirectoryPage>(`${base}factories?${new URLSearchParams({ q: params.get("q") || "", status: params.get("status") ?? "ACTIVE", page: params.get("page") || "1" })}`, refresh, true, true);
  const selectedId = directoryId || list.value?.items[0]?.id;
  const detail = useLoad<DirectoryRecord>(`${base}factories/${selectedId}`, refresh, !!selectedId, true);
  function filter(values: Record<string, string>) { const next = new URLSearchParams(params); for (const [key, value] of Object.entries(values)) next.set(key, value); next.delete("tab"); setParams(next); }
  function saved(value: DirectoryRecord) { setEditing(undefined); setNotice("资料已保存，库存与历史单据未被改写。"); setRefresh(r => r + 1); void navigate(`/production/factories/${value.id}`); }
  return <section className={styles.workspace}>
    {notice && <StatusMessage kind="success" title={notice} />}
    {list.value && list.error && <StatusMessage kind="warning" title="工厂列表更新失败">{list.error}</StatusMessage>}
    <div className={styles.masterDetail}><aside className={styles.factoryList}>
      <header className={styles.directoryHeading}><div><h2>工厂管理</h2></div>{canWrite && <Button ref={trigger} variant="primary" icon={<Plus />} onClick={() => setEditing("new")}>新建工厂</Button>}</header>
      <form className={styles.filters} onSubmit={e => { e.preventDefault(); filter({ q: query.trim(), page: "1" }); }}><div className={styles.search}><Search aria-hidden="true" /><Input aria-label="搜索工厂名称或编号" type="search" placeholder="搜索工厂名称或编号" value={query} onChange={e => setQuery(e.target.value)} /><Button variant="quiet" type="submit">查找</Button></div><FormField label="状态"><select value={params.get("status") ?? "ACTIVE"} onChange={e => filter({ status: e.target.value, page: "1" })}><option value="">全部状态</option><option value="ACTIVE">启用中</option><option value="INACTIVE">已停用</option></select></FormField></form>
      {list.value ? <><div className={styles.factoryItems}>{list.value.items.map(f => <Link key={f.id} aria-current={selectedId === f.id ? "page" : undefined} to={`/production/factories/${f.id}?${params}`}><strong>{f.name}</strong><span>F-{f.id} <small>待跟进 {f.open_order_count || "0"} 单</small></span><span>{f.region || "地区未填写"}{f.status === "INACTIVE" ? " · 已停用" : ""}</span></Link>)}{!list.value.items.length && <p className={styles.empty}>没有匹配的工厂，试试其他名称或状态。</p>}</div><Pagination page={list.value.page} totalItems={list.value.total} totalPages={Math.max(1, Math.ceil(list.value.total / 50))} onPageChange={page => filter({ page: String(page) })} /></> : <ReadState error={list.error} />}
    </aside><div className={styles.detail}>{selectedId ? detail.value?.id === selectedId ? <ReadContent loading={detail.loading} error={detail.error} retry={() => setRefresh(r => r + 1)}><FactoryDetail key={selectedId} record={detail.value} canWrite={canWrite} edit={() => setEditing(detail.value)} refresh={refresh} /></ReadContent> : <ReadState error={detail.error} /> : !list.value ? <ReadState error={list.error} /> : <div className={styles.empty}><Factory /><h2>从一家工厂开始</h2><p>新建档案或调整筛选后选择工厂。</p></div>}</div></div>
    {editing && <DirectoryEditor key={typeof editing === "string" ? "new" : `factories:${editing.id}:${editing.revision}`} kind="factories" initial={editing === "new" ? undefined : editing} onSaved={saved} onClose={() => setEditing(undefined)} returnFocusTarget={trigger} />}
  </section>;
}
function WarehouseDirectory({ canWrite }: { canWrite: boolean }) {
  const [opening,setOpening]=useState<DirectoryRecord>();
  const [refresh, setRefresh] = useState(0); const [editing, setEditing] = useState<DirectoryRecord | "new">(); const [notice, setNotice] = useState(""); const trigger = useRef<HTMLButtonElement>(null); const navigate = useNavigate();
  return <section className={styles.workspace}>{notice && <StatusMessage kind="success" title={notice} />}
    <WarehouseCenter canWrite={canWrite} refresh={refresh} reload={() => setRefresh(r => r + 1)} edit={setEditing} createRef={trigger} />
    {editing && <DirectoryEditor key={typeof editing === "string" ? "new" : `warehouse:${editing.id}:${editing.revision}`} kind="warehouses" initial={editing === "new" ? undefined : editing} returnFocusTarget={trigger} onClose={() => setEditing(undefined)} onSaved={(value, withOpening) => { setEditing(undefined); if(withOpening)setOpening(value); setNotice("资料已保存，库存与历史单据未被改写。"); setRefresh(r => r + 1); void navigate(`/production/warehouses/${value.id}?tab=profile`); }} />}
    {opening&&<WarehouseOpeningDialog warehouseId={opening.id} name={opening.name} close={()=>setOpening(undefined)} saved={()=>{setOpening(undefined);setRefresh(r=>r+1);void navigate(`/production/warehouses/${opening.id}?tab=stock`);}}/>}
  </section>;
}
function Profile({ record }: { record: DirectoryRecord }) {
  return <><dl className={styles.profile}>{[["编号", record.id], ["地区", [record.country, record.region].filter(Boolean).join(" · ")], ["运营方", record.operator], ["联系人", record.contact], ["联系方式", record.phone], ["地址", record.address], ["备注", record.notes], [record.type ? "外部仓码" : "外部编号", record.external_code], ["时区", record.timezone], ["卖家账号 / 站点", [record.seller_account, record.marketplace].filter(Boolean).join(" / ")]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || "未填写"}</dd></div>)}</dl><Disclosure className={styles.help}><summary>资料变更记录（最近100次）</summary>{record.history?.map(h => <article key={h.revision}><h3>修订 {h.revision} · {h.actor_name || "操作人待核"}</h3><p>{h.reason} · {h.created_at}</p><Disclosure><summary>查看前后值</summary><pre>{JSON.stringify({ 修改前: h.before_value, 修改后: h.after_value }, null, 2)}</pre></Disclosure></article>)}</Disclosure></>;
}
function FactoryDetail({ record, canWrite, edit, refresh }: { record: DirectoryRecord; canWrite: boolean; edit: () => void; refresh: number }) {
  const [params, setParams] = useSearchParams(); const tab = params.get("tab") || "orders"; const [query, setQuery] = useState(""); const [page, setPage] = useState(1); const [status, setStatus] = useState("");
  const orders = useLoad<DocumentPage>(`${base}orders?${new URLSearchParams({ factory: record.id, q: query, status, page: String(page), page_size: "20" })}`, refresh);
  return <><header className={styles.heading}><h1>{record.name} <State record={record} /></h1>{canWrite && <Button variant="secondary" icon={<Pencil />} onClick={edit}>编辑资料 / 停用</Button>}</header><dl className={styles.summary}><div><dt>工厂编号</dt><dd>F-{record.id}</dd></div><div><dt>所在地</dt><dd>{record.region || "未填写"}</dd></div><div><dt>联系人</dt><dd>{record.contact || "未填写"}</dd></div></dl><nav className={styles.tabs} aria-label="工厂详情">{[["orders", "生产订单"], ["warehouses", "常用仓库"], ["profile", "基本资料与记录"]].map(([key, label]) => <Button key={key} variant="quiet" aria-pressed={tab === key} onClick={() => { const next = new URLSearchParams(params); next.set("tab", key!); setParams(next); }}>{label}</Button>)}</nav>
    {tab === "profile" ? <Profile record={record} /> : tab === "warehouses" ? <LinkedRecords kind="warehouses" ids={record.warehouse_ids || []} /> : <><div className={styles.filters}><Input aria-label="搜索本厂订单" type="search" placeholder="搜索订单号或SKU" value={query} onChange={e => { setQuery(e.target.value); setPage(1); }} /><select aria-label="本厂订单状态" value={status} onChange={e => { setStatus(e.target.value); setPage(1); }}><option value="">全部状态</option><option value="CONFIRMED">已确认</option><option value="DRAFT">草稿</option><option value="VOID">已作废</option></select>{canWrite && record.status === "ACTIVE" && <LinkButton to={`/production/orders/new?factory=${record.id}`} icon={<Plus />}>下生产单</LinkButton>}</div><h2>生产订单（{orders.value?.total ?? "…"}）</h2>{orders.value ? <><Table aria-label="本厂生产订单"><thead><tr><th>生产单号 / 日期</th><th>下单件数</th><th>已生产</th><th>已入库</th><th>已出货</th><th>操作</th></tr></thead><tbody>{orders.value.items.map(o => <tr key={o.id}><td>{o.business_number || o.system_number}<small>{o.business_date} · {o.status === "DRAFT" ? "草稿" : o.status === "VOID" ? "已作废" : "已确认"}</small></td><td>{units(o.expected_units || "0")}</td><td>{o.lines?.some(l => l.produced_units == null) ? "待登记 / 部分未知" : units((o.lines || []).reduce((sum, l) => sum + BigInt(l.produced_units || "0"), 0n).toString())}</td><td>{units(o.received_units || "0")}</td><td>{units(o.actual_units)}</td><td><LinkButton variant="primary" to={`/production/orders/${o.id}?factory=${record.id}`}>继续跟进</LinkButton></td></tr>)}{!orders.value.items.length && <tr><td colSpan={6}>当前筛选没有生产单。新建工厂不会自动产生订单。</td></tr>}</tbody></Table><Pagination page={page} totalItems={orders.value.total} totalPages={Math.max(1, Math.ceil(orders.value.total / 20))} onPageChange={setPage} /></> : <ReadState error={orders.error} />}</>}
    <StatusMessage kind="info" title="一张生产单交给一家工厂">工厂与仓库分别管理；停用后旧订单仍可查，不能用于承接新单。待跟进数指含开放明细的已确认订单，不是SKU数量。</StatusMessage></>;
}
function LinkedRecords({ kind, ids }: { kind: DirectoryKind; ids: string[] }) {
  return ids.length ? <ul className={styles.links}>{ids.map(id => <LinkedRecord key={id} kind={kind} id={id} />)}</ul> : <p className={styles.empty}>尚未关联。可以在编辑资料中补充，不按名称自动猜测。</p>;
}
function LinkedRecord({ kind, id }: { kind: DirectoryKind; id: string }) {
  const record = useLoad<DirectoryRecord>(`${base}${kind}/${id}`);
  const name = record.value?.name || `编号 ${id}`;
  const Icon = kind === "warehouses" ? Warehouse : Factory;
  return <li><Link className={styles.linkedRecord} aria-label={name} to={`/production/${kind}/${id}`}><Icon aria-hidden="true" /><span><strong>{name}</strong><small>{record.value?.type ? warehouseTypes[record.value.type] : record.value?.region || "地区待填写"}</small></span>{record.value && <State record={record.value} />}<ChevronRight size={16} aria-hidden="true" /></Link>{record.error && <ReadState error={record.error} />}</li>;
}


function DirectoryEditor({ kind, initial, onSaved, onClose, returnFocusTarget }: { kind: DirectoryKind; initial?: DirectoryRecord; onSaved: (r: DirectoryRecord, withOpening?: boolean) => void; onClose: () => void; returnFocusTarget: React.RefObject<HTMLButtonElement | null> }) {
  const [withOpening,setWithOpening]=useState(false);
  const sourceScopes=useLoad<{scopes:{id:number;seller_account_display_name:string;marketplace_scope_code:string}[]}>('/api/catalog/production-sources/capabilities');
  const factories = kind === "factories"; const [values, setValues] = useState<Record<string, string>>(Object.fromEntries(["name", "region", "address", "operator", "contact", "phone", "timezone", "seller_account", "marketplace", "country", "notes", "external_code"].map(k => [k, typeof initial?.[k as keyof DirectoryRecord] === "string" ? initial[k as keyof DirectoryRecord] as string : ""])));
  const [status, setStatus] = useState(initial?.status || "ACTIVE"); const [type, setType] = useState(initial?.type || "OWN"); const [reason, setReason] = useState(""); const [dirty, setDirty] = useState(false); const [closing, setClosing] = useState(false);
  const relationKey = factories ? "warehouse_ids" : "factory_ids"; const relatedKind = factories ? "warehouses" : "factories";
  const [links, setLinks] = useState(initial?.[relationKey] || []); const [query, setQuery] = useState(""); const [page, setPage] = useState(1);
  const related = useLoad<DirectoryPage>(`${base}${relatedKind}?status=&q=${encodeURIComponent(query)}&page=${page}`);
  const command = useCommand<DirectoryRecord>(value => { leave.allowLeave(); onSaved(value,withOpening&&!factories&&!initial&&["中国","CN","China"].includes(values.country||"")&&["FACTORY","OWN","THIRD_PARTY"].includes(type)); }); const leave = useProductionLeave(dirty, command.busy, command.unknown);
  function close() { if (command.busy || command.unknown) return; if (dirty) setClosing(true); else onClose(); }
  const field = (key: string, label: string, max = 255) => <FormField key={key} label={label}><Input maxLength={max} value={values[key]} onChange={e => setValues(v => ({ ...v, [key]: e.target.value }))} /></FormField>;
  const statusField = <FormField label="状态"><select value={status} onChange={e => setStatus(e.target.value)}><option value="ACTIVE">启用</option><option value="INACTIVE">停用（历史保留）</option></select></FormField>;
  const relations = <div className={styles.relations}>
    {factories && <p className={styles.relationHelp}>登记这家工厂经常送货的仓库，方便查阅。不代表仓库归工厂所有；下单时仍需单独选择入库仓，不会自动入库或改变库存、货权。</p>}
    <Input aria-label="查找关联资料" type="search" value={query} placeholder="搜索名称或编号" onChange={e => { setQuery(e.target.value); setPage(1); }} />
    <p>{factories ? `已选 ${links.length} 个常用仓库，可多选，也可暂不选择。` : `已选编号：${links.join("、") || "暂无"}。关联不转移货权，也不重复计算库存。`}</p>
    {links.filter(id => !related.value?.items.some(r => r.id === id)).map(id => <label key={id}><input type="checkbox" checked onChange={() => setLinks(v => v.filter(x => x !== id))} />已选编号 {id}（本页外）</label>)}
    {related.value?.items.map(r => <label key={r.id}><input type="checkbox" checked={links.includes(r.id)} onChange={e => setLinks(v => e.target.checked ? [...v, r.id] : v.filter(x => x !== r.id))} /><span>{r.name}{r.status === "INACTIVE" ? "（停用）" : ""}{factories && <small>{warehouseTypes[r.type || ""] || "仓库"} · W-{r.id}</small>}</span></label>)}
    {!related.value && !related.error && <p>正在读取可选资料…</p>}
    {related.value && !related.value.items.length && <p>没有匹配的资料，请调整搜索；也可以暂不选择。</p>}
    {related.error && <ReadState error={related.error} />}
    {related.value && related.value.total > 50 && <Pagination page={page} totalItems={related.value.total} totalPages={Math.ceil(related.value.total / 50)} onPageChange={setPage} />}
  </div>;
  return <Dialog open dismissDisabled={command.busy || command.unknown} contentClassName={styles.factoryDialog} onOpenChange={open => { if (!open) close(); }} returnFocusTarget={returnFocusTarget} size="large" title={`${initial ? "编辑" : "新建"}${factories ? "工厂" : "仓库 / 地点"}`} >
    <form className={`${styles.editor} ${styles.factoryEditor}`} onChangeCapture={() => setDirty(true)} onSubmit={e => { e.preventDefault(); command.submit(`${base}${kind}${initial ? `/${initial.id}` : ""}`, { ...values, status, ...(factories ? {} : { type }), [relationKey]: links, ...(initial ? { expected_revision: initial.revision, reason } : {}) }, initial ? "PUT" : "POST"); }}>
      <fieldset disabled={command.busy || command.unknown}>
        {factories ? <>
          <section className={styles.factorySection}>
            <FormField label="工厂全名" required><Input required maxLength={120} autoComplete="organization" placeholder="填写工厂的完整名称" value={values.name} onChange={e => setValues(v => ({ ...v, name: e.target.value }))} /></FormField>
            <FactoryRegionPicker value={values.region || ""} onChange={region => { setValues(v => ({ ...v, region })); setDirty(true); }} />
            <div className={styles.formGrid}>{field("contact", "联系人")}{field("phone", "联系方式")}</div>
            {field("address", "详细地址", 500)}
          </section>
          <Disclosure className={styles.factoryDisclosure}><summary>更多资料（选填）<span>{status === "ACTIVE" ? "启用中" : "已停用"}</span></summary>
            <div className={styles.disclosureBody}><div className={styles.formGrid}>{statusField}{field("operator", "运营方（不是货主）")}{field("timezone", "时区（例如 Asia/Shanghai）")}{field("external_code", "外部编号（可选）")}</div>{field("notes", "备注", 2000)}</div>
          </Disclosure>
          <Disclosure className={styles.factoryDisclosure}><summary>常用仓库（选填）<span>{links.length ? `已选 ${links.length} 个` : "暂不选择也能建厂"}</span></summary>{relations}</Disclosure>
        </> : <>
          <section className={styles.factorySection}>
            <FormField label="仓库 / 地点名称" required><Input required maxLength={120} placeholder="填写便于辨认的完整名称" value={values.name} onChange={e => setValues(v => ({ ...v, name: e.target.value }))} /></FormField>
            <div className={styles.formGrid}>
              <FormField label="类型" required><select disabled={!!initial && initial.type !== "UNCLASSIFIED"} value={type} onChange={e => setType(e.target.value)}>{Object.entries(warehouseTypes).filter(([k]) => k !== (initial?.type === "FACTORY" ? "OWN" : "FACTORY") && (k !== "UNCLASSIFIED" || !!initial)).map(([k, label]) => <option key={k} value={k}>{label}</option>)}</select></FormField>
              <FormField label="国家 / 地区" required><select required disabled={!!initial?.country} value={values.country} onChange={e=>{setValues(v=>({...v,country:e.target.value,region:''}));setDirty(true);}}><option value="">请选择国家 / 地区</option>{values.country&&!countries.includes(values.country)&&<option>{values.country}</option>}{warehouseCountries.map(country=><option key={country}>{country}</option>)}</select></FormField>
            </div>
            {type === "FBA" && <div className={styles.formGrid}><FormField label="卖家店铺" required><select required disabled={!!initial} value={values.seller_account} onChange={e=>setValues(v=>({...v,seller_account:e.target.value,marketplace:'US'}))}><option value="">请选择已确认店铺</option>{initial?.seller_account&&<option value={initial.seller_account}>{sourceScopes.value?.scopes.find(s=>`scope:${s.id}`===initial.seller_account)?.seller_account_display_name||initial.seller_account}</option>}{sourceScopes.value?.scopes.filter(s=>s.marketplace_scope_code==="amazon_us"&&(!initial||`scope:${s.id}`!==initial.seller_account)).map(s=><option key={s.id} value={`scope:${s.id}`}>{s.seller_account_display_name}</option>)}</select></FormField><FormField label="站点" required><select required disabled={!!initial} value={values.marketplace} onChange={e=>setValues(v=>({...v,marketplace:e.target.value}))}><option value="">请选择站点</option><option value="US">美国站</option>{initial?.marketplace&&initial.marketplace!=='US'&&<option value={initial.marketplace}>{initial.marketplace}</option>}</select></FormField>{sourceScopes.error&&<StatusMessage kind="danger" title="店铺读取失败">{sourceScopes.error}</StatusMessage>}{sourceScopes.value&&!sourceScopes.value.scopes.some(s=>s.marketplace_scope_code==="amazon_us")&&<StatusMessage kind="warning" title="请先在商品准备流程中确认店铺"/>}</div>}
            <div className={styles.warehouseAddress}>{values.country==='中国'?<FactoryRegionPicker fixedCountry="中国" value={`中国${values.region?' / '+values.region:''}`} onChange={region=>setValues(v=>({...v,region:region.split(' / ').slice(1).join(' / ')}))}/>:field('region','所在地区')}{field("address", "地址", 500)}</div>
            <div className={styles.formGrid}>{field("contact", "联系人")}{field("phone", "联系方式")}</div>
          </section>
          <Disclosure className={styles.factoryDisclosure}><summary>更多资料（选填）<span>{status === "ACTIVE" ? "启用中" : "已停用"}</span></summary><div className={styles.disclosureBody}><div className={styles.formGrid}>{statusField}{field("operator", "运营方（不是货主）")}{field("timezone", "时区（例如 Asia/Shanghai）")}{field("external_code", "外部仓码（可选）")}</div>{field("notes", "备注", 2000)}</div></Disclosure>
          <Disclosure className={styles.factoryDisclosure}><summary>往来工厂（选填）<span>{links.length ? `已选 ${links.length} 家` : "可稍后补充"}</span></summary><p className={styles.directoryHint}>记录与本仓有往来的工厂，仅供查阅；不会自动指定订单、入库或转移货权。</p>{relations}</Disclosure>
        </>}
        {!factories&&!initial&&['中国','CN','China'].includes(values.country||'')&&['FACTORY','OWN','THIRD_PARTY'].includes(type)&&<label><input type="checkbox" checked={withOpening} onChange={e=>setWithOpening(e.target.checked)}/>创建后导入期初库存</label>}
        {initial && <div className={styles.factorySection}><FormField label="修改 / 停用原因" required><Input required maxLength={2000} value={reason} onChange={e => setReason(e.target.value)} /></FormField>{status === "INACTIVE" && <StatusMessage kind="warning" title="停用不删除历史">{factories ? `当前有 ${initial.open_order_count || "0"} 张含开放明细的已确认订单。旧单仍可跟进，新单不能选择此工厂。` : "停用后将阻止此仓新库存操作；已有草稿仍保留，不能确认过账。"}</StatusMessage>}</div>}
        <div className={styles.factoryFooter}><div className={styles.actions}><Button variant="secondary" onClick={close}>取消</Button><Button variant="primary" type="submit">{initial ? "保存资料修改" : "创建档案"}</Button></div></div>
      </fieldset>
    </form>
    <div className={styles.factoryFeedback}>{command.feedback}{leave.prompt}</div>
    <ProductionConfirmDialog open={closing} onOpenChange={setClosing} closeOnOutsideClick={false} title="资料尚未保存，是否放弃？">
      <div className={styles.actions}><Button variant="primary" onClick={() => setClosing(false)}>继续编辑</Button><Button variant="danger" onClick={() => { leave.allowLeave(); onClose(); }}>放弃并关闭</Button></div>
    </ProductionConfirmDialog>
  </Dialog>;
}
