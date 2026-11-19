import { useEffect, useRef, type ReactNode } from "react";
import { Button, FormField, Skeleton, StatusMessage } from "../../design-system";
import styles from "./OrderWorkbench.module.css";

export type FactoryRecord = { id: string; name: string; order_count?: string };
export type WarehouseScope = { warehouse_type?: string; warehouse_status?: string; warehouse_id: string; owner_id: string; warehouse_name: string; owner_name: string };
export type WorkbenchStock = { scopes: WarehouseScope[]; writes_enabled?: boolean; items: { warehouse_id: string; owner_id: string; sku_id: string; state: string; free_available_units: string | null }[] };
export function ReadState({ error }: { error?: string }) { return error ? <StatusMessage kind="danger" title="读取未完成">{error}</StatusMessage> : <div className={styles.readPlaceholder} role="status" aria-label="正在读取"><p>正在读取…</p><Skeleton lines={4} height={36} /></div>; }
export function ReadContent({ loading, error, retry, children }: { loading: boolean; error?: string; retry: () => void; children: ReactNode }) {
  const focus = useRef<HTMLElement | null>(null);
  const wasLoading = useRef(loading);
  useEffect(() => {
    if (wasLoading.current && !loading && !error && document.activeElement === document.body && focus.current?.isConnected) focus.current.focus({ preventScroll: true });
    wasLoading.current = loading;
  }, [loading, error]);
  return <div aria-busy={loading} onFocusCapture={event => { if (event.target instanceof HTMLElement) focus.current = event.target; }}>
    <div className={styles.readStatus} role={loading || error ? "status" : undefined}>{loading ? "正在更新，暂不可操作…" : error ? <>更新失败，旧内容仅供参考，操作已暂停：{error} <Button variant="secondary" onClick={retry}>重新读取</Button></> : null}</div>
    <div className={styles.readContent} inert={loading || !!error} aria-disabled={loading || !!error}>
      {/* Page layout stays outside native fieldsets; each editing form owns its disabled state. */}
      <div className={styles.readBody}>{children}</div>
    </div>
  </div>;
}
export function Fields({ children }: { children: ReactNode }) { return <div className={styles.fields}>{children}</div>; }
export function WarehouseField({ scopes, value, onChange, label = "仓库", disabled = false, required = true }: { scopes: WarehouseScope[]; value: string; onChange: (value: string) => void; label?: string; disabled?: boolean; required?: boolean }) {
  return <FormField label={label} required={required}><select required={required} disabled={disabled} value={value} onChange={e => onChange(e.target.value)}><option value="">{required ? "请选择已登记仓库" : "未登记（保留历史未知）"}</option>{scopes.map(s => <option key={`${s.warehouse_id}:${s.owner_id}`} value={`${s.warehouse_id}:${s.owner_id}`}>{s.warehouse_name}</option>)}</select></FormField>;
}
