import type { ReactNode } from "react";
import { History, RefreshCw } from "lucide-react";
import type { UndoablePublishedMoveResponse, VersionDetailResponse, VersionLineageResponse, VersionSummaryResponse } from "../../api/generated";
import type { ReportType } from "../../api/types";
import { Button, EmptyState, FormField, Input, PageHeader, Select, Skeleton, StatusBadge, StatusMessage } from "../../design-system";
import { formatTimestamp, lineageLabel, reportTypeLabel, statusLabel } from "./versionPresentation";
import css from "./VersionHistoryView.module.css";

type Props = {
 reportDate: string; reportType: ReportType; setReportDate: (value: string) => void; setReportType: (value: ReportType) => void;
 batchReviewMode: boolean; routeBatchReviewRunId?: number; canAdminister: boolean; canManageData: boolean; isViewer: boolean;
 undoLookupUnavailable: boolean; notice?: string; error?: string; versions: VersionSummaryResponse[];
 currentPublication?: VersionSummaryResponse; activeDraft?: VersionSummaryResponse; selectedVersionId?: number;
 loading: boolean; detailLoading: boolean; detail?: VersionDetailResponse; selectedUndoableMove?: UndoablePublishedMoveResponse;
 onForceRebuildRequest?: (draft: VersionSummaryResponse) => void; openRollback: (version: VersionSummaryResponse) => void;
 selectVersion: (version: VersionSummaryResponse) => void; onRevision: (version: VersionDetailResponse) => void;
 onMove: (version: VersionSummaryResponse) => void; onUndoMove: () => void; onRetry: () => void;
 batchHistory?: ReactNode; versionRows?: ReactNode; children?: ReactNode;
};
export function VersionHistoryView({ reportDate, reportType, setReportDate, setReportType, batchReviewMode, routeBatchReviewRunId, canAdminister, canManageData, isViewer, undoLookupUnavailable, notice, error, versions, currentPublication, activeDraft, selectedVersionId, loading, detailLoading, detail, selectedUndoableMove, onForceRebuildRequest, openRollback, selectVersion, onRevision, onMove, onUndoMove, onRetry, batchHistory, versionRows, children }: Props) {
  return (
    <main className={css.page} id="main-content">
      <PageHeader eyebrow="日期数据 · 版本记录" title="版本记录" description={batchReviewMode ? `仅显示批量任务 #${routeBatchReviewRunId} 产生且当前仍为待发布的草稿。` : "每个报告日与报表类型独立维护发布指针。历史版本不会覆盖，回滚也会留下新的发布事件。"}
        meta={<StatusBadge tone="quiet" label={canAdminister ? "管理员" : canManageData ? "数据管理" : "只读查看"} />}
        actions={!batchReviewMode ? <form aria-label="版本筛选" className={css.filters} onSubmit={event => event.preventDefault()}>
          <FormField label="报告日期"><Input onChange={event => setReportDate(event.target.value)} type="date" value={reportDate} /></FormField>
          <FormField label="报表类型"><Select onChange={event => setReportType(event.target.value as ReportType)} value={reportType}><option value="business_report">经营报告</option><option value="return_report">退货报告</option></Select></FormField>
        </form> : <a className={css.link} href={`/review/batch/${routeBatchReviewRunId}`}>返回批量任务</a>} />
      {!batchReviewMode && <nav aria-label="版本记录导航" className={css.links}><a className={css.link} href={`/published/${reportDate}?report_type=${reportType}`}>返回日期工作台</a><a className={css.link} href={`/?month=${reportDate.slice(0, 7)}`}>返回总表</a></nav>}

      {batchHistory}
      {isViewer && <p className={css["boundary"]}>查看人员仅能读取已发布版本和查看人员可见备注。</p>}
      {canAdminister && undoLookupUnavailable && (
        <p className={css["boundary"]}>撤销状态暂时无法读取；已隐藏撤销入口，版本浏览不受影响。</p>
      )}
      {notice && <StatusMessage kind="success" title="操作结果">{notice}</StatusMessage>}
      {error && <StatusMessage kind="danger" title="版本记录操作未完成" action={<Button icon={<RefreshCw />} onClick={onRetry}>重新读取版本记录</Button>}>{error}</StatusMessage>}

      <section className={css["docket"]} aria-labelledby="version-docket-title">
        <div>
          <span>{batchReviewMode ? "批量审核" : "当前报告范围"}</span>
          <h2 id="version-docket-title">{batchReviewMode ? `批量任务 #${routeBatchReviewRunId} · 待发布草稿` : `${reportTypeLabel(reportType)} · ${reportDate}`}</h2>
        </div>
        <dl>
          <div><dt>当前发布</dt><dd>{currentPublication ? `v${currentPublication.version_no}` : "—"}</dd></div>
          <div><dt>活动草稿</dt><dd>{activeDraft ? `v${activeDraft.version_no}` : "—"}</dd></div>
          <div><dt>可见版本</dt><dd>{versions.length}</dd></div>
        </dl>
      </section>

      {loading ? (
        <div role="status" className={css.loading}><p>{batchReviewMode ? "正在读取任务的待发布草稿…" : "正在读取该日期的版本谱系…"}</p><Skeleton lines={4} /></div>
      ) : versions.length === 0 && error ? null : versions.length === 0 ? (
        <EmptyState icon={<History />} title={batchReviewMode ? "此任务当前没有待发布草稿。" : `该日期的${reportTypeLabel(reportType)}还没有版本。`} description={batchReviewMode ? "草稿发布、退回或发生状态变化后会自动离开此筛选。" : "完成导入、审核与发布后，版本证据会出现在这里。"} />
      ) : (
        <div className={css["workspace"]}>
          <section aria-labelledby="version-list-title" className={css["list-panel"]}>
            <header><p>版本历史</p><h2 id="version-list-title">版本列表</h2></header>
            <VersionSpine
              canAdminister={canAdminister}
              currentPublication={currentPublication}
              onForceRebuildRequest={onForceRebuildRequest}
              onRollback={openRollback}
              onSelect={selectVersion}
              selectedVersionId={selectedVersionId}
              versions={versions}
            />
          </section>

          <section aria-label="所选版本详情" className={css["detail-panel"]}>
            {detailLoading && <div role="status" className={css.loading}><p>正在读取版本详情…</p><Skeleton lines={4} /></div>}
            {!detailLoading && !detail && <EmptyState title="版本详情尚未读取" description="选择其他版本，或重新读取版本记录。" />}
            {!detailLoading && detail && (
              <>
                <header className={css["detail-heading"]}>
                  <div><span>版本 #{detail.version_id}</span><h2 id="version-detail-title">v{detail.version_no} · {statusLabel(detail)}</h2></div>
                  <div className={css["detail-actions"]}>
                    <a className={css.link} href={`/${canManageData ? "review" : "published"}/${detail.report_date}?report_type=${detail.report_type}`}>{detail.is_active_draft && canManageData ? "继续审核草稿" : "返回日期工作台"}</a>
                    <StatusBadge tone={detail.is_current_publication ? "good" : detail.is_active_draft ? "warn" : "quiet"} label={statusLabel(detail)} />
                    {canManageData && detail.is_current_publication && (
                      <Button
                        className={css["move-action"]}
                        disabled={Boolean(activeDraft) || !detail.published_at}
                        onClick={() => onRevision(detail)}
                        title={activeDraft
                          ? "该报告已有活动草稿，需先完成或废弃该草稿。"
                          : !detail.published_at
                            ? "当前发布缺少发布时间，无法建立并发预期。"
                            : undefined}
                        type="button"
                      >
                        创建修订
                      </Button>
                    )}
                    {canAdminister && detail.is_current_publication && (
                      <Button
                        className={css["move-action"]}
                        disabled={Boolean(activeDraft) || !detail.published_at}
                        onClick={() => onMove(detail)}
                        title={activeDraft ? "来源日期已有活动草稿，需先完成或废弃该草稿。" : undefined}
                        type="button"
                      >
                        移动到其他日期
                      </Button>
                    )}
                    {selectedUndoableMove && (
                      <Button
                        className={css["undo-move-action"]}
                        onClick={onUndoMove}
                        type="button"
                      >
                        撤销跨日期移动
                      </Button>
                    )}
                  </div>
                </header>
                {detail.status === "published" && versionRows}
                {canManageData && detail.is_current_publication && activeDraft && (
                  <p className={css["source-draft-block"]}>该报告已有活动草稿 v{activeDraft.version_no}；请先完成或废弃该草稿，再创建新的修订。</p>
                )}
                <dl className={css["facts"]}>
                  <div><dt>创建时间</dt><dd>{formatTimestamp(detail.created_at)}</dd></div>
                  <div><dt>封存时间</dt><dd>{formatTimestamp(detail.sealed_at)}</dd></div>
                  <div><dt>发布时间</dt><dd>{formatTimestamp(detail.published_at)}</dd></div>
                  <div><dt>修订</dt><dd>数据 r{detail.data_revision} / 审核 r{detail.review_revision}</dd></div>
                </dl>

                <div className={css["lineage-grid"]}>
                  <section><h3>父版本</h3><LineageList emptyText="没有父版本；这是该链的起点。" items={detail.parents} /></section>
                  <section><h3>后续版本</h3><LineageList emptyText="没有后续版本。" items={detail.children} /></section>
                </div>

                <section className={css["notes"]} aria-labelledby="viewer-notes-title">
                  <header><h3 id="viewer-notes-title">查看人员可见备注</h3><span>{detail.viewer_visible_notes.length} 条</span></header>
                  {detail.viewer_visible_notes.length > 0 ? (
                    <ol>{detail.viewer_visible_notes.map((note) => <li key={note.note_key}><p>{note.body}</p><span>修订 {note.revision_number} · {formatTimestamp(note.created_at)}</span></li>)}</ol>
                  ) : <p>此版本没有查看人员可见备注。</p>}
                </section>
              </>
            )}
          </section>
        </div>
      )}

      {children}
    </main>
  );
}

function VersionSpine({
  canAdminister,
  currentPublication,
  onForceRebuildRequest,
  onRollback,
  onSelect,
  selectedVersionId,
  versions,
}: {
  canAdminister: boolean;
  currentPublication?: VersionSummaryResponse;
  onForceRebuildRequest?: (draft: VersionSummaryResponse) => void;
  onRollback: (version: VersionSummaryResponse) => void;
  onSelect: (version: VersionSummaryResponse) => void;
  selectedVersionId?: number;
  versions: VersionSummaryResponse[];
}) {
  return (
    <ol className={css["spine"]}>
      {versions.map((version) => {
        const rollbackEligible = canAdminister
          && version.status === "published"
          && !version.is_current_publication
          && currentPublication?.dataset_id === version.dataset_id;
        return (
          <li
            className={css["spine-item"]}
            key={version.version_id}
          >
            <span className={css["node"]} aria-hidden="true" />
            <article aria-current={selectedVersionId === version.version_id ? "true" : undefined}>
              <Button
                aria-label={`查看版本 v${version.version_no}，${statusLabel(version)}`}
                variant="quiet" className={css["select"]} aria-pressed={selectedVersionId === version.version_id}
                onClick={() => onSelect(version)}
                type="button"
              >
                <span className={css["version-no"]}>v{version.version_no}</span>
                <StatusBadge tone={version.is_current_publication ? "good" : version.is_active_draft ? "warn" : "quiet"} label={statusLabel(version)} />
                <small>{formatTimestamp(version.created_at)}</small>
                <span className={css["revision"]}>数据 r{version.data_revision} · 审核 r{version.review_revision}</span>
              </Button>
              <div className={css["item-actions"]}>
                {rollbackEligible && <Button onClick={() => onRollback(version)} type="button">回滚到 v{version.version_no}</Button>}
                {canAdminister && version.is_active_draft && onForceRebuildRequest && (
                  <Button onClick={() => onForceRebuildRequest(version)} type="button">请求重建 v{version.version_no}</Button>
                )}
              </div>
            </article>
          </li>
        );
      })}
    </ol>
  );
}

function LineageList({
  emptyText,
  items,
}: {
  emptyText: string;
  items: VersionLineageResponse[];
}) {
  if (items.length === 0) return <p className={css["lineage-empty"]}>{emptyText}</p>;
  return (
    <ul className={css["lineage-list"]}>
      {items.map((item) => (
        <li key={`${item.version_id}:${item.lineage_type}:${item.lineage_ordinal}`}>
          <span>{lineageLabel(item)}</span>
          <small>{item.report_date} · {reportTypeLabel(item.report_type)}</small>
        </li>
      ))}
    </ul>
  );
}
