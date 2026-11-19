import { useEffect } from "react";
import { Check, RotateCcw } from "lucide-react";
import { Button, StatusMessage } from "../../design-system";
import type { Document } from "./types";
import { useCommand } from "./useProductionApi";
import styles from "./OrderCompletionAction.module.css";

export function OrderCompletionAction({ order, canWrite, blocked = false, saved, reload, onGuardChange }: {
  order: Document; canWrite: boolean; blocked?: boolean; onGuardChange?: (id:string,busy:boolean,unknown:boolean)=>void; saved: (result: Document) => void; reload: () => void;
}) {
  const command = useCommand<Document>(saved);
  useEffect(()=>{onGuardChange?.(order.id,command.busy,command.unknown);},[onGuardChange,order.id,command.busy,command.unknown]);
  useEffect(()=>()=>onGuardChange?.(order.id,false,false),[onGuardChange,order.id]);
  if (order.status !== "CONFIRMED" || order.production_completion_state === undefined) return null;
  const completed = order.production_completion_state === "COMPLETED";
  const ready = order.production_completion_ready === true;
  const locked = blocked || command.busy || command.unknown;
  return <div className={styles.completion}>
    <div className={styles.action}>
      {completed ? <><span className={styles.done}><Check size={14} aria-hidden="true"/>已完成</span>{canWrite && <Button variant="quiet" icon={<RotateCcw size={14}/>} aria-label="恢复进行中" title="恢复进行中" disabled={locked} onClick={() => command.submit(`/api/production/orders/${order.id}/reopen-production`, { expected_revision: order.revision })}/>}</>
        : ready ? canWrite ? <Button variant="secondary" icon={<Check size={14}/>} disabled={locked} onClick={() => command.submit(`/api/production/orders/${order.id}/complete-production`, { expected_revision: order.revision })}>确认完成</Button> : <span>待确认完成</span> : <span>进行中</span>}
    </div>
    {completed && !ready && <StatusMessage kind="warning" title="数量已变更">请核对是否需要恢复进行中。</StatusMessage>}
    {command.feedback}
    {!command.unknown && command.feedback && <Button variant="quiet" onClick={reload}>重新读取订单</Button>}
  </div>;
}
