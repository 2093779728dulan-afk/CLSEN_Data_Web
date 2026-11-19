import type { Meta, StoryObj } from "@storybook/react-vite";
import { Dialog } from "../../design-system";
import { InventoryReviewNotice, InventoryReviewPreview } from "./InventoryReviewDialog";
import styles from "./Production.module.css";

// Fictional state fixtures only. No sessions, source files or network calls.
function ReviewStateStory({ state }: { state: "preview" | "conflict" | "unknown" }) {
  return <main><h1>库存资料核对 · 虚构状态</h1><Dialog open onOpenChange={() => undefined} title="核对保存状态" description="资料决定不会产生库存过账；下列记录和数量均为虚构测试夹具。" size="large"><div className={styles.inventoryReviewForm}>
    {state === "preview" && <InventoryReviewPreview preview={{ preview_hash: "a".repeat(64), before: { warehouse_1_units: "18", product_count: 1, color_count: 1, warehouse_pending: 2, unknown_cells: 12, incomplete_total_rows: 0 }, after: { warehouse_1_units: "23", product_count: 2, color_count: 3, warehouse_pending: 0, unknown_cells: 12, incomplete_total_rows: 0 }, stocktaken_on: null, cutoff_note: "" }} />}
    {state === "conflict" && <InventoryReviewNotice error="核对版本已变化，整批未保存。输入仍保留；读取最新版本并比较后重新预览，不自动覆盖。" />}
    {state === "unknown" && <InventoryReviewNotice operationId="10000000-0000-4000-8000-000000000001" />}
  </div></Dialog></main>;
}
const meta = { title: "Pages/Inventory Review", component: ReviewStateStory, parameters: { layout: "fullscreen" }, args: { state: "preview" } } satisfies Meta<typeof ReviewStateStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Preview: Story = {};
export const Conflict: Story = { args: { state: "conflict" } };
export const ResultUnknown: Story = { args: { state: "unknown" } };
