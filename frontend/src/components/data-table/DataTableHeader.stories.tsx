import type { Meta, StoryObj } from "@storybook/react-vite";
import { useMemo, useState } from "react";
import { DataTableHeader, type DataTableSort } from "./DataTableHeader";
import { useColumnLayout, type DataTableColumn } from "./useColumnLayout";
import css from "./DataTableHeader.module.css";
import "./dataTable.css";

type Scenario = "reference" | "ascending" | "descending" | "return-report" | "long-headers" | "split-groups";
const base: DataTableColumn[] = [
  { column_id: "sku", source_header: "Seller SKU", standard_field_name: "seller_sku", is_key: true, display_order: 0 },
  { column_id: "title", source_header: "商品名称", standard_field_name: "title", is_key: false, display_order: 1 },
  { column_id: "sales", source_header: "销售额", standard_field_name: "sales", is_key: false, display_order: 2, participates_in_statistics: true },
  { column_id: "sessions", source_header: "访问次数", standard_field_name: "sessions", is_key: false, display_order: 3, participates_in_statistics: true },
  { column_id: "extension", source_header: "来源备注", standard_field_name: null, is_key: false, display_order: 4 },
];
const records = [{ sku: "DEMO-BLUE-S", title: "示例蓝色衬衫", sales: 120.5, sessions: 340, extension: "虚构来源 A" }, { sku: "DEMO-WHITE-M", title: "示例白色衬衫", sales: 80, sessions: 230, extension: "虚构来源 B" }, { sku: "DEMO-GREEN-L", title: "示例绿色衬衫", sales: 200, sessions: 420, extension: "虚构来源 C" }];
function TableHeaderStory({ scenario = "reference" }: { scenario?: Scenario }) {
  const columns = useMemo(() => base.map(column => ({ ...column,
    display_order: scenario === "split-groups" && column.column_id === "title" ? 2 : scenario === "split-groups" && column.column_id === "sales" ? 1 : column.display_order,
    source_header: scenario === "long-headers" ? `${column.source_header} · 来源中的较长原始字段名称（虚构）` : scenario === "return-report" && column.column_id === "sales" ? "退款金额" : column.source_header,
    standard_field_name: scenario === "return-report" && column.column_id === "sales" ? "refund_amount" : column.standard_field_name,
  })), [scenario]);
  const layout = useColumnLayout({ columns, identity: { namespace: "workbench", userId: `storybook-table-header-${scenario}`, siteId: "fictional", reportType: scenario === "return-report" ? "return_report" : "business_report" } });
  const [sort, setSort] = useState<DataTableSort>(scenario === "ascending" || scenario === "descending" ? { columnId: "sales", direction: scenario === "ascending" ? "asc" : "desc" } : null);
  const widths = layout.widths;
  const sortedRows = [...records].sort((left, right) => {
    if (!sort) return 0;
    const a = left[sort.columnId as keyof typeof left]; const b = right[sort.columnId as keyof typeof right];
    const result = typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b));
    return sort.direction === "asc" ? result : -result;
  });
  return <section aria-label="共享分组表头样板" className={css.story}>
    <h2>分组表头与列交互</h2>
    <p>点击列名切换升序、降序与原始顺序；拖动列边缘，或聚焦后用左右方向键调整列宽。</p>
    <div aria-label="可横向滚动的虚构表格" className={css.scroll} ref={layout.containerRef} role="region" tabIndex={0}>
      <table aria-label="虚构报表" className={css.table} style={{ width: 52 + layout.visibleColumns.reduce((total, column) => total + widths[column.column_id]!, 0) }}>
        <DataTableHeader columns={layout.visibleColumns} frozenLeft={Object.fromEntries(Object.entries(layout.frozenLeft).map(([id, left]) => [id, left + 52]))} groups={layout.groups} leadingColumn={{ label: "行号", width: 52 }} onResize={(id, width) => layout.resize(id, width)} onSort={command => setSort(command.direction ? { columnId: command.columnId, direction: command.direction } : null)} sort={sort} widths={widths} />
        <tbody>{sortedRows.map((row, index) => <tr key={row.sku}><td className={css.identity} style={{ left: 0 }}>{index + 1}</td>{layout.visibleColumns.map(column => <td className={layout.frozenIds.includes(column.column_id) ? css.identity : undefined} key={column.column_id} style={layout.frozenIds.includes(column.column_id) ? { left: layout.frozenLeft[column.column_id]! + 52 } : undefined}>{row[column.column_id as keyof typeof row]}</td>)}</tr>)}</tbody>
      </table>
    </div>
    <p>全虚构数据：样板在本地排序；实际页面沿用服务端排序。列宽只保存到本故事的浏览器偏好。</p>
  </section>;
}
const meta = { title: "Patterns/Table Header", component: TableHeaderStory, parameters: { layout: "fullscreen" } } satisfies Meta<typeof TableHeaderStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Reference: Story = { args: { scenario: "reference" } };
export const Ascending: Story = { args: { scenario: "ascending" } };
export const Descending: Story = { args: { scenario: "descending" } };
export const ReturnReport: Story = { args: { scenario: "return-report" } };
export const LongHeaders: Story = { args: { scenario: "long-headers" } };
export const SplitGroups: Story = { args: { scenario: "split-groups" } };
