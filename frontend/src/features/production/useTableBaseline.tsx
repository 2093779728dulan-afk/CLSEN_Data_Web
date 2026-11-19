import { useEffect, useState } from "react";
import { useAuthzGeneration } from "../../app/AuthzGenerationContext";
import { StatusMessage } from "../../design-system";
import { useLoad } from "./useProductionApi";
import { marker, withoutTableBaseline, type TableBaseline } from "./tableImportDiff";

export function useTableBaseline(note: string | undefined, kind: string) {
  const savedId = [...(note || "").matchAll(marker)].at(-1)?.[1];
  const [applied, setApplied] = useState<TableBaseline>();
  const { registerSensitivePurge } = useAuthzGeneration();
  useEffect(() => registerSensitivePurge(() => setApplied(undefined)), [registerSensitivePurge]);
  const saved = useLoad<TableBaseline>(`/api/production/table-baselines/${savedId}`, 0, !!savedId && !applied);
  const value = applied || saved.value;
  const baseline = value?.kind === kind ? value : undefined;
  const blocked = !!(savedId || applied) && !baseline;
  function withNote(text: string) {
    if (blocked) throw new Error("原表核对记录尚未就绪，请等待读取完成或重新导入。");
    const result = `${withoutTableBaseline(text)}${baseline ? `\n表格基准=${baseline.id}` : ""}`;
    if (result.length > 2000) throw new Error("备注与原表引用合计超过2000字，请缩短备注后保存。");
    return result;
  }
  return { baseline, apply: setApplied, blocked, withNote,
    feedback: blocked ? <StatusMessage kind={saved.error || value ? "danger" : "info"} title={saved.error || (value ? "原表记录与本次业务类型不一致" : "正在读取原表核对记录…")} /> : null };
}

