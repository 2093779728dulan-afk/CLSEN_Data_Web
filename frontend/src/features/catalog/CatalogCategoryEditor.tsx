import { ChevronDown, ChevronRight, FileText, Folder, FolderOpen, FolderTree, Plus, Settings2, X } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";
import { Button, FormField, Input, Select, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import { createCatalogCategory, listCatalogCategories, updateCatalogCategory, type CatalogCategory } from "./catalogApi";
import css from "./CatalogCategoryEditor.module.css";

const codeHint = "2–64 位，字母开头；可用字母、数字、_、-，不能含空格、中文或斜杠。";
function validCode(code: string) { return /^[A-Z][A-Z0-9_-]{1,63}$/.test(code.normalize("NFKC").trim().toUpperCase()); }
const emptyDraft = (): CatalogCategory => ({ category_id: 0, code: "", display_name: "", parent_category_id: null, aliases: [], status: "enabled" });
export type CatalogCategoryServices = { list: typeof listCatalogCategories; create: typeof createCatalogCategory; update: typeof updateCatalogCategory };
const defaultServices: CatalogCategoryServices = { list: listCatalogCategories, create: createCatalogCategory, update: updateCatalogCategory };
export function CatalogCategoryEditor({ services = defaultServices }: { services?: CatalogCategoryServices }) {
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<CatalogCategory[]>([]);
  const [draft, setDraft] = useState<CatalogCategory>(emptyDraft);
  const [dirty, setDirty] = useState(false);
  const [search, setSearch] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const hintId = useId();
  const [readFailed, setReadFailed] = useState(false);
  const [readAttempt, setReadAttempt] = useState(0);
  const readCategories = services.list;
  const [openRoots, setOpenRoots] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true); setReadFailed(false);
    void readCategories().then((value) => {
      if (!active) return;
      setItems(value);
      setOpenRoots(new Set(value.filter((item) => !item.parent_category_id && value.some((child) => child.parent_category_id === item.category_id)).map((item) => item.category_id)));
    }).catch(() => { if (active) setReadFailed(true); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [open, readAttempt, readCategories]);
  const roots = items.filter((item) => !item.parent_category_id);
  const hasChildren = items.some((item) => item.parent_category_id === draft.category_id);
  const selectableRoots = roots.filter((item) => item.category_id !== draft.category_id && (item.status === "enabled" || item.category_id === draft.parent_category_id));
  const choose = (item: CatalogCategory) => {
    if (dirty) { setError("当前修改尚未保存，请先保存或点击“取消修改”。"); return; }
    setDraft({ ...item, aliases: [...item.aliases] }); setError(undefined); setNotice(undefined);
  };
  const edit = (changes: Partial<CatalogCategory>) => { setDraft((value) => ({ ...value, ...changes })); setDirty(true); setError(undefined); setNotice(undefined); };
  const cancel = () => { setDraft(items.find((item) => item.category_id === draft.category_id) ?? emptyDraft()); setDirty(false); setError(undefined); setNotice(undefined); };
  const persist = async () => {
    setError(undefined); setNotice(undefined);
    if (!validCode(draft.code)) { setError(`分类代码格式不正确。${codeHint}`); return; }
    if (!draft.display_name.trim()) { setError("请填写分类名称。"); return; }
    setBusy(true);
    try {
      const cleaned = { ...draft, aliases: draft.aliases.map((alias) => alias.trim()).filter(Boolean) };
      const saved = draft.category_id ? await services.update(cleaned) : await services.create(cleaned.code, cleaned.display_name, cleaned.aliases, cleaned.parent_category_id ?? null);
      setDirty(false);
      if (saved) {
        setDraft(saved);
        setItems((current) => [...current.filter((item) => item.category_id !== saved.category_id), saved].sort((a, b) => a.code.localeCompare(b.code)));
      }
      setNotice("已保存分类。商品关联与历史目录保持不变。");
    } catch { setError("保存失败。请检查代码或别名是否重复，上级是否为启用的主分类；已有细分类的主分类不能移到其他分类下。"); }
    finally { setBusy(false); }
  };
  const matches = (item: CatalogCategory) => `${item.code} ${item.display_name} ${item.aliases.join(" ")}`.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase());
  const groups = roots.map((root) => ({ root, children: items.filter((item) => item.parent_category_id === root.category_id) })).filter(({ root, children }) => matches(root) || children.some(matches));
  const orphaned = items.filter((item) => item.parent_category_id && !roots.some((root) => root.category_id === item.parent_category_id) && matches(item));
  useEffect(() => {
    if (!search.trim()) return;
    const query = search.trim().toLocaleLowerCase();
    const matchesSearch = (item: CatalogCategory) => `${item.code} ${item.display_name} ${item.aliases.join(" ")}`.toLocaleLowerCase().includes(query);
    setOpenRoots((current) => {
      const next = new Set(current);
      items.filter((item) => !item.parent_category_id).forEach((root) => {
        const children = items.filter((item) => item.parent_category_id === root.category_id);
        if (matchesSearch(root) || children.some(matchesSearch)) next.add(root.category_id);
      });
      return next;
    });
  }, [search, items]);
  const toggleRoot = (categoryId: number) => setOpenRoots((current) => {
    const next = new Set(current);
    if (next.has(categoryId)) next.delete(categoryId); else next.add(categoryId);
    return next;
  });
  const categoryStatus = (item: CatalogCategory) => item.status === "disabled" && <StatusBadge tone="quiet" label="停用" />;
  const categoryIdentity = (item: CatalogCategory) => <span className={css.identity}><strong>{item.display_name}</strong><code>{item.code}</code></span>;
  const selectButton = (item: CatalogCategory, className: string | undefined, icon: ReactNode) => <button type="button" disabled={busy} className={className} aria-label={`编辑 ${item.display_name}`} aria-pressed={draft.category_id === item.category_id} aria-current={draft.category_id === item.category_id ? "true" : undefined} onClick={() => choose(item)}><span className={css.categoryIcon}>{icon}</span>{categoryIdentity(item)}{categoryStatus(item)}</button>;
  if (!open) return <Button icon={<Settings2 />} onClick={() => setOpen(true)}>管理分类</Button>;
  return <section className={css.panel} aria-label="分类字典管理">
    <header className={css.header}><div><p>商品分类</p><h3>主分类与细分类</h3><span>先选分类，再维护名称、代码与归属。</span></div><div className={css.headerActions}><Button icon={<Plus />} disabled={busy || loading || readFailed} onClick={() => choose(emptyDraft())}>新建分类</Button><Button variant="secondary" aria-label="关闭分类管理" icon={<X />} disabled={busy} onClick={() => { if (dirty) setError("当前修改尚未保存，请先保存或点击“取消修改”。"); else setOpen(false); }}>关闭管理</Button></div></header>
    <div className={css.workspace}>
      <aside className={css.list} aria-label="分类列表"><div className={css.listHeading}><span><FolderTree size={16} />分类目录</span><small>{roots.length} 主分类 · {items.length - roots.length} 细分类</small></div><Input aria-label="查找分类" placeholder="搜索名称或代码" value={search} onChange={(event) => setSearch(event.target.value)} /><div className={css.groups} tabIndex={0} role="group" aria-label="商品分类目录">{loading ? <div role="status" aria-label="正在读取分类"><Skeleton lines={5} height={40} /><p>正在读取分类…</p></div> : readFailed ? <StatusMessage kind="danger" title="分类字典读取未完成" action={<Button onClick={() => setReadAttempt(value => value + 1)}>重新读取分类</Button>}>分类字段暂不可修改。</StatusMessage> : <>{groups.map(({ root, children }) => {
        const visibleChildren = children.filter((item) => matches(root) || matches(item));
        const expandable = visibleChildren.length > 0;
        const expanded = openRoots.has(root.category_id);
        const groupId = `${hintId}-category-${root.category_id}`;
        return <div key={root.category_id} className={css.treeGroup} role="group" aria-label={`${root.display_name}分类组`}>
          <div className={css.folderRow}>
            {expandable ? <button type="button" className={css.folderToggle} aria-label={`${expanded ? "收起" : "展开"} ${root.display_name}`} aria-expanded={expanded} aria-controls={groupId} disabled={busy} onClick={() => toggleRoot(root.category_id)}>{expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}</button> : <span className={css.folderTogglePlaceholder} aria-hidden="true" />}
            {selectButton(root, css.folderButton, expanded ? <FolderOpen size={16} /> : <Folder size={16} />)}
            <span className={css.childCount} aria-label={`${children.length} 个细分类`}>{children.length || "—"}</span>
          </div>
          {expandable && expanded && <div id={groupId} className={css.subFiles} role="group">{visibleChildren.map((item) => <div key={item.category_id}>{selectButton(item, css.fileButton, <FileText size={15} />)}</div>)}</div>}
        </div>;
      })}{orphaned.map((item) => <div key={item.category_id} className={css.orphaned}>{selectButton(item, css.fileButton, <FileText size={15} />)}</div>)}{!groups.length && !orphaned.length && <p className={css.empty}>{search ? "没有匹配的分类" : "尚无分类，从右侧新建"}</p>}</>}</div></aside>
      <form className={css.editor} onSubmit={(event) => { event.preventDefault(); void persist(); }}>
        <div className={css.editorHeading}><div><span className={css.kind}>{draft.category_id ? "编辑分类" : "新建分类"} · {draft.parent_category_id ? "细分类" : "主分类"}</span><h4>{draft.category_id ? (items.find((item) => item.category_id === draft.category_id)?.display_name ?? "分类详情") : "填写分类信息"}</h4></div>{dirty && <StatusBadge tone="warn" label="未保存" />}</div>
        <fieldset disabled={busy || loading || readFailed} className={css.fields}>
          <FormField label="分类名称" required><Input aria-label="分类名称" value={draft.display_name} maxLength={128} placeholder="如 短款连衣裙" onChange={event => edit({ display_name: event.target.value })} /></FormField>
          <FormField label="分类代码" required hint={codeHint}><Input aria-label={draft.category_id ? `分类 ${draft.category_id} 代码` : "分类代码"} value={draft.code} maxLength={64} placeholder="如 DRESS_MINI" onChange={event => edit({ code: event.target.value.toUpperCase() })} /></FormField>
          <FormField label="上级分类" hint={hasChildren ? "已有细分类，保持为主分类。" : "选择上级后，当前分类归入该主分类；最多两级。"}><Select aria-label="上级分类" disabled={hasChildren} value={draft.parent_category_id ?? ""} onChange={event => edit({ parent_category_id: Number(event.target.value) || null })}><option value="">无上级 · 作为主分类</option>{selectableRoots.map(root => <option key={root.category_id} value={root.category_id}>{root.display_name}（{root.code}）</option>)}</Select></FormField>
          <FormField label="状态" hint="停用后保留已有商品和历史记录。"><Select aria-label="分类状态" value={draft.status} disabled={!draft.category_id} onChange={event => edit({ status: event.target.value as CatalogCategory["status"] })}><option value="enabled">启用</option><option value="disabled">停用</option></Select></FormField>
          <FormField className={css.full} label="别名（可选）" hint="同义名称用中文逗号分隔，无需重复新建分类。"><Input aria-label="分类别名" value={draft.aliases.join("，")} placeholder="如 Mini dress，短裙装" onChange={event => edit({ aliases: event.target.value.split("，") })} /></FormField>
        </fieldset>
        {error && <div className={css.feedback}><StatusMessage kind="danger" title="分类修改未完成">{error}</StatusMessage></div>}{notice && <div className={css.feedback}><StatusMessage kind="success" title="分类已保存">{notice}</StatusMessage></div>}
        <footer className={css.footer}><span>保存分类字典，不会自动批准商品变更。</span><div><Button disabled={busy} onClick={cancel}>取消修改</Button><Button type="submit" variant="primary" loading={busy} loadingLabel="正在保存分类" disabled={loading || readFailed || !dirty}>{draft.category_id ? "保存修改" : "创建分类"}</Button></div></footer>
      </form>
    </div>
    <div className={css.footnote}>商品关联使用固定身份。修改分类代码或上级后，历史目录仍保留批准时的分类路径。</div>
  </section>;
}
