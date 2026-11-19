import { useRef, useState } from "react";
import { requestApi, writeApi } from "../../api/client";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { Button, FormField, StatusMessage, Table } from "../../design-system";
import type { ManualBatch, ManualKind } from "./manualTablesApi";
import styles from "../production/Production.module.css";

type Choice = Pick<ManualBatch, "id" | "filename" | "revision" | "kind">;
type Comparison = { rows: { style: string; color: string; size: string; before?: string | null; inventory?: string | null; orders?: string | null; packing?: string | null; unexplained_difference: string | null; unshipped_planned: string | null }[]; warnings: string[] };
const roles: [string, string, ManualKind][] = [["before", "之前库存（选填）", "inventory"], ["inventory", "本次结存", "inventory"], ["orders", "预下单", "orders"], ["packing", "装箱资料", "packing"]];

export function ManualComparison() {
  const { generation } = useAuthzGeneration(); const live = useRef(generation); live.current = generation;
  const [choices, setChoices] = useState<Choice[]>([]); const [selection, setSelection] = useState<Record<string, string>>({});
  const [result, setResult] = useState<Comparison>(); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  async function load() {
    const epoch = live.current; setBusy(true); setError("");
    try {
      let page = 1; const all: Choice[] = [];
      for (;;) {
        const value = await requestApi<{ items: Choice[]; total: number }>(`/api/manual-tables/batches?page=${page}`);
        if (epoch !== live.current) return; all.push(...value.items); if (all.length >= value.total || !value.items.length) break; page++;
      }
      setChoices(all);
    } catch (reason) { if (epoch === live.current) setError(reason instanceof Error ? reason.message : "资料列表读取失败。"); }
    finally { if (epoch === live.current) setBusy(false); }
  }
  async function compare() {
    const epoch = live.current; setBusy(true); setError("");
    try {
      const references = Object.fromEntries(Object.entries(selection).filter(([, id]) => id).map(([role, id]) => [role, { id, revision: choices.find(c => c.id === id)?.revision }]));
      const value = await writeApi<Comparison>("/api/manual-tables/compare", { body: { references } });
      if (epoch === live.current) setResult(value);
    } catch (reason) { if (epoch === live.current) setError(reason instanceof Error ? reason.message : "对照未完成，请重新选择资料修订。"); }
    finally { if (epoch === live.current) setBusy(false); }
  }
  return <details className={styles.panel} onToggle={event => { if (event.currentTarget.open && !choices.length) void load(); }}><summary>相关人工资料对照（仅比较选定批次）</summary><p>比较预下单、装箱与库存的规格数量。之前库存－本次出货与当前结存的差额仅供核对，不自动登记收发。</p><div className={styles.fields}>{roles.map(([role, label, kind]) => <FormField key={role} label={label}><select aria-label={label} value={selection[role] || ""} disabled={busy} onChange={event => { setSelection(s => ({ ...s, [role]: event.target.value })); setResult(undefined); }}><option value="">未选择</option>{choices.filter(c => c.kind === kind).map(c => <option key={c.id} value={c.id}>{c.filename} · 修订{c.revision}</option>)}</select></FormField>)}</div><div className={styles.actions}><Button disabled={busy || Object.values(selection).filter(Boolean).length < 2} onClick={() => void compare()}>核对所选资料</Button><Button variant="quiet" disabled={busy} onClick={() => void load()}>刷新可选修订</Button></div>{error && <StatusMessage kind="danger" title="请核对资料选择">{error}</StatusMessage>}{result && <>{result.warnings.map(w => <p key={w}>{w}</p>)}<Table title="所选规格对照"><thead><tr><th>规格</th><th>之前库存</th><th>本次结存</th><th>预下单</th><th>装箱</th><th>预计未发</th><th>结存未解释差额</th></tr></thead><tbody>{result.rows.map((r, i) => <tr key={i}><td>{r.style} · {r.color}/{r.size}</td><td>{r.before ?? "未提供"}</td><td>{r.inventory ?? "未提供"}</td><td>{r.orders ?? "未提供"}</td><td>{r.packing ?? "未提供"}</td><td>{r.unshipped_planned ?? "待核"}</td><td>{r.unexplained_difference ?? "待核"}</td></tr>)}</tbody></Table></>}</details>;
}
