import { Check, PencilLine, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button, FormField, Input, Select, Skeleton, StatusBadge, StatusMessage, Table } from "../../design-system";
import css from "./CatalogChangeReview.module.css";
import { catalogNameDisplay, type CatalogNameSuggestion } from "./catalogTypes";

import {
  approveStyleChange, createStyleChangeDraft, getCatalogNameSuggestions, getStyleChangePreview, listCatalogCategories,
  type CatalogCategory, type CatalogStyle, type CatalogStyleChangePreview,
} from "./catalogApi";

type Props = {
  catalogPublicationRevision: number;
  onApproved: () => Promise<void>;
  style: CatalogStyle;
  services?: CatalogChangeServices;
  restoredDraftId?: number;
  nameSuggestion?: CatalogNameSuggestion;
};

export type CatalogChangeServices = {
  categories: typeof listCatalogCategories;
  prepare: typeof createStyleChangeDraft;
  approve: typeof approveStyleChange;
  load?: typeof getStyleChangePreview;
  names?: typeof getCatalogNameSuggestions;
};
const defaultServices: CatalogChangeServices = { categories: listCatalogCategories, prepare: createStyleChangeDraft, approve: approveStyleChange, names: getCatalogNameSuggestions };

function categoryLabel(category: { code: string | null; display_name: string | null; parent_name?: string | null }) {
  return category.code ? `${category.parent_name ? `${category.parent_name} / ` : ""}${category.display_name}（${category.code}）` : "待分类";
}

export function CatalogChangeReview({ catalogPublicationRevision, onApproved, style, services = defaultServices, restoredDraftId, nameSuggestion }: Props) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(style.standard_name);
  const nameInput = useRef<HTMLInputElement>(null);
  const [suggestions, setSuggestions] = useState<CatalogNameSuggestion[]>([]);
  const [namesFailed, setNamesFailed] = useState(false);
  const [namesReading, setNamesReading] = useState(false);
  const [namesLimited, setNamesLimited] = useState(false);
  const [chosenSource, setChosenSource] = useState<string>();
  const readNames = services.names;
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
  const readDraft = services.load ?? getStyleChangePreview;
  const [restoring, setRestoring] = useState(false);
  const [restoreError, setRestoreError] = useState<string>();
  const [restoreAttempt, setRestoreAttempt] = useState(0);
  const stale = Boolean(preview && preview.base_catalog_publication_revision !== catalogPublicationRevision);
  const readonly = preview?.status === "approved";
  useEffect(() => {
    if (!nameSuggestion) return;
    setOpen(true); setPreview(undefined); setError(undefined);
    setName(nameSuggestion.name); setReason(`依据${nameSuggestion.source}补充商品名称`);
  }, [nameSuggestion]);
  useEffect(() => { if (open && nameSuggestion) nameInput.current?.focus(); }, [open, nameSuggestion]);
  useEffect(() => {
    if (!open || !readNames) return;
    let active = true;
    setNamesReading(true); setNamesFailed(false);
    void readNames(style.style_id).then(result => {
      if (active) { setSuggestions(result.items); setNamesLimited(result.limited); }
    }).catch(() => { if (active) { setNamesFailed(true); setSuggestions([]); } })
      .finally(() => { if (active) setNamesReading(false); });
    return () => { active = false; };
  }, [open, readNames, style.style_id]);
  useEffect(() => {
    if (!restoredDraftId) return;
    let active = true;
    setOpen(true); setRestoring(true); setPreview(undefined); setRestoreError(undefined);
    void readDraft(restoredDraftId).then(value => {
      if (!active) return;
      if (value.style_id !== style.style_id) throw new Error("此草稿不属于当前商品，请返回待归属与审核选择正确记录。");
      setPreview(value); setName(value.after.standard_name); setCategoryId(value.after.category.category_id?.toString() ?? "");
    }).catch(reason => { if (active) setRestoreError(reason instanceof Error && /[\u3400-\u9fff]/.test(reason.message) ? reason.message : "此名称／分类草稿尚未读取完成，请重试；没有新建或批准记录。"); })
      .finally(() => { if (active) setRestoring(false); });
    return () => { active = false; };
  }, [restoredDraftId, restoreAttempt, style.style_id, readDraft]);

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
      {restoring && <p role="status">正在恢复已保存的名称／分类草稿…</p>}
      {restoreError && <StatusMessage kind="danger" title="草稿尚未读取完成" action={<Button onClick={() => setRestoreAttempt(value => value + 1)}>重新读取此草稿</Button>}>{restoreError}</StatusMessage>}
      {stale && <StatusMessage kind="warning" title="原草稿基准已变化">原草稿和历史保留。请返回修改，按当前目录生成新的变更预览后核对。</StatusMessage>}
      {readonly && <StatusMessage kind="info" title="本草稿已批准">此处仅展示原变更及依据，不会再次批准。</StatusMessage>}
      {reading && <div role="status" aria-label="正在读取分类字典"><Skeleton height={40} /><p>正在读取分类字典…</p></div>}
      {readFailed && <StatusMessage kind="danger" title="分类字典读取未完成" action={<Button onClick={() => setReadAttempt(value => value + 1)}>重新读取分类</Button>}>编辑内容已保留，读取成功后可生成预览。</StatusMessage>}
      {!preview ? <form onSubmit={event => { event.preventDefault(); void prepare(); }}>
        <fieldset disabled={busy || reading || readFailed || restoring || Boolean(restoreError)} className={css.fields}>
          <FormField label="标准商品名称（选填）" hint="留空显示名称待补，可继续维护分类；补名保留原商品身份与业务关联。"><Input ref={nameInput} maxLength={255} placeholder="暂未确定可留空，后续补充" onChange={event => setName(event.target.value)} value={name} /></FormField>
          {readNames && <FormField label="从官方报告选择名称（可选）" hint={["按当前商品已批准的店铺与SKU关联读取；选择后仍需核对预览及批准。", chosenSource ? `参考来源：${chosenSource}；尚未批准。` : "", namesLimited ? "当前候选来自每类报告最近50条关联记录，其他历史标题可在原报告查看。" : "", namesFailed ? "报告名称暂未读取成功，可关闭后重试；仍可留空待补或手动填写。" : ""].filter(Boolean).join(" ")}><Select value="" disabled={namesReading || !suggestions.length} onChange={event => { const item = suggestions[Number(event.target.value)]; if (!event.target.value || !item) return; setName(item.name); setChosenSource(item.source); setReason(`依据${item.source}补充商品名称`); }}><option value="">{namesReading ? "正在读取报告名称…" : suggestions.length ? "请选择报告中的名称" : "暂无可选名称，可留空待补或手动填写"}</option>{suggestions.map((item, index) => <option value={index} key={`${item.source}:${item.name}`}>{item.name} · {item.source}</option>)}</Select></FormField>}
          {nameSuggestion && <p>候选依据：{nameSuggestion.source}。请核对为该款商品的通用名称，再生成预览。</p>}
          <FormField label="主分类"><Select onChange={event => setCategoryId(event.target.value)} value={rootId}><option value="">待分类</option>{categories.filter(item => !item.parent_category_id && item.status === "enabled").map(item => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</Select></FormField>
          {rootId && <FormField label="细分类（可选）"><Select onChange={event => setCategoryId(event.target.value || rootId)} value={selected?.parent_category_id ? categoryId : ""}><option value="">仅主分类 / 暂不细分</option>{children.map(item => <option key={item.category_id} value={item.category_id}>{item.display_name}（{item.code}）</option>)}</Select></FormField>}
        </fieldset>
        <div className={css.scope}>这份草稿只包含当前商品；变体、Seller SKU 与其他商品不会进入本次修改。</div>
        <footer className={css.footer}><span>生成预览不会发布目录。</span><Button type="submit" variant="primary" loading={busy} loadingLabel="正在生成预览" disabled={reading || readFailed || restoring || Boolean(restoreError)}>生成变更预览</Button></footer>
      </form> : <div>
        <Table className={css.comparison} title="变更预览" description={`草稿 #${preview.draft_id} · 修订 ${preview.draft_revision}，仅下列字段进入本次批准。`}><thead><tr><th scope="col">字段</th><th scope="col">修改前</th><th scope="col">批准后</th></tr></thead><tbody><tr><th scope="row">标准名称</th><td>{catalogNameDisplay(preview.before.standard_name)}</td><td className={css.after}>{catalogNameDisplay(preview.after.standard_name)}</td></tr><tr><th scope="row">主分类</th><td>{categoryLabel(preview.before.category)}</td><td className={css.after}>{categoryLabel(preview.after.category)}</td></tr></tbody></Table>
        <div className={css.reason}><FormField label="批准原因" required hint="至少 3 个字符，记录本次维护的原因。"><Input disabled={busy} maxLength={500} minLength={3} onChange={event => setReason(event.target.value)} value={reason} /></FormField></div>
        <footer className={css.footer}><Button disabled={busy} onClick={() => { setPreview(undefined); setError(undefined); }}>返回修改</Button><Button variant="primary" icon={<Check />} loading={busy} loadingLabel="正在批准并刷新" disabled={stale || readonly || restoring || reason.trim().length < 3} onClick={() => void approve()}>批准并生成新目录版本</Button></footer>
      </div>}
      {error && <div className={css.feedback}><StatusMessage kind="danger" title="本次操作未完成">{error}</StatusMessage></div>}
    </div>
  </section>;
}
