import { useLocation } from "react-router-dom";
import { LinkButton, StatusMessage } from "../../design-system";
import { useLoad } from "./useProductionApi";
import type { Document } from "./types";

function receiptDateConflict(dispatchedOn: string | null | undefined, receivedOn: (string | null | undefined)[]) {
  if (!dispatchedOn) return undefined;
  const first = receivedOn.filter((day): day is string => !!day).sort()[0];
  return first && first < dispatchedOn ? first : undefined;
}

export function ShipmentDateNotice({ shipmentId, dispatchedOn, receivedOn, canWrite }: {
  shipmentId: string; dispatchedOn?: string | null;
  receivedOn: (string | null | undefined)[]; canWrite: boolean;
}) {
  const location = useLocation();
  const source = useLoad<Document>(`/api/production/shipments/${shipmentId}`, 0, dispatchedOn === undefined);
  const date = dispatchedOn === undefined ? source.value?.business_date : dispatchedOn;
  const earlier = receiptDateConflict(date, receivedOn);
  if (!earlier) return null;
  const returnTo = `${location.pathname}${location.search}`;
  const query = new URLSearchParams({ return_to: returnTo });
  return <StatusMessage kind="warning" title="收货日期早于发货日期" action={
    <LinkButton variant="quiet" to={`/production/shipments/${shipmentId}${canWrite ? "/edit" : ""}?${query}`} state={{ overviewReturn: returnTo }}>{canWrite ? "更正出货日期" : "查看出货单"}</LinkButton>
  }>发货 {date} · 收货 {earlier}。请核对实际发生日期。</StatusMessage>;
}
