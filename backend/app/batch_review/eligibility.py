"""Strict, side-effect-free eligibility evaluation."""

from __future__ import annotations

from collections.abc import Set

from app.batch_review.types import (
    BatchReviewCandidate,
    BatchReviewReasonCode,
    BatchReviewTargetState,
    EligibilityDecision,
    TargetKey,
)

_REASON_MESSAGES = {
    BatchReviewReasonCode.RECOGNITION_UNCERTAIN: "报告日期、类型或编码未能唯一确认。",
    BatchReviewReasonCode.SOURCE_UNAVAILABLE: "原始文件当前不可安全读取。",
    BatchReviewReasonCode.BATCH_STATE_CONFLICT: "导入批次当前状态不允许批量推进。",
    BatchReviewReasonCode.DUPLICATE_TARGET_IN_RUN: (
        "本任务中已有文件指向相同日期和报表类型。"
    ),
    BatchReviewReasonCode.ACTIVE_DRAFT_EXISTS: "目标日期和类型已经存在活动草稿。",
    BatchReviewReasonCode.PUBLICATION_EXISTS: "目标日期和类型已经存在当前发布版本。",
    BatchReviewReasonCode.ALREADY_MATERIALIZED: "该批次已经生成过数据版本。",
    BatchReviewReasonCode.PERMISSION_DENIED: "当前用户没有批量审核权限。",
}


def _decision(
    candidate: BatchReviewCandidate,
    reason_code: BatchReviewReasonCode,
) -> EligibilityDecision:
    return EligibilityDecision(
        eligible=False,
        target_key=candidate.target_key,
        reason_code=reason_code,
        reason_message=_REASON_MESSAGES[reason_code],
        manual_review_url=candidate.manual_review_url,
    )


def evaluate_candidate(
    candidate: BatchReviewCandidate,
    target: BatchReviewTargetState,
    seen_targets: Set[TargetKey],
) -> EligibilityDecision:
    """Return an eligibility decision using only authoritative server facts."""

    if not candidate.actor_roles.intersection({"admin", "data_manager"}):
        return _decision(candidate, BatchReviewReasonCode.PERMISSION_DENIED)
    if not candidate.source_available:
        return _decision(candidate, BatchReviewReasonCode.SOURCE_UNAVAILABLE)
    if (
        candidate.recognition_status != "recognized"
        or candidate.report_date is None
        or candidate.report_type is None
        or candidate.encoding is None
    ):
        return _decision(candidate, BatchReviewReasonCode.RECOGNITION_UNCERTAIN)
    if candidate.batch_status not in {"uploaded", "staged"}:
        return _decision(candidate, BatchReviewReasonCode.BATCH_STATE_CONFLICT)
    if candidate.already_materialized:
        return _decision(candidate, BatchReviewReasonCode.ALREADY_MATERIALIZED)
    if target.active_draft_exists:
        return _decision(candidate, BatchReviewReasonCode.ACTIVE_DRAFT_EXISTS)
    if target.publication_exists:
        return _decision(candidate, BatchReviewReasonCode.PUBLICATION_EXISTS)
    target_key = candidate.target_key
    if target_key is None:
        return _decision(candidate, BatchReviewReasonCode.RECOGNITION_UNCERTAIN)
    if target_key in seen_targets:
        return _decision(candidate, BatchReviewReasonCode.DUPLICATE_TARGET_IN_RUN)
    return EligibilityDecision(
        eligible=True,
        target_key=target_key,
        reason_code=None,
        reason_message="可安全推进至待发布。",
        manual_review_url=candidate.manual_review_url,
    )
