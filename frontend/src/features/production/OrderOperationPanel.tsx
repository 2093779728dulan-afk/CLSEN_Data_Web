import { useSearchParams } from "react-router-dom";
import { Plus } from "lucide-react";
import { Button, LinkButton, StatusMessage } from "../../design-system";
import type { Document } from "./types";
import type { WorkbenchStock } from "./WorkbenchFields";
import { ReceiptPanel, ReceiptRecords, ShipmentPanel, ShipmentRecords } from "./WorkbenchOperations";
import { ProductionOperationDialog } from "./ProductionOperationDialog";
import styles from "./OrderWorkbench.module.css";

export function OrderOperationPanel({ mode, order, stock, stockError, blocked = false, canWrite, saved }: { mode: "receive" | "ship"; order: Document; stock?: WorkbenchStock; stockError?: string; blocked?: boolean; canWrite: boolean; saved: () => void }) {
  const [params, setParams] = useSearchParams();
  const title = mode === "receive" ? "入库" : "本单出货";
  const dialogTitle = mode === "receive" ? "入库" : params.get("shipment") ? "出货装箱" : "新建出货单";
  const open = params.get("operation") === "guided" || mode === "ship" && !!params.get("shipment");
  const enabled = canWrite && (mode === "ship" || !!stock?.writes_enabled);
  function change(opening: boolean) {
    const next = new URLSearchParams(params);
    if (opening) next.set("operation", "guided"); else next.delete("operation");
    if (opening && mode === "receive") next.delete("receipt_draft");
    next.delete("shipment");
    setParams(next);
  }
  return <>
    <div className={styles.sectionHeading}><h2>{title}</h2>{enabled && <Button variant="primary" icon={<Plus />} disabled={blocked || !!stockError} onClick={() => change(true)}>{mode === "receive" ? "新建入库" : "新建出货单"}</Button>}</div>
    <p className={styles.muted}>{mode === "receive" ? "按步骤填写或导入实收明细，核对库存影响后再确认入库。" : "按步骤核对来源与目的地、填写数量并装箱，确认实际交接后才计入已出货。"}与仓库中心使用同一套操作向导。</p>
    {!enabled && <StatusMessage kind="info" title={!canWrite ? "当前账号只读" : stockError ? "库存资料读取失败，请重新读取后操作" : "当前环境的库存写入未启用"}>可以查看本单记录。</StatusMessage>}
    {mode === "receive" && params.get("receipt_draft") && <LinkButton variant="secondary" to={`?${new URLSearchParams({ ...Object.fromEntries(params), operation: "guided" })}`}>继续处理入库草稿 {params.get("receipt_draft")}</LinkButton>}
    {mode === "receive" ? <ReceiptRecords order={order} stock={stock} /> : <ShipmentRecords order={order} />}
    {open && enabled && <ProductionOperationDialog title={dialogTitle} description={`本次关联生产单：${order.business_number || order.system_number}`} blocked={blocked || !!stockError} close={() => change(false)}>
      {mode === "receive" ? <ReceiptPanel guided resumeDraftId={params.get("receipt_draft") || undefined} order={order} stock={stock} stockError={stockError} canWrite={canWrite} saved={saved} onGuidedClose={() => change(false)} onDraftSaved={id => { const next = new URLSearchParams(params); if (id) next.set("receipt_draft", id); else next.delete("receipt_draft"); setParams(next, { replace: true }); }} /> : <ShipmentPanel guided order={order} stock={stock} stockError={stockError} canWrite={canWrite} saved={saved} onGuidedClose={() => change(false)} />}
    </ProductionOperationDialog>}
  </>;
}
