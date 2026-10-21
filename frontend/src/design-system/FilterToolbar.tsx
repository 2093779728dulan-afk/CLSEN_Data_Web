import { useRef, type ReactNode } from "react";
import { X } from "lucide-react";
import { Button } from "./Button";
import { Checkbox } from "./Checkbox";
import { FormField } from "./FormField";
import { SearchInput } from "./SearchInput";
import styles from "./FilterToolbar.module.css";

export type FilterToolbarProps = {
  children?: ReactNode; matchingCount: number; totalCount: number; query: string; onQueryChange: (query: string) => void;
  onlyPending?: boolean; onOnlyPendingChange?: (onlyPending: boolean) => void; onReset?: () => void;
  hasAdditionalFilters?: boolean; searchLabel?: string; pendingLabel?: string; placeholder?: string;
};

export function FilterToolbar({ children, matchingCount, totalCount, query, onQueryChange, onlyPending = false, onOnlyPendingChange, onReset, hasAdditionalFilters = false, searchLabel = "搜索当前审核项", pendingLabel = "仅看待处理", placeholder = "款号、SKU 或字段内容" }: FilterToolbarProps) {
  const filtered = Boolean(query || onlyPending || hasAdditionalFilters);
  const search = useRef<HTMLInputElement>(null);
  return <div className={styles.toolbar}>
    <div className={styles.controls}>
      <FormField className={styles.search} label={searchLabel}><SearchInput onValueChange={onQueryChange} placeholder={placeholder} ref={search} value={query} /></FormField>
      {children}
      {onOnlyPendingChange && <div className={styles.pending}><Checkbox checked={onlyPending} label={pendingLabel} onChange={event => onOnlyPendingChange(event.target.checked)} /></div>}
    </div>
    <div className={styles.meta}>
      <p aria-atomic="true" aria-live="polite" className={styles.count}>匹配 <strong>{matchingCount}</strong><span> / {totalCount} 项</span></p>
      <div className={styles.chips}>
        {query && <button aria-label="移除搜索条件" className={styles.chip} onClick={() => { onQueryChange(""); search.current?.focus(); }} title={query} type="button"><span>搜索：{query}</span><X aria-hidden="true" /></button>}
        {onlyPending && <button aria-label="移除待处理筛选" className={styles.chip} onClick={() => { onOnlyPendingChange?.(false); search.current?.focus(); }} type="button"><span>待处理</span><X aria-hidden="true" /></button>}
      </div>
      <Button className={styles.reset} disabled={!filtered} onClick={() => { if (onReset) onReset(); else { onQueryChange(""); onOnlyPendingChange?.(false); } search.current?.focus(); }} variant="quiet">重置筛选</Button>
    </div>
  </div>;
}
