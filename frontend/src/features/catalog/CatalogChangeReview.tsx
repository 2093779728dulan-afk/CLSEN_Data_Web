import { Check, PencilLine, X } from "lucide-react";
import { useEffect, useState } from "react";
import { Button, FormField, Input, Select, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import css from "./CatalogChangeReview.module.css";

import {
  approveStyleChange, createStyleChangeDraft, listCatalogCategories,
  type CatalogCategory, type CatalogStyle, type CatalogStyleChangePreview,
} from "./catalogApi";

type Props = {
  catalogPublicationRevision: number;
  onApproved: () => Promise<void>;
  style: CatalogStyle;
  services?: CatalogChangeServices;
};

export type CatalogChangeServices = {
  categories: typeof listCatalogCategories;
  prepare: typeof createStyleChangeDraft;
  approve: typeof approveStyleChange;
};
const defaultServices: CatalogChangeServices = { categories: listCatalogCategories, prepare: createStyleChangeDraft, approve: approveStyleChange };

function categoryLabel(category: { code: string | null; display_name: string | null; parent_name?: string | null }) {
  return category.code ? `${category.parent_name ? `${category.parent_name} / ` : ""}${category.display_name}（${category.code}）` : "待分类";
}

export function CatalogChangeReview({ catalogPublicationRevision, onApproved, style, services = defaultServices }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(style.standard_name);
  const [categoryId, setCategoryId] = useState<string>(style.category_id?.toString() ?? "");
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  const [preview, setPreview] = useState<CatalogStyleChangePreview>();
  const [reason, setReason] = useState("日常商品主档维护");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [reading, setReading] = useState(false);
  const [readFailed, setReadFailed] = useState(false);
  const [readAttempt, setReadAttempt] = useState(0);
  const readCategories = services.categories;

  useEffect(() => {
    if (!open) return;
    let active = true;
    setReading(true); setReadFailed(false);
    void readCategories().then(value => { if (active) setCategories(value); })
      .catch(() => { if (active) setReadFailed(true); })
      .finally(() => { if (active) setReading(false); });
    return () => { active = false; };
  }, [open, readAttempt, readCategories]);

  const selected = categories.find((item) => item.category_id === Number(categoryId));
  const rootId = selected?.parent_category_id?.toString() ?? categoryId;
  const children = categories.filter((item) => item.parent_category_id === Number(rootId) && item.status === "enabled");
  const prepare = async () => {
    setBusy(true); setError(undefined);
    try { setPreview(await services.prepare(style, catalogPublicationRevision, name, categoryId ? Number(categoryId) : null)); }
    catch (value) { setError(value instanceof Error ? value.message : "无法生成变更预览。"); }
    finally { setBusy(false); }
  };
  const approve = async () => {
    if (!preview) return;
    setBusy(true); setError(undefined);
    try { await services.approve(preview, reason); await onApproved(); setOpen(false); setPreview(undefined); }
    catch (value) { setError(value instanceof Error ? value.message : "无法批准本次修改。"); }
    finally { setBusy(false); }
  };

  if (!open) return <Button variant="primary" icon={<PencilLine />} onClick={() => { setError(undefined); setOpen(true); }}>修改名称 / 分类</Button>;
  return <section className={css.panel} aria-label="单商品修改" aria-busy={busy || reading}>
    <header className={css.header}><div><span className={css.eyebrow}>单商品维护 · {style.style_code}</span><h3>名称与主分类</h3><p>修改先进入独立草稿，核对预览后再批准。</p></div><Button variant="quiet" aria-label="关闭修改" icon={<X />} disabled={busy} onClick={() => { setOpen(false); setPreview(undefined); }}>关闭</Button></header>
    <div className={css.identity}><span>STYLE #{style.style_id}</span><span>目录修订 {catalogPublicationRevision}</span><StatusBadge tone={preview ? "warn" : "quiet"} label={preview ? "待批准" : "编辑草稿"} /></div>
    <ol className={css.steps} aria-label="修改步骤"><li aria-current={!preview ? "step" : undefined}><span>1</span>编辑信息</li><li aria-current={preview ? "step" : undefined}><span>2</span>核对并批准</li></ol>
    <div className={css.body}>
      {reading && <div role="status" aria-label="正在读取分类字典"><Skeleton height={40} /><p>正在读取分类字典…</p></div>}
      {readFailed && <StatusMessage kind="danger" title="分类字典读取未完成" action={<Button onClick={() => setReadAttempt(value => value + 1)}>重新读取分类</Button>}>编辑内容已保留，读取成功后可生成预览。</StatusMessage>}
      {!preview ? <form onSubmit={event => { event.preventDefault(); void prepare(); }}>
        <fieldset disabled={busy || reading || readFailed} className={css.fields}>
          <FormField label="标准商品名称" required hint="仅修改当前商品的标准名称。"><Input maxLength={255} onChange={event => setName(event.target.value)} value={name} /></FormField>
          <FormField label="主分类"><Select onChange={event => setCategoryId(event.target.value)} value={rootId}><option value="">待分类</option>{categories.filter(item => !item.parent_category_id && item.status === "enabled").map(item => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</Select></FormField>
          {rootId && <FormField label="细分类（可选）"><Select onChange={event => setCategoryId(event.target.value || rootId)} value={selected?.parent_category_id ? categoryId : ""}><option value="">仅主分类 / 暂不细分</option>{children.map(item => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</Select></FormField>}
        </fieldset>
        <div className={css.scope}>这份草稿只包含当前商品；变体、Seller SKU 与其他商品不会进入本次修改。</div>
        <footer className={css.footer}><span>生成预览不会发布目录。</span><Button type="submit" variant="primary" loading={busy} loadingLabel="正在生成预览" disabled={reading || readFailed || !name.trim()}>生成变更预览</Button></footer>
      </form> : <div>
        <Table className={css.comparison} title="变更预览" description={`草稿 #${preview.draft_id} · 修订 ${preview.draft_revision}，仅下列字段进入本次批准。`}><thead><tr><th scope="col">字段</th><th scope="col">修改前</th><th scope="col">批准后</th></tr></thead><tbody><tr><th scope="row">标准名称</th><td>{preview.before.standard_name}</td><td className={css.after}>{preview.after.standard_name}</td></tr><tr><th scope="row">主分类</th><td>{categoryLabel(preview.before.category)}</td><td className={css.after}>{categoryLabel(preview.after.category)}</td></tr></tbody></Table>
        <div className={css.reason}><FormField label="批准原因" required hint="至少 3 个字符，记录本次维护的原因。"><Input disabled={busy} maxLength={500} minLength={3} onChange={event => setReason(event.target.value)} value={reason} /></FormField></div>
        <footer className={css.footer}><Button disabled={busy} onClick={() => { setPreview(undefined); setError(undefined); }}>返回修改</Button><Button variant="primary" icon={<Check />} loading={busy} loadingLabel="正在批准并刷新" disabled={reason.trim().length < 3} onClick={() => void approve()}>批准并生成新目录版本</Button></footer>
      </div>}
      {error && <div className={css.feedback}><StatusMessage kind="danger" title="本次操作未完成">{error}</StatusMessage></div>}
    </div>
  </section>;
}
