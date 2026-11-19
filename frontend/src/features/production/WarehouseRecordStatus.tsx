import styles from "./WarehouseCenter.module.css";

export function WarehouseRecordStatus({ status, kind = "IN", shipment = false }: { status: string; kind?: string; shipment?: boolean }) {
  const success = shipment ? status === "CONFIRMED" : status === "POSTED";
  const cancelled = shipment ? status === "VOID" : status === "REVERSED";
  const draft = status === "DRAFT";
  const label = success ? shipment ? "已发货" : kind === "IN" ? "已入库" : kind === "OUT" ? "已出库" : "已过账" : cancelled ? shipment ? "已作废" : "已冲销" : draft ? shipment ? "装箱草稿" : "草稿" : "状态待核";
  return <span className={`${styles.badge} ${success ? styles.ready : cancelled ? styles.danger : draft ? styles.draft : styles.pending}`}>{label}</span>;
}

export function WarehouseRecordSteps({ status, preview, shipment = false, outbound = false }: { status: string; preview?: boolean; shipment?: boolean; outbound?: boolean }) {
  const complete = status === "POSTED" || status === "CONFIRMED";
  if (status === "REVERSED" || status === "VOID") return null;
  const current = complete ? 2 : preview ? 1 : 0;
  return <ol className={styles.recordSteps} aria-label="单据处理步骤">{[shipment ? "装箱草稿" : "草稿", "核对预览", shipment ? "确认发货" : outbound ? "确认出库" : "确认入库"].map((label, index) => <li key={label} aria-current={index === current ? "step" : undefined} data-complete={index < current || complete}><span>{index + 1}</span>{label}</li>)}</ol>;
}
