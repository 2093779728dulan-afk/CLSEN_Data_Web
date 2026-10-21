import type { DataTableReportType, PresentableColumn } from "../../features/workbench/workbenchTypes";

export type { DataTableReportType, PresentableColumn } from "../../features/workbench/workbenchTypes";

export const WIDTH_LIMITS = { min: 72, max: 480 } as const;

export const ROW_NUMBER_WIDTH = 52;

export type ColumnPresentationGroup =
  | "product"
  | "traffic"
  | "conversion"
  | "sales"
  | "return"
  | "resolution"
  | "amount"
  | "other";

export type ColumnGroupSpan = {
  key: ColumnPresentationGroup;
  label: string;
  columnIds: string[];
  colSpan: number;
  alignment: "left" | "right";
};

type GroupMetadata = Pick<ColumnGroupSpan, "label" | "alignment">;

const BUSINESS_GROUPS: Record<ColumnPresentationGroup, GroupMetadata> = {
  product: { label: "商品信息", alignment: "left" },
  traffic: { label: "流量", alignment: "right" },
  conversion: { label: "转化", alignment: "right" },
  sales: { label: "销售", alignment: "right" },
  return: { label: "退货信息", alignment: "left" },
  resolution: { label: "处理结果", alignment: "left" },
  amount: { label: "金额", alignment: "right" },
  other: { label: "其他", alignment: "left" },
};

const RETURN_GROUPS: Record<ColumnPresentationGroup, GroupMetadata> = {
  ...BUSINESS_GROUPS,
  return: { label: "退货信息", alignment: "left" },
  resolution: { label: "处理结果", alignment: "left" },
  amount: { label: "金额", alignment: "right" },
};

function columnText(column: PresentableColumn) {
  return `${column.standard_field_name ?? ""} ${column.source_header}`.normalize("NFC").toLocaleLowerCase();
}

function matches(column: PresentableColumn, expression: RegExp) {
  return expression.test(columnText(column));
}

export function clampColumnWidth(value: number) {
  return Math.min(WIDTH_LIMITS.max, Math.max(WIDTH_LIMITS.min, Math.round(value)));
}

export function recommendedWidth(column: PresentableColumn) {
  const name = columnText(column);
  if (/title|product.?name|商品.*名|标题/.test(name)) return 300;
  if (/asin|sku|fnsku/.test(name)) return 144;
  if (/date|status|reason|日期|状态|原因/.test(name)) return 152;
  if (/quantity|units|sales|amount|rate|数量|金额|比例|率/.test(name)) return 104;
  return 168;
}

function productColumn(column: PresentableColumn) {
  return column.is_key || matches(column, /asin|sku|fnsku|product|title|商品|产品|品牌|店铺|listing|parent/);
}

function trafficColumn(column: PresentableColumn) {
  return matches(column, /session|traffic|page.?view|impression|click|访客|流量|浏览|曝光|点击/);
}

function conversionColumn(column: PresentableColumn) {
  return matches(column, /conversion|order.?item|unit.?session|buy.?box|转化|订单商品|购买/);
}

function salesColumn(column: PresentableColumn) {
  return matches(column, /sales|revenue|ordered.?product.?sales|售价|销售额|销售/);
}

function amountColumn(column: PresentableColumn) {
  return matches(column, /amount|fee|cost|price|金额|费用|成本|价格/);
}

function returnColumn(column: PresentableColumn) {
  return matches(column, /return|refund|退货|退款/);
}

function resolutionColumn(column: PresentableColumn) {
  return matches(column, /resolution|disposition|status|reason|replacement|处理|解决|状态|原因|换货/);
}

export function classifyColumn(reportType: DataTableReportType, column: PresentableColumn): ColumnPresentationGroup {
  if (productColumn(column)) return "product";

  if (reportType === "business_report") {
    if (trafficColumn(column)) return "traffic";
    if (conversionColumn(column)) return "conversion";
    if (salesColumn(column) || amountColumn(column)) return "sales";
    return "other";
  }

  if (amountColumn(column)) return "amount";
  if (returnColumn(column)) return "return";
  if (resolutionColumn(column)) return "resolution";
  return "other";
}

function groupMetadata(reportType: DataTableReportType, key: ColumnPresentationGroup) {
  return (reportType === "business_report" ? BUSINESS_GROUPS : RETURN_GROUPS)[key];
}

export function groupVisibleColumns(reportType: DataTableReportType, columns: readonly PresentableColumn[]): ColumnGroupSpan[] {
  return columns.reduce<ColumnGroupSpan[]>((groups, column) => {
    const key = classifyColumn(reportType, column);
    const previous = groups.at(-1);
    if (previous?.key === key) {
      previous.columnIds.push(column.column_id);
      previous.colSpan += 1;
      return groups;
    }

    const { label, alignment } = groupMetadata(reportType, key);
    groups.push({ key, label, columnIds: [column.column_id], colSpan: 1, alignment });
    return groups;
  }, []);
}

function resolvedWidth(column: PresentableColumn, widths: Readonly<Record<string, number>>) {
  const width = widths[column.column_id];
  return typeof width === "number" && Number.isFinite(width)
    ? clampColumnWidth(width)
    : recommendedWidth(column);
}

/**
 * The row number is always frozen by the table itself.  This function returns
 * only data-column IDs, prioritising key identity fields and then product data.
 *
 * At desktop widths (>=1280px), row number plus every returned column is capped
 * at 45% of the viewport. Below that breakpoint, the mandatory identity column
 * is exempt from the cap so narrow screens retain their row context; additional
 * frozen columns still use the remaining 45%-based budget.
 */
export function frozenColumnIds(
  reportType: DataTableReportType,
  columns: readonly PresentableColumn[],
  widths: Readonly<Record<string, number>>,
  viewportWidth: number,
): string[] {
  const isDesktopViewport = viewportWidth >= 1280;
  const supplementalWidthBudget = Math.max(0, viewportWidth * 0.45 - ROW_NUMBER_WIDTH);
  const priority = [...columns].sort((left, right) => {
    const leftRank = left.is_key ? 0 : classifyColumn(reportType, left) === "product" ? 1 : 2;
    const rightRank = right.is_key ? 0 : classifyColumn(reportType, right) === "product" ? 1 : 2;
    return leftRank - rightRank;
  });
  const identity = priority.find((column) => column.is_key);
  const frozen: string[] = [];
  let usedWidth = 0;

  if (identity) {
    frozen.push(identity.column_id);
    usedWidth = resolvedWidth(identity, widths);
    // `resolvedWidth` is bounded at 480px, so this branch is unreachable at
    // desktop widths (52 + 480 <= 1280 * 45%). It documents that the desktop
    // cap remains authoritative should those bounds ever change.
    if (isDesktopViewport && ROW_NUMBER_WIDTH + usedWidth > viewportWidth * 0.45) {
      return frozen;
    }
  }

  for (const column of priority) {
    if (column.column_id === identity?.column_id) continue;
    const width = resolvedWidth(column, widths);
    // On narrow screens, `usedWidth` may already exceed the budget because the
    // required identity column is retained. No extra column may compound that.
    if (usedWidth + width > supplementalWidthBudget) continue;
    frozen.push(column.column_id);
    usedWidth += width;
  }

  return frozen;
}
