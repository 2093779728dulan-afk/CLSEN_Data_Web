import type { FormEvent, ReactNode, Ref } from "react";
import { Button, Checkbox, Input, Radio, Select, Skeleton, StatusMessage } from "../../design-system";
import type { InspectionResponse, ReportType, SuccessfulParse, VersionSummary } from "../../api/types";
import type { DraftReviewContext, ImportQueueItem, UploadSession } from "./workflowTypes";
import { auditOperatorLabel, type AuditOperator } from "./auditReason";
import entryCss from "./ImportIntakeView.module.css";
import decisionCss from "./ImportIntakeView.module.css";
import buttonCss from "../../design-system/Button.module.css";

export type ImportIntakeViewProps = {
  activeStage: string; reachedSteps: number; assignedDate: string; reportType: ReportType;
  encoding: ImportQueueItem["encoding"]; files: File[]; fileInputRef?: Ref<HTMLInputElement>;
  importQueue: ImportQueueItem[]; activeQueueId?: string; upload?: UploadSession;
  inspection?: InspectionResponse; parsed?: SuccessfulParse; draft?: DraftReviewContext; published: boolean;
  busyAction?: string; error?: string; notice?: string; operator?: AuditOperator;
  materializeReason: string; materializePreview?: { activeDraft?: VersionSummary; publication?: VersionSummary; reportDate: string; reportType: ReportType };
  materializeDecision?: "merge" | "replace" | "force-rebuild" | "cancel"; forceRebuildConfirmed: boolean;
  materializeMerge: { ready: boolean }; canForceRebuild: boolean;
  reset: () => void; activateQueueItem: (item: ImportQueueItem) => void; retryQueueInspection: (item: ImportQueueItem) => void | Promise<void>;
  reviewNextQueuedFile: () => void; uploadAndInspect: (event: FormEvent) => void | Promise<void>;
  changeAssignedDate: (value: string) => void; changeReportType: (value: ReportType) => void;
  changeEncoding: (value: ImportQueueItem["encoding"]) => void; setFiles: (value: File[]) => void;
  updateBatchDate: () => void | Promise<void>; confirmParse: () => void | Promise<void>;
  reparseCurrentBaseline: () => void; setMaterializeReason: (value: string) => void; resetPendingMaterialize: () => void;
  inspectMaterializeTarget: () => void | Promise<void>; selectMaterializeDecision: (value: "merge" | "replace" | "force-rebuild" | "cancel") => void;
  setForceRebuildConfirmed: (value: boolean) => void; confirmMaterializeDecision: () => void | Promise<void>;
  sourcePreview?: ReactNode; mergeMatrix?: ReactNode; draftWorkspace?: ReactNode; notes?: ReactNode; batchEntry?: ReactNode;
};

function reportTypeLabel(reportType: ReportType) { return reportType === "business_report" ? "经营报告" : "退货报告"; }
function hasMaterializeConflict(preview: NonNullable<ImportIntakeViewProps["materializePreview"]>) { return preview.activeDraft !== undefined || preview.publication !== undefined; }
function existingStageLabel(stage: string | undefined) {
  const labels: Record<string, string> = { draft: "草稿待审核", failed: "处理失败", parsed: "已解析", processing: "处理中", published: "已发布", ready: "待发布", uploaded: "已上传" };
  return stage ? labels[stage] ?? stage : "待继续处理";
}

export function ImportIntakeView({ activeStage, reachedSteps, assignedDate, reportType, encoding, files, fileInputRef, importQueue, activeQueueId, upload, inspection, parsed, draft, published, busyAction, error, notice, operator, materializeReason, materializePreview, materializeDecision, forceRebuildConfirmed, materializeMerge, canForceRebuild, reset, activateQueueItem, retryQueueInspection, reviewNextQueuedFile, uploadAndInspect, changeAssignedDate, changeReportType, changeEncoding, setFiles, updateBatchDate, confirmParse, reparseCurrentBaseline, setMaterializeReason, resetPendingMaterialize, inspectMaterializeTarget, selectMaterializeDecision, setForceRebuildConfirmed, confirmMaterializeDecision, sourcePreview, mergeMatrix, draftWorkspace, notes, batchEntry }: ImportIntakeViewProps) {
  return (
    <section className={entryCss["import-workflow"]} aria-label="导入审核流程">
      <header className={entryCss["review-taskbar"]}>
        <div>
          <p className="section-kicker">当前任务</p>
          <h2>{activeStage}</h2>
          <p>{draft ? `${draft.reportDate} · ${reportTypeLabel(draft.reportType)} · 草稿 v${draft.head.version_no}` : `${assignedDate} · ${reportTypeLabel(reportType)}`}</p>
        </div>
        <ol aria-label="导入证据链" className={entryCss["custody-chain"]}>
          {["原始文件", "识别确认", "解析基线", "审核草稿", "发布版本"].map((label, index) => (
            <li aria-current={index === Math.max(0, reachedSteps - 1) ? "step" : undefined} className={index < reachedSteps ? `${entryCss["custody-chain__step"]} ${entryCss["custody-chain__step--reached"]}` : entryCss["custody-chain__step"]} key={label}>
              <span>{String(index + 1).padStart(2, "0")}</span><strong>{label}</strong>
            </li>
          ))}
        </ol>
      </header>

      {importQueue.length > 0 && (
        <section aria-label="批量导入队列" className={entryCss["import-queue"]}>
          <header><div><p className="section-kicker">批量导入队列</p><h2>{importQueue.length} 份文件 · 上传结果</h2></div><div className={entryCss["import-queue__header-actions"]}><p>清空只会移除当前页面队列，不会删除服务器上的原始文件或导入批次。</p><Button variant="quiet" disabled={busyAction !== undefined} onClick={reset} type="button">清空页面队列</Button></div></header>
          <ol>
            {importQueue.map((item, index) => {
              const active = item.id === activeQueueId;
              const status = item.status === "existing" ? item.existing?.stage === "published" ? "文件已导入并发布" : `已有批次 · ${existingStageLabel(item.existing?.stage)}` : item.status === "failed" ? "失败" : item.status === "completed" ? "已发布" : item.parsed ? "基线待生成草稿" : active ? "正在人工确认" : "等待人工确认";
              const itemClass = [entryCss["import-queue__item"], active ? entryCss["import-queue__item--active"] : undefined, item.status === "existing" ? entryCss["import-queue__item--existing"] : undefined].filter(Boolean).join(" ");
              return <li className={itemClass} key={item.id}><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.upload?.fileName ?? files[index]?.name ?? `文件 ${index + 1}`}</strong><small>{item.assignedDate} · {status}{item.upload ? ` · 批次 #${item.upload.upload.batch_id}` : ""}</small>{item.status === "existing" ? <small>本次未新增该文件的导入批次，未改变已发布日报。{item.existing?.stage !== "published" && `服务器阶段：${existingStageLabel(item.existing?.stage)}。`}</small> : item.error && <em>{item.error}</em>}{item.status === "existing" && item.error && !item.error.startsWith("服务器阶段：") && <em>{item.error}</em>}</div>{item.status === "ready" && !active && !draft ? <Button variant="quiet" disabled={busyAction !== undefined} onClick={() => activateQueueItem(item)} type="button">开始审核</Button> : item.status === "existing" && item.existing?.stage === "published" ? <><Button variant="quiet" disabled={busyAction !== undefined} onClick={() => { void retryQueueInspection(item); }} type="button">用此原始文件重新审核</Button><a className={`${buttonCss.button} ${buttonCss.quiet}`} href={`/review/${item.existing.reportDate ?? item.assignedDate}?report_type=${item.existing.reportType ?? item.reportType}#main-content`}>查看已发布日报</a></> : item.status === "existing" ? <Button variant="quiet" disabled={busyAction !== undefined} onClick={() => { void retryQueueInspection(item); }} type="button">{busyAction === `inspect:${item.id}` ? "正在读取…" : "继续审核"}</Button> : item.status === "failed" && item.upload ? <Button variant="quiet" disabled={busyAction !== undefined} onClick={() => { void retryQueueInspection(item); }} type="button">{busyAction === `inspect:${item.id}` ? "正在重试…" : "重新识别"}</Button> : null}</li>;
            })}
          </ol>
          {batchEntry}
          {published && <Button className={entryCss["import-queue__next-action"]} variant="primary" onClick={reviewNextQueuedFile} type="button">{importQueue.some((item) => item.status === "ready" && item.id !== activeQueueId) ? "审核下一份文件" : "完成本次批量"}</Button>}
        </section>
      )}

      {!upload && !draft && busyAction !== "resume" && busyAction !== "reparse" && (
        <form className={entryCss["intake-panel"]} onSubmit={(event) => { void uploadAndInspect(event); }}>
          <div className={entryCss["intake-panel__copy"]}><p className="section-kicker">新建导入批次</p><h2>批量文件逐份识别，再进入各自工作日</h2><p>批量上传会从每个文件识别报告日期并放入对应日期队列；识别不到日期时才使用下方日期作为待确认归属。文件不会直接进入业务数据。</p></div>
          <div className={entryCss["intake-panel__fields"]}>
            <label className="field-stack">识别不到日期时的归属日<Input onChange={(event) => changeAssignedDate(event.target.value)} required type="date" value={assignedDate} /></label>
            <label className={entryCss["file-drop"]}>CSV 文件（可多选）<input ref={fileInputRef} disabled={busyAction === "upload"} accept=".csv,text/csv" aria-label="CSV 文件" multiple onChange={(event) => setFiles(Array.from(event.target.files ?? []))} type="file" /><span>{files.length === 1 ? files[0]?.name : files.length > 1 ? `已选择 ${files.length} 份 CSV` : "选择一份或多份 CSV"}</span></label>
            <Button variant="primary" loading={busyAction === "upload"} disabled={files.length === 0 || busyAction === "upload"} type="submit">{busyAction === "upload" ? `正在逐份保存（共 ${files.length} 份）…` : files.length > 1 ? `保存并检查 ${files.length} 份文件` : "保存并检查文件"}</Button>
          </div>
        </form>
      )}

      {busyAction === "resume" && <div className={entryCss.restoration} role="status"><p>正在恢复这个日期的活动草稿…</p><Skeleton lines={3} /></div>}
      {busyAction === "reparse" && <div className={entryCss.restoration} role="status"><p>正在恢复来源批次的识别证据…</p><Skeleton lines={3} /></div>}

      {published && !draft && (
        <section className={entryCss["baseline-panel"]} role="status">
          <span className={entryCss["baseline-panel__mark"]}>发</span>
          <div><p className="section-kicker">发布已完成</p><h2>这份文件已经进入当前发布版本</h2><p>刷新没有重新打开已完成的解析基线。可以继续审核队列中的下一份文件。</p></div>
        </section>
      )}

      {upload && inspection && !parsed && !draft && !published && (
        <section className={entryCss["inspection-panel"]}>
          <header><div><p className="section-kicker">导入批次 #{upload.upload.batch_id}</p><h2>人工确认识别结果</h2><p>{upload.fileName}{"sha256_hex" in upload.upload ? ` · SHA-256 ${upload.upload.sha256_hex.slice(0, 12)}…` : ""}</p></div><div className={entryCss["inspection-panel__header-actions"]}><a className={`${buttonCss.button} ${buttonCss.quiet}`} download href={`/api/imports/${upload.upload.batch_id}/raw-file`}>下载原始 CSV</a><Button variant="quiet" onClick={reset} type="button">{importQueue.length > 1 ? "清空页面队列" : "改用其他文件"}</Button></div></header>
          {inspection.report_date && inspection.report_date !== assignedDate && (
            <div className={entryCss["date-discrepancy"]} role="status"><span>日期差异</span><div><strong>识别日期与所选报告日不同</strong><p>识别日期 <b>{inspection.report_date}</b>；当前所属日期 <b>{assignedDate}</b>。请依据原表选择，不会自动改写。</p></div><Button variant="secondary" onClick={() => changeAssignedDate(inspection.report_date ?? assignedDate)} type="button">采用识别日期</Button></div>
          )}
          <div className={entryCss["inspection-grid"]}>
            <label className="field-stack">报表类型<Select onChange={(event) => changeReportType(event.target.value as ReportType)} value={reportType}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></Select></label>
            <label className="field-stack">所属报告日<Input onChange={(event) => changeAssignedDate(event.target.value)} type="date" value={assignedDate} /></label>
            <label className="field-stack">文件编码<Select onChange={(event) => changeEncoding(event.target.value as typeof encoding)} value={encoding}><option value="utf-8-sig">UTF-8 BOM</option><option value="utf-8">UTF-8</option><option value="windows-1252">Windows-1252</option></Select></label>
            <div className={entryCss["inspection-evidence"]}><span>识别规则</span><code>{inspection.ruleset_version}</code><span>{inspection.issue_codes.length ? `${inspection.issue_codes.length} 项识别提示` : "未发现结构提示"}</span></div>
          </div>
          <div className={entryCss["inspection-actions"]}><Button variant="secondary" loading={busyAction === "date"} disabled={busyAction === "date"} onClick={() => { void updateBatchDate(); }} type="button">{busyAction === "date" ? "正在更新…" : "保存所属日期"}</Button><Button variant="primary" loading={busyAction === "parse"} disabled={busyAction === "parse"} onClick={() => { void confirmParse(); }} type="button">{busyAction === "parse" ? "正在解析…" : "确认并解析"}</Button></div>
        </section>
      )}

      {upload && inspection && !draft && !published && (
        <>{sourcePreview}</>
      )}

      {upload && inspection && parsed && !draft && !published && (
        <section className={entryCss["baseline-panel"]}>
          <span className={entryCss["baseline-panel__mark"]}>基</span>
          <div className={entryCss["baseline-panel__summary"]}><div><p className="section-kicker">不可变解析基线 #{parsed.parse_baseline_id}</p><h2>已解析 {parsed.source_row_count} 行源数据</h2><p>当前所属日期为 <strong>{assignedDate}</strong>。尚未生成草稿时仍可修正；系统会新建解析基线，不改写旧证据。</p></div><Button variant="quiet" disabled={busyAction === "materialize"} onClick={reparseCurrentBaseline} type="button">修改日期并重新解析</Button></div>
          <div className={entryCss["baseline-panel__action"]}>
            <label className="field-stack">生成草稿原因<textarea onChange={(event) => { setMaterializeReason(event.target.value); resetPendingMaterialize(); }} rows={3} value={materializeReason} /></label>
            {operator && <p className="stage-placeholder">操作人来源：当前登录会话 · {auditOperatorLabel(operator)}。提交时服务器会按该会话记录用户 ID；默认说明仍可补充修改。</p>}
            {!materializePreview || !hasMaterializeConflict(materializePreview) ? (
              <Button variant="primary" loading={busyAction === "materialize"} disabled={busyAction === "materialize" || !materializeReason.trim()} onClick={() => { void inspectMaterializeTarget(); }} type="button">{busyAction === "materialize" ? "正在检查当日版本…" : "生成审核草稿"}</Button>
            ) : (
              <fieldset className={decisionCss["target-conflict"]}>
                <legend>目标日期已有数据，请选择草稿生成方式</legend>
                <div className={decisionCss["target-conflict__ledger"]}>
                  <span>{materializePreview.reportDate} · {reportTypeLabel(materializePreview.reportType)}</span>
                  {materializePreview.activeDraft && <strong>活动草稿 v{materializePreview.activeDraft.version_no}</strong>}
                  {materializePreview.publication && <strong>发布版本 v{materializePreview.publication.version_no}</strong>}
                </div>
                <div className={decisionCss["target-choice"]}><Radio aria-label="合并到现有数据" checked={materializeDecision === "merge"} disabled={busyAction === "materialize"} name="materialize-decision" onChange={() => selectMaterializeDecision("merge")} label={<> 合并到现有数据 </>} description={<> 保留目标版本并加入本次解析结果。同一业务键在两侧都出现时，需要逐组决定保留哪条；系统不会自动删除或覆盖。 </>} /></div>
                <div className={decisionCss["target-choice"]}><Radio aria-label="替换当前发布版本" checked={materializeDecision === "replace"} disabled={busyAction === "materialize" || materializePreview.activeDraft !== undefined} name="materialize-decision" onChange={() => selectMaterializeDecision("replace")} label={<> 替换当前发布版本 </>} description={<> {materializePreview.activeDraft ? "目标有活动草稿，普通导入不能覆盖；请合并或由管理员强制重建。" : "新草稿仅采用本次解析结果，已发布版本仍保留在版本历史中。"} </>} /></div>
                {canForceRebuild && materializePreview.activeDraft && <div className={decisionCss["target-choice"]}><Radio aria-label="管理员强制重建活动草稿" checked={materializeDecision === "force-rebuild"} disabled={busyAction === "materialize"} name="materialize-decision" onChange={() => selectMaterializeDecision("force-rebuild")} label={<> 管理员强制重建活动草稿 </>} description={<> 废弃目标活动草稿，以本次解析基线重建；旧草稿、修改和备注仍保留在审计历史中，已发布版本不会被直接覆盖。 </>} /></div>}
                <div className={decisionCss["target-choice"]}><Radio aria-label="取消，不生成草稿" checked={materializeDecision === "cancel"} disabled={busyAction === "materialize"} name="materialize-decision" onChange={() => selectMaterializeDecision("cancel")} label={<> 取消，不生成草稿 </>} description={<> 保留解析基线和目标日期现状，不发送写请求。 </>} /></div>
                {materializeDecision === "force-rebuild" && <div className={decisionCss["target-choice"]}><Checkbox aria-label="确认废弃目标活动草稿并保留审计历史" checked={forceRebuildConfirmed} disabled={busyAction === "materialize"} onChange={(event) => setForceRebuildConfirmed(event.target.checked)} label={<>确认废弃目标活动草稿并保留审计历史</>} description={<> 我确认目标活动草稿会被废弃，但不会删除历史，也不会绕过新草稿的校验与人工确认。 </>} /></div>}
                {materializeDecision === "merge" && mergeMatrix}
                <Button loading={busyAction === "materialize"} variant={materializeDecision === "cancel" ? "secondary" : "primary"} disabled={busyAction === "materialize" || !materializeDecision || !materializeReason.trim() || (materializeDecision === "force-rebuild" && !forceRebuildConfirmed) || (materializeDecision === "merge" && (materializePreview.activeDraft || materializePreview.publication) !== undefined && !materializeMerge.ready)} onClick={() => { void confirmMaterializeDecision(); }} type="button">{busyAction === "materialize" ? "正在处理…" : materializeDecision === "cancel" ? "确认取消" : materializeDecision === "force-rebuild" ? "强制重建审核草稿" : "按所选方式生成草稿"}</Button>
              </fieldset>
            )}
          </div>
        </section>
      )}

      {notice && <StatusMessage kind="success" title="操作结果">{notice}</StatusMessage>}
      {error && <StatusMessage kind="danger" title="操作未完成">{error}</StatusMessage>}
      {draft && draftWorkspace}
      {!draft && !published && notes}
    </section>
  );
}
