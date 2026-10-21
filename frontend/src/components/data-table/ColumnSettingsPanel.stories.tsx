import type { Meta, StoryObj } from "@storybook/react-vite";
import { useMemo, useRef, useState } from "react";
import { Button } from "../../design-system";
import { ColumnSettingsPanel } from "./ColumnSettingsPanel";
import { useColumnLayout, type DataTableColumn } from "./useColumnLayout";
import css from "./ColumnSettingsPanel.module.css";
import "./dataTable.css";

type Scenario = "reference" | "filtered-empty" | "identity-only" | "long-columns" | "many-columns" | "empty";
const columns: DataTableColumn[] = [
  { column_id: "sku", source_header: "Seller SKU", standard_field_name: "seller_sku", is_key: true, display_order: 0 },
  { column_id: "sales", source_header: "销售额", standard_field_name: "sales", is_key: false, display_order: 1, participates_in_statistics: true },
  { column_id: "sessions", source_header: "访问次数", standard_field_name: "sessions", is_key: false, display_order: 2, participates_in_statistics: true },
  { column_id: "extension", source_header: "来源扩展字段", standard_field_name: null, is_key: false, display_order: 3 },
];
const longColumns = columns.map((column, index) => ({ ...column, source_header: index === 0 ? "用于跨报告核对的 Seller SKU 商品标识字段" : `${column.source_header} · 原始来源文件中的较长字段说明（虚构）` }));
const manyColumns = [...columns, ...Array.from({ length: 24 }, (_, index) => ({ column_id: `extra-${index}`, source_header: `来源字段 ${index + 1}`, standard_field_name: null, is_key: false, display_order: index + 4 }))];
function ColumnSettingsStory({ scenario = "reference" }: { scenario?: Scenario }) {
  const data = useMemo(() => scenario === "empty" ? [] : scenario === "identity-only" ? columns.slice(0, 1) : scenario === "long-columns" ? longColumns : scenario === "many-columns" ? manyColumns : columns, [scenario]);
  const layout = useColumnLayout({ columns: data, identity: { namespace: "workbench", userId: `storybook-column-settings-${scenario}`, siteId: "fictional", reportType: "business_report" } });
  const [open, setOpen] = useState(true);
  const trigger = useRef<HTMLButtonElement>(null);
  return <div className={css.story}>
    <Button aria-controls="story-column-settings" aria-expanded={open} onClick={() => setOpen(!open)} ref={trigger}>列设置</Button>
    {open && <ColumnSettingsPanel columns={data} id="story-column-settings" layout={layout} onChange={() => undefined} onClose={() => { setOpen(false); window.setTimeout(() => trigger.current?.focus(), 0); }} />}
    <p className={css.note}>虚构列结构，复用实际列偏好逻辑；仅保存本故事的浏览器偏好，不请求 API。</p>
    <output aria-label="当前显示列" className={css.note}>{layout.visibleColumns.map(column => column.source_header).join(" / ") || "暂无显示列"}</output>
  </div>;
}
const meta = { title: "Patterns/Column Settings", component: ColumnSettingsStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof ColumnSettingsStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const FilteredEmpty: Story = { args: { scenario: "filtered-empty" } };
export const IdentityOnly: Story = { args: { scenario: "identity-only" } };
export const LongColumns: Story = { args: { scenario: "long-columns" } };
export const ManyColumns: Story = { args: { scenario: "many-columns" } };
export const Empty: Story = { args: { scenario: "empty" } };
