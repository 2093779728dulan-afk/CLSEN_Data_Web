export type ImportRow = { key: string; label: string; row?: number; values: Record<string, string> };
export type TableBaseline = { id: string; kind: string; filename: string; rows: ImportRow[] };
export const marker = /(?:\n)?表格基准=(table-baseline-[a-f0-9]{64})/g;
export function withoutTableBaseline(note = "") { return note.replace(marker, ""); }
export function tableChanges(baseline: ImportRow[], current: ImportRow[]) {
  const changes: { label: string; field: string; before: string; after: string; row?: number }[] = [];
  for (const original of baseline) {
    const now = current.find(row => row.key === original.key);
    if (!now) { changes.push({ label: original.label, field: "移除明细", before: Object.entries(original.values).map(([k,v]) => `${k} ${v}`).join(" · "), after: "已移除", row: original.row }); continue; }
    for (const field of new Set([...Object.keys(original.values), ...Object.keys(now.values)])) {
      if ((original.values[field] || "") !== (now.values[field] || "")) changes.push({ label: now.label, field, before: original.values[field] || "未填", after: now.values[field] || "未填", row: original.row });
    }
  }
  for (const row of current.filter(row => !baseline.some(item => item.key === row.key))) changes.push({ label: row.label, field: "手工新增", before: "原表无此明细", after: Object.entries(row.values).map(([k,v]) => `${k} ${v}`).join(" · ") });
  return changes;
}


export function stockImportRows(kind: string, lines: {sku_id:string;quality:string;units:string;purpose:string;production_allocations?:{order_line_id:string;units:string}[]}[], label:(sku:string)=>string): ImportRow[] {
  const qualities:Record<string,string>={QUALIFIED:"合格",PENDING:"待检",DEFECTIVE:"次品"};
  if(kind==="ADJUST")return lines.filter(line=>line.sku_id && line.quality).map(line=>({key:`${line.sku_id}:${line.quality}`,label:label(line.sku_id),values:{"状态":qualities[line.quality] || line.quality,"实盘总数":line.units}}));
  const rows=new Map<string,ImportRow>();
  for(const line of lines.filter(line=>line.purpose==="PRODUCTION_RECEIPT"))for(const allocation of line.production_allocations || []){
    const row=rows.get(allocation.order_line_id) || {key:allocation.order_line_id,label:label(line.sku_id),values:{"合格":"0","待检":"0","次品":"0"}};
    const quality=qualities[line.quality];if(quality && /^\d+$/.test(allocation.units))row.values[quality]=(BigInt(row.values[quality] || "0")+BigInt(allocation.units)).toString();
    rows.set(row.key,row);
  }
  return [...rows.values()];
}
