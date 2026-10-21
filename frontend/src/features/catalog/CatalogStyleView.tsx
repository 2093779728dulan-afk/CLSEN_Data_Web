import { ArrowLeft, ChevronDown, ChevronRight, FileSearch, RefreshCw, Shirt } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { SafeSourceRefView } from "../../components/source-reference/SafeSourceRefView";
import { Button, ContentReveal, EmptyState, ErrorState, FilterToolbar, LinkButton, Pagination, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import { getCatalogVariantEvidence, getCatalogVariantSellerSkus, type CatalogEvidenceItem, type CatalogPage, type CatalogSellerSkuAlias, type CatalogSku, type CatalogSourceSummary, type CatalogStyle } from "./catalogApi";
import { catalogReadError } from "./catalogReadError";
import { catalogStatusDisplay } from "./catalogTypes";
import styles from "./CatalogStyleView.module.css";

export type CatalogStyleDetail = { catalog_version_id: number; catalog_publication_revision?: number; permissions?: { can_edit: boolean; can_manage_categories: boolean }; style: CatalogStyle; skus: CatalogSku[] };
export type CatalogVariantReaders = { aliases: typeof getCatalogVariantSellerSkus; evidence: typeof getCatalogVariantEvidence };
const defaultReaders: CatalogVariantReaders = { aliases: getCatalogVariantSellerSkus, evidence: getCatalogVariantEvidence };
type Failure = ReturnType<typeof catalogReadError>;

function SourceSummary({ value }: { value: CatalogSourceSummary }) {
  return <span className={styles.summary}>{value.source_report_count} 份报告 · {value.observation_count} 条观察 · {value.first_seen_date ?? "—"} 至 {value.latest_seen_date ?? "—"}</span>;
}

function EvidenceRow({ item }: { item: CatalogEvidenceItem }) {
  const [copyMessage, setCopyMessage] = useState("");
  const reportQuery = new URLSearchParams({ report_date: item.report_date, report_type: item.report_type });
  const copySku = async () => {
    try { await navigator.clipboard.writeText(item.seller_sku.preview); setCopyMessage("已复制 SKU"); }
    catch { setCopyMessage("复制失败，请手动选择 SKU 文本复制"); }
  };
  const structurallyUnsafe = /[<>&"']/u.test(item.seller_sku.preview);
  return <li className={styles.evidenceRow}>
    <header><StatusBadge label={item.report_type === "business_report" ? "经营报告" : "退货报告"} tone="quiet" /><span>报告归属日：{item.report_date}</span><span>记录事件日期：{item.event_date ?? "未提供"}</span></header>
    <div className={styles.sourceField}><strong>Seller SKU</strong><SafeSourceRefView source={item.seller_sku} />{!item.seller_sku.is_truncated && !item.seller_sku.is_unsafe && !structurallyUnsafe && <Button variant="quiet" onClick={() => void copySku()}>复制 SKU</Button>}<span role="status">{copyMessage}</span></div>
    {item.title && <div className={styles.sourceField}><strong>标题</strong><SafeSourceRefView source={item.title} /></div>}
    <div className={styles.locator}><Link to={`/versions?${reportQuery.toString()}`}>查看来源报告版本</Link><p>按报告归属日查找，并选择下方系统版本编号对应的记录。请按对应文件及记录序号核对，不可用系统记录编号定位 Excel 行。</p><p>来源文件：{item.source_filename ?? "未保留文件关联"}</p><p>原表记录序号：{item.source_record_number ?? "未提供"}（表头为第 1 条；CSV 多行单元格会导致文本物理行号不同）</p>{item.report_type === "return_report" && <><p>原始退货时间：{item.source_event_timestamp ?? "未保留"}</p><p>导入来源时区：{item.source_timezone ?? "未提供"}；原始时间如带 UTC 偏移，以该偏移为准。事件日期与报告归属日可能不同。</p></>}{item.title?.is_unsafe && <p>标题含需安全处理的字符，当前展示为安全摘要；此标记不代表 SKU 错误。</p>}</div>
    <details className={styles.trace}><summary>系统追溯信息</summary><span>系统版本编号 {item.published_version_id} · 系统记录编号 {item.source_row_id}（非文件行号）</span><code>{item.evidence_digest.slice(-8)}</code></details>
  </li>;
}

function VariantDetails({ sku, readers }: { sku: CatalogSku; readers: CatalogVariantReaders }) {
  const { aliases: readAliases, evidence: readEvidence } = readers;
  const panelId = useId();
  const [expanded, setExpanded] = useState(false);
  const [aliases, setAliases] = useState<CatalogPage<CatalogSellerSkuAlias>>();
  const [evidence, setEvidence] = useState<CatalogPage<CatalogEvidenceItem>>();
  const [aliasRequest, setAliasRequest] = useState<{ page: number; attempt: number }>();
  const [evidenceRequest, setEvidenceRequest] = useState<{ page: number; attempt: number }>();
  const [aliasBusy, setAliasBusy] = useState(false);
  const [evidenceBusy, setEvidenceBusy] = useState(false);
  const [aliasError, setAliasError] = useState<Failure>();
  const [evidenceError, setEvidenceError] = useState<Failure>();
  const status = catalogStatusDisplay(sku.status);
  const loadAliases = (page = 1) => { setAliasBusy(true); setAliasError(undefined); setAliasRequest(previous => ({ page, attempt: (previous?.attempt ?? 0) + 1 })); };
  const loadEvidence = (page = 1) => { setEvidenceBusy(true); setEvidenceError(undefined); setEvidenceRequest(previous => ({ page, attempt: (previous?.attempt ?? 0) + 1 })); };
  useEffect(() => {
    if (!aliasRequest) return;
    let active = true;
    void readAliases(sku.sku_id, aliasRequest.page).then(value => { if (active) { setAliases(value); setAliasBusy(false); } }).catch((reason: unknown) => {
      if (!active) return;
      const failure = catalogReadError(reason, "销售别名读取未完成，请重试。");
      setAliasError(failure); setAliasBusy(false);
      if (!failure.retry) { setAliases(undefined); setEvidence(undefined); }
    });
    return () => { active = false; };
  }, [aliasRequest, readAliases, sku.sku_id]);
  useEffect(() => {
    if (!evidenceRequest) return;
    let active = true;
    void readEvidence(sku.sku_id, evidenceRequest.page).then(value => { if (active) { setEvidence(value); setEvidenceBusy(false); } }).catch((reason: unknown) => {
      if (!active) return;
      const failure = catalogReadError(reason, "来源明细读取未完成，请重试。");
      setEvidenceError(failure); setEvidenceBusy(false);
      if (!failure.retry) { setAliases(undefined); setEvidence(undefined); setAliasError(failure); }
    });
    return () => { active = false; };
  }, [evidenceRequest, readEvidence, sku.sku_id]);
  const toggle = () => { const next = !expanded; setExpanded(next); if (next && !aliases && !aliasBusy && (!aliasError || aliasError.retry)) loadAliases(); };
  return <article className={styles.variant} aria-label={`变体 ${sku.internal_display_sku}`}>
    <div className={styles.variantHeading}><div><span className={styles.eyebrow}>内部展示 SKU</span><h4>{sku.internal_display_sku}</h4><small>实际变体 {sku.standard_color} / {sku.standard_size} · 系统身份 SKU #{sku.sku_id}</small></div><StatusBadge label={status.label} tone={status.tone} /><Button aria-controls={panelId} aria-expanded={expanded} icon={expanded ? <ChevronDown /> : <ChevronRight />} onClick={toggle} variant="quiet">{expanded ? "收起 Seller SKU" : "展开 Seller SKU"}</Button></div>
    <div className={styles.variantSummary}><strong>{sku.seller_sku_count} 个 Seller SKU</strong><SourceSummary value={sku.source_summary} /></div>
    <div id={panelId} hidden={!expanded} className={styles.variantBody}>
      {aliasBusy && !aliases && <div role="status" aria-label="正在读取关联 Seller SKU"><Skeleton lines={3} /></div>}
      {aliasError && <ErrorState title="商品关联读取未完成" description={aliasError.message} action={aliasError.retry ? <Button onClick={() => loadAliases(aliasRequest?.page)}>重新读取销售别名</Button> : undefined} />}
      {aliases && !aliasError && <section aria-label="关联 Seller SKU"><div className={styles.sectionHeading}><div><h3>关联 Seller SKU</h3><p>同一稳定 SKU 下的已批准销售标识，共 {aliases.total_items} 个。</p></div><Button icon={<FileSearch />} loading={evidenceBusy} loadingLabel="正在读取来源" onClick={() => loadEvidence(1)}>查看来源明细</Button></div>
        {aliases.items.length === 0 ? <EmptyState title="暂无已批准 Seller SKU" description="当前变体没有已批准的销售别名，不自动补齐映射。" /> : <Table className={styles.aliasTable} aria-label={`关联 Seller SKU ${sku.internal_display_sku}`}><thead><tr><th scope="col">销售标识</th><th scope="col">账号与站点</th><th scope="col">来源摘要</th></tr></thead><tbody>{aliases.items.map(alias => <tr key={alias.mapping_id}><td><SafeSourceRefView source={alias.seller_sku} /></td><td>{alias.seller_account} · {alias.marketplace}</td><td><SourceSummary value={alias.source_summary} /></td></tr>)}</tbody></Table>}
        <Pagination loading={aliasBusy} page={aliases.page} totalItems={aliases.total_items} totalPages={Math.max(1, Math.ceil(aliases.total_items / aliases.page_size))} itemLabel="销售标识" onPageChange={loadAliases} />
      </section>}
      {evidenceBusy && !evidence && <div role="status" aria-label="正在读取来源明细"><Skeleton lines={4} /></div>}
      {evidenceError && !(aliasError && !aliasError.retry) && <ErrorState title="来源明细读取未完成" description={evidenceError.message} action={evidenceError.retry ? <Button onClick={() => loadEvidence(evidenceRequest?.page)}>重新读取来源明细</Button> : undefined} />}
      {evidence && !evidenceError && !(aliasError && !aliasError.retry) && <section aria-label="来源明细"><div className={styles.sectionHeading}><div><h3>来源明细</h3><p>按需读取安全摘要，第 {evidence.page} 页，共 {evidence.total_items} 条。</p></div></div>{evidence.items.length ? <ul className={styles.evidenceList}>{evidence.items.map(item => <EvidenceRow item={item} key={item.evidence_id} />)}</ul> : <EmptyState title="暂无来源明细" description="当前查询未返回来源记录，销售别名和已批准变体仍按原记录展示。" />}<Pagination loading={evidenceBusy} page={evidence.page} totalItems={evidence.total_items} totalPages={Math.max(1, Math.ceil(evidence.total_items / evidence.page_size))} itemLabel="来源记录" onPageChange={loadEvidence} /></section>}
    </div>
  </article>;
}

export function CatalogStyleView({ value, failure, reading = false, styleReturn = "/catalog", onRefresh, pending, actions, readers = defaultReaders }: {
  value?: CatalogStyleDetail; failure?: Failure; reading?: boolean; styleReturn?: string;
  onRefresh: () => void; pending?: ReactNode; actions?: ReactNode; readers?: CatalogVariantReaders;
}) {
  const [query, setQuery] = useState("");
  const retained = Boolean(value && failure?.retry);
  const skus = (value?.skus ?? []).filter(sku => `${sku.internal_display_sku} ${sku.standard_color} ${sku.standard_size}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const status = value ? catalogStatusDisplay(value.style.status) : undefined;
  return <section className={styles.page} aria-label="商品完整详情">
    <div className={styles.toolbar}><LinkButton to={styleReturn} icon={<ArrowLeft />} variant="quiet">{styleReturn === "/catalog/unmatched" ? "返回待处理" : "返回商品主档"}</LinkButton><Button icon={<RefreshCw />} loading={reading} loadingLabel="正在读取商品" disabled={Boolean(failure && !failure.retry)} onClick={onRefresh}>刷新商品详情</Button></div>
    {failure && !retained ? <ErrorState title="商品详情读取未完成" description={failure.message} action={failure.retry ? <Button onClick={onRefresh}>重新读取商品</Button> : <LinkButton to={styleReturn}>返回列表</LinkButton>} /> : !value ? <div role="status" aria-label="正在读取商品详情"><Skeleton lines={5} /><Skeleton lines={4} /></div> : <>
      {retained && <StatusMessage kind="warning" title="刷新未完成，当前显示上次读取的商品">{failure?.message}</StatusMessage>}
      <ContentReveal className={styles.content}>
        <header className={styles.header}><div className={styles.ticket}><Shirt aria-hidden="true" /><span>款式编号</span><strong>{value.style.style_code}</strong><small>系统永久身份 STYLE #{value.style.style_id}</small></div><div className={styles.heading}><div className={styles.badges}><StatusBadge label="已批准商品" tone="quiet" /><StatusBadge label={status!.label} tone={status!.tone} />{!value.permissions?.can_edit && !value.permissions?.can_manage_categories && <StatusBadge label="只读" tone="quiet" />}</div><h2>{value.style.standard_name}</h2><p>{value.style.category_id ? `${value.style.category_parent ? `${value.style.category_parent.display_name} / ` : ""}${value.style.category_name}（${value.style.category_code}）` : value.style.category_recorded === false ? "未记录分类" : "待分类"}</p><SourceSummary value={value.style.source_summary} /></div></header>
        <dl className={styles.metrics}><div><dt>实际变体</dt><dd>{value.style.variant_count}</dd></div><div><dt>Seller SKU</dt><dd>{value.style.seller_sku_count}</dd></div><div><dt>目录版本</dt><dd>{value.catalog_version_id}</dd></div><div><dt>商品修订</dt><dd>{value.style.revision}</dd></div></dl>
        {pending}{actions && <fieldset className={styles.actions} disabled={reading || Boolean(failure)}><legend className={styles.actionsLabel}>主档维护</legend>{actions}</fieldset>}
        <ol aria-label="商品身份层级" className={styles.hierarchy}><li><strong>款式编号</strong><small>{value.style.style_code}</small></li><li><strong>实际变体</strong><small>已确认存在的颜色与尺码</small></li><li><strong>Seller SKU</strong><small>按账号与站点区分的销售别名</small></li><li><strong>来源</strong><small>报告、版本与原表记录定位</small></li></ol>
        <section className={styles.variants} aria-label="实际变体"><div className={styles.sectionHeading}><div><h3>实际变体</h3><p>每行都是当前批准版本中真实存在的一个变体，不会补齐颜色 × 尺码组合。</p></div><span aria-live="polite">{reading ? "正在刷新，保留当前商品" : `${value.skus.length} 个变体`}</span></div>
          <FilterToolbar matchingCount={skus.length} totalCount={value.skus.length} query={query} onQueryChange={setQuery} onReset={() => setQuery("")} searchLabel="查找实际变体" placeholder="内部展示 SKU、颜色或尺码" />
          {!skus.length ? <EmptyState title={value.skus.length ? "没有符合条件的变体" : "当前商品卡暂无实际变体"} description={value.skus.length ? "调整颜色、尺码或 SKU，也可以重置搜索。" : "只展示服务端返回的已批准变体，不推测缺失组合。"} /> : skus.map(sku => <VariantDetails key={`${sku.sku_id}:${value.catalog_publication_revision ?? value.catalog_version_id}`} sku={sku} readers={readers} />)}
        </section>
      </ContentReveal>
    </>}
  </section>;
}
