/**
 * Generated from FastAPI OpenAPI. Do not edit by hand.
 * Run: pwsh ./scripts/generate-api-client.ps1
 */
// OpenAPI SHA-256: a8fc0e39a907cd22e0289b88754b312a536136e290ca13a8fbce76806605651d

export interface components {
  schemas: {
    "ActiveDraftMoveTargetRequest": { "action": "merge" | "cancel" | "force_rebuild"; "dataset_id": number; "draft": components["schemas"]["DraftPointerRequest"]; "publication": components["schemas"]["PublicationPointerRequest"]; "rebuild_strategy"?: "merge" | "replace" | null; "target_kind": "active_draft"; };
    "ActiveDraftReassignmentTargetRequest": { "action": "merge" | "cancel"; "expected_active_draft": components["schemas"]["VersionExpectationRequest"]; "expected_dataset_id": number; "expected_publication_version_id"?: number | null; "target_kind": "active_draft"; };
    "AddRowRequest": { "data_revision": number; "dataset_id": number; "pointed_at": string; "reason": string; "review_revision": number; "source_batch_id": number; "status": "draft" | "ready_for_publish"; "values": Record<string, components["schemas"]["TypedFieldValueRequest"]>; };
    "AdminCommandLookupRequest": { "operation_token": string; "reason": string; };
    "AnalyticsPermissions": { "can_approve_high_risk": boolean; "can_approve_normal": boolean; "can_download_original": boolean; "can_manage_catalog": boolean; "can_submit": boolean; "can_view_catalog_history": boolean; "can_view_evidence_history": boolean; };
    "AnalyticsProvenance": { "catalog_version": number; "catalog_version_id": string; "consistent_as_of": string; "effective_return_basis": components["schemas"]["ReturnBasis"]; "fact_basis": components["schemas"]["FactBasis"]; "fact_cutoff_at": string; "from": string; "identity_source": "p0_catalog"; "identity_version_id": string; "publication_refs": components["schemas"]["PublicationRefs"]; "reporting_timezone": string; "return_basis": components["schemas"]["ReturnBasis"]; "return_dedup_snapshot_id": string; "site_config_version_id": string; "to": string; "trend_effective_return_basis": components["schemas"]["ReturnBasis"] | null; };
    "AnalyticsReadiness": { "catalog_approved": boolean; "coverage_from": string | null; "coverage_to": string | null; "prerequisites_present": boolean; "published_business_reports"?: number; "published_reports": number; "published_return_reports"?: number; "return_snapshot_present": boolean; "source_scope_confirmed": boolean; };
    "ApiErrorDetail": { "code": string; "message": string; "request_id": string; };
    "ApiErrorResponse": { "error": components["schemas"]["ApiErrorDetail"]; };
    "ApplyDecisionsRequest": { "expected_workflow_revision": number; "mutations": Array<components["schemas"]["DecisionMutationRequest"]>; "operation_token": string; };
    "ApproveImportRequest": { "expected_catalog_publication_revision": number; "expected_workflow_revision": number; "operation_token": string; "projection_digest": string; "projection_id": number; "reason": string; };
    "AuditEventPageResponse": { "items": Array<components["schemas"]["AuditEventResponse"]>; "limit": number; "next_offset": number | null; "offset": number; "total": number; };
    "AuditEventResponse": { "actor_user_id": number | null; "actor_username": string | null; "event_type": string; "id": number; "object_id": string | null; "object_type": string; "occurred_at": string; "redacted_payload": Record<string, unknown>; "request_id": string | null; "site_id": number | null; };
    "AvailableSeries": { "active": boolean; "dimension": components["schemas"]["SeriesDimension"]; "key": string; "label": string; "sort_order": number; "total": components["schemas"]["MetricValue"]; };
    "BackupSnapshotStatus": { "audit_event_count": number; "backup_uuid": string; "completed_at": string | null; "database_name": string; "failure_code": string | null; "id": number; "key_id": string; "publication_count": number; "raw_file_count": number; "restore_verified_at": string | null; "schema_revision": string; "sealed_at": string | null; "started_at": string; "status": "running" | "sealed" | "succeeded" | "failed"; "version_count": number; };
    "BatchReviewItemResponse": { "attempt_count": number; "batch_id": number; "dataset_id": number | null; "encoding": string | null; "filename": string; "id": number; "manual_review_url": string | null; "operation_token": string | null; "outcome_unknown": boolean; "reason_code": string | null; "reason_message": string | null; "recognition_status": string; "recovery_available": boolean; "report_date": string | null; "report_type": string | null; "retry_allowed": boolean; "selected": boolean; "status": string; "validation_run_id": number | null; "version_id": number | null; };
    "BatchReviewRunResponse": { "allowed_actions": Array<string>; "id": number; "items": Array<components["schemas"]["BatchReviewItemResponse"]>; "revision": number; "status": string; "summary": components["schemas"]["BatchReviewSummaryResponse"]; };
    "BatchReviewSummaryResponse": { "active": number; "eligible": number; "failed": number; "manual_review": number; "ready_for_publish": number; "skipped": number; "total": number; };
    "CalendarDayReason": "blocking_issues" | "failed_import" | "file_integrity_error" | "draft" | "warnings" | "processing_import";
    "CalendarDayResponse": { "draft_report_types": Array<components["schemas"]["ReportType"]>; "published_report_types": Array<components["schemas"]["ReportType"]>; "reasons": Array<components["schemas"]["CalendarDayReason"]>; "report_date": string; "status": components["schemas"]["CalendarDayStatus"]; };
    "CalendarDayStatus": "red" | "yellow" | "blue" | "green" | "gray";
    "CalendarEntryResponse": { "dataset_id": number; "report_date": string; "report_type": "business_report" | "return_report"; "status": components["schemas"]["CalendarStatus"]; "version_id": number; "version_no": number; };
    "CalendarStatus": "published" | "ready_for_publish" | "draft";
    "CatalogScopePermissionsResponse": { "can_confirm": boolean; };
    "CatalogScopeStatusResponse": { "marketplace_scope_code": "amazon_us"; "permissions": components["schemas"]["CatalogScopePermissionsResponse"]; "report_source_scope_id": number | null; "seller_account_display_name": string | null; "site_config_revision": number; "site_config_version_id": number; "status": "unconfirmed" | "confirmed"; };
    "CategoryCreateRequest": { "aliases"?: Array<string>; "code": string; "display_name": string; "operation_token": string; "parent_category_id"?: number | null; };
    "CategoryUpdateRequest": { "aliases"?: Array<string>; "code"?: string | null; "display_name": string; "operation_token": string; "parent_category_id"?: number | null; "status": string; };
    "CellComparisonResponse": { "base": components["schemas"]["TypedFieldValueResponse"] | null; "changed_from_base": boolean; "changed_from_source": boolean; "current": components["schemas"]["TypedFieldValueResponse"]; "field_name": string; "history": Array<components["schemas"]["FieldChangeResponse"]>; "notes": Array<components["schemas"]["LatestNoteResponse"]>; "parent_restore_options": Array<components["schemas"]["ParentRestoreOptionResponse"]>; "source": components["schemas"]["TypedFieldValueResponse"] | null; "source_restore_option": components["schemas"]["SourceRestoreOptionResponse"] | null; };
    "CellValue": string | number | null;
    "ChangeDateRequest": { "report_date": string; };
    "ChangeRowStateRequest": { "data_revision": number; "dataset_id": number; "operation": "exclude" | "restore" | "delete"; "pointed_at": string; "reason": string; "review_revision": number; "status": "draft" | "ready_for_publish"; };
    "ConfirmCatalogScopeRequest": { "expected_site_config_revision": number; "marketplace_scope_code": "amazon_us"; "operation_token": string; "reason": string; "seller_account_display_name": string; "seller_account_scope_key": string; };
    "ConfirmParseRequest": { "encoding": "utf-8-sig" | "utf-8" | "windows-1252"; "report_date": string; "report_type": "business_report" | "return_report"; "site_config_version_id"?: number | null; };
    "ConfirmRequest": { "confirmation_accepted": true; "confirmation_statement_version": string; "expected_revision": number; "selected_item_ids": Array<number>; };
    "ConfirmWorkbenchImportRequest": { "encoding": components["schemas"]["SupportedEncoding"]; "report_date": string; "report_type": components["schemas"]["ReportType"]; };
    "ConfirmationTotalRequest": { "field_name": string; "value": string; };
    "CoverageBlock": { "confirmed_distinct_rows": number | null; "coverage_from": string; "coverage_to": string; "dedup_decision_rate": string | null; "dedup_status": components["schemas"]["CoverageStatus"]; "duplicate_of_rows": number | null; "eligible_rows": number; "excluded_rows": number; "expected_days": number; "identity_decision_rate": string | null; "identity_status": components["schemas"]["CoverageStatus"]; "mapped_rows": number; "mapping_rate": string | null; "missing_days": number; "published_days": number; "report_coverage_rate": string | null; "report_type": components["schemas"]["ReportType"]; "unique_rows": number | null; "unmatched_rows": number; "unresolved_rows": number | null; };
    "CoverageStatus": "not_applicable" | "partial" | "complete";
    "CreateCatalogExportRequest": { "expected_catalog_publication_revision": number; "operation_token": string; };
    "CreateImportBatchNoteRequest": { "body": string; "visibility"?: "internal"; };
    "CreateNoteRequest": { "body": string; "expected_review_revision": number; "field_name"?: string | null; "row_id"?: number | null; "target_type"?: "version" | "row" | "field"; "visibility"?: "internal" | "viewer_visible"; };
    "CreatePublishedMoveRequest": { "expected_source_publication": components["schemas"]["PublicationPointerRequest"]; "merge_decisions"?: Array<components["schemas"]["MergeDecisionRequest"]>; "reason": string; "source_dataset_id": number; "target": components["schemas"]["MoveTargetRequest"]; "target_report_date": string; };
    "CreateRevisionRequest": { "expected_publication": components["schemas"]["PublicationPointerRequest"]; "reason": string; };
    "CreateSiteConfigVersionRequest": { "change_reason": string; "currency_code": string; "effective_at": string; "reporting_timezone": string; "site_id": number; "source_timezone": string; };
    "CreateUserRequest": { "display_name": string; "email"?: string | null; "password": string; "roles": Array<string>; "status"?: "active" | "disabled" | "locked"; "username": string; };
    "CreateWorkbenchRevisionRequest": { "published_version_id": number; "reason": string; };
    "CsrfTokenResponse": { "csrf_token": string; };
    "CurrentUserResponse": { "display_name": string; "id": number; "roles": Array<string>; "username": string; };
    "DailyLedgerResponse": { "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "rows": Array<components["schemas"]["DailyLedgerRow"]>; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; };
    "DailyLedgerRow": { "business_status": components["schemas"]["ReportLedgerStatus"]; "conversion_rate": string | null; "counts_as_incomplete": boolean; "overall_status": components["schemas"]["OverallLedgerStatus"]; "pending_summary": string | null; "reasons": Array<components["schemas"]["LedgerReason"]>; "report_date": string; "return_quantity": number | null; "return_status": components["schemas"]["ReportLedgerStatus"]; "sales": string | null; "sessions": number | null; "units_ordered": number | null; };
    "DashboardMetric": { "business_version_id": number | null; "conversion_rate": string | null; "report_date": string; "return_quantity": number; "return_version_id": number | null; "sales": string; "sessions": number; "units_ordered": number; };
    "DashboardSummary": { "metrics": Array<components["schemas"]["DashboardMetric"]>; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; };
    "DateRange": { "from_date": string; "to_date": string; };
    "DateWorkbenchResponse": { "actions": Array<components["schemas"]["WorkbenchAction"]>; "columns": Array<components["schemas"]["WorkbenchColumnResponse"]>; "head": components["schemas"]["WorkbenchHeadResponse"] | null; "pagination": components["schemas"]["WorkbenchPaginationResponse"]; "pending_upload_count": number; "permissions": components["schemas"]["WorkbenchPermissionsResponse"]; "report_date": string; "report_type": components["schemas"]["ReportType"]; "rows": Array<components["schemas"]["WorkbenchRowResponse"]>; "source": components["schemas"]["WorkbenchSource"]; "tabs": Array<components["schemas"]["WorkbenchTabResponse"]>; "validation": components["schemas"]["WorkbenchValidationSummaryResponse"] | null; };
    "DecisionMutationRequest": { "decision_group_key"?: string | null; "mutation_id": string; "payload": Record<string, components["schemas"]["JsonValue"]>; "row_key"?: string | null; "type": string; };
    "DedupDecisionRequest": { "canonical_member_id"?: number | null; "decision": "confirmed_distinct" | "duplicate_of"; "expected_dedup_publication_revision": number; "expected_group_revision": number; "operation_token": string; "reason": string; };
    "DedupPayloadResponse": { "payload": string; };
    "DiscardDraftRequest": { "dataset_id": number; "expected_active_draft": components["schemas"]["VersionExpectationRequest"]; "reason": string; };
    "DraftCommandResponse": { "completed_at": string; "data_revision": number; "dataset_id": number; "operation_token": string; "result_kind": "revision_created" | "published_move_revision_created" | "published_move_revision_cancelled"; "review_revision": number; "source_dataset_id": number | null; "source_version_id": number | null; "status": "draft" | "cancelled"; "version_id": number; "version_no": number; };
    "DraftHeadResponse": { "data_revision": number; "dataset_id": number; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; "version_id": number; "version_no": number; };
    "DraftMutationResponse": { "data_revision": number; "dataset_id": number; "operation_token": string; "review_revision": number; "source_dataset_id": number | null; "source_version_id": number | null; "status": "draft" | "discarded" | "cancelled"; "superseded_version_ids": Array<number>; "version_id": number; "version_no": number; };
    "DraftPointerRequest": { "data_revision": number; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; "version_id": number; };
    "DraftWorkspaceHeadResponse": { "data_revision": number; "dataset_id": number; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; "version_id": number; "version_no": number; };
    "EmptyMoveTargetRequest": { "dataset_id"?: null; "target_kind": "empty"; };
    "EmptyReassignmentTargetRequest": { "expected_dataset_id"?: null; "target_kind": "empty"; };
    "FactBasis": "current" | "catalog_snapshot";
    "FieldChangeResponse": { "actor_user_id": number; "actor_username": string; "after": components["schemas"]["TypedFieldValueResponse"]; "before": components["schemas"]["TypedFieldValueResponse"]; "data_revision": number; "id": number; "occurred_at": string; "operation": "set" | "restore_source" | "restore_parent" | "restore_previous"; "reason": string; "restored_field_change_id": number | null; "restored_parent_version_id": number | null; "restored_source_row_id": number | null; };
    "FieldContractResponse": { "ascii_only": boolean; "editable": boolean; "included_in_totals": boolean; "kind": "text" | "integer" | "decimal" | "utc_datetime"; "max_length": number | null; "name": string; "nullable": boolean; "precision": number | null; "required_on_add": boolean; "scale": number | null; };
    "FinalizePublishedMoveRequest": { "confirmation": components["schemas"]["PublicationConfirmationRequest"]; "expected_source_publication": components["schemas"]["PublicationPointerRequest"]; "expected_target_draft": components["schemas"]["DraftPointerRequest"]; "expected_target_publication": components["schemas"]["PublicationPointerRequest"]; "reason": string; "source_dataset_id": number; "target_dataset_id": number; "validation": components["schemas"]["ValidationExpectationRequest"]; };
    "ForceRebuildDraftRequest": { "batch_id": number; "expected_active_draft": components["schemas"]["VersionExpectationRequest"]; "expected_publication_version_id"?: number | null; "parse_baseline_id": number; "reason": string; "report_date": string; };
    "FromExportImportRequest": { "expected_catalog_publication_revision": number; "export_id": number; "operation_token": string; };
    "FullValidationResponse": { "completed_at": string; "data_digest": string; "data_revision": number; "id": number; "is_current": boolean; "issues": Array<components["schemas"]["ValidationIssueResponse"]>; "result": "passed" | "failed" | "error"; "ruleset_version": string; "started_at": string; "status": "succeeded" | "failed"; "summary": Record<string, unknown>; };
    "HeartbeatThresholdsResponse": { "heartbeat_seconds": 10; "offline_seconds": 60; "refresh_seconds": 15; "stale_seconds": 30; };
    "ImportBatchNoteResponse": { "author_user_id": number; "author_username": string; "body": string; "created_at": string; "import_batch_id": number; "note_id": number; "note_key": string; "revision_number": number; "target_type"?: "import_batch"; "visibility": "internal" | "viewer_visible"; };
    "ImportReasonRequest": { "expected_workflow_revision": number; "operation_token": string; "reason": string; };
    "ImportRevisionRequest": { "expected_workflow_revision": number; "operation_token": string; };
    "InspectionResponse": { "encoding": string | null; "issue_codes": Array<string>; "report_date": string | null; "report_type": "business_report" | "return_report" | null; "ruleset_version": string; "status": string; };
    "IssueReviewStateResponse": { "actor_user_id": number | null; "actor_username": string | null; "comment": string | null; "event_id": number | null; "event_type": "acknowledge" | "resolve" | "reopen" | null; "occurred_at": string | null; "state": "open" | "acknowledged" | "resolved"; };
    "JsonValue": unknown;
    "LatestNoteResponse": { "author_user_id": number; "author_username": string; "body": string; "created_at": string; "field_name": string | null; "note_id": number; "note_key": string; "review_revision": number; "revision_number": number; "row_id": number | null; "target_type": "version" | "row" | "field"; "visibility": "internal" | "viewer_visible"; };
    "LedgerReason": "blocking_issues" | "failed_import" | "file_integrity_error" | "draft" | "warnings" | "processing_import";
    "LineageType": "base" | "draft_predecessor" | "merge_target" | "merge_source" | "moved_source";
    "LoginRequest": { "password": string; "username": string; };
    "LoginResponse": { "csrf_token": string; "expires_at": string; "user": components["schemas"]["CurrentUserResponse"]; };
    "MaintenanceStatusResponse": { "backups": Array<components["schemas"]["BackupSnapshotStatus"]>; "maintenance_active": boolean; "observed_at": string; "outbox": components["schemas"]["OutboxStatus"]; "queues": Array<components["schemas"]["QueueStatusResponse"]>; "restores": Array<components["schemas"]["RestoreVerificationStatus"]>; "worker": components["schemas"]["WorkerFleetStatusResponse"]; "write_lock": components["schemas"]["MaintenanceWriteLockStatus"]; };
    "MaintenanceWriteLockStatus": { "held": boolean; "observed_seconds": number; "owner_connection_id": number | null; "warning": boolean; };
    "MarkReadyRequest": { "confirmed_report_date": string; "confirmed_report_type": "business_report" | "return_report"; "confirmed_row_count": number; "confirmed_totals": Record<string, string>; "data_revision": number; "dataset_id": number; "pointed_at": string; "reason": string; "review_revision": number; "ruleset_version": string; "status": "draft" | "ready_for_publish"; "validation_data_digest": string; "validation_run_id": number; };
    "MaterializeBaselineRequest": { "batch_id": number; "expected_active_draft"?: components["schemas"]["VersionExpectationRequest"] | null; "expected_publication_version_id"?: number | null; "merge_decisions"?: Array<components["schemas"]["MergeDecisionRequest"]>; "parse_baseline_id": number; "reason": string; "report_date": string; "strategy": "merge" | "replace"; };
    "MergeConflictPreviewResponse": { "source_row_id": number; "source_row_ordinal": number; "source_values": Record<string, string | null>; "target_row_id": number; "target_row_ordinal": number; "target_values": Record<string, string | null>; };
    "MergeDecisionRequest": { "action": "keep_target" | "keep_source" | "keep_both"; "reason"?: string | null; "source_row_id": number; "target_row_id": number; };
    "MergePreviewResponse": { "conflicts": Array<components["schemas"]["MergeConflictPreviewResponse"]>; "report_type": "business_report" | "return_report"; "source_id": number; "source_kind": "parse_baseline" | "dataset_version"; "target_version_id": number; };
    "MetricEvaluability": { "conversion": components["schemas"]["MetricStatus"]; "returns": components["schemas"]["MetricStatus"]; "sales": components["schemas"]["MetricStatus"]; "sessions": components["schemas"]["MetricStatus"]; "units": components["schemas"]["MetricStatus"]; };
    "MetricName": "units" | "sales" | "returns" | "sessions" | "conversion";
    "MetricStatus": "evaluable" | "not_evaluable";
    "MetricTotals": { "conversion_denominator": number | null; "conversion_numerator": number | null; "returns": number | null; "sales": string | null; "sessions": number | null; "units": number | null; };
    "MetricValue": { "denominator": number | null; "expected_days": number; "is_partial": boolean; "null_reason": components["schemas"]["NullReason"] | null; "numerator": number | null; "observed_days": number; "source_completeness": components["schemas"]["SourceCompleteness"]; "value": number | string | null; "value_state": components["schemas"]["ValueState"]; };
    "MetricValues": { "conversion": components["schemas"]["MetricValue"]; "returns": components["schemas"]["MetricValue"]; "sales": components["schemas"]["MetricValue"]; "sessions": components["schemas"]["MetricValue"]; "units": components["schemas"]["MetricValue"]; };
    "MoveTargetRequest": components["schemas"]["EmptyMoveTargetRequest"] | components["schemas"]["PublishedMoveTargetRequest"] | components["schemas"]["ActiveDraftMoveTargetRequest"];
    "NullReason": "missing_report" | "undefined_denominator" | "no_observed_reports";
    "OutboxStatus": { "completed": number; "failed": number; "oldest_pending_at": string | null; "pending": number; "processing": number; };
    "OverallLedgerStatus": "complete" | "partial" | "review" | "blocked" | "empty" | "future";
    "ParentRestoreOptionResponse": { "parent_version_id": number; "value": components["schemas"]["TypedFieldValueResponse"]; };
    "PreflightRequest": { "batch_ids": Array<number>; };
    "ProductCardResponse": { "latest_published_date": string | null; "name_status": components["schemas"]["ProductNameStatus"]; "product_name": string | null; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; "style_code": string; "summary": components["schemas"]["ProductCardSummary"]; "trend": Array<components["schemas"]["ProductTrendPoint"]>; "variants": Array<components["schemas"]["ProductVariant"]>; };
    "ProductCardSummary": { "conversion_rate": string | null; "published_days": number; "return_quantity": number; "sales": string; "sessions": number; "units_ordered": number; };
    "ProductDashboard": { "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "rows": Array<components["schemas"]["ProductMetric"]>; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; };
    "ProductLedgerResponse": { "direction": components["schemas"]["SortDirection"]; "page": number; "page_size": number; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "rows": Array<components["schemas"]["ProductLedgerRow"]>; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; "sort": components["schemas"]["ProductLedgerSort"]; "total_rows": number; };
    "ProductLedgerRow": { "color_count": number; "conversion_rate": string | null; "latest_published_date": string | null; "name_status": components["schemas"]["ProductNameStatus"]; "product_name": string | null; "published_days": number; "return_quantity": number; "row_kind": components["schemas"]["ProductRowKind"]; "sales": string; "sessions": number; "size_count": number; "style_code": string | null; "unclassified_sku": string | null; "units_ordered": number; "variant_count": number; };
    "ProductLedgerSort": "sales" | "units_ordered" | "sessions" | "conversion_rate" | "return_quantity" | "published_days" | "latest_published_date" | "style_code" | "product_name";
    "ProductMetric": { "asin": string | null; "conversion_rate": string | null; "sales": string; "sessions": number; "sku": string | null; "units_ordered": number; };
    "ProductNameStatus": "available" | "multiple" | "missing";
    "ProductRowKind": "product" | "unclassified";
    "ProductTrendPoint": { "conversion_rate": string | null; "report_date": string; "return_quantity": number; "sales": string; "sessions": number; "units_ordered": number; };
    "ProductVariant": { "asins": Array<string>; "color": string; "fnskus": Array<string>; "product_name": string | null; "seller_sku": string; "size": string; };
    "PublicationCommandResponse": { "command_id": number; "command_type": "publish" | "rollback" | "move" | "reverse_move"; "completed_at": string; "operation_token": string; "transitions": Array<components["schemas"]["PublicationTransitionResponse"]>; };
    "PublicationConfirmationRequest": { "confirmed_report_date": string; "report_type": "business_report" | "return_report"; "row_count": number; "totals"?: Array<components["schemas"]["ConfirmationTotalRequest"]>; };
    "PublicationDay": { "dataset_id": string | null; "pointer_revision": number | null; "published_version_id": string | null; "report_date": string; "report_status": components["schemas"]["ReportStatus"]; "report_type": components["schemas"]["ReportType"]; "snapshot_member_id": string | null; };
    "PublicationPointerRequest": { "published_at"?: string | null; "version_id"?: number | null; };
    "PublicationPointerResponse": { "published_at": string | null; "version_id": number | null; };
    "PublicationPointerSnapshotResponse": { "published_at": string | null; "version_id": number | null; };
    "PublicationReference": { "dataset_id": number; "published_at": string; "report_date": string; "report_type": "business_report" | "return_report"; "site_id": number; "version_id": number; };
    "PublicationRefs": { "members": Array<components["schemas"]["PublicationDay"]>; "members_digest": string; "members_digest_version": "publication_refs_jcs_v1"; "mode": components["schemas"]["FactBasis"]; "snapshot_id": string | null; };
    "PublicationTransitionResponse": { "dataset_id": number; "event_id": number; "event_type": "published" | "replaced" | "rolled_back" | "moved_out" | "moved_in" | "move_reversed"; "next_version_id": number | null; "peer_dataset_id": number | null; "previous_version_id": number | null; "sequence_number": number; };
    "PublishRequest": { "confirmation": components["schemas"]["PublicationConfirmationRequest"]; "expected_draft": components["schemas"]["DraftPointerRequest"]; "expected_publication": components["schemas"]["PublicationPointerRequest"]; "reason": string; "validation": components["schemas"]["ValidationExpectationRequest"]; };
    "PublishedDateSummary": { "matching_row_count": number; "metric_scope"?: "full_day"; "publication": components["schemas"]["PublicationReference"]; "published_at": string; "report_date": string; "return_quantity": number | null; "sales": string | null; "sessions": number | null; "total_row_count": number; "units_ordered": number | null; "version_id": number; "version_no": number; };
    "PublishedDetailCell": { "column_id": string; "value": string | number | null; };
    "PublishedDetailColumn": { "column_id": string; "display_order": number; "is_key": boolean; "participates_in_statistics": boolean; "source_header": string; "standard_field_name": string | null; "value_kind": "text" | "integer" | "decimal" | "utc_datetime"; };
    "PublishedDetailPagination": { "page": number; "page_size": number; "total_items": number; "total_pages": number; };
    "PublishedDetailPermissions": { "can_export": boolean; };
    "PublishedDetailRange": { "from_date": string; "to_date": string; };
    "PublishedDetailRow": { "cells": Array<components["schemas"]["PublishedDetailCell"]>; "published_at": string; "report_date": string; "row_ordinal": number; "version_id": number; "version_no": number; };
    "PublishedMoveContextResponse": { "revision_operation_token": string; "source_dataset_id": number; "source_publication": components["schemas"]["PublicationPointerResponse"]; "source_report_date": string; "target_publication": components["schemas"]["PublicationPointerResponse"]; };
    "PublishedMoveTargetRequest": { "dataset_id": number; "publication": components["schemas"]["PublicationPointerRequest"]; "strategy": "merge" | "replace"; "target_kind": "published"; };
    "PublishedRangeResponse": { "from_date": string | null; "to_date": string | null; };
    "PublishedReassignmentTargetRequest": { "expected_dataset_id": number; "expected_publication_version_id": number; "strategy": "merge" | "replace"; "target_kind": "published"; };
    "PublishedRowsResponse": { "columns": Array<components["schemas"]["PublishedDetailColumn"]>; "pagination": components["schemas"]["PublishedDetailPagination"]; "permissions": components["schemas"]["PublishedDetailPermissions"]; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["PublishedDetailRange"]; "rows": Array<components["schemas"]["PublishedDetailRow"]>; "scope_token": string; };
    "PublishedSummaryResponse": { "pagination": components["schemas"]["PublishedDetailPagination"]; "permissions": components["schemas"]["PublishedDetailPermissions"]; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["PublishedDetailRange"]; "scope_token": string; "summaries": Array<components["schemas"]["PublishedDateSummary"]>; };
    "QueueCapabilitiesResponse": { "actionable": boolean; "in_flight": boolean; "retry_wait": boolean; "stale": boolean; "stuck": boolean; };
    "QueueStatusResponse": { "actionable": number | null; "capabilities": components["schemas"]["QueueCapabilitiesResponse"]; "consecutive_failures": number | null; "consumer_health": "healthy" | "failing" | "unknown" | "not_observed"; "failed": number | null; "failure_code": string | null; "in_flight": number | null; "last_failed_at": string | null; "last_succeeded_at": string | null; "native_status_counts": Record<string, number> | null; "next_retry_at": string | null; "oldest_work_at": string | null; "query_health": "healthy" | "unknown"; "queue_name": "return_dedup" | "publication_outbox" | "catalog_export" | "catalog_import"; "retry_wait": number | null; "stale": number | null; "stuck": number | null; "unresolved_building": number | null; };
    "RawFilePreviewResponse": { "encoding": "utf-8-sig" | "utf-8" | "windows-1252"; "headers": Array<string>; "row_count": number; "rows": Array<Array<string>>; "truncated": boolean; };
    "ReassignDraftDateRequest": { "merge_decisions"?: Array<components["schemas"]["MergeDecisionRequest"]>; "reason": string; "source_dataset_id": number; "source_draft": components["schemas"]["VersionExpectationRequest"]; "target": components["schemas"]["ReassignmentTargetRequest"]; "target_report_date": string; };
    "ReassignmentTargetRequest": components["schemas"]["EmptyReassignmentTargetRequest"] | components["schemas"]["PublishedReassignmentTargetRequest"] | components["schemas"]["ActiveDraftReassignmentTargetRequest"];
    "RebaseImportRequest": { "expected_catalog_publication_revision": number; "expected_workflow_revision": number; "operation_token": string; "replacement_export_id": number; };
    "ReportLedgerStatus": "published" | "draft" | "processing" | "failed" | "blocked" | "missing" | "future";
    "ReportStatus": "published" | "missing";
    "ReportType": "business_report" | "return_report";
    "RestoreCatalogVersionRequest": { "expected_catalog_publication_revision": number; "operation_token": string; "reason": string; };
    "RestoreFieldRequest": { "data_revision": number; "dataset_id": number; "field_change_id"?: number | null; "parent_version_id"?: number | null; "parsed_source_row_id"?: number | null; "pointed_at": string; "reason": string; "review_revision": number; "row_id": number; "source_batch_id"?: number | null; "source_kind": "previous" | "parent" | "source"; "status": "draft" | "ready_for_publish"; };
    "RestoreVerificationStatus": { "backup_uuid": string; "completed_at": string | null; "failure_code": string | null; "id": number; "started_at": string; "status": "running" | "succeeded" | "failed"; "target_database_name": string; "verification_uuid": string; };
    "ResumeCatalogExportRequest": { "expected_job_revision": number; "operation_token": string; };
    "ResumeImportRequest": { "expected_parse_attempt_revision": number; "expected_workflow_revision": number; "operation_token": string; };
    "ReturnBasis": "event_date" | "report_date";
    "ReturnBreakdown": { "asin": string | null; "bucket_date": string; "disposition": string | null; "quantity": number; "reason": string | null; "reporting_timezone": string; "site_config_version_id": number; "sku": string | null; };
    "ReturnDashboard": { "basis": "report_date" | "event_date"; "publications": Array<components["schemas"]["PublicationReference"]>; "range": components["schemas"]["DateRange"]; "rows": Array<components["schemas"]["ReturnBreakdown"]>; "site_config_versions": Array<components["schemas"]["SiteConfigurationReference"]>; };
    "ReturnDedupDecisionRequest": { "canonical_member_id"?: number | null; "decision": "confirmed_distinct" | "duplicate_of"; "expected_dedup_publication_revision": number; "expected_group_revision": number; "operation_token": string; "reason": string; };
    "ReturnDedupDecisionResponse": { "canonical_member_id": number | null; "decision": "confirmed_distinct" | "duplicate_of"; "dedup_publication_revision": number; "group_id": string; "group_revision": number; "snapshot_id": number; };
    "ReturnDedupGroupMemberResponse": { "dataset_id": number; "published_version_id": number; "report_date": string; "source_key_id": number; "source_ref": components["schemas"]["app__catalog__source_refs__SafeSourceRef"]; };
    "ReturnDedupGroupPageResponse": { "dedup_publication_revision": number; "groups": Array<components["schemas"]["ReturnDedupGroupResponse"]>; "page": number; "page_size": number; "snapshot_id": number; "total_items": number; };
    "ReturnDedupGroupResponse": { "canonical_member_id": number | null; "decision": "unresolved" | "confirmed_distinct" | "duplicate_of"; "group_id": string; "group_revision": number; "member_count": number; "members": Array<components["schemas"]["ReturnDedupGroupMemberResponse"]>; };
    "ReturnDedupRetryRequest": { "expected_job_revision": number; "operation_token": string; "proposed_set_digest": string; };
    "ReturnDedupStagingRequest": { "dataset_id": number; "expected_dedup_publication_revision": number; "expected_publication_revision": number; "operation_token": string; "proposed_version_id": number; };
    "ReturnDedupStagingResponse": { "command_url": string; "failure_reason": string | null; "job_id": number; "job_revision": number; "next_job_revision": number; "proposed_set_digest": string; "result_snapshot_id": number | null; "retry_allowed": boolean; "status": "building" | "ready" | "failed" | "superseded"; "status_url": string; };
    "ReturnInitializationPreview": { "coverage_from": string; "coverage_to": string; "dataset_id": number; "existing_job_id"?: number | null; "expected_dedup_publication_revision": number; "expected_publication_revision": number; "expected_set_digest": string; "initialization_revision": number; "proposed_version_id": number; "published_return_reports": number; };
    "ReturnInitializationRequest": { "dataset_id": number; "expected_dedup_publication_revision": number; "expected_publication_revision": number; "expected_set_digest": string; "initialization_revision": number; "operation_token": string; "proposed_version_id": number; };
    "ReturnToDraftRequest": { "data_revision": number; "dataset_id": number; "pointed_at": string; "reason": string; "review_revision": number; "status": "draft" | "ready_for_publish"; };
    "ReviewIssueRequest": { "action": "acknowledge" | "resolve" | "reopen"; "comment"?: string | null; "data_revision": number; "dataset_id": number; "issue_requires_note": boolean; "issue_severity": "warning" | "blocking"; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; "validation_run_id": number; };
    "ReviewRowResponse": { "base_row_id": number | null; "cells": Array<components["schemas"]["CellComparisonResponse"]>; "history": Array<components["schemas"]["RowChangeResponse"]>; "logical_row_id": string; "notes": Array<components["schemas"]["LatestNoteResponse"]>; "original_parsed_source_row_id": number | null; "row_id": number; "row_ordinal": number; "row_state": "active" | "excluded" | "deleted"; };
    "ReviewWorkspaceResponse": { "fields": Array<components["schemas"]["FieldContractResponse"]>; "head": components["schemas"]["DraftWorkspaceHeadResponse"]; "latest_full_validation": components["schemas"]["FullValidationResponse"] | null; "pagination": components["schemas"]["WorkspacePaginationResponse"]; "publication_mode": "ordinary" | "published_move"; "published_move": components["schemas"]["PublishedMoveContextResponse"] | null; "report_date": string; "report_type": components["schemas"]["ReportType"]; "rows": Array<components["schemas"]["ReviewRowResponse"]>; "ruleset_version": string; "source_batches": Array<components["schemas"]["SourceBatchResponse"]>; "version_notes": Array<components["schemas"]["LatestNoteResponse"]>; };
    "ReviseImportBatchNoteRequest": { "body": string; "expected_note_id": number; "expected_revision_number": number; "visibility"?: "internal"; };
    "ReviseNoteRequest": { "body": string; "expected_note_id": number; "expected_review_revision": number; "expected_revision_number": number; "field_name"?: string | null; "row_id"?: number | null; "target_type"?: "version" | "row" | "field"; "visibility"?: "internal" | "viewer_visible"; };
    "RevisionRequest": { "expected_revision": number; };
    "RoleResponse": { "code": string; "description": string; };
    "RollbackRequest": { "expected_publication": components["schemas"]["PublicationPointerRequest"]; "reason": string; "target_version_id": number; };
    "RowChangeResponse": { "actor_user_id": number; "actor_username": string; "after": Record<string, unknown>; "before": Record<string, unknown>; "data_revision": number; "id": number; "occurred_at": string; "operation": "add" | "exclude" | "restore" | "delete"; "reason": string; "source_batch_id": number | null; };
    "RunValidationRequest": { "data_revision": number; "dataset_id": number; "ruleset_version": string; };
    "SeriesDimension": "total" | "color" | "size" | "sku";
    "SetFieldRequest": { "data_revision": number; "dataset_id": number; "field_name": string; "pointed_at": string; "reason": string; "review_revision": number; "row_id": number; "status": "draft" | "ready_for_publish"; "value": components["schemas"]["TypedFieldValueRequest"]; };
    "SetWorkbenchCellRequest": { "expected_cell_revision": number; "head": components["schemas"]["WorkbenchExpectedHeadRequest"]; "reason": string; "value": components["schemas"]["WorkbenchCellValueRequest"]; };
    "SiteConfigVersionResponse": { "change_reason": string | null; "created_at": string; "created_by_user_id": number | null; "currency_code": string; "effective_at": string; "id": number; "is_current": boolean; "reporting_timezone": string; "site_code": string; "site_display_name": string; "site_id": number; "source_timezone": string; "version_number": number; };
    "SiteConfigurationReference": { "currency_code": string; "reporting_timezone": string; "site_code": string; "site_config_version_id": number; "site_id": number; "source_timezone": string; };
    "SiteContextResponse": { "currency_code": string; "display_name": string; "reporting_timezone": string; "site_code": string; "site_config_version_id": number; "site_id": number; "source_timezone": string; };
    "SiteCoverage": { "business": components["schemas"]["CoverageBlock"]; "returns": components["schemas"]["CoverageBlock"]; "scope": "site"; };
    "SiteReconciliation": { "duplicate_totals": components["schemas"]["MetricTotals"]; "excluded_totals": components["schemas"]["MetricTotals"]; "mapped_totals": components["schemas"]["MetricTotals"]; "metric_status": components["schemas"]["MetricEvaluability"]; "scope": "site"; "source_totals": components["schemas"]["MetricTotals"]; "unmatched_totals": components["schemas"]["MetricTotals"]; "unresolved_duplicate_totals": components["schemas"]["MetricTotals"]; };
    "SortDirection": "asc" | "desc";
    "SourceBatchResponse": { "batch_id": number; };
    "SourceCompleteness": "complete" | "partial" | "indeterminate";
    "SourceReportCoverage": { "contributing_report_date_from": string | null; "contributing_report_date_to": string | null; "coverage_from": string; "coverage_to": string; "days": Array<components["schemas"]["PublicationDay"]>; };
    "SourceRestoreOptionResponse": { "parsed_source_row_id": number; "source_batch_id": number; "value": components["schemas"]["TypedFieldValueResponse"]; };
    "StyleCardResponse": { "available_series": Array<components["schemas"]["AvailableSeries"]>; "effective_return_basis": components["schemas"]["ReturnBasis"]; "permissions": components["schemas"]["AnalyticsPermissions"]; "provenance": components["schemas"]["AnalyticsProvenance"]; "series": Array<components["schemas"]["TrendSeries"]>; "source_report_coverage": components["schemas"]["SourceReportCoverage"]; "style": components["schemas"]["StyleIdentity"]; "style_reconciliation": components["schemas"]["StyleReconciliation"]; "summary": components["schemas"]["StyleSummary"]; "trend_effective_return_basis": components["schemas"]["ReturnBasis"] | null; "variants": Array<components["schemas"]["StyleVariant"]>; };
    "StyleChangeApproveRequest": { "expected_catalog_publication_revision": number; "expected_draft_revision": number; "operation_token": string; "reason": string; };
    "StyleChangeDraftRequest": { "category_action": string; "category_id"?: number | null; "expected_catalog_publication_revision": number; "expected_style_revision": number; "operation_token": string; "standard_name": string; };
    "StyleIdentity": { "color_count": number; "size_count": number; "sku_count": number; "standard_name": string; "status": "enabled" | "disabled"; "style_code": string; "style_id": string; };
    "StyleLedgerResponse": { "coverage": components["schemas"]["SiteCoverage"]; "direction": "asc" | "desc"; "filtered_sales_total": string | null; "page": number; "page_size": number; "permissions": components["schemas"]["AnalyticsPermissions"]; "provenance": components["schemas"]["AnalyticsProvenance"]; "reconciliation": components["schemas"]["SiteReconciliation"]; "rows": Array<components["schemas"]["StyleLedgerRow"]>; "sort": "style_code" | "standard_name" | "units" | "sales" | "returns" | "sessions" | "conversion"; "total_rows": number; };
    "StyleLedgerRow": { "color_count": number; "latest_report_date": string | null; "metrics": components["schemas"]["MetricValues"]; "size_count": number; "sku_count": number; "source_title_count": number; "standard_name": string; "status": "enabled" | "disabled"; "style_code": string; "style_id": string; };
    "StyleReconciliation": { "metric_status": components["schemas"]["MetricEvaluability"]; "scope": "style"; "selected_color_totals": components["schemas"]["MetricTotals"] | null; "series_scope": "style" | "selected_color"; "series_scope_totals": components["schemas"]["MetricTotals"]; "summary_totals": components["schemas"]["MetricTotals"]; "variant_totals": components["schemas"]["MetricTotals"]; };
    "StyleSummary": { "metrics": components["schemas"]["MetricValues"]; };
    "StyleVariant": { "internal_display_sku": string; "metrics": components["schemas"]["MetricValues"]; "seller_sku_aliases": Array<components["schemas"]["app__analytics__style_models__SafeSourceRef"]>; "sku_id": string; "standard_color": string; "standard_size": string; "status": "enabled" | "disabled"; };
    "SupportedEncoding": "utf-8-sig" | "utf-8" | "windows-1252";
    "TrendPoint": { "date": string; "denominator": number | null; "null_reason": components["schemas"]["NullReason"] | null; "numerator": number | null; "source_completeness": components["schemas"]["SourceCompleteness"]; "value": number | string | null; "value_state": components["schemas"]["ValueState"]; };
    "TrendSeries": { "key": string; "points": Array<components["schemas"]["TrendPoint"]>; };
    "TypedFieldValueRequest": { "type": "text" | "integer" | "decimal" | "utc_datetime" | "null"; "value": string | number | null; };
    "TypedFieldValueResponse": { "type": "text" | "integer" | "decimal" | "utc_datetime" | "null"; "value": string | number | null; };
    "UndoPublishedMoveRequest": { "expected_source_publication": components["schemas"]["PublicationPointerRequest"]; "expected_target_publication": components["schemas"]["PublicationPointerRequest"]; "reason": string; "restore_source_version_id": number; "restore_target_version_id"?: number | null; "source_dataset_id": number; "target_dataset_id": number; };
    "UndoWorkbenchCellRequest": { "head": components["schemas"]["WorkbenchExpectedHeadRequest"]; "reason"?: string; };
    "UndoablePublishedMoveResponse": { "completed_at": string; "move_command_id": number; "moved_target_version_id": number; "report_type": "business_report" | "return_report"; "restore_source_version_id": number; "restore_target_version_id": number | null; "source_current_publication": components["schemas"]["PublicationPointerSnapshotResponse"]; "source_dataset_id": number; "source_report_date": string; "target_current_publication": components["schemas"]["PublicationPointerSnapshotResponse"]; "target_dataset_id": number; "target_report_date": string; };
    "UpdateUserRequest": { "display_name"?: string | null; "email"?: string | null; "expected_updated_at": string; "new_password"?: string | null; "roles"?: Array<string> | null; "status"?: "active" | "disabled" | "locked" | null; };
    "UploadResponse": { "batch_id": number; "content_reused": boolean; "duplicate": boolean; "raw_file_id": number; "sha256_hex": string; };
    "UserResponse": { "created_at": string; "display_name": string; "email": string | null; "id": number; "last_login_at": string | null; "roles": Array<string>; "status": "active" | "disabled" | "locked"; "updated_at": string; "username": string; };
    "ValidationExpectationRequest": { "data_digest": string; "data_revision": number; "ruleset_version": string; "run_id": number; "version_id": number; };
    "ValidationIssueResponse": { "created_at": string; "details": unknown; "field_name": string | null; "id": number; "message": string; "processed_value": unknown; "requires_note": boolean; "review": components["schemas"]["IssueReviewStateResponse"]; "row_id": number | null; "rule_code": string; "severity": "warning" | "blocking"; "source_value": unknown; };
    "ValidationRunResponse": { "data_digest": string; "data_revision": number; "result": "passed" | "failed" | "error"; "status": "succeeded" | "failed"; "summary": Record<string, unknown>; "validation_run_id": number; "version_id": number; };
    "ValueState": "observed" | "zero" | "missing_report" | "undefined_denominator";
    "VersionDetailResponse": { "children": Array<components["schemas"]["VersionLineageResponse"]>; "created_at": string; "data_revision": number; "dataset_id": number; "dedup_publication_revision": number | null; "draft_pointed_at": string | null; "is_active_draft": boolean; "is_current_publication": boolean; "parents": Array<components["schemas"]["VersionLineageResponse"]>; "publication_revision": number | null; "published_at": string | null; "report_date": string; "report_type": components["schemas"]["ReportType"]; "review_revision": number; "sealed_at": string | null; "status": components["schemas"]["VersionStatus"]; "version_id": number; "version_no": number; "viewer_visible_notes": Array<components["schemas"]["ViewerVisibleNoteResponse"]>; };
    "VersionExpectationRequest": { "data_revision": number; "review_revision": number; "version_id": number; };
    "VersionLineageResponse": { "dataset_id": number; "lineage_ordinal": number; "lineage_type": components["schemas"]["LineageType"]; "report_date": string; "report_type": components["schemas"]["ReportType"]; "status": components["schemas"]["VersionStatus"]; "version_id": number; "version_no": number; };
    "VersionStatus": "draft" | "ready_for_publish" | "published" | "discarded";
    "VersionSummaryResponse": { "created_at": string; "data_revision": number; "dataset_id": number; "dedup_publication_revision": number | null; "draft_pointed_at": string | null; "is_active_draft": boolean; "is_current_publication": boolean; "publication_revision": number | null; "published_at": string | null; "report_date": string; "report_type": components["schemas"]["ReportType"]; "review_revision": number; "sealed_at": string | null; "status": components["schemas"]["VersionStatus"]; "version_id": number; "version_no": number; };
    "ViewerVisibleNoteResponse": { "body": string; "created_at": string; "note_key": string; "revision_number": number; };
    "WorkbenchAction": "upload" | "edit" | "undo" | "validate" | "publish" | "create_revision";
    "WorkbenchCellMutationResponse": { "cell": components["schemas"]["WorkbenchMutationCellResponse"]; "change_id": number; "head": components["schemas"]["WorkbenchMutationHeadResponse"]; "operation_token": string; };
    "WorkbenchCellResponse": { "base": components["schemas"]["CellValue"]; "cell_revision": number; "changed": boolean; "column_id": string; "current": components["schemas"]["CellValue"]; "editable": boolean; };
    "WorkbenchCellValueRequest": { "type": "text" | "integer" | "decimal" | "utc_datetime" | "null"; "value": string | number | null; };
    "WorkbenchChangePageResponse": { "changes": Array<components["schemas"]["WorkbenchChangeResponse"]>; "page": number; "page_size": number; "total_changes": number; "total_pages": number; };
    "WorkbenchChangeResponse": { "actor_user_id": number; "actor_username": string; "after": unknown; "before": unknown; "cell_revision": number; "change_id": number; "column_id": string; "data_revision": number; "ledger_kind": "standard" | "extension"; "occurred_at": string; "operation": string; "reason": string; "row_id": number; "undoes_change_id": number | null; };
    "WorkbenchColumnResponse": { "column_id": string; "display_order": number; "editable": boolean; "is_key": boolean; "participates_in_statistics": boolean; "source_header": string; "standard_field_name": string | null; "value_kind": "text" | "integer" | "decimal" | "utc_datetime"; };
    "WorkbenchExpectedHeadRequest": { "data_revision": number; "dataset_id": number; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; };
    "WorkbenchHeadResponse": { "data_revision": number; "dataset_id": number; "pointed_at": string; "review_revision": number; "ruleset_version": string; "status": "draft" | "ready_for_publish" | "published" | "discarded"; "version_id": number; "version_no": number; };
    "WorkbenchImportResponse": { "batch_id": number; "dataset_id": number | null; "duplicate": boolean; "encoding": components["schemas"]["SupportedEncoding"] | null; "issue_codes": Array<string>; "message": string | null; "report_date": string | null; "report_type": components["schemas"]["ReportType"] | null; "stage": string; "status": "workspace_ready" | "confirmation_required" | "conflict_required" | "duplicate" | "failed" | "processing"; "version_id": number | null; "workspace_url": string | null; };
    "WorkbenchMutationCellResponse": { "base": string | null; "cell_revision": number; "changed": boolean; "column_id": string; "current": string | null; "row_id": number; };
    "WorkbenchMutationHeadResponse": { "data_revision": number; "dataset_id": number; "pointed_at": string; "review_revision": number; "status": "draft" | "ready_for_publish"; "version_id": number; };
    "WorkbenchPaginationResponse": { "page": number; "page_size": number; "total_pages": number; "total_rows": number; };
    "WorkbenchPermissionsResponse": { "can_create_revision": boolean; "can_edit": boolean; "can_publish": boolean; "can_undo": boolean; "can_upload": boolean; "can_validate": boolean; };
    "WorkbenchRevisionResponse": { "data_revision": number; "dataset_id": number; "pointed_at": string; "result_kind": "revision_created" | "existing_revision"; "review_revision": number; "status": "draft" | "ready_for_publish"; "version_id": number; "version_no": number; };
    "WorkbenchRowResponse": { "cells": Array<components["schemas"]["WorkbenchCellResponse"]>; "row_id": number; "row_ordinal": number; "row_state": "active" | "excluded" | "deleted"; };
    "WorkbenchSource": "draft" | "published" | "empty";
    "WorkbenchTabResponse": { "dataset_id"?: number | null; "report_type": components["schemas"]["ReportType"]; "source": components["schemas"]["WorkbenchSource"]; "status"?: "draft" | "ready_for_publish" | "published" | "discarded" | null; "version_id"?: number | null; };
    "WorkbenchValidationSummaryResponse": { "data_revision": number; "is_current": boolean; "result": "passed" | "failed" | "error"; "run_id": number; "status": "succeeded" | "failed"; "summary": Record<string, unknown>; };
    "WorkerConsumerStatusResponse": { "consecutive_failures": number; "consumer_health": "healthy" | "failing" | "unknown" | "not_observed"; "failure_code": string | null; "last_poll_completed_at": string | null; "last_poll_failed_at": string | null; "last_poll_started_at": string | null; "last_poll_succeeded_at": string | null; "queue_name": "return_dedup" | "publication_outbox" | "catalog_export" | "catalog_import"; };
    "WorkerFleetStatusResponse": { "failure_code": string | null; "instances": Array<components["schemas"]["WorkerInstanceStatusResponse"]>; "query_health": "healthy" | "unknown"; "thresholds": components["schemas"]["HeartbeatThresholdsResponse"]; };
    "WorkerInstanceStatusResponse": { "build_id": string; "consumers": Array<components["schemas"]["WorkerConsumerStatusResponse"]>; "heartbeat_age_seconds": number | null; "heartbeat_sequence": number; "heartbeat_status": "online" | "stale" | "offline" | "stopped" | "unknown"; "instance_id": string; "last_heartbeat_at": string | null; "last_result_code": string | null; "lifecycle_status": "running" | "stopped"; "role": string; "supported_queues": Array<"return_dedup" | "publication_outbox" | "catalog_export" | "catalog_import">; };
    "WorkspacePaginationResponse": { "page": number; "page_size": number; "total_pages": number; "total_rows": number; };
    "app__analytics__style_models__SafeSourceRef": { "is_truncated": boolean; "is_unsafe": boolean; "preview": string; "sha256": string; "source_ref_id": string; };
    "app__catalog__source_refs__SafeSourceRef": { "is_truncated": boolean; "is_unsafe": boolean; "preview": string; "sha256": string; "source_ref_id": string; };
  };
}

export type ActiveDraftMoveTargetRequest = components["schemas"]["ActiveDraftMoveTargetRequest"];
export type ActiveDraftReassignmentTargetRequest = components["schemas"]["ActiveDraftReassignmentTargetRequest"];
export type AddRowRequest = components["schemas"]["AddRowRequest"];
export type AdminCommandLookupRequest = components["schemas"]["AdminCommandLookupRequest"];
export type AnalyticsPermissions = components["schemas"]["AnalyticsPermissions"];
export type AnalyticsProvenance = components["schemas"]["AnalyticsProvenance"];
export type AnalyticsReadiness = components["schemas"]["AnalyticsReadiness"];
export type ApiErrorDetail = components["schemas"]["ApiErrorDetail"];
export type ApiErrorResponse = components["schemas"]["ApiErrorResponse"];
export type ApplyDecisionsRequest = components["schemas"]["ApplyDecisionsRequest"];
export type ApproveImportRequest = components["schemas"]["ApproveImportRequest"];
export type AuditEventPageResponse = components["schemas"]["AuditEventPageResponse"];
export type AuditEventResponse = components["schemas"]["AuditEventResponse"];
export type AvailableSeries = components["schemas"]["AvailableSeries"];
export type BackupSnapshotStatus = components["schemas"]["BackupSnapshotStatus"];
export type BatchReviewItemResponse = components["schemas"]["BatchReviewItemResponse"];
export type BatchReviewRunResponse = components["schemas"]["BatchReviewRunResponse"];
export type BatchReviewSummaryResponse = components["schemas"]["BatchReviewSummaryResponse"];
export type CalendarDayReason = components["schemas"]["CalendarDayReason"];
export type CalendarDayResponse = components["schemas"]["CalendarDayResponse"];
export type CalendarDayStatus = components["schemas"]["CalendarDayStatus"];
export type CalendarEntryResponse = components["schemas"]["CalendarEntryResponse"];
export type CalendarStatus = components["schemas"]["CalendarStatus"];
export type CatalogScopePermissionsResponse = components["schemas"]["CatalogScopePermissionsResponse"];
export type CatalogScopeStatusResponse = components["schemas"]["CatalogScopeStatusResponse"];
export type CategoryCreateRequest = components["schemas"]["CategoryCreateRequest"];
export type CategoryUpdateRequest = components["schemas"]["CategoryUpdateRequest"];
export type CellComparisonResponse = components["schemas"]["CellComparisonResponse"];
export type CellValue = components["schemas"]["CellValue"];
export type ChangeDateRequest = components["schemas"]["ChangeDateRequest"];
export type ChangeRowStateRequest = components["schemas"]["ChangeRowStateRequest"];
export type ConfirmCatalogScopeRequest = components["schemas"]["ConfirmCatalogScopeRequest"];
export type ConfirmParseRequest = components["schemas"]["ConfirmParseRequest"];
export type ConfirmRequest = components["schemas"]["ConfirmRequest"];
export type ConfirmWorkbenchImportRequest = components["schemas"]["ConfirmWorkbenchImportRequest"];
export type ConfirmationTotalRequest = components["schemas"]["ConfirmationTotalRequest"];
export type CoverageBlock = components["schemas"]["CoverageBlock"];
export type CoverageStatus = components["schemas"]["CoverageStatus"];
export type CreateCatalogExportRequest = components["schemas"]["CreateCatalogExportRequest"];
export type CreateImportBatchNoteRequest = components["schemas"]["CreateImportBatchNoteRequest"];
export type CreateNoteRequest = components["schemas"]["CreateNoteRequest"];
export type CreatePublishedMoveRequest = components["schemas"]["CreatePublishedMoveRequest"];
export type CreateRevisionRequest = components["schemas"]["CreateRevisionRequest"];
export type CreateSiteConfigVersionRequest = components["schemas"]["CreateSiteConfigVersionRequest"];
export type CreateUserRequest = components["schemas"]["CreateUserRequest"];
export type CreateWorkbenchRevisionRequest = components["schemas"]["CreateWorkbenchRevisionRequest"];
export type CsrfTokenResponse = components["schemas"]["CsrfTokenResponse"];
export type CurrentUserResponse = components["schemas"]["CurrentUserResponse"];
export type DailyLedgerResponse = components["schemas"]["DailyLedgerResponse"];
export type DailyLedgerRow = components["schemas"]["DailyLedgerRow"];
export type DashboardMetric = components["schemas"]["DashboardMetric"];
export type DashboardSummary = components["schemas"]["DashboardSummary"];
export type DateRange = components["schemas"]["DateRange"];
export type DateWorkbenchResponse = components["schemas"]["DateWorkbenchResponse"];
export type DecisionMutationRequest = components["schemas"]["DecisionMutationRequest"];
export type DedupDecisionRequest = components["schemas"]["DedupDecisionRequest"];
export type DedupPayloadResponse = components["schemas"]["DedupPayloadResponse"];
export type DiscardDraftRequest = components["schemas"]["DiscardDraftRequest"];
export type DraftCommandResponse = components["schemas"]["DraftCommandResponse"];
export type DraftHeadResponse = components["schemas"]["DraftHeadResponse"];
export type DraftMutationResponse = components["schemas"]["DraftMutationResponse"];
export type DraftPointerRequest = components["schemas"]["DraftPointerRequest"];
export type DraftWorkspaceHeadResponse = components["schemas"]["DraftWorkspaceHeadResponse"];
export type EmptyMoveTargetRequest = components["schemas"]["EmptyMoveTargetRequest"];
export type EmptyReassignmentTargetRequest = components["schemas"]["EmptyReassignmentTargetRequest"];
export type FactBasis = components["schemas"]["FactBasis"];
export type FieldChangeResponse = components["schemas"]["FieldChangeResponse"];
export type FieldContractResponse = components["schemas"]["FieldContractResponse"];
export type FinalizePublishedMoveRequest = components["schemas"]["FinalizePublishedMoveRequest"];
export type ForceRebuildDraftRequest = components["schemas"]["ForceRebuildDraftRequest"];
export type FromExportImportRequest = components["schemas"]["FromExportImportRequest"];
export type FullValidationResponse = components["schemas"]["FullValidationResponse"];
export type HeartbeatThresholdsResponse = components["schemas"]["HeartbeatThresholdsResponse"];
export type ImportBatchNoteResponse = components["schemas"]["ImportBatchNoteResponse"];
export type ImportReasonRequest = components["schemas"]["ImportReasonRequest"];
export type ImportRevisionRequest = components["schemas"]["ImportRevisionRequest"];
export type InspectionResponse = components["schemas"]["InspectionResponse"];
export type IssueReviewStateResponse = components["schemas"]["IssueReviewStateResponse"];
export type JsonValue = components["schemas"]["JsonValue"];
export type LatestNoteResponse = components["schemas"]["LatestNoteResponse"];
export type LedgerReason = components["schemas"]["LedgerReason"];
export type LineageType = components["schemas"]["LineageType"];
export type LoginRequest = components["schemas"]["LoginRequest"];
export type LoginResponse = components["schemas"]["LoginResponse"];
export type MaintenanceStatusResponse = components["schemas"]["MaintenanceStatusResponse"];
export type MaintenanceWriteLockStatus = components["schemas"]["MaintenanceWriteLockStatus"];
export type MarkReadyRequest = components["schemas"]["MarkReadyRequest"];
export type MaterializeBaselineRequest = components["schemas"]["MaterializeBaselineRequest"];
export type MergeConflictPreviewResponse = components["schemas"]["MergeConflictPreviewResponse"];
export type MergeDecisionRequest = components["schemas"]["MergeDecisionRequest"];
export type MergePreviewResponse = components["schemas"]["MergePreviewResponse"];
export type MetricEvaluability = components["schemas"]["MetricEvaluability"];
export type MetricName = components["schemas"]["MetricName"];
export type MetricStatus = components["schemas"]["MetricStatus"];
export type MetricTotals = components["schemas"]["MetricTotals"];
export type MetricValue = components["schemas"]["MetricValue"];
export type MetricValues = components["schemas"]["MetricValues"];
export type MoveTargetRequest = components["schemas"]["MoveTargetRequest"];
export type NullReason = components["schemas"]["NullReason"];
export type OutboxStatus = components["schemas"]["OutboxStatus"];
export type OverallLedgerStatus = components["schemas"]["OverallLedgerStatus"];
export type ParentRestoreOptionResponse = components["schemas"]["ParentRestoreOptionResponse"];
export type PreflightRequest = components["schemas"]["PreflightRequest"];
export type ProductCardResponse = components["schemas"]["ProductCardResponse"];
export type ProductCardSummary = components["schemas"]["ProductCardSummary"];
export type ProductDashboard = components["schemas"]["ProductDashboard"];
export type ProductLedgerResponse = components["schemas"]["ProductLedgerResponse"];
export type ProductLedgerRow = components["schemas"]["ProductLedgerRow"];
export type ProductLedgerSort = components["schemas"]["ProductLedgerSort"];
export type ProductMetric = components["schemas"]["ProductMetric"];
export type ProductNameStatus = components["schemas"]["ProductNameStatus"];
export type ProductRowKind = components["schemas"]["ProductRowKind"];
export type ProductTrendPoint = components["schemas"]["ProductTrendPoint"];
export type ProductVariant = components["schemas"]["ProductVariant"];
export type PublicationCommandResponse = components["schemas"]["PublicationCommandResponse"];
export type PublicationConfirmationRequest = components["schemas"]["PublicationConfirmationRequest"];
export type PublicationDay = components["schemas"]["PublicationDay"];
export type PublicationPointerRequest = components["schemas"]["PublicationPointerRequest"];
export type PublicationPointerResponse = components["schemas"]["PublicationPointerResponse"];
export type PublicationPointerSnapshotResponse = components["schemas"]["PublicationPointerSnapshotResponse"];
export type PublicationReference = components["schemas"]["PublicationReference"];
export type PublicationRefs = components["schemas"]["PublicationRefs"];
export type PublicationTransitionResponse = components["schemas"]["PublicationTransitionResponse"];
export type PublishRequest = components["schemas"]["PublishRequest"];
export type PublishedDateSummary = components["schemas"]["PublishedDateSummary"];
export type PublishedDetailCell = components["schemas"]["PublishedDetailCell"];
export type PublishedDetailColumn = components["schemas"]["PublishedDetailColumn"];
export type PublishedDetailPagination = components["schemas"]["PublishedDetailPagination"];
export type PublishedDetailPermissions = components["schemas"]["PublishedDetailPermissions"];
export type PublishedDetailRange = components["schemas"]["PublishedDetailRange"];
export type PublishedDetailRow = components["schemas"]["PublishedDetailRow"];
export type PublishedMoveContextResponse = components["schemas"]["PublishedMoveContextResponse"];
export type PublishedMoveTargetRequest = components["schemas"]["PublishedMoveTargetRequest"];
export type PublishedRangeResponse = components["schemas"]["PublishedRangeResponse"];
export type PublishedReassignmentTargetRequest = components["schemas"]["PublishedReassignmentTargetRequest"];
export type PublishedRowsResponse = components["schemas"]["PublishedRowsResponse"];
export type PublishedSummaryResponse = components["schemas"]["PublishedSummaryResponse"];
export type QueueCapabilitiesResponse = components["schemas"]["QueueCapabilitiesResponse"];
export type QueueStatusResponse = components["schemas"]["QueueStatusResponse"];
export type RawFilePreviewResponse = components["schemas"]["RawFilePreviewResponse"];
export type ReassignDraftDateRequest = components["schemas"]["ReassignDraftDateRequest"];
export type ReassignmentTargetRequest = components["schemas"]["ReassignmentTargetRequest"];
export type RebaseImportRequest = components["schemas"]["RebaseImportRequest"];
export type ReportLedgerStatus = components["schemas"]["ReportLedgerStatus"];
export type ReportStatus = components["schemas"]["ReportStatus"];
export type ReportType = components["schemas"]["ReportType"];
export type RestoreCatalogVersionRequest = components["schemas"]["RestoreCatalogVersionRequest"];
export type RestoreFieldRequest = components["schemas"]["RestoreFieldRequest"];
export type RestoreVerificationStatus = components["schemas"]["RestoreVerificationStatus"];
export type ResumeCatalogExportRequest = components["schemas"]["ResumeCatalogExportRequest"];
export type ResumeImportRequest = components["schemas"]["ResumeImportRequest"];
export type ReturnBasis = components["schemas"]["ReturnBasis"];
export type ReturnBreakdown = components["schemas"]["ReturnBreakdown"];
export type ReturnDashboard = components["schemas"]["ReturnDashboard"];
export type ReturnDedupDecisionRequest = components["schemas"]["ReturnDedupDecisionRequest"];
export type ReturnDedupDecisionResponse = components["schemas"]["ReturnDedupDecisionResponse"];
export type ReturnDedupGroupMemberResponse = components["schemas"]["ReturnDedupGroupMemberResponse"];
export type ReturnDedupGroupPageResponse = components["schemas"]["ReturnDedupGroupPageResponse"];
export type ReturnDedupGroupResponse = components["schemas"]["ReturnDedupGroupResponse"];
export type ReturnDedupRetryRequest = components["schemas"]["ReturnDedupRetryRequest"];
export type ReturnDedupStagingRequest = components["schemas"]["ReturnDedupStagingRequest"];
export type ReturnDedupStagingResponse = components["schemas"]["ReturnDedupStagingResponse"];
export type ReturnInitializationPreview = components["schemas"]["ReturnInitializationPreview"];
export type ReturnInitializationRequest = components["schemas"]["ReturnInitializationRequest"];
export type ReturnToDraftRequest = components["schemas"]["ReturnToDraftRequest"];
export type ReviewIssueRequest = components["schemas"]["ReviewIssueRequest"];
export type ReviewRowResponse = components["schemas"]["ReviewRowResponse"];
export type ReviewWorkspaceResponse = components["schemas"]["ReviewWorkspaceResponse"];
export type ReviseImportBatchNoteRequest = components["schemas"]["ReviseImportBatchNoteRequest"];
export type ReviseNoteRequest = components["schemas"]["ReviseNoteRequest"];
export type RevisionRequest = components["schemas"]["RevisionRequest"];
export type RoleResponse = components["schemas"]["RoleResponse"];
export type RollbackRequest = components["schemas"]["RollbackRequest"];
export type RowChangeResponse = components["schemas"]["RowChangeResponse"];
export type RunValidationRequest = components["schemas"]["RunValidationRequest"];
export type SeriesDimension = components["schemas"]["SeriesDimension"];
export type SetFieldRequest = components["schemas"]["SetFieldRequest"];
export type SetWorkbenchCellRequest = components["schemas"]["SetWorkbenchCellRequest"];
export type SiteConfigVersionResponse = components["schemas"]["SiteConfigVersionResponse"];
export type SiteConfigurationReference = components["schemas"]["SiteConfigurationReference"];
export type SiteContextResponse = components["schemas"]["SiteContextResponse"];
export type SiteCoverage = components["schemas"]["SiteCoverage"];
export type SiteReconciliation = components["schemas"]["SiteReconciliation"];
export type SortDirection = components["schemas"]["SortDirection"];
export type SourceBatchResponse = components["schemas"]["SourceBatchResponse"];
export type SourceCompleteness = components["schemas"]["SourceCompleteness"];
export type SourceReportCoverage = components["schemas"]["SourceReportCoverage"];
export type SourceRestoreOptionResponse = components["schemas"]["SourceRestoreOptionResponse"];
export type StyleCardResponse = components["schemas"]["StyleCardResponse"];
export type StyleChangeApproveRequest = components["schemas"]["StyleChangeApproveRequest"];
export type StyleChangeDraftRequest = components["schemas"]["StyleChangeDraftRequest"];
export type StyleIdentity = components["schemas"]["StyleIdentity"];
export type StyleLedgerResponse = components["schemas"]["StyleLedgerResponse"];
export type StyleLedgerRow = components["schemas"]["StyleLedgerRow"];
export type StyleReconciliation = components["schemas"]["StyleReconciliation"];
export type StyleSummary = components["schemas"]["StyleSummary"];
export type StyleVariant = components["schemas"]["StyleVariant"];
export type SupportedEncoding = components["schemas"]["SupportedEncoding"];
export type TrendPoint = components["schemas"]["TrendPoint"];
export type TrendSeries = components["schemas"]["TrendSeries"];
export type TypedFieldValueRequest = components["schemas"]["TypedFieldValueRequest"];
export type TypedFieldValueResponse = components["schemas"]["TypedFieldValueResponse"];
export type UndoPublishedMoveRequest = components["schemas"]["UndoPublishedMoveRequest"];
export type UndoWorkbenchCellRequest = components["schemas"]["UndoWorkbenchCellRequest"];
export type UndoablePublishedMoveResponse = components["schemas"]["UndoablePublishedMoveResponse"];
export type UpdateUserRequest = components["schemas"]["UpdateUserRequest"];
export type UploadResponse = components["schemas"]["UploadResponse"];
export type UserResponse = components["schemas"]["UserResponse"];
export type ValidationExpectationRequest = components["schemas"]["ValidationExpectationRequest"];
export type ValidationIssueResponse = components["schemas"]["ValidationIssueResponse"];
export type ValidationRunResponse = components["schemas"]["ValidationRunResponse"];
export type ValueState = components["schemas"]["ValueState"];
export type VersionDetailResponse = components["schemas"]["VersionDetailResponse"];
export type VersionExpectationRequest = components["schemas"]["VersionExpectationRequest"];
export type VersionLineageResponse = components["schemas"]["VersionLineageResponse"];
export type VersionStatus = components["schemas"]["VersionStatus"];
export type VersionSummaryResponse = components["schemas"]["VersionSummaryResponse"];
export type ViewerVisibleNoteResponse = components["schemas"]["ViewerVisibleNoteResponse"];
export type WorkbenchAction = components["schemas"]["WorkbenchAction"];
export type WorkbenchCellMutationResponse = components["schemas"]["WorkbenchCellMutationResponse"];
export type WorkbenchCellResponse = components["schemas"]["WorkbenchCellResponse"];
export type WorkbenchCellValueRequest = components["schemas"]["WorkbenchCellValueRequest"];
export type WorkbenchChangePageResponse = components["schemas"]["WorkbenchChangePageResponse"];
export type WorkbenchChangeResponse = components["schemas"]["WorkbenchChangeResponse"];
export type WorkbenchColumnResponse = components["schemas"]["WorkbenchColumnResponse"];
export type WorkbenchExpectedHeadRequest = components["schemas"]["WorkbenchExpectedHeadRequest"];
export type WorkbenchHeadResponse = components["schemas"]["WorkbenchHeadResponse"];
export type WorkbenchImportResponse = components["schemas"]["WorkbenchImportResponse"];
export type WorkbenchMutationCellResponse = components["schemas"]["WorkbenchMutationCellResponse"];
export type WorkbenchMutationHeadResponse = components["schemas"]["WorkbenchMutationHeadResponse"];
export type WorkbenchPaginationResponse = components["schemas"]["WorkbenchPaginationResponse"];
export type WorkbenchPermissionsResponse = components["schemas"]["WorkbenchPermissionsResponse"];
export type WorkbenchRevisionResponse = components["schemas"]["WorkbenchRevisionResponse"];
export type WorkbenchRowResponse = components["schemas"]["WorkbenchRowResponse"];
export type WorkbenchSource = components["schemas"]["WorkbenchSource"];
export type WorkbenchTabResponse = components["schemas"]["WorkbenchTabResponse"];
export type WorkbenchValidationSummaryResponse = components["schemas"]["WorkbenchValidationSummaryResponse"];
export type WorkerConsumerStatusResponse = components["schemas"]["WorkerConsumerStatusResponse"];
export type WorkerFleetStatusResponse = components["schemas"]["WorkerFleetStatusResponse"];
export type WorkerInstanceStatusResponse = components["schemas"]["WorkerInstanceStatusResponse"];
export type WorkspacePaginationResponse = components["schemas"]["WorkspacePaginationResponse"];
export type app__analytics__style_models__SafeSourceRef = components["schemas"]["app__analytics__style_models__SafeSourceRef"];
export type app__catalog__source_refs__SafeSourceRef = components["schemas"]["app__catalog__source_refs__SafeSourceRef"];

export const API_OPERATIONS = {
  "list_audit_events_api_admin_audit_events_get": { method: "GET", path: "/api/admin/audit-events" },
  "rollback_dataset_api_admin_datasets__dataset_id__rollback_post": { method: "POST", path: "/api/admin/datasets/{dataset_id}/rollback" },
  "force_rebuild_draft_api_admin_drafts__version_id__force_rebuild_post": { method: "POST", path: "/api/admin/drafts/{version_id}/force-rebuild" },
  "maintenance_status_api_admin_maintenance_get": { method: "GET", path: "/api/admin/maintenance" },
  "list_undoable_published_moves_api_admin_published_moves_undoable_get": { method: "GET", path: "/api/admin/published-moves/undoable" },
  "undo_published_move_api_admin_published_moves__move_command_id__undo_post": { method: "POST", path: "/api/admin/published-moves/{move_command_id}/undo" },
  "finalize_published_move_api_admin_published_moves__move_revision_operation_token__finalize_post": { method: "POST", path: "/api/admin/published-moves/{move_revision_operation_token}/finalize" },
  "list_roles_api_admin_roles_get": { method: "GET", path: "/api/admin/roles" },
  "list_site_config_versions_api_admin_site_config_versions_get": { method: "GET", path: "/api/admin/site-config-versions" },
  "create_site_config_version_api_admin_site_config_versions_post": { method: "POST", path: "/api/admin/site-config-versions" },
  "list_users_api_admin_users_get": { method: "GET", path: "/api/admin/users" },
  "create_user_api_admin_users_post": { method: "POST", path: "/api/admin/users" },
  "update_user_api_admin_users__user_id__patch": { method: "PATCH", path: "/api/admin/users/{user_id}" },
  "create_published_move_revision_api_admin_versions__version_id__move_date_post": { method: "POST", path: "/api/admin/versions/{version_id}/move-date" },
  "issue_login_csrf_token_api_auth_csrf_get": { method: "GET", path: "/api/auth/csrf" },
  "login_api_auth_login_post": { method: "POST", path: "/api/auth/login" },
  "logout_api_auth_logout_post": { method: "POST", path: "/api/auth/logout" },
  "current_user_api_auth_me_get": { method: "GET", path: "/api/auth/me" },
  "admin_lookup_catalog_command_api_catalog_admin_commands__operation_token__lookup_post": { method: "POST", path: "/api/catalog/admin/commands/{operation_token}/lookup" },
  "list_categories_api_catalog_categories_get": { method: "GET", path: "/api/catalog/categories" },
  "create_category_api_catalog_categories_post": { method: "POST", path: "/api/catalog/categories" },
  "update_category_api_catalog_categories__category_id__put": { method: "PUT", path: "/api/catalog/categories/{category_id}" },
  "get_catalog_command_api_catalog_commands__operation_token__get": { method: "GET", path: "/api/catalog/commands/{operation_token}" },
  "list_catalog_evidence_api_catalog_evidence_get": { method: "GET", path: "/api/catalog/evidence" },
  "create_catalog_export_api_catalog_exports_post": { method: "POST", path: "/api/catalog/exports" },
  "get_latest_catalog_export_api_catalog_exports_latest_get": { method: "GET", path: "/api/catalog/exports/latest" },
  "get_catalog_export_api_catalog_exports__export_id__get": { method: "GET", path: "/api/catalog/exports/{export_id}" },
  "download_catalog_export_api_catalog_exports__export_id__file_get": { method: "GET", path: "/api/catalog/exports/{export_id}/file" },
  "resume_catalog_export_api_catalog_exports__export_id__resume_post": { method: "POST", path: "/api/catalog/exports/{export_id}/resume" },
  "list_catalog_imports_api_catalog_imports_get": { method: "GET", path: "/api/catalog/imports" },
  "upload_catalog_import_api_catalog_imports_post": { method: "POST", path: "/api/catalog/imports" },
  "create_import_from_export_api_catalog_imports_from_export_post": { method: "POST", path: "/api/catalog/imports/from-export" },
  "get_catalog_import_api_catalog_imports__import_id__get": { method: "GET", path: "/api/catalog/imports/{import_id}" },
  "preview_catalog_import_api_catalog_imports__import_id__approval_preview_post": { method: "POST", path: "/api/catalog/imports/{import_id}/approval-preview" },
  "approve_catalog_import_api_catalog_imports__import_id__approve_post": { method: "POST", path: "/api/catalog/imports/{import_id}/approve" },
  "apply_catalog_decisions_api_catalog_imports__import_id__decisions_post": { method: "POST", path: "/api/catalog/imports/{import_id}/decisions" },
  "download_catalog_import_file_api_catalog_imports__import_id__file_get": { method: "GET", path: "/api/catalog/imports/{import_id}/file" },
  "get_catalog_identity_owners_api_catalog_imports__import_id__identity_owners__row_key__get": { method: "GET", path: "/api/catalog/imports/{import_id}/identity-owners/{row_key}" },
  "rebase_catalog_import_api_catalog_imports__import_id__rebase_post": { method: "POST", path: "/api/catalog/imports/{import_id}/rebase" },
  "reject_catalog_import_api_catalog_imports__import_id__reject_post": { method: "POST", path: "/api/catalog/imports/{import_id}/reject" },
  "resume_catalog_import_api_catalog_imports__import_id__resume_post": { method: "POST", path: "/api/catalog/imports/{import_id}/resume" },
  "get_catalog_import_rows_api_catalog_imports__import_id__rows__section__get": { method: "GET", path: "/api/catalog/imports/{import_id}/rows/{section}" },
  "reveal_draft_source_api_catalog_imports__import_id__source_identifiers__source_ref_id__get": { method: "GET", path: "/api/catalog/imports/{import_id}/source-identifiers/{source_ref_id}" },
  "submit_catalog_import_api_catalog_imports__import_id__submit_post": { method: "POST", path: "/api/catalog/imports/{import_id}/submit" },
  "validate_catalog_import_api_catalog_imports__import_id__validate_post": { method: "POST", path: "/api/catalog/imports/{import_id}/validate" },
  "withdraw_catalog_import_api_catalog_imports__import_id__withdraw_post": { method: "POST", path: "/api/catalog/imports/{import_id}/withdraw" },
  "list_return_dedup_groups_api_catalog_return_dedup_groups_get": { method: "GET", path: "/api/catalog/return-dedup/groups" },
  "decide_return_dedup_group_api_catalog_return_dedup_groups__group_id__decision_post": { method: "POST", path: "/api/catalog/return-dedup/groups/{group_id}/decision" },
  "reveal_approved_source_api_catalog_source_identifiers__source_ref_id__get": { method: "GET", path: "/api/catalog/source-identifiers/{source_ref_id}" },
  "get_catalog_scope_api_catalog_source_scope_get": { method: "GET", path: "/api/catalog/source-scope" },
  "confirm_catalog_scope_api_catalog_source_scope_confirm_post": { method: "POST", path: "/api/catalog/source-scope/confirm" },
  "preview_style_change_api_catalog_style_change_drafts__draft_id__get": { method: "GET", path: "/api/catalog/style-change-drafts/{draft_id}" },
  "approve_style_change_api_catalog_style_change_drafts__draft_id__approve_post": { method: "POST", path: "/api/catalog/style-change-drafts/{draft_id}/approve" },
  "list_catalog_styles_api_catalog_styles_get": { method: "GET", path: "/api/catalog/styles" },
  "get_catalog_style_api_catalog_styles__style_id__get": { method: "GET", path: "/api/catalog/styles/{style_id}" },
  "create_style_change_api_catalog_styles__style_id__change_drafts_post": { method: "POST", path: "/api/catalog/styles/{style_id}/change-drafts" },
  "list_catalog_style_pending_items_api_catalog_styles__style_id__pending_items_get": { method: "GET", path: "/api/catalog/styles/{style_id}/pending-items" },
  "list_catalog_unmatched_api_catalog_unmatched_get": { method: "GET", path: "/api/catalog/unmatched" },
  "list_catalog_variant_evidence_api_catalog_variants__sku_id__evidence_get": { method: "GET", path: "/api/catalog/variants/{sku_id}/evidence" },
  "list_catalog_variant_seller_skus_api_catalog_variants__sku_id__seller_skus_get": { method: "GET", path: "/api/catalog/variants/{sku_id}/seller-skus" },
  "list_catalog_versions_api_catalog_versions_get": { method: "GET", path: "/api/catalog/versions" },
  "get_catalog_version_diff_api_catalog_versions__version_id__diff_get": { method: "GET", path: "/api/catalog/versions/{version_id}/diff" },
  "restore_catalog_version_api_catalog_versions__version_id__restore_post": { method: "POST", path: "/api/catalog/versions/{version_id}/restore" },
  "daily_ledger_api_dashboard_daily_ledger_get": { method: "GET", path: "/api/dashboard/daily-ledger" },
  "product_card_api_dashboard_product_card__style_code__get": { method: "GET", path: "/api/dashboard/product-card/{style_code}" },
  "product_ledger_api_dashboard_product_ledger_get": { method: "GET", path: "/api/dashboard/product-ledger" },
  "products_api_dashboard_products_get": { method: "GET", path: "/api/dashboard/products" },
  "returns_api_dashboard_returns_get": { method: "GET", path: "/api/dashboard/returns" },
  "style_ledger_api_dashboard_style_ledger_get": { method: "GET", path: "/api/dashboard/style-ledger" },
  "style_readiness_api_dashboard_style_readiness_get": { method: "GET", path: "/api/dashboard/style-readiness" },
  "style_card_api_dashboard_styles__style_id__card_get": { method: "GET", path: "/api/dashboard/styles/{style_id}/card" },
  "summary_api_dashboard_summary_get": { method: "GET", path: "/api/dashboard/summary" },
  "list_calendar_entries_api_data_calendar_get": { method: "GET", path: "/api/data-calendar" },
  "list_calendar_days_api_data_calendar_days_get": { method: "GET", path: "/api/data-calendar/days" },
  "get_site_context_api_data_calendar_site_context_get": { method: "GET", path: "/api/data-calendar/site-context" },
  "materialize_baseline_api_datasets_materialize_post": { method: "POST", path: "/api/datasets/materialize" },
  "preview_merge_conflicts_api_datasets_merge_preview_get": { method: "GET", path: "/api/datasets/merge-preview" },
  "publish_dataset_api_datasets__dataset_id__publish_post": { method: "POST", path: "/api/datasets/{dataset_id}/publish" },
  "create_revision_api_datasets__dataset_id__revisions_post": { method: "POST", path: "/api/datasets/{dataset_id}/revisions" },
  "get_draft_head_api_drafts__version_id__get": { method: "GET", path: "/api/drafts/{version_id}" },
  "discard_draft_api_drafts__version_id__discard_post": { method: "POST", path: "/api/drafts/{version_id}/discard" },
  "set_field_api_drafts__version_id__fields_post": { method: "POST", path: "/api/drafts/{version_id}/fields" },
  "restore_field_api_drafts__version_id__fields__field_name__restore_post": { method: "POST", path: "/api/drafts/{version_id}/fields/{field_name}/restore" },
  "review_issue_api_drafts__version_id__issues__issue_id__review_post": { method: "POST", path: "/api/drafts/{version_id}/issues/{issue_id}/review" },
  "mark_ready_api_drafts__version_id__mark_ready_post": { method: "POST", path: "/api/drafts/{version_id}/mark-ready" },
  "create_note_api_drafts__version_id__notes_post": { method: "POST", path: "/api/drafts/{version_id}/notes" },
  "revise_note_api_drafts__version_id__notes__note_key__revisions_post": { method: "POST", path: "/api/drafts/{version_id}/notes/{note_key}/revisions" },
  "reassign_draft_date_api_drafts__version_id__reassign_date_post": { method: "POST", path: "/api/drafts/{version_id}/reassign-date" },
  "return_to_draft_api_drafts__version_id__return_to_draft_post": { method: "POST", path: "/api/drafts/{version_id}/return-to-draft" },
  "get_review_workspace_api_drafts__version_id__review_workspace_get": { method: "GET", path: "/api/drafts/{version_id}/review-workspace" },
  "add_row_api_drafts__version_id__rows_post": { method: "POST", path: "/api/drafts/{version_id}/rows" },
  "change_row_state_api_drafts__version_id__rows__row_id__state_post": { method: "POST", path: "/api/drafts/{version_id}/rows/{row_id}/state" },
  "health_live_api_health_live_get": { method: "GET", path: "/api/health/live" },
  "health_ready_api_health_ready_get": { method: "GET", path: "/api/health/ready" },
  "upload_import_api_imports_post": { method: "POST", path: "/api/imports" },
  "list_batch_reviews_api_imports_batch_reviews_get": { method: "GET", path: "/api/imports/batch-reviews" },
  "create_preflight_api_imports_batch_reviews_preflight_post": { method: "POST", path: "/api/imports/batch-reviews/preflight" },
  "get_batch_review_api_imports_batch_reviews__run_id__get": { method: "GET", path: "/api/imports/batch-reviews/{run_id}" },
  "confirm_batch_review_api_imports_batch_reviews__run_id__confirm_post": { method: "POST", path: "/api/imports/batch-reviews/{run_id}/confirm" },
  "advance_batch_review_item_api_imports_batch_reviews__run_id__items__item_id__advance_post": { method: "POST", path: "/api/imports/batch-reviews/{run_id}/items/{item_id}/advance" },
  "retry_batch_review_item_api_imports_batch_reviews__run_id__items__item_id__retry_post": { method: "POST", path: "/api/imports/batch-reviews/{run_id}/items/{item_id}/retry" },
  "pause_batch_review_api_imports_batch_reviews__run_id__pause_post": { method: "POST", path: "/api/imports/batch-reviews/{run_id}/pause" },
  "resume_batch_review_api_imports_batch_reviews__run_id__resume_post": { method: "POST", path: "/api/imports/batch-reviews/{run_id}/resume" },
  "change_import_date_api_imports__batch_id__change_date_post": { method: "POST", path: "/api/imports/{batch_id}/change-date" },
  "confirm_parse_api_imports__batch_id__confirm_parse_post": { method: "POST", path: "/api/imports/{batch_id}/confirm-parse" },
  "inspect_import_api_imports__batch_id__inspect_post": { method: "POST", path: "/api/imports/{batch_id}/inspect" },
  "list_import_batch_notes_api_imports__batch_id__notes_get": { method: "GET", path: "/api/imports/{batch_id}/notes" },
  "create_import_batch_note_api_imports__batch_id__notes_post": { method: "POST", path: "/api/imports/{batch_id}/notes" },
  "revise_import_batch_note_api_imports__batch_id__notes__note_key__revisions_post": { method: "POST", path: "/api/imports/{batch_id}/notes/{note_key}/revisions" },
  "download_raw_file_api_imports__batch_id__raw_file_get": { method: "GET", path: "/api/imports/{batch_id}/raw-file" },
  "preview_raw_file_api_imports__batch_id__raw_file_preview_get": { method: "GET", path: "/api/imports/{batch_id}/raw-file/preview" },
  "create_return_dedup_staging_api_publications_return_dedup_staging_post": { method: "POST", path: "/api/publications/return-dedup-staging" },
  "get_return_dedup_staging_api_publications_return_dedup_staging__job_id__get": { method: "GET", path: "/api/publications/return-dedup-staging/{job_id}" },
  "retry_return_dedup_staging_api_publications_return_dedup_staging__job_id__retry_post": { method: "POST", path: "/api/publications/return-dedup-staging/{job_id}/retry" },
  "preview_return_initialization_api_publications_return_initialization_get": { method: "GET", path: "/api/publications/return-initialization" },
  "initialize_returns_api_publications_return_initialization_post": { method: "POST", path: "/api/publications/return-initialization" },
  "export_published_details_api_published_details_export_csv_get": { method: "GET", path: "/api/published-details/export.csv" },
  "published_details_range_api_published_details_range_get": { method: "GET", path: "/api/published-details/range" },
  "published_detail_rows_api_published_details_rows_get": { method: "GET", path: "/api/published-details/rows" },
  "published_detail_summaries_api_published_details_summaries_get": { method: "GET", path: "/api/published-details/summaries" },
  "run_validation_api_validation_runs__version_id__post": { method: "POST", path: "/api/validation-runs/{version_id}" },
  "list_versions_api_versions_get": { method: "GET", path: "/api/versions" },
  "get_version_api_versions__version_id__get": { method: "GET", path: "/api/versions/{version_id}" },
  "get_version_rows_api_versions__version_id__rows_get": { method: "GET", path: "/api/versions/{version_id}/rows" },
  "get_date_workbench_api_workbench_dates__report_date__get": { method: "GET", path: "/api/workbench/dates/{report_date}" },
  "create_workbench_revision_api_workbench_dates__report_date___report_type__revision_post": { method: "POST", path: "/api/workbench/dates/{report_date}/{report_type}/revision" },
  "upload_workbench_import_api_workbench_imports_post": { method: "POST", path: "/api/workbench/imports" },
  "list_pending_workbench_imports_api_workbench_imports_pending_get": { method: "GET", path: "/api/workbench/imports/pending" },
  "get_workbench_import_api_workbench_imports__batch_id__get": { method: "GET", path: "/api/workbench/imports/{batch_id}" },
  "confirm_workbench_import_api_workbench_imports__batch_id__confirm_post": { method: "POST", path: "/api/workbench/imports/{batch_id}/confirm" },
  "get_workbench_changes_api_workbench_versions__version_id__changes_get": { method: "GET", path: "/api/workbench/versions/{version_id}/changes" },
  "set_workbench_cell_api_workbench_versions__version_id__rows__row_id__cells__column_id__patch": { method: "PATCH", path: "/api/workbench/versions/{version_id}/rows/{row_id}/cells/{column_id}" },
  "undo_workbench_cell_api_workbench_versions__version_id__undo_post": { method: "POST", path: "/api/workbench/versions/{version_id}/undo" },
} as const;

export interface operations {
  "list_audit_events_api_admin_audit_events_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "limit"?: number; "offset"?: number; "event_type"?: string | null; "actor_user_id"?: number | null; "site_id"?: number | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["AuditEventPageResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "rollback_dataset_api_admin_datasets__dataset_id__rollback_post": {
    security: "SessionCookie";
    path: { "dataset_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RollbackRequest"];
    responses: {
      200: components["schemas"]["PublicationCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "force_rebuild_draft_api_admin_drafts__version_id__force_rebuild_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ForceRebuildDraftRequest"];
    responses: {
      201: components["schemas"]["DraftMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "maintenance_status_api_admin_maintenance_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["MaintenanceStatusResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_undoable_published_moves_api_admin_published_moves_undoable_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["UndoablePublishedMoveResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "undo_published_move_api_admin_published_moves__move_command_id__undo_post": {
    security: "SessionCookie";
    path: { "move_command_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["UndoPublishedMoveRequest"];
    responses: {
      200: components["schemas"]["PublicationCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "finalize_published_move_api_admin_published_moves__move_revision_operation_token__finalize_post": {
    security: "SessionCookie";
    path: { "move_revision_operation_token": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["FinalizePublishedMoveRequest"];
    responses: {
      200: components["schemas"]["PublicationCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_roles_api_admin_roles_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["RoleResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_site_config_versions_api_admin_site_config_versions_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "site_id"?: number | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["SiteConfigVersionResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_site_config_version_api_admin_site_config_versions_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateSiteConfigVersionRequest"];
    responses: {
      201: components["schemas"]["SiteConfigVersionResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_users_api_admin_users_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["UserResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_user_api_admin_users_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateUserRequest"];
    responses: {
      201: components["schemas"]["UserResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "update_user_api_admin_users__user_id__patch": {
    security: "SessionCookie";
    path: { "user_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["UpdateUserRequest"];
    responses: {
      200: components["schemas"]["UserResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_published_move_revision_api_admin_versions__version_id__move_date_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreatePublishedMoveRequest"];
    responses: {
      201: components["schemas"]["DraftCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "issue_login_csrf_token_api_auth_csrf_get": {
    security: "public";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["CsrfTokenResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "login_api_auth_login_post": {
    security: "public";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["LoginRequest"];
    responses: {
      200: components["schemas"]["LoginResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "logout_api_auth_logout_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "X-CSRF-Token"?: string | null; };
    requestBody: never;
    responses: {
      204: void;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "current_user_api_auth_me_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["CurrentUserResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "admin_lookup_catalog_command_api_catalog_admin_commands__operation_token__lookup_post": {
    security: "SessionCookie";
    path: { "operation_token": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["AdminCommandLookupRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_categories_api_catalog_categories_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_category_api_catalog_categories_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CategoryCreateRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "update_category_api_catalog_categories__category_id__put": {
    security: "SessionCookie";
    path: { "category_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CategoryUpdateRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_command_api_catalog_commands__operation_token__get": {
    security: "SessionCookie";
    path: { "operation_token": string; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_evidence_api_catalog_evidence_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "version_id"?: number | null; "import_id"?: number | null; "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_catalog_export_api_catalog_exports_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateCatalogExportRequest"];
    responses: {
      202: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_latest_catalog_export_api_catalog_exports_latest_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_export_api_catalog_exports__export_id__get": {
    security: "SessionCookie";
    path: { "export_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "download_catalog_export_api_catalog_exports__export_id__file_get": {
    security: "SessionCookie";
    path: { "export_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "resume_catalog_export_api_catalog_exports__export_id__resume_post": {
    security: "SessionCookie";
    path: { "export_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ResumeCatalogExportRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_imports_api_catalog_imports_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "page"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "upload_catalog_import_api_catalog_imports_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-Original-Filename": string; "Content-Length": string; "X-CSRF-Token"?: string | null; };
    requestBody: never;
    responses: {
      202: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_import_from_export_api_catalog_imports_from_export_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["FromExportImportRequest"];
    responses: {
      201: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_import_api_catalog_imports__import_id__get": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "preview_catalog_import_api_catalog_imports__import_id__approval_preview_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ImportRevisionRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "approve_catalog_import_api_catalog_imports__import_id__approve_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ApproveImportRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "apply_catalog_decisions_api_catalog_imports__import_id__decisions_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ApplyDecisionsRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "download_catalog_import_file_api_catalog_imports__import_id__file_get": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_identity_owners_api_catalog_imports__import_id__identity_owners__row_key__get": {
    security: "SessionCookie";
    path: { "import_id": number; "row_key": string; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "rebase_catalog_import_api_catalog_imports__import_id__rebase_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RebaseImportRequest"];
    responses: {
      201: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "reject_catalog_import_api_catalog_imports__import_id__reject_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ImportReasonRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "resume_catalog_import_api_catalog_imports__import_id__resume_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ResumeImportRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_import_rows_api_catalog_imports__import_id__rows__section__get": {
    security: "SessionCookie";
    path: { "import_id": number; "section": "styles" | "skus" | "mappings" | "exceptions" | "evidence"; };
    query: { "page"?: number; "page_size"?: number; "workflow_revision"?: number | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "reveal_draft_source_api_catalog_imports__import_id__source_identifiers__source_ref_id__get": {
    security: "SessionCookie";
    path: { "import_id": number; "source_ref_id": string; };
    query: { "workflow_revision": number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "submit_catalog_import_api_catalog_imports__import_id__submit_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ImportRevisionRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "validate_catalog_import_api_catalog_imports__import_id__validate_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ImportRevisionRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "withdraw_catalog_import_api_catalog_imports__import_id__withdraw_post": {
    security: "SessionCookie";
    path: { "import_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ImportReasonRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_return_dedup_groups_api_catalog_return_dedup_groups_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "status"?: "unresolved" | "resolved" | "all"; "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ReturnDedupGroupPageResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "decide_return_dedup_group_api_catalog_return_dedup_groups__group_id__decision_post": {
    security: "SessionCookie";
    path: { "group_id": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReturnDedupDecisionRequest"];
    responses: {
      200: components["schemas"]["ReturnDedupDecisionResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "reveal_approved_source_api_catalog_source_identifiers__source_ref_id__get": {
    security: "SessionCookie";
    path: { "source_ref_id": string; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_scope_api_catalog_source_scope_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["CatalogScopeStatusResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "confirm_catalog_scope_api_catalog_source_scope_confirm_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ConfirmCatalogScopeRequest"];
    responses: {
      200: components["schemas"]["CatalogScopeStatusResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "preview_style_change_api_catalog_style_change_drafts__draft_id__get": {
    security: "SessionCookie";
    path: { "draft_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "approve_style_change_api_catalog_style_change_drafts__draft_id__approve_post": {
    security: "SessionCookie";
    path: { "draft_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["StyleChangeApproveRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_styles_api_catalog_styles_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_style_api_catalog_styles__style_id__get": {
    security: "SessionCookie";
    path: { "style_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_style_change_api_catalog_styles__style_id__change_drafts_post": {
    security: "SessionCookie";
    path: { "style_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["StyleChangeDraftRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_style_pending_items_api_catalog_styles__style_id__pending_items_get": {
    security: "SessionCookie";
    path: { "style_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_unmatched_api_catalog_unmatched_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "page"?: number; "page_size"?: number; "from"?: string | null; "to"?: string | null; "return_basis"?: "report_date" | "event_date"; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_variant_evidence_api_catalog_variants__sku_id__evidence_get": {
    security: "SessionCookie";
    path: { "sku_id": number; };
    query: { "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_variant_seller_skus_api_catalog_variants__sku_id__seller_skus_get": {
    security: "SessionCookie";
    path: { "sku_id": number; };
    query: { "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_catalog_versions_api_catalog_versions_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_catalog_version_diff_api_catalog_versions__version_id__diff_get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "restore_catalog_version_api_catalog_versions__version_id__restore_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RestoreCatalogVersionRequest"];
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "daily_ledger_api_dashboard_daily_ledger_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["DailyLedgerResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "product_card_api_dashboard_product_card__style_code__get": {
    security: "SessionCookie";
    path: { "style_code": string; };
    query: { "from": string; "to": string; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ProductCardResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "product_ledger_api_dashboard_product_ledger_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; "search"?: string | null; "sort"?: "sales" | "units_ordered" | "sessions" | "conversion_rate" | "return_quantity" | "published_days" | "latest_published_date" | "style_code" | "product_name"; "direction"?: "asc" | "desc"; "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ProductLedgerResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "products_api_dashboard_products_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; "limit"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ProductDashboard"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "returns_api_dashboard_returns_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; "basis"?: "report_date" | "event_date"; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ReturnDashboard"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "style_ledger_api_dashboard_style_ledger_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from"?: string | null; "to"?: string | null; "category_id"?: number | null; "search"?: string | null; "sort"?: "style_code" | "standard_name" | "units" | "sales" | "returns" | "sessions" | "conversion"; "direction"?: "asc" | "desc"; "page"?: number; "page_size"?: number; "catalog_version"?: string | null; "fact_basis"?: components["schemas"]["FactBasis"]; "return_basis"?: components["schemas"]["ReturnBasis"]; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["StyleLedgerResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "style_readiness_api_dashboard_style_readiness_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["AnalyticsReadiness"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "style_card_api_dashboard_styles__style_id__card_get": {
    security: "SessionCookie";
    path: { "style_id": string; };
    query: { "from"?: string | null; "to"?: string | null; "metric"?: components["schemas"]["MetricName"]; "dimension"?: components["schemas"]["SeriesDimension"]; "color_key"?: string | null; "series"?: string | null; "catalog_version"?: string | null; "fact_basis"?: components["schemas"]["FactBasis"]; "return_basis"?: components["schemas"]["ReturnBasis"]; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["StyleCardResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "summary_api_dashboard_summary_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["DashboardSummary"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_calendar_entries_api_data_calendar_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["CalendarEntryResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_calendar_days_api_data_calendar_days_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "from": string; "to": string; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["CalendarDayResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_site_context_api_data_calendar_site_context_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["SiteContextResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "materialize_baseline_api_datasets_materialize_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["MaterializeBaselineRequest"];
    responses: {
      201: components["schemas"]["DraftMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "preview_merge_conflicts_api_datasets_merge_preview_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "target_version_id": number; "source_kind": "parse_baseline" | "dataset_version"; "source_id": number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["MergePreviewResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "publish_dataset_api_datasets__dataset_id__publish_post": {
    security: "SessionCookie";
    path: { "dataset_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["PublishRequest"];
    responses: {
      200: components["schemas"]["PublicationCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_revision_api_datasets__dataset_id__revisions_post": {
    security: "SessionCookie";
    path: { "dataset_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateRevisionRequest"];
    responses: {
      201: components["schemas"]["DraftCommandResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_draft_head_api_drafts__version_id__get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["DraftHeadResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "discard_draft_api_drafts__version_id__discard_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["DiscardDraftRequest"];
    responses: {
      200: components["schemas"]["DraftMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "set_field_api_drafts__version_id__fields_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["SetFieldRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "restore_field_api_drafts__version_id__fields__field_name__restore_post": {
    security: "SessionCookie";
    path: { "version_id": number; "field_name": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RestoreFieldRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "review_issue_api_drafts__version_id__issues__issue_id__review_post": {
    security: "SessionCookie";
    path: { "version_id": number; "issue_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReviewIssueRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "mark_ready_api_drafts__version_id__mark_ready_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["MarkReadyRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_note_api_drafts__version_id__notes_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateNoteRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "revise_note_api_drafts__version_id__notes__note_key__revisions_post": {
    security: "SessionCookie";
    path: { "version_id": number; "note_key": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReviseNoteRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "reassign_draft_date_api_drafts__version_id__reassign_date_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReassignDraftDateRequest"];
    responses: {
      200: components["schemas"]["DraftMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "return_to_draft_api_drafts__version_id__return_to_draft_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReturnToDraftRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_review_workspace_api_drafts__version_id__review_workspace_get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: { "changed_only"?: boolean; "row_state"?: "active" | "excluded" | "deleted" | null; "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ReviewWorkspaceResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "add_row_api_drafts__version_id__rows_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["AddRowRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "change_row_state_api_drafts__version_id__rows__row_id__state_post": {
    security: "SessionCookie";
    path: { "version_id": number; "row_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ChangeRowStateRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "health_live_api_health_live_get": {
    security: "public";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Record<string, string>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "health_ready_api_health_ready_get": {
    security: "public";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: unknown;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "upload_import_api_imports_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_date"?: string | null; "site_config_version_id"?: number | null; };
    headers: { "X-Original-Filename"?: string | null; "X-CSRF-Token"?: string | null; };
    requestBody: Blob;
    responses: {
      201: components["schemas"]["UploadResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_batch_reviews_api_imports_batch_reviews_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "page"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_preflight_api_imports_batch_reviews_preflight_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["PreflightRequest"];
    responses: {
      201: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_batch_review_api_imports_batch_reviews__run_id__get": {
    security: "SessionCookie";
    path: { "run_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "confirm_batch_review_api_imports_batch_reviews__run_id__confirm_post": {
    security: "SessionCookie";
    path: { "run_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ConfirmRequest"];
    responses: {
      200: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "advance_batch_review_item_api_imports_batch_reviews__run_id__items__item_id__advance_post": {
    security: "SessionCookie";
    path: { "run_id": number; "item_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: never;
    responses: {
      200: components["schemas"]["BatchReviewItemResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "retry_batch_review_item_api_imports_batch_reviews__run_id__items__item_id__retry_post": {
    security: "SessionCookie";
    path: { "run_id": number; "item_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RevisionRequest"];
    responses: {
      200: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "pause_batch_review_api_imports_batch_reviews__run_id__pause_post": {
    security: "SessionCookie";
    path: { "run_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RevisionRequest"];
    responses: {
      200: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "resume_batch_review_api_imports_batch_reviews__run_id__resume_post": {
    security: "SessionCookie";
    path: { "run_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RevisionRequest"];
    responses: {
      200: components["schemas"]["BatchReviewRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "change_import_date_api_imports__batch_id__change_date_post": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ChangeDateRequest"];
    responses: {
      204: void;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "confirm_parse_api_imports__batch_id__confirm_parse_post": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ConfirmParseRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "inspect_import_api_imports__batch_id__inspect_post": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: { "X-CSRF-Token"?: string | null; };
    requestBody: never;
    responses: {
      200: components["schemas"]["InspectionResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_import_batch_notes_api_imports__batch_id__notes_get": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["ImportBatchNoteResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_import_batch_note_api_imports__batch_id__notes_post": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateImportBatchNoteRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "revise_import_batch_note_api_imports__batch_id__notes__note_key__revisions_post": {
    security: "SessionCookie";
    path: { "batch_id": number; "note_key": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReviseImportBatchNoteRequest"];
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "download_raw_file_api_imports__batch_id__raw_file_get": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Blob;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "preview_raw_file_api_imports__batch_id__raw_file_preview_get": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: { "encoding"?: "utf-8-sig" | "utf-8" | "windows-1252"; "row_limit"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["RawFilePreviewResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_return_dedup_staging_api_publications_return_dedup_staging_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReturnDedupStagingRequest"];
    responses: {
      202: components["schemas"]["ReturnDedupStagingResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_return_dedup_staging_api_publications_return_dedup_staging__job_id__get": {
    security: "SessionCookie";
    path: { "job_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ReturnDedupStagingResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "retry_return_dedup_staging_api_publications_return_dedup_staging__job_id__retry_post": {
    security: "SessionCookie";
    path: { "job_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReturnDedupRetryRequest"];
    responses: {
      200: components["schemas"]["ReturnDedupStagingResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "preview_return_initialization_api_publications_return_initialization_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["ReturnInitializationPreview"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "initialize_returns_api_publications_return_initialization_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ReturnInitializationRequest"];
    responses: {
      202: components["schemas"]["ReturnDedupStagingResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "export_published_details_api_published_details_export_csv_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_type": components["schemas"]["ReportType"]; "from": string; "to": string; "scope_token": string; "column_id": Array<string>; "search"?: string | null; "sort_column_id"?: string | null; "direction"?: "asc" | "desc"; "report_date"?: string | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Blob;
      403: components["schemas"]["ApiErrorResponse"];
      409: components["schemas"]["ApiErrorResponse"];
      422: components["schemas"]["ApiErrorResponse"];
      500: components["schemas"]["ApiErrorResponse"];
    };
  };
  "published_details_range_api_published_details_range_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_type": components["schemas"]["ReportType"]; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["PublishedRangeResponse"];
      403: components["schemas"]["ApiErrorResponse"];
      409: components["schemas"]["ApiErrorResponse"];
      422: components["schemas"]["ApiErrorResponse"];
      500: components["schemas"]["ApiErrorResponse"];
    };
  };
  "published_detail_rows_api_published_details_rows_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_type": components["schemas"]["ReportType"]; "from": string; "to": string; "search"?: string | null; "sort_column_id"?: string | null; "direction"?: "asc" | "desc"; "page"?: number; "page_size"?: number; "scope_token"?: string | null; "report_date"?: string | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["PublishedRowsResponse"];
      403: components["schemas"]["ApiErrorResponse"];
      409: components["schemas"]["ApiErrorResponse"];
      422: components["schemas"]["ApiErrorResponse"];
      500: components["schemas"]["ApiErrorResponse"];
    };
  };
  "published_detail_summaries_api_published_details_summaries_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_type": components["schemas"]["ReportType"]; "from": string; "to": string; "search"?: string | null; "page"?: number; "page_size"?: number; "scope_token"?: string | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["PublishedSummaryResponse"];
      403: components["schemas"]["ApiErrorResponse"];
      409: components["schemas"]["ApiErrorResponse"];
      422: components["schemas"]["ApiErrorResponse"];
      500: components["schemas"]["ApiErrorResponse"];
    };
  };
  "run_validation_api_validation_runs__version_id__post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["RunValidationRequest"];
    responses: {
      200: components["schemas"]["ValidationRunResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_versions_api_versions_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_date"?: string | null; "report_type"?: components["schemas"]["ReportType"] | null; "batch_review_run_id"?: number | null; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["VersionSummaryResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_version_api_versions__version_id__get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["VersionDetailResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_version_rows_api_versions__version_id__rows_get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: { "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Record<string, unknown>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_date_workbench_api_workbench_dates__report_date__get": {
    security: "SessionCookie";
    path: { "report_date": string; };
    query: { "report_type": components["schemas"]["ReportType"]; "page"?: number; "page_size"?: number; "search"?: string | null; "sort_column_id"?: string | null; "direction"?: "asc" | "desc"; "changed_only"?: boolean; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["DateWorkbenchResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "create_workbench_revision_api_workbench_dates__report_date___report_type__revision_post": {
    security: "SessionCookie";
    path: { "report_date": string; "report_type": "business_report" | "return_report"; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["CreateWorkbenchRevisionRequest"];
    responses: {
      201: components["schemas"]["WorkbenchRevisionResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "upload_workbench_import_api_workbench_imports_post": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: { "report_date"?: string | null; "expected_report_type"?: components["schemas"]["ReportType"] | null; };
    headers: { "Idempotency-Key": string; "X-Original-Filename"?: string | null; "X-CSRF-Token"?: string | null; };
    requestBody: Blob;
    responses: {
      200: components["schemas"]["WorkbenchImportResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "list_pending_workbench_imports_api_workbench_imports_pending_get": {
    security: "SessionCookie";
    path: Record<string, never>;
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: Array<components["schemas"]["WorkbenchImportResponse"]>;
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_workbench_import_api_workbench_imports__batch_id__get": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["WorkbenchImportResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "confirm_workbench_import_api_workbench_imports__batch_id__confirm_post": {
    security: "SessionCookie";
    path: { "batch_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["ConfirmWorkbenchImportRequest"];
    responses: {
      200: components["schemas"]["WorkbenchImportResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "get_workbench_changes_api_workbench_versions__version_id__changes_get": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: { "page"?: number; "page_size"?: number; };
    headers: Record<string, never>;
    requestBody: never;
    responses: {
      200: components["schemas"]["WorkbenchChangePageResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "set_workbench_cell_api_workbench_versions__version_id__rows__row_id__cells__column_id__patch": {
    security: "SessionCookie";
    path: { "version_id": number; "row_id": number; "column_id": string; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["SetWorkbenchCellRequest"];
    responses: {
      200: components["schemas"]["WorkbenchCellMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
  "undo_workbench_cell_api_workbench_versions__version_id__undo_post": {
    security: "SessionCookie";
    path: { "version_id": number; };
    query: Record<string, never>;
    headers: { "Idempotency-Key": string; "X-CSRF-Token"?: string | null; };
    requestBody: components["schemas"]["UndoWorkbenchCellRequest"];
    responses: {
      200: components["schemas"]["WorkbenchCellMutationResponse"];
      422: components["schemas"]["ApiErrorResponse"];
    };
  };
}

export type ApiOperationId = keyof operations;
export type ApiPath<Id extends ApiOperationId> = operations[Id]["path"];
export type ApiQuery<Id extends ApiOperationId> = operations[Id]["query"];
export type ApiHeaders<Id extends ApiOperationId> = operations[Id]["headers"];
export type ApiRequestBody<Id extends ApiOperationId> = operations[Id]["requestBody"];
export type ApiResponse<
  Id extends ApiOperationId,
  Status extends keyof operations[Id]["responses"],
> = operations[Id]["responses"][Status];
export type ApiSuccessResponse<Id extends ApiOperationId> = ApiResponse<
  Id,
  Extract<keyof operations[Id]["responses"], 200 | 201 | 202 | 203 | 204 | 205 | 206 | 207 | 208 | 226>
>;
