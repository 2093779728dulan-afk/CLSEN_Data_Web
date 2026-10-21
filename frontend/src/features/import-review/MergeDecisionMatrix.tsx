import { useEffect, useMemo, useRef, useState } from "react";

import { requestApi } from "../../api/client";
import type { MergeDecisionRequest } from "../../api/generated";
import { Button, Pagination, Select } from "../../design-system";
import { auditOperatorLabel, defaultAuditReason, type AuditOperator } from "./auditReason";
import decisionCss from "./ReviewDecision.module.css";

const CONFLICTS_PER_PAGE = 4;

const decisionLabels: Record<MergeDecisionRequest["action"], string> = {
  keep_both: "重复记录两行都保留",
  keep_source: "重复记录采用来源行",
  keep_target: "重复记录保留目标行",
};

const fieldLabels: Record<string, string> = {
  asin: "ASIN",
  child_asin: "子 ASIN",
  fnsku: "FNSKU",
  license_plate_number: "牌照编号",
  order_id: "订单号",
  parent_asin: "父 ASIN",
  quantity: "数量",
  return_date: "退货日期",
  sku: "SKU",
  title: "商品标题",
};

type MergeConflictPreview = {
  target_row_id: number;
  target_row_ordinal: number;
  target_values: Record<string, string | null>;
  source_row_id: number;
  source_row_ordinal: number;
  source_values: Record<string, string | null>;
};

type MergePreviewResponse = {
  report_type: "business_report" | "return_report";
  target_version_id: number;
  source_kind: "parse_baseline" | "dataset_version";
  source_id: number;
  conflicts: MergeConflictPreview[];
};

type DecisionDraft = {
  action?: MergeDecisionRequest["action"];
  reason: string;
  automaticReason?: boolean;
};

export type MergeDecisionState = {
  decisions: MergeDecisionRequest[];
  ready: boolean;
};

type Props = {
  disabled?: boolean;
  onStateChange: (state: MergeDecisionState) => void;
  operator?: AuditOperator;
  sourceId: number;
  sourceKind: "parse_baseline" | "dataset_version";
  targetVersionId: number;
};

function pairKey(conflict: MergeConflictPreview) {
  return `${conflict.target_row_id}:${conflict.source_row_id}`;
}

function display(value: string | null | undefined) {
  return value === null || value === undefined || value === "" ? "—" : value;
}

function fieldNames(conflict: MergeConflictPreview) {
  return [...new Set([
    ...Object.keys(conflict.target_values),
    ...Object.keys(conflict.source_values),
  ])];
}

function changedFields(conflict: MergeConflictPreview) {
  return fieldNames(conflict).filter(
    (name) => conflict.target_values[name] !== conflict.source_values[name],
  );
}

function comparisonFields(
  conflict: MergeConflictPreview,
  reportType: MergePreviewResponse["report_type"] | undefined,
) {
  const names = fieldNames(conflict);
  const changed = changedFields(conflict);
  if (changed.length) return changed;
  const preferred = reportType === "return_report"
    ? ["return_date", "order_id", "sku"]
    : ["child_asin", "sku", "title"];
  return [...preferred.filter((name) => names.includes(name)), ...names.filter((name) => !preferred.includes(name))].slice(0, 3);
}

function generatedDecisionReason(
  conflict: MergeConflictPreview,
  action: MergeDecisionRequest["action"],
  operator: AuditOperator | undefined,
  targetVersionId: number,
) {
  return defaultAuditReason(
    operator,
    decisionLabels[action],
    `目标版本 #${targetVersionId} · 目标第 ${conflict.target_row_ordinal} 行 · 来源第 ${conflict.source_row_ordinal} 行`,
  );
}

export function MergeDecisionMatrix({
  disabled = false,
  onStateChange,
  operator,
  sourceId,
  sourceKind,
  targetVersionId,
}: Props) {
  const [conflicts, setConflicts] = useState<MergeConflictPreview[]>();
  const [reportType, setReportType] = useState<MergePreviewResponse["report_type"]>();
  const [drafts, setDrafts] = useState<Record<string, DecisionDraft>>({});
  const [error, setError] = useState<string>();
  const [page, setPage] = useState(1);
  const [pageAction, setPageAction] = useState<MergeDecisionRequest["action"] | "">("");
  const callbackRef = useRef(onStateChange);
  const requestId = useRef(0);
  callbackRef.current = onStateChange;

  useEffect(() => {
    const currentRequest = ++requestId.current;
    setConflicts(undefined);
    setReportType(undefined);
    setDrafts({});
    setError(undefined);
    setPage(1);
    setPageAction("");
    callbackRef.current({ decisions: [], ready: false });
    void requestApi<MergePreviewResponse>(
      `/api/datasets/merge-preview?target_version_id=${targetVersionId}`
      + `&source_kind=${sourceKind}&source_id=${sourceId}`,
    ).then((response) => {
      if (requestId.current !== currentRequest) return;
      setReportType(response.report_type);
      setConflicts(response.conflicts);
      setDrafts(Object.fromEntries(response.conflicts
        .filter((conflict) => fieldNames(conflict).length > 0 && changedFields(conflict).length === 0)
        .map((conflict) => [pairKey(conflict), {
          action: "keep_target" as const,
          reason: `系统默认：两侧全部字段完全相同，保留目标行以避免重复计入；目标版本 #${targetVersionId} · 目标第 ${conflict.target_row_ordinal} 行 · 来源第 ${conflict.source_row_ordinal} 行。`,
          automaticReason: true,
        }])));
    }).catch((caught: unknown) => {
      if (requestId.current !== currentRequest) return;
      setError(caught instanceof Error ? caught.message : "重复行对照读取失败。");
    });
    return () => { requestId.current += 1; };
  }, [sourceId, sourceKind, targetVersionId]);

  const state = useMemo<MergeDecisionState>(() => {
    if (!conflicts || error) return { decisions: [], ready: false };
    const decisions: MergeDecisionRequest[] = [];
    for (const conflict of conflicts) {
      const draft = drafts[pairKey(conflict)];
      if (!draft?.action || !draft.reason.trim()) {
        return { decisions: [], ready: false };
      }
      decisions.push({
        action: draft.action,
        reason: draft.reason.trim(),
        source_row_id: conflict.source_row_id,
        target_row_id: conflict.target_row_id,
      });
    }
    return { decisions, ready: true };
  }, [conflicts, drafts, error]);

  useEffect(() => {
    callbackRef.current(state);
  }, [state]);

  const updateDraft = (key: string, update: Partial<DecisionDraft>) => {
    setDrafts((current) => ({
      ...current,
      [key]: { reason: "", ...current[key], ...update },
    }));
  };

  const totalPages = Math.max(1, Math.ceil((conflicts?.length ?? 0) / CONFLICTS_PER_PAGE));
  const visibleConflicts = conflicts?.slice(
    (page - 1) * CONFLICTS_PER_PAGE,
    page * CONFLICTS_PER_PAGE,
  ) ?? [];
  const completedCount = conflicts?.filter((conflict) => {
    const draft = drafts[pairKey(conflict)];
    return Boolean(draft?.action && draft.reason.trim());
  }).length ?? 0;
  const pageHasPending = visibleConflicts.some((conflict) => {
    const draft = drafts[pairKey(conflict)];
    return !draft?.action || !draft.reason.trim();
  });

  const applyActionToPendingPage = () => {
    if (!pageAction) return;
    setDrafts((current) => {
      const next = { ...current };
      for (const conflict of visibleConflicts) {
        const key = pairKey(conflict);
        const existing = current[key];
        if (existing?.action && existing.reason.trim()) continue;
        next[key] = {
          action: pageAction,
          reason: generatedDecisionReason(conflict, pageAction, operator, targetVersionId),
        };
      }
      return next;
    });
  };

  return (
    <section aria-label="重复记录合并决定" className={decisionCss["merge-matrix"]}>
      <header>
        <div><strong>重复记录确认</strong><span>每页 {CONFLICTS_PER_PAGE} 组 · 目标版本 × 本次源表</span></div>
        {conflicts && <b>{conflicts.length} 组重复记录 · 已处理 {completedCount}/{conflicts.length}</b>}
      </header>
      {reportType && <aside className={decisionCss["merge-matrix__rule"]}><strong>为什么需要处理？</strong><p>{reportType === "business_report" ? "经营报告按“子 ASIN + SKU”识别同一业务记录。" : "退货报告按“退货日期 + 订单号 + SKU + ASIN + FNSKU + 数量 + 牌照编号”识别同一业务记录。"}目标版本与本次源表出现相同业务键时，系统不会自行删除或覆盖。全部字段完全相同时，默认保留目标行并填写依据，所有分页一并处理；你仍可改选。有差异的记录需人工决定。默认选择不会立即写入，确认生成草稿后才执行。</p></aside>}
      {operator && <p className="stage-placeholder">决定依据会自动带入当前操作人和冲突行来源 · {auditOperatorLabel(operator)}。</p>}
      {!conflicts && !error && <p role="status">正在生成完整冲突矩阵…</p>}
      {error && <p className="form-error" role="alert">{error} 请重新选择合并方式后重试。</p>}
      {conflicts?.length === 0 && <p className={decisionCss["merge-matrix__clear"]}>没有重复业务键，可以安全保留两侧记录。</p>}
      {conflicts && conflicts.length > 0 && (
        <div className={decisionCss["merge-matrix__page-actions"]}>
          <label>当前页统一处理方式<Select aria-label="当前页统一处理方式" disabled={disabled} onChange={(event) => setPageAction(event.target.value as MergeDecisionRequest["action"] | "")} value={pageAction}><option value="">请选择</option><option value="keep_target">保留目标行</option><option value="keep_source">保留来源行</option><option value="keep_both">两行都保留</option></Select></label>
          <Button disabled={disabled || !pageAction || !pageHasPending} onClick={applyActionToPendingPage} variant="secondary">应用到当前页未处理项</Button>
        </div>
      )}
      <div className={decisionCss["merge-matrix__list"]}>{visibleConflicts.map((conflict) => {
        const index = conflicts?.indexOf(conflict) ?? 0;
        const key = pairKey(conflict);
        const draft = drafts[key] ?? { reason: "" };
        const differences = changedFields(conflict);
        const fields = comparisonFields(conflict, reportType);
        return (
          <article aria-label={`重复记录 ${index + 1}`} key={key}>
            <div className={decisionCss["merge-matrix__pair-heading"]}>
              <div><strong>重复记录 {index + 1}</strong><span>目标第 {conflict.target_row_ordinal} 行 · 来源第 {conflict.source_row_ordinal} 行</span></div>
              <em>{differences.length === 0 ? "字段完全相同" : `${differences.length} 个字段不同`}</em>
            </div>
            <dl className={decisionCss["merge-matrix__comparison"]}>
              {fields.slice(0, 6).map((name) => (
                <div key={name}>
                  <dt>{fieldLabels[name] ?? name}</dt>
                  {conflict.target_values[name] === conflict.source_values[name]
                    ? <dd className={decisionCss["merge-matrix__same-value"]}><span>{display(conflict.target_values[name])}</span><em>两侧相同</em></dd>
                    : <dd><span>{display(conflict.target_values[name])}</span><i>→</i><span>{display(conflict.source_values[name])}</span></dd>}
                </div>
              ))}
            </dl>
            <details>
              <summary>查看两行的全部字段</summary>
              <table><thead><tr><th>字段</th><th>目标行</th><th>来源行</th></tr></thead><tbody>{fieldNames(conflict).map((name) => <tr key={name}><th>{fieldLabels[name] ?? name}</th><td>{display(conflict.target_values[name])}</td><td>{display(conflict.source_values[name])}</td></tr>)}</tbody></table>
            </details>
            <div className={decisionCss["merge-matrix__decision"]}>
              <label>处理方式<select aria-label={`重复记录 ${index + 1} 处理方式`} disabled={disabled} onChange={(event) => { const action = event.target.value ? event.target.value as MergeDecisionRequest["action"] : undefined; updateDraft(key, { action, reason: draft.automaticReason ? (action ? generatedDecisionReason(conflict, action, operator, targetVersionId) : "") : draft.reason.trim() || (action ? generatedDecisionReason(conflict, action, operator, targetVersionId) : ""), automaticReason: false }); }} value={draft.action ?? ""}><option value="">请选择</option><option value="keep_target">保留目标行</option><option value="keep_source">保留来源行</option><option value="keep_both">两行都保留</option></select></label>
              <label>决定依据<input aria-label={`重复记录 ${index + 1} 决定依据`} disabled={disabled} maxLength={1000} onChange={(event) => updateDraft(key, { reason: event.target.value, automaticReason: false })} placeholder="说明与原表核对后的判断" value={draft.reason} /></label>
            </div>
          </article>
        );
      })}</div>
      {conflicts && conflicts.length > CONFLICTS_PER_PAGE && <Pagination itemLabel="重复记录" onPageChange={setPage} page={page} totalItems={conflicts.length} totalPages={totalPages} />}
      {conflicts && conflicts.length > 0 && !state.ready && <p className={decisionCss["merge-matrix__pending"]}>完成每组重复记录的处理方式和决定依据后，才能继续生成草稿。</p>}
    </section>
  );
}
