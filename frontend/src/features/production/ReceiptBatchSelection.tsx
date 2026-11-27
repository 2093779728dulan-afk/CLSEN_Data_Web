import { Disclosure } from "../../design-system";
import { useState } from "react";
import { Table } from "../../design-system";
import { receiptOrderGroups } from "./orderProgress";
import styles from "./OrderWorkbench.module.css";

export function ReceiptBatchSelection({ groups, selected, disabled, onChange }: {
  groups: ReturnType<typeof receiptOrderGroups>; selected: string[]; disabled: boolean; onChange: (id: string, checked: boolean) => void;
}) {
  const [open, setOpen] = useState(selected.length === 0);
  const completed = groups.filter(group => group.complete);
  const rows = (items: typeof groups) => <Table className={styles.receiptOrderTable} aria-label="选择本批来源订单"><thead><tr><th>订单 / 工厂</th><th>下单</th><th>已入库</th><th>待收</th></tr></thead><tbody>{items.map(group => <tr key={group.id}>
    <th scope="row"><label><input type="checkbox" aria-label={`选择订单${group.id} ${group.label}`} checked={selected.includes(group.id)} disabled={disabled} onChange={event => onChange(group.id, event.target.checked)} /><span title={group.label}>{group.label}<small>{group.factory}</small></span></label></th>
    <td>{group.expected.toLocaleString("zh-CN")}</td><td>{group.received?.toLocaleString("zh-CN") ?? ""}</td><td>{group.remaining?.toLocaleString("zh-CN") ?? ""}</td>
  </tr>)}</tbody></Table>;
  return <Disclosure className={styles.receiptOrderSelection} open={open} onToggle={event => setOpen(event.currentTarget.open)}>
    <summary>选择订单 · 已选 {selected.length}/{groups.length}</summary>
    {groups.some(group => !group.complete) && rows(groups.filter(group => !group.complete))}
    {!!completed.length && <Disclosure><summary>已收齐 · {completed.length} 单</summary>{rows(completed)}</Disclosure>}
  </Disclosure>;
}
