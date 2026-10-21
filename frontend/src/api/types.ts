import type {
  CalendarDayReason as GeneratedCalendarDayReason,
  CalendarDayResponse,
  CalendarDayStatus as GeneratedCalendarDayStatus,
  CalendarEntryResponse,
  CalendarStatus as GeneratedCalendarStatus,
  CellComparisonResponse,
  CurrentUserResponse,
  DraftHeadResponse,
  DraftMutationResponse,
  FieldChangeResponse,
  FieldContractResponse,
  FullValidationResponse,
  InspectionResponse as GeneratedInspectionResponse,
  LatestNoteResponse,
  PublicationCommandResponse as GeneratedPublicationCommandResponse,
  PublicationPointerResponse,
  ReportType as GeneratedReportType,
  ReviewRowResponse,
  ReviewWorkspaceResponse as GeneratedReviewWorkspaceResponse,
  TypedFieldValueResponse,
  UploadResponse as GeneratedUploadResponse,
  ValidationIssueResponse,
  ValidationRunResponse,
  VersionStatus as GeneratedVersionStatus,
  VersionSummaryResponse,
} from "./generated";

export type Role = "admin" | "data_manager" | "viewer";

export type Principal = Omit<CurrentUserResponse, "roles"> & {
  roles: Role[];
};

export type ReportType = GeneratedReportType;
export type CalendarStatus = GeneratedCalendarStatus;
export type CalendarDayStatus = GeneratedCalendarDayStatus;
export type CalendarDayReason = GeneratedCalendarDayReason;

export type CalendarEntry = CalendarEntryResponse;

export type CalendarDay = CalendarDayResponse;

export type UploadResponse = GeneratedUploadResponse;

export type InspectionResponse = Omit<GeneratedInspectionResponse, "encoding"> & {
  encoding: "utf-8-sig" | "utf-8" | "windows-1252" | null;
};

export type SuccessfulParse = {
  batch_id: number;
  parse_attempt_id: number;
  parse_baseline_id: number;
  confirmation_revision: number;
  report_type: ReportType;
  source_row_count: number;
};

export type FailedParse = {
  batch_id: number;
  parse_attempt_id: number;
  confirmation_revision: number;
  error_code: string;
};

export type ConfirmParseResponse = {
  result: SuccessfulParse | FailedParse;
};

export function isSuccessfulParse(
  result: SuccessfulParse | FailedParse,
): result is SuccessfulParse {
  return "parse_baseline_id" in result;
}

export type VersionExpectation = {
  version_id: number;
  data_revision: number;
  review_revision: number;
};

export type DraftHead = DraftHeadResponse;

export type DraftMutation = DraftMutationResponse;

export type VersionStatus = GeneratedVersionStatus;

export type VersionSummary = VersionSummaryResponse;

export type ValidationStageSummary = {
  data_digest: string;
  row_count: number;
  totals: Record<string, string>;
  warning_count: number;
  blocking_count: number;
};

export type ValidationSummary = {
  schema_version: 1;
  report_date: string;
  report_type: ReportType;
  row_count: number;
  totals: Record<string, string>;
  stages: {
    parse_fidelity: ValidationStageSummary;
    draft_explainability: ValidationStageSummary;
  };
};

export type ValidationRun = Omit<ValidationRunResponse, "summary"> & {
  summary: ValidationSummary;
};

export type TypedFieldValue = TypedFieldValueResponse;

export type ReviewFieldContract = FieldContractResponse;

export type ReviewNote = LatestNoteResponse;

export type FieldChange = FieldChangeResponse;

export type ReviewCell = CellComparisonResponse;

export type ReviewRow = ReviewRowResponse;

export type ReviewIssue = ValidationIssueResponse;

export type WorkspaceValidation = Omit<FullValidationResponse, "summary"> & {
  summary: ValidationSummary;
};

export type ReviewWorkspace = Omit<
  GeneratedReviewWorkspaceResponse,
  "latest_full_validation"
> & {
  latest_full_validation: WorkspaceValidation | null;
};

export type PublicationPointer = PublicationPointerResponse;

export type PublicationCommandResponse = GeneratedPublicationCommandResponse;
