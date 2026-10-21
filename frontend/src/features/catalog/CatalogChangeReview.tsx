import { Check, PencilLine, X } from "lucide-react";
import { useEffect, useState } from "react";

import {
  approveStyleChange, createStyleChangeDraft, listCatalogCategories,
  type CatalogCategory, type CatalogStyle, type CatalogStyleChangePreview,
} from "./catalogApi";

type Props = {
  catalogPublicationRevision: number;
  onApproved: () => Promise<void>;
  style: CatalogStyle;
};

function categoryLabel(category: { code: string | null; display_name: string | null; parent_name?: string | null }) {
  return category.code ? `${category.parent_name ? `${category.parent_name} / ` : ""}${category.display_name}（${category.code}）` : "待分类";
}

export function CatalogChangeReview({ catalogPublicationRevision, onApproved, style }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(style.standard_name);
  const [categoryId, setCategoryId] = useState<string>(style.category_id?.toString() ?? "");
  const [categories, setCategories] = useState<CatalogCategory[]>([]);
  const [preview, setPreview] = useState<CatalogStyleChangePreview>();
  const [reason, setReason] = useState("日常商品主档维护");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();

  useEffect(() => {
    if (open) void listCatalogCategories().then(setCategories).catch(() => setError("无法读取分类字典。"));
  }, [open]);

  const selected = categories.find((item) => item.category_id === Number(categoryId));
  const rootId = selected?.parent_category_id?.toString() ?? categoryId;
  const children = categories.filter((item) => item.parent_category_id === Number(rootId) && item.status === "enabled");
  const prepare = async () => {
    setBusy(true); setError(undefined);
    try { setPreview(await createStyleChangeDraft(style, catalogPublicationRevision, name, categoryId ? Number(categoryId) : null)); }
    catch (value) { setError(value instanceof Error ? value.message : "无法生成变更预览。"); }
    finally { setBusy(false); }
  };
  const approve = async () => {
    if (!preview) return;
    setBusy(true); setError(undefined);
    try { await approveStyleChange(preview, reason); await onApproved(); setOpen(false); setPreview(undefined); }
    catch (value) { setError(value instanceof Error ? value.message : "无法批准本次修改。"); }
    finally { setBusy(false); }
  };

  if (!open) return <button className="catalog-primary-action" onClick={() => setOpen(true)} type="button"><PencilLine aria-hidden="true" />修改名称 / 分类</button>;
  return <section className="catalog-change-panel" aria-label="单商品修改">
    <div className="catalog-change-panel__heading"><div><p className="section-kicker">独立修改草稿</p><h3>名称与主分类</h3></div><button aria-label="关闭修改" onClick={() => { setOpen(false); setPreview(undefined); }} type="button"><X aria-hidden="true" /></button></div>
    {!preview ? <div className="catalog-change-form">
      <label>标准商品名称<input maxLength={255} onChange={(event) => setName(event.target.value)} value={name} /></label>
      <label>主分类<select onChange={(event) => setCategoryId(event.target.value)} value={rootId}><option value="">待分类</option>{categories.filter((item) => !item.parent_category_id && item.status === "enabled").map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</select></label>
      {rootId && <label>细分类（可选）<select onChange={(event) => setCategoryId(event.target.value || rootId)} value={selected?.parent_category_id ? categoryId : ""}><option value="">仅主分类 / 暂不细分</option>{children.map((item) => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</select></label>}
      <p>这份草稿只包含当前商品；变体、Seller SKU 与其他商品不会进入本次修改。</p>
      <button className="catalog-primary-action" disabled={busy || !name.trim()} onClick={() => void prepare()} type="button">生成变更预览</button>
    </div> : <div className="catalog-change-review">
      <div><span>字段</span><strong>修改前</strong><strong>批准后</strong></div>
      <div><span>标准名称</span><del>{preview.before.standard_name}</del><ins>{preview.after.standard_name}</ins></div>
      <div><span>主分类</span><del>{categoryLabel(preview.before.category)}</del><ins>{categoryLabel(preview.after.category)}</ins></div>
      <label>批准原因<input maxLength={500} minLength={3} onChange={(event) => setReason(event.target.value)} value={reason} /></label>
      <div className="catalog-change-review__actions"><button disabled={busy} onClick={() => setPreview(undefined)} type="button">返回修改</button><button className="catalog-primary-action" disabled={busy || reason.trim().length < 3} onClick={() => void approve()} type="button"><Check aria-hidden="true" />批准并生成新目录版本</button></div>
    </div>}
    {error && <p className="form-error" role="alert">{error}</p>}
  </section>;
}
