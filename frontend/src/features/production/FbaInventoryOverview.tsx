import { Disclosure } from "../../design-system";
import { Fragment, useState, type ReactNode } from "react";

import { Button, Input, LinkButton, StatusMessage, Table } from "../../design-system";
import type { FbaInventoryView, FbaScope } from "./fbaTypes";
import type { Sku } from "./types";
import styles from "./FbaWorkspace.module.css";
import warehouseStyles from "./WarehouseCenter.module.css";

type InventoryItem = FbaInventoryView["groups"][number]["items"][number];
const amount = (value: string | null) => value === null ? "待核" : BigInt(value) === 0n ? "" : BigInt(value).toLocaleString("zh-CN");
const total = (items: InventoryItem[]) => items.some(item => item.on_hand === null)
  ? null
  : items.reduce((sum, item) => sum + BigInt(item.on_hand!), 0n).toString();
const movementNames = { RECEIPT: "FBA入库", FULFILLMENT: "销售出库", RETURN: "实物退回", COUNT: "盘点调整" };
const qualities: Record<string, string> = { QUALIFIED: "合格", PENDING: "待检", DEFECTIVE: "不可售" };
const sizeOrder = ["XS", "S", "M", "L", "XL", "XXL", "3XL"];

export function FbaInventoryOverview({ view, scope, catalog, children }: {
  view?: FbaInventoryView;
  scope: FbaScope;
  catalog: Sku[];
  children?: ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState("");
  const [closed, setClosed] = useState<string[]>([]);
  const stockUrl = (kind: string, batch?: string) => `/production/warehouses/${scope.warehouse_id}?${new URLSearchParams({
    owner: scope.owner_id, tab: "stock", fba_view: kind, ...(batch ? { fba_batch: batch } : {}),
  })}`;
  if (!view) return <StatusMessage kind="info" title="库存汇总尚未返回，请重新读取" />;

  const groupName = (style: string, sku: string) => catalog.find(item => item.style_id === style)?.style_code
    || catalog.find(item => item.sku_id === sku)?.style_code || "款号待核";
  const catalogIds = new Set(catalog.map(sku => sku.sku_id));
  const scopedGroups = view.groups.map(group => ({ ...group, items: group.items.filter(item => catalogIds.has(item.sku_id)) }))
    .filter(group => group.items.length).map(group => ({ ...group, on_hand: total(group.items) }));
  const scopedOnHand = total(scopedGroups.flatMap(group => group.items));
  const catalogGroups = new Map(scopedGroups.map(group => [group.style_id, { ...group, items: [...group.items] }]));
  const recorded = new Set(view.groups.flatMap(group => group.items.map(item => item.sku_id)));
  for (const sku of catalog) {
    if (sku.status !== "active" || !sku.style_id || recorded.has(sku.sku_id)) continue;
    const group: FbaInventoryView["groups"][number] = catalogGroups.get(sku.style_id) ?? { style_id: sku.style_id, on_hand: "0", items: [] };
    group.items.push({ sku_id: sku.sku_id, style_id: sku.style_id, seller_sku: sku.code || sku.label,
      on_hand: "0", available: "0", received: "0", fulfilled: "0", returned: "0" });
    catalogGroups.set(sku.style_id, group);
  }
  const groups = [...catalogGroups.values()].map(group => ({ ...group, items: group.items.filter(item => {
    const sku = catalog.find(sku => sku.sku_id === item.sku_id);
    return (item.on_hand === null || BigInt(item.on_hand) !== 0n) && [groupName(group.style_id, item.sku_id), item.seller_sku, sku?.standard_color, sku?.standard_size]
      .join(" ").toLocaleLowerCase().includes(query.trim().toLocaleLowerCase());
  }) })).filter(group => group.items.length);
  const variants = groups.flatMap(group => group.items.map(item => {
    const sku = catalog.find(sku => sku.sku_id === item.sku_id);
    return { item, group: group.style_id, color: sku?.standard_color || item.seller_sku, size: sku?.standard_size || "尺码待核" };
  }));
  const sizes = [...new Set(catalog.map(sku => sku.standard_size || "尺码待核"))].sort((left, right) => {
    const leftIndex = sizeOrder.indexOf(left), rightIndex = sizeOrder.indexOf(right);
    return (leftIndex < 0 ? 99 : leftIndex) - (rightIndex < 0 ? 99 : rightIndex)
      || left.localeCompare(right, "zh-CN", { numeric: true });
  });
  const renderMovements = (item: InventoryItem) => {
    const movements = view.movements.filter(movement => movement.sku_id === item.sku_id);
    return <section key={item.sku_id} className={styles.inventoryMovements} aria-label={`${item.seller_sku}库存变动`}>
    <div className={styles.movementHeading}>
      <strong>{catalog.find(sku => sku.sku_id === item.sku_id)?.code || item.seller_sku}</strong>
      <dl>{([
      ["已入库", item.received], ["已出库", item.fulfilled], ["实物退回", item.returned], ["账面可发", item.available],
      ] as const).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{amount(value)}</dd></div>)}</dl>
    </div>
    {!!movements.length && <Disclosure className={styles.movementHistory}>
      <summary><span>变动记录</span><span className={styles.movementCount}>{movements.length}</span></summary>
      <div className={styles.movementList}>{movements.map(movement => <Disclosure className={styles.movementRecord} key={movement.id}>
        <summary aria-label={`${movementNames[movement.kind]} ${amount(movement.units)}件 · ${movement.occurred_at.slice(0, 10)}`}>
          <time dateTime={movement.occurred_at}>{movement.occurred_at.slice(0, 10)}</time>
          <span>{movementNames[movement.kind]}{movement.kind === "RETURN" ? ` · ${qualities[movement.quality || ""] || "质量待核"}` : ""}</span>
          <strong>{BigInt(movement.units) > 0n ? "+" : ""}{amount(movement.units)}</strong>

        </summary>
        <div className={styles.movementEvidence}>
          <p>{movement.reason}</p><p>来源：{movement.reference}</p><time dateTime={movement.occurred_at}>{movement.occurred_at}</time>
          {movement.batch_id && <LinkButton variant="quiet" to={stockUrl("receipts", movement.batch_id)}>查看接收原件</LinkButton>}
          {!!movement.report_version_ids.length && <LinkButton variant="quiet" to="/ledger/published-details">查看报告记录</LinkButton>}
        </div>
      </Disclosure>)}</div>
    </Disclosure>}
    {!movements.length && <p>暂无已确认变动</p>}
  </section>;
  };

  return <section className={styles.inventoryOverview} aria-label="FBA库存简览">
    <div className={styles.inventoryHeading}>
      <dl className={styles.onHandSummary} aria-label="FBA账面库存汇总"><dt>在库</dt><dd>{amount(scopedOnHand)}</dd></dl>
    </div>
    <Input type="search" aria-label="查找FBA款号或规格" placeholder="搜索款号、颜色或尺码" value={query} onChange={event => {
      setQuery(event.target.value);
      setClosed([]);
    }} />
    {!!groups.length && <Table className={`${warehouseStyles.matrix} ${styles.inventoryMatrix}`} aria-label="FBA在库库存" style={{ minWidth: 240 + (sizes.length + 1) * 64 }}>
      <thead><tr>
        <th scope="col">款号</th><th scope="col">颜色</th>
        {sizes.map(size => <th scope="col" key={size}>{size}</th>)}
        <th scope="col" className={warehouseStyles.totalColumn}>合计</th>
      </tr></thead>
      <tbody>{groups.map(group => {
        const rows = variants.filter(variant => variant.group === group.style_id);
        const colors = [...new Set(rows.map(variant => variant.color))];
        const collapsed = closed.includes(group.style_id);
        const title = groupName(group.style_id, group.items[0]!.sku_id);
        return (collapsed ? [null] : colors).map((color, index) => {
          const colorRows = color === null ? rows : rows.filter(variant => variant.color === color);
          const active = color === null ? undefined : colorRows.find(variant => variant.item.sku_id === selected);
          return <Fragment key={`${group.style_id}:${color ?? "collapsed"}`}>
            <tr className={index === 0 ? warehouseStyles.productStart : undefined}>
              <th scope="row" className={warehouseStyles.styleIdentity}>
                {index === 0 ? <Button variant="quiet" aria-expanded={!collapsed}

                  onClick={() => setClosed(current => current.includes(group.style_id) ? current.filter(id => id !== group.style_id) : [...current, group.style_id])}
                >{title} · {collapsed ? "查看" : "收起"}</Button> : <span>{title}</span>}
              </th>
              <td className={warehouseStyles.colorIdentity}>{color ?? <span className={warehouseStyles.collapsedColors}>{colors.length}种颜色 · 已收起</span>}</td>
              {sizes.map(size => {
                const matches = colorRows.filter(variant => variant.size === size);
                const exists = catalog.some(sku => sku.style_id === group.style_id
                  && (color === null || (sku.standard_color || sku.code || sku.label) === color)
                  && (sku.standard_size || "尺码待核") === size);
                return <td key={size} className={!exists ? styles.absentSize : undefined}
                  title={!exists ? "未建档此尺码" : undefined} aria-label={!exists ? `${title} ${color ?? ""} ${size}：未建档此尺码` : undefined}>
                  {!matches.length ? <span className={warehouseStyles.unregistered} />
                    : collapsed ? <span className={warehouseStyles.quantity}><strong>{amount(total(matches.map(variant => variant.item)))}</strong></span>
                      : matches.map(({ item }) => <Button key={item.sku_id} variant="quiet" title={item.seller_sku}
                        aria-label={`查看${item.seller_sku}库存变动`} aria-expanded={selected === item.sku_id}
                        className={selected === item.sku_id ? warehouseStyles.selectedCell : undefined}
                        onClick={() => setSelected(current => current === item.sku_id ? "" : item.sku_id)}
                      ><span className={warehouseStyles.quantity}><strong>{amount(item.on_hand)}</strong></span></Button>)}
                </td>;
              })}
              <td className={warehouseStyles.totalColumn}><span className={warehouseStyles.quantity}><strong>{amount(collapsed && !query.trim() ? group.on_hand : total(colorRows.map(variant => variant.item)))}</strong></span></td>
            </tr>
            {active && <tr className={styles.inventoryDetailRow}><td colSpan={sizes.length + 3}>{renderMovements(active.item)}</td></tr>}
          </Fragment>;
        });
      })}</tbody>
      <tfoot><tr>
        <th scope="row" colSpan={2}>{query.trim() ? "筛选合计" : "本仓合计"}</th>
        {sizes.map(size => <td key={size}><span className={warehouseStyles.quantity}><strong>{amount(total(variants.filter(variant => variant.size === size).map(variant => variant.item)))}</strong></span></td>)}
        <td className={warehouseStyles.totalColumn}><span className={warehouseStyles.quantity}><strong>{amount(query.trim() ? total(variants.map(variant => variant.item)) : scopedOnHand)}</strong></span></td>
      </tr></tfoot>
    </Table>}
    {!groups.length && <p>{query ? "没有匹配的款号或规格" : "暂无已登记规格"}</p>}
    {!!view.issues.length && <Disclosure className={styles.inventoryIssues}>
      <summary>待核 {view.issues.length} 项</summary>
      {view.issues.map(issue => <p key={issue.id}><LinkButton variant="quiet" to={stockUrl(issue.view, issue.batch_id)}>
        {issue.sku_id ? `${catalog.find(sku => sku.sku_id === issue.sku_id)?.code || issue.sku_id} · ` : ""}{issue.label}
      </LinkButton></p>)}
    </Disclosure>}
    <Disclosure className={styles.balanceDetails}>
      <summary>库存记录与对账</summary>
      <div className={styles.balanceDetailsBody}>
        <LinkButton to="/">发布总表</LinkButton>
        {view.latest_movement_at && <p>最近变动 {view.latest_movement_at.slice(0, 10)}</p>}{children}
      </div>
    </Disclosure>
  </section>;
}
