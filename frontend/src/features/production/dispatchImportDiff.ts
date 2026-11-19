import type { OperationImportPreview } from "./OperationTableImport";
import type { Source } from "./types";

export function dispatchImportChanges(imported: OperationImportPreview, sources: Source[], options: {value:string;label:string}[]) {
  const originals:NonNullable<OperationImportPreview["source_rows"]> = imported.source_rows ?? imported.rows.map(row => ({
    row: row.row, sku_code: options.find(option => option.value === row.sku_id)?.label ?? row.sku_label,
    units: row.units ?? null, source_cell:"",
  }));
  const changes: {key:string;row:string;kind:string;before:string;after:string}[] = [];
  const label = (source:Source) => options.find(option => option.value === source.sku_id)?.label || source.import_code || source.sku_label || "商品待选";
  for (const original of originals) {
    const current = sources.find(source => source.import_row === original.row);
    const position = original.source_filename ? `${original.source_filename} 第${original.source_row}行` : `第${original.row}行`;
    const before = `${original.sku_code} · ${original.units ?? "待核"}件`;
    if (!current) {
      changes.push({key:`removed-${original.row}`,row:position,kind:"移除商品",before,after:"已移除"});
      continue;
    }
    const changedProduct = label(current) !== original.sku_code;
    const changedQuantity = current.actual_units !== original.units;
    if (changedProduct || changedQuantity) changes.push({
      key:`changed-${original.row}`,row:position,
      kind:changedProduct ? changedQuantity ? "商品及数量" : "更换商品" : "修改数量",
      before,after:`${label(current)} · ${current.actual_units || "未填写"}件`,
    });
  }
  sources.forEach((source,index) => {
    if (source.import_row === undefined && (source.sku_id || source.import_code || source.actual_units)) changes.push({
      key:`added-${index}`,row:"手工新增",kind:"新增商品",before:"原表无此行",
      after:`${label(source)} · ${source.actual_units || "未填写"}件`,
    });
  });
  return changes;
}

