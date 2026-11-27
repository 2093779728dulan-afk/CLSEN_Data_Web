import { Disclosure } from "../../design-system";
import { useState } from "react";
import { FormField, Input, StatusMessage, Table } from "../../design-system";
import styles from "./Production.module.css";

type MatchStatus = "UNIQUE_CANDIDATE" | "AMBIGUOUS" | "DISABLED" | "EXCLUDED" | "UNMATCHED";
type Candidate = {
  sku_id: string; style_id: string; sku_revision: string; code: string; color: string; size: string;
  status: "enabled" | "disabled"; style_status: "enabled" | "disabled";
  match_routes: ("INTERNAL_IDENTITY" | "SELLER_MAPPING")[];
  source_scopes: { report_source_scope_id: string; marketplace_scope_code: string }[];
};
export type ProductCandidate = {
  style_id: string; style_revision: string; code: string; name: string; status: "enabled" | "disabled";
  skus: { sku_id: string; sku_revision: string; code: string; color: string; size: string; status: "enabled" | "disabled" }[];
};
export type CatalogReferenceResult = {
  status: "NOT_CONFIGURED" | "UNAVAILABLE" | "OUTSIDE_SCOPE" | "CHECKED_SNAPSHOT";
  source?: { site_id: string; site_code: string; catalog_version_id: string; catalog_publication_revision: string; version_number: string; checked_at: string };
  counts?: Partial<Record<MatchStatus, number>>;
  rows?: { source_row: number; source_sku: string; status: MatchStatus; candidates: Candidate[]; excluded_scopes: { report_source_scope_id: string; marketplace_scope_code: string }[];
    product_lookup?: { code: string; basis: "SOURCE_COLUMN" | "SKU_PREFIX_HINT"; checked: boolean; candidates: ProductCandidate[] } | null }[];
  products?: Record<string, ProductCandidate[]>;
  products_checked_at?: string | null;
  confirmation_enabled: false;
};
const labels: Record<MatchStatus, string> = {
  UNIQUE_CANDIDATE: "唯一候选，待确认", AMBIGUOUS: "候选或范围冲突", DISABLED: "目录候选已停用",
  EXCLUDED: "来源有忽略决定", UNMATCHED: "未找到编码匹配",
};

function ProductLookup({ products }: { products: Record<string, ProductCandidate[]> }) {
  const [query, setQuery] = useState("");
  const code = query.trim();
  const checked = Object.hasOwn(products, code);
  const candidates = checked ? products[code] : [];
  return <div className={styles.productLookup}>
    <FormField label="按产品号查询主档" hint="输入完整款号，查看本批已核对产品的颜色、尺码及稳定ID。">
      <Input type="search" placeholder="输入产品款号" value={query} onChange={event => setQuery(event.target.value)} />
    </FormField>
    {code && <div role="status">{!checked ? "本批尚未核对此产品号，不代表主档中没有商品。" : !candidates?.length ? "此款号在当前主档快照中未找到产品。" : `找到${candidates.length}个产品候选；颜色与尺码仍须逐行核对，尚未绑定SKU。`}</div>}
    {candidates?.map(product => <article key={product.style_id}>
      <h3>{product.code} · {product.name}</h3>
      <p>产品{product.status === "enabled" ? "启用" : "已停用"} · A款式ID {product.style_id} · 修订{product.style_revision}</p>
      {product.skus.length ? <Table className={styles.productSkuTable} aria-label={`${product.code}主档颜色与尺码`}><thead><tr><th scope="col">主档SKU</th><th scope="col">颜色</th><th scope="col">尺码</th><th scope="col">状态</th><th scope="col">A SKU ID</th></tr></thead><tbody>{product.skus.map(sku => <tr key={sku.sku_id}><th scope="row">{sku.code}</th><td>{sku.color}</td><td>{sku.size}</td><td>{sku.status === "enabled" ? "启用" : "已停用"}</td><td>{sku.sku_id}</td></tr>)}</tbody></Table> : <p>当前目录未列出此产品的SKU，仍需补齐商品身份。</p>}
    </article>)}
  </div>;
}

export function CatalogReferencePanel({ reference }: { reference?: CatalogReferenceResult }) {
  const checked = reference?.status === "CHECKED_SNAPSHOT" && reference.source;
  return <section id="source-catalog-reference" tabIndex={-1} className={`${styles.panel} ${styles.reviewTarget}`} aria-labelledby="source-catalog-reference-heading">
    <h2 id="source-catalog-reference-heading">商品主档核对 · 只读</h2>
    {checked ? <><dl className={styles.metadata}><div><dt>主档来源</dt><dd>A本地已发布目录 · {checked.site_code}</dd></div><div><dt>目录版本</dt><dd>{checked.version_number} · ID {checked.catalog_version_id}</dd></div><div><dt>发布修订</dt><dd>{checked.catalog_publication_revision}</dd></div><div><dt>核对时间</dt><dd>{new Date(checked.checked_at).toLocaleString("zh-CN")}</dd></div></dl>
      <p>原表逐行核对：唯一启用候选{reference.counts?.UNIQUE_CANDIDATE || 0}条，未匹配{reference.counts?.UNMATCHED || 0}条，冲突{reference.counts?.AMBIGUOUS || 0}条，停用{reference.counts?.DISABLED || 0}条，已有忽略决定{reference.counts?.EXCLUDED || 0}条。</p>
      <StatusMessage kind="info" title="候选保留来源身份，尚未正式绑定">在下方明细的“关联状态”查看每行结果。编码匹配不代表发运日期、来源账号或订单归属已核实；未匹配也不等于商品不存在。请核对编码口径或补齐主档映射，不能按相似名称强行关联。</StatusMessage>
      <p className={styles.reviewHint}>这是核对时的只读快照。A主档更新后需重新核对；正式确认前仍须由服务端校验有效版本。本页不修改A目录，也不会把A的ID当成B虚构商品ID。</p>
      {!!Object.keys(reference.products || {}).length && <><p>产品核对时间：{reference.products_checked_at ? new Date(reference.products_checked_at).toLocaleString("zh-CN") : "未记录"}。先按款号定位产品，再核对颜色与尺码；装箱单的编码前缀仅作产品查找线索。</p><ProductLookup products={reference.products || {}} /></>}
    </> : <StatusMessage kind={reference?.status === "UNAVAILABLE" ? "warning" : "info"} title="本份来源尚未完成主档核对">{reference?.status === "OUTSIDE_SCOPE" ? "本次只核对已授权的三份原表；这份新来源未纳入本次范围。" : reference?.status === "UNAVAILABLE" ? "只读核对资料不可用，请恢复有效副本。原表草稿仍可查看和保存。" : "当前没有可用的A已发布主档核对结果。"} 正式商品绑定保持待处理。</StatusMessage>}
  </section>;
}

export function CatalogCandidateCell({ reference, sourceRow }: { reference?: CatalogReferenceResult; sourceRow: number }) {
  const row = reference?.status === "CHECKED_SNAPSHOT" ? reference.rows?.find(row => row.source_row === sourceRow) : undefined;
  if (!row) return <span>SKU待匹配<small className={styles.secondary}>尚未纳入主档核对</small></span>;
  const lookup = row.product_lookup;
  const products = lookup?.checked ? lookup.candidates : [];
  return <div className={styles.catalogCandidate}><span>{row.status === "UNMATCHED" && products.length ? "找到产品 · SKU待核" : labels[row.status]}</span>
    {lookup && <small className={styles.secondary}>{lookup.basis === "SOURCE_COLUMN" ? "原表款号" : "编码前缀线索"}：{lookup.code}</small>}
    {!!products.length && <Disclosure><summary>查看产品候选（{products.length}）</summary>{products.map(product => <div key={product.style_id}><strong>{product.code} · {product.name}</strong><p>A款式ID {product.style_id} · 修订{product.style_revision} · {product.status === "enabled" ? "启用" : "已停用"}</p><p>含{product.skus.length}个SKU；在上方按产品号查看颜色、尺码与SKU ID。</p></div>)}</Disclosure>}
    {!!row.candidates.length && <Disclosure><summary>查看主档候选（{row.candidates.length}）</summary>{row.candidates.map(candidate => <div key={candidate.sku_id}>
      <strong>{candidate.code}</strong><p>{candidate.color} / {candidate.size}</p>
      <p>A · {reference?.source?.site_code} · SKU ID {candidate.sku_id} · 款式ID {candidate.style_id} · 修订{candidate.sku_revision}</p>
      <p>{candidate.match_routes.map(route => route === "INTERNAL_IDENTITY" ? "目录规范编码相同" : "已发布卖家SKU映射").join("、")}</p>
      {candidate.source_scopes.map(scope => <p key={`${scope.report_source_scope_id}:${scope.marketplace_scope_code}`}>来源范围 {scope.marketplace_scope_code} / {scope.report_source_scope_id}</p>)}
    </div>)}</Disclosure>}
    {!!row.excluded_scopes.length && <small className={styles.secondary}>需核对来源范围的忽略决定，不能自动恢复映射。</small>}
    <small className={styles.secondary}>尚未正式绑定</small>
  </div>;
}
