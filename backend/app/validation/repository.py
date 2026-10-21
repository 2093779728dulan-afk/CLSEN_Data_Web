"""MySQL adapter for atomic full validation evidence reads and terminal writes."""

from __future__ import annotations

import hmac
import json
import random
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError

from app.imports.types import ReportType
from app.parsers.types import FieldKind, ParseSettings, SupportedEncoding

from .codec import decode_field_value, encode_field_value
from .fidelity import (
    BaselineRowEvidence,
    FieldMappingEvidence,
    ParseFidelityEvidence,
    SourceFieldMappingEvidence,
    SourceRowEvidence,
)
from .fields import FieldValue, FieldValueError, get_report_field_contract
from .full import (
    FullValidationEvaluation,
    FullValidationEvidence,
    ParseFidelityInput,
    evaluate_full_validation,
)
from .replay import (
    DataChangeEvent,
    DraftReplayEvidence,
    DraftRow,
    FieldChange,
    RestoreValueEvidence,
    RowChange,
)
from .types import (
    EditableVersionStatus,
    RunValidationCommand,
    ValidationCommitOutcomeUnknown,
    ValidationEvidenceError,
    ValidationOperationConflict,
    ValidationPermissionDenied,
    ValidationPersistenceError,
    ValidationRunOutcome,
    ValidationRunReceipt,
    ValidationRunStatus,
    ValidationSummary,
    ValidationTransactionBusy,
    ValidationVersionConflict,
)

_MAX_TRANSACTION_RETRIES = 3
_RETRYABLE_MYSQL_ERROR_CODES = frozenset({1205, 1213})
_RETRY_BASE_DELAY_SECONDS = 0.005
_RETRY_MAX_DELAY_SECONDS = 0.04


@dataclass(frozen=True, slots=True)
class _Actor:
    user_id: int
    roles: frozenset[str]


@dataclass(frozen=True, slots=True)
class _LockedValidationScope:
    dataset_id: int
    version_id: int
    version_status: EditableVersionStatus
    data_revision: int
    review_revision: int
    site_id: int
    report_date: date
    report_type: ReportType
    ruleset_version: str


def _mysql_datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("validation timestamps must be timezone-aware")
    if value.utcoffset() is None:
        raise ValueError("validation timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _database_utc(value: object, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValidationEvidenceError(f"database returned an invalid {label}")
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise ValidationEvidenceError(f"database returned an invalid {label}")
    return value.astimezone(UTC)


def _mysql_error_code(error: DBAPIError) -> int | None:
    arguments = getattr(error.orig, "args", ())
    if arguments and isinstance(arguments[0], int):
        return arguments[0]
    return None


def _wait_for_transaction_retry(retry_number: int) -> None:
    if retry_number < 1:
        raise ValueError("retry_number must be positive")
    ceiling = min(
        _RETRY_BASE_DELAY_SECONDS * (2 ** (retry_number - 1)),
        _RETRY_MAX_DELAY_SECONDS,
    )
    time.sleep(random.uniform(ceiling / 2, ceiling))


def _as_bytes(value: object, *, length: int, label: str) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise ValidationEvidenceError(f"{label} is not binary")
    result = bytes(value)
    if len(result) != length:
        raise ValidationEvidenceError(f"{label} has an invalid length")
    return result


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _json_value(value: object, label: str) -> object:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise ValidationEvidenceError(f"{label} is not valid JSON") from error
    return value


def _json_mapping(value: object, label: str) -> Mapping[str, object]:
    payload = _json_value(value, label)
    if not isinstance(payload, Mapping) or not all(
        isinstance(key, str) for key in payload
    ):
        raise ValidationEvidenceError(f"{label} must be a JSON object")
    return cast(Mapping[str, object], payload)


def _as_report_type(value: object) -> ReportType:
    if value not in {"business_report", "return_report"}:
        raise ValidationEvidenceError("database returned an unsupported report type")
    return cast(ReportType, value)


class MySqlValidationRepository:
    """Own one complete transaction for evidence locking, validation, and writes."""

    def __init__(
        self,
        engine: Engine,
        *,
        retry_waiter: Callable[[int], None] | None = None,
    ) -> None:
        self._engine = engine
        self._retry_waiter = retry_waiter or _wait_for_transaction_retry

    def run_validation(
        self,
        command: RunValidationCommand,
        *,
        occurred_at: datetime,
    ) -> ValidationRunReceipt:
        timestamp = _mysql_datetime(occurred_at)

        def recover_known_outcome() -> ValidationRunReceipt | None:
            try:
                return self._recover_operation(command)
            except ValidationPersistenceError:
                raise
            except SQLAlchemyError as error:
                raise ValidationPersistenceError(
                    "validation operation recovery failed"
                ) from error

        recovered = recover_known_outcome()
        if recovered is not None:
            return recovered

        retry_count = 0
        while True:
            try:
                with self._engine.begin() as connection:
                    return self._run_transaction(connection, command, timestamp)
            except DBAPIError as error:
                if error.connection_invalidated:
                    try:
                        recovered = self._recover_operation(command)
                    except Exception as recovery_error:
                        raise ValidationCommitOutcomeUnknown(
                            "validation commit acknowledgement was lost and "
                            "terminal-result recovery failed"
                        ) from recovery_error
                    if recovered is not None:
                        return recovered
                    raise ValidationCommitOutcomeUnknown(
                        "validation commit acknowledgement was lost"
                    ) from error
                if _mysql_error_code(error) not in _RETRYABLE_MYSQL_ERROR_CODES:
                    raise ValidationPersistenceError(
                        "validation transaction failed"
                    ) from error
                if retry_count >= _MAX_TRANSACTION_RETRIES:
                    raise ValidationTransactionBusy(
                        "validation transaction remained busy after 4 attempts"
                    ) from error
                retry_count += 1
                recovered = recover_known_outcome()
                if recovered is not None:
                    return recovered
                self._retry_waiter(retry_count)
            except ValidationPersistenceError:
                raise
            except SQLAlchemyError as error:
                raise ValidationPersistenceError(
                    "validation transaction failed"
                ) from error

    def _run_transaction(
        self,
        connection: Connection,
        command: RunValidationCommand,
        occurred_at: datetime,
    ) -> ValidationRunReceipt:
        recovered = self._claim_operation(
            connection,
            command=command,
            registered_at=occurred_at,
        )
        if recovered is not None:
            return recovered
        actor = self._load_actor(connection, actor_user_id=command.actor_user_id)
        scope = self._lock_scope(connection, command)
        evidence = self._load_evidence(connection, scope)
        try:
            evaluation = evaluate_full_validation(evidence)
        except (RuntimeError, ValueError) as error:
            raise ValidationEvidenceError(
                "validation evidence cannot be evaluated"
            ) from error
        return self._record_evaluation(
            connection,
            actor=actor,
            command=command,
            scope=scope,
            evaluation=evaluation,
            occurred_at=occurred_at,
        )

    def _claim_operation(
        self,
        connection: Connection,
        *,
        command: RunValidationCommand,
        registered_at: datetime,
    ) -> ValidationRunReceipt | None:
        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO review_operation_tokens (
                        operation_token, operation_kind, operation_digest,
                        actor_user_id, registered_at
                    ) VALUES (
                        :operation_token, 'run_validation', :operation_digest,
                        :actor_user_id, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "operation_digest": command.operation_digest,
                    "actor_user_id": command.actor_user_id,
                    "registered_at": registered_at,
                },
            )
            savepoint.commit()
            return None
        except IntegrityError as error:
            savepoint.rollback()
            if _mysql_error_code(error) != 1062:
                raise
        return self._operation_result(
            connection,
            command=command,
            require_result=True,
        )

    def _recover_operation(
        self,
        command: RunValidationCommand,
    ) -> ValidationRunReceipt | None:
        with self._engine.connect() as connection:
            return self._operation_result(
                connection,
                command=command,
                require_result=False,
            )

    def _operation_result(
        self,
        connection: Connection,
        *,
        command: RunValidationCommand,
        require_result: bool,
    ) -> ValidationRunReceipt | None:
        token = (
            connection.execute(
                sa.text(
                    """
                    SELECT operation_kind, operation_digest, actor_user_id
                    FROM review_operation_tokens
                    WHERE operation_token = :operation_token
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if token is None:
            return None
        stored_digest = _as_bytes(
            token["operation_digest"],
            length=32,
            label="validation operation digest",
        )
        if (
            token["operation_kind"] != "run_validation"
            or int(token["actor_user_id"]) != command.actor_user_id
            or not hmac.compare_digest(stored_digest, command.operation_digest)
        ):
            raise ValidationOperationConflict(
                "operation token is already bound to another command"
            )

        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT results.result_kind,
                           results.result_dataset_id,
                           results.result_version_id,
                           results.result_status,
                           results.result_data_revision,
                           results.result_review_revision,
                           results.validation_run_id,
                           runs.run_type,
                           runs.ruleset_version,
                           runs.status AS validation_status,
                           runs.result AS validation_result,
                           runs.data_digest,
                           runs.summary_json,
                           results.completed_at
                    FROM review_operation_results AS results
                    INNER JOIN validation_runs AS runs
                        ON runs.version_id = results.result_version_id
                       AND runs.id = results.validation_run_id
                    WHERE results.operation_token = :operation_token
                      AND results.operation_kind = 'run_validation'
                    LIMIT 1
                    """
                ),
                {"operation_token": command.operation_token.bytes},
            )
            .mappings()
            .first()
        )
        if row is None:
            if require_result:
                raise ValidationCommitOutcomeUnknown(
                    "finalized validation token has no terminal result"
                )
            return None
        return self._receipt_from_row(
            command,
            cast(Mapping[str, object], row),
        )

    @staticmethod
    def _receipt_from_row(
        command: RunValidationCommand,
        row: Mapping[str, object],
    ) -> ValidationRunReceipt:
        if row["result_kind"] != "applied" or row["run_type"] != "full":
            raise ValidationEvidenceError(
                "validation terminal result has invalid semantics"
            )
        dataset_id = int(cast(Any, row["result_dataset_id"]))
        version_id = int(cast(Any, row["result_version_id"]))
        data_revision = int(cast(Any, row["result_data_revision"]))
        if (
            dataset_id != command.dataset_id
            or version_id != command.version_id
            or data_revision != command.data_revision
            or row["ruleset_version"] != command.ruleset_version
        ):
            raise ValidationEvidenceError(
                "validation terminal result differs from its command scope"
            )
        version_status = str(row["result_status"])
        if version_status not in {"draft", "ready_for_publish"}:
            raise ValidationEvidenceError(
                "validation terminal result has an invalid version status"
            )
        status = str(row["validation_status"])
        result = str(row["validation_result"])
        if status not in {"succeeded", "failed"} or result not in {
            "passed",
            "failed",
            "error",
        }:
            raise ValidationEvidenceError(
                "validation run has an invalid terminal state"
            )
        summary_payload = _json_value(row["summary_json"], "validation summary")
        try:
            summary = ValidationSummary.from_payload(summary_payload)
        except ValueError as error:
            raise ValidationEvidenceError(
                "validation summary does not satisfy schema v1"
            ) from error
        return ValidationRunReceipt(
            operation_token=command.operation_token,
            validation_run_id=int(cast(Any, row["validation_run_id"])),
            dataset_id=dataset_id,
            version_id=version_id,
            version_status=cast(EditableVersionStatus, version_status),
            data_revision=data_revision,
            review_revision=int(cast(Any, row["result_review_revision"])),
            ruleset_version=str(row["ruleset_version"]),
            status=cast(ValidationRunStatus, status),
            result=cast(ValidationRunOutcome, result),
            data_digest=_as_bytes(
                row["data_digest"],
                length=32,
                label="validation data digest",
            ),
            summary=summary,
            completed_at=_database_utc(row["completed_at"], "completion timestamp"),
        )

    @staticmethod
    def _load_actor(connection: Connection, *, actor_user_id: int) -> _Actor:
        user = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, status
                    FROM users
                    WHERE id = :actor_user_id
                    FOR SHARE
                    """
                ),
                {"actor_user_id": actor_user_id},
            )
            .mappings()
            .first()
        )
        if user is None or user["status"] != "active":
            raise ValidationPermissionDenied("actor is not an active user")
        roles = frozenset(
            str(value)
            for value in connection.scalars(
                sa.text(
                    """
                    SELECT roles.code
                    FROM user_roles
                    INNER JOIN roles ON roles.id = user_roles.role_id
                    WHERE user_roles.user_id = :actor_user_id
                    ORDER BY roles.code
                    FOR SHARE
                    """
                ),
                {"actor_user_id": actor_user_id},
            )
        )
        if not roles.intersection({"admin", "data_manager"}):
            raise ValidationPermissionDenied(
                "only administrators and data managers may validate drafts"
            )
        return _Actor(user_id=actor_user_id, roles=roles)

    @staticmethod
    def _lock_scope(
        connection: Connection,
        command: RunValidationCommand,
    ) -> _LockedValidationScope:
        locked = connection.execute(
            sa.text(
                """
                UPDATE daily_dataset_locks
                SET lock_revision = CASE
                    WHEN lock_revision = 18446744073709551615 THEN 0
                    ELSE lock_revision + 1
                END
                WHERE dataset_id = :dataset_id
                """
            ),
            {"dataset_id": command.dataset_id},
        )
        if locked.rowcount != 1:
            raise ValidationVersionConflict("daily dataset lock row is missing")
        dataset = (
            connection.execute(
                sa.text(
                    """
                    SELECT id, site_id, report_date, report_type
                    FROM daily_datasets
                    WHERE id = :dataset_id
                    """
                ),
                {"dataset_id": command.dataset_id},
            )
            .mappings()
            .first()
        )
        if dataset is None:
            raise ValidationVersionConflict("daily dataset does not exist")
        pointer = (
            connection.execute(
                sa.text(
                    """
                    SELECT version_id, version_status
                    FROM dataset_drafts
                    WHERE dataset_id = :dataset_id
                    FOR UPDATE
                    """
                ),
                {"dataset_id": command.dataset_id},
            )
            .mappings()
            .first()
        )
        if pointer is None or int(pointer["version_id"]) != command.version_id:
            raise ValidationVersionConflict("version is not the active draft")
        version = (
            connection.execute(
                sa.text(
                    """
                    SELECT dataset_id, id, report_type, status,
                           data_revision, review_revision, ruleset_version,
                           sealed_at
                    FROM dataset_versions
                    WHERE dataset_id = :dataset_id AND id = :version_id
                    FOR UPDATE
                    """
                ),
                {
                    "dataset_id": command.dataset_id,
                    "version_id": command.version_id,
                },
            )
            .mappings()
            .first()
        )
        if version is None:
            raise ValidationVersionConflict("active version does not exist")
        status = str(version["status"])
        if (
            status not in {"draft", "ready_for_publish"}
            or pointer["version_status"] != status
            or version["sealed_at"] is not None
        ):
            raise ValidationVersionConflict("version is no longer editable")
        if (
            int(version["data_revision"]) != command.data_revision
            or str(version["ruleset_version"]) != command.ruleset_version
        ):
            raise ValidationVersionConflict("validation scope changed")
        report_type = _as_report_type(version["report_type"])
        if report_type != _as_report_type(dataset["report_type"]):
            raise ValidationEvidenceError("dataset and version report types differ")
        report_date = dataset["report_date"]
        if not isinstance(report_date, date) or isinstance(report_date, datetime):
            raise ValidationEvidenceError("database returned an invalid report date")
        return _LockedValidationScope(
            dataset_id=command.dataset_id,
            version_id=command.version_id,
            version_status=cast(EditableVersionStatus, status),
            data_revision=command.data_revision,
            review_revision=int(version["review_revision"]),
            site_id=int(dataset["site_id"]),
            report_date=report_date,
            report_type=report_type,
            ruleset_version=command.ruleset_version,
        )

    @staticmethod
    def _field_value(value: object) -> FieldValue:
        if isinstance(value, datetime):
            value = _database_utc(value, "typed field value")
        if value is None or isinstance(value, (str, Decimal, datetime)):
            return value
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValidationEvidenceError("typed field value has an invalid type")
        return value

    @staticmethod
    def _field_mapping(value: object) -> FieldMappingEvidence:
        payload = _json_mapping(value, "parse field mapping")
        raw_header = payload.get("source_header")
        raw_fields = payload.get("fields")
        if (
            set(payload) != {"source_header", "fields"}
            or not isinstance(raw_header, list)
            or not all(isinstance(item, str) for item in raw_header)
            or not isinstance(raw_fields, list)
        ):
            raise ValidationEvidenceError("parse field mapping has an invalid shape")
        fields: list[SourceFieldMappingEvidence] = []
        for item in raw_fields:
            if not isinstance(item, Mapping) or set(item) != {
                "source",
                "target",
                "kind",
            }:
                raise ValidationEvidenceError(
                    "parse field mapping entry has an invalid shape"
                )
            source = item["source"]
            target = item["target"]
            kind = item["kind"]
            if not isinstance(source, str) or not isinstance(target, str):
                raise ValidationEvidenceError("parse field mapping names are invalid")
            try:
                parsed_kind = FieldKind(kind)
            except (TypeError, ValueError) as error:
                raise ValidationEvidenceError(
                    "parse field mapping kind is invalid"
                ) from error
            fields.append(SourceFieldMappingEvidence(source, target, parsed_kind))
        return FieldMappingEvidence(
            source_header=tuple(cast(list[str], raw_header)),
            fields=tuple(fields),
        )

    @classmethod
    def _load_parse_inputs(
        cls,
        connection: Connection,
        scope: _LockedValidationScope,
    ) -> tuple[ParseFidelityInput, ...]:
        descriptors = (
            connection.execute(
                sa.text(
                    """
                    SELECT members.parse_baseline_id,
                           baselines.parse_attempt_id,
                           attempts.batch_id, attempts.parser_version,
                           attempts.ruleset_version, attempts.encoding,
                           attempts.delimiter, attempts.field_mapping,
                           attempts.source_row_count,
                           configs.source_timezone,
                           baselines.report_type, baselines.row_count,
                           baselines.totals_json, baselines.data_digest
                    FROM version_base_snapshots AS snapshots
                    INNER JOIN version_base_snapshot_members AS members
                        ON members.snapshot_id = snapshots.id
                       AND members.member_type = 'parse_baseline'
                    INNER JOIN parse_baselines AS baselines
                        ON baselines.id = members.parse_baseline_id
                    INNER JOIN parse_attempts AS attempts
                        ON attempts.id = baselines.parse_attempt_id
                    INNER JOIN site_config_versions AS configs
                        ON configs.id = attempts.site_config_version_id
                    WHERE snapshots.version_id = :version_id
                    ORDER BY members.member_ordinal, members.id
                    """
                ),
                {"version_id": scope.version_id},
            )
            .mappings()
            .all()
        )
        contract = get_report_field_contract(
            scope.report_type,
            scope.ruleset_version,
        )
        typed_table = (
            "business_parse_baseline_rows"
            if scope.report_type == "business_report"
            else "return_parse_baseline_rows"
        )
        selected_values = ", ".join(
            f"typed.{name} AS value_{name}" for name in contract.field_names
        )
        inputs: list[ParseFidelityInput] = []
        for descriptor in descriptors:
            if _as_report_type(descriptor["report_type"]) != scope.report_type:
                raise ValidationEvidenceError(
                    "parse baseline report type differs from the version"
                )
            encoding = descriptor["encoding"]
            if encoding not in {"utf-8-sig", "utf-8", "windows-1252"}:
                raise ValidationEvidenceError("parse encoding is unsupported")
            if descriptor["delimiter"] != ",":
                raise ValidationEvidenceError("parse delimiter is unsupported")
            mapping = cls._field_mapping(descriptor["field_mapping"])
            source_rows_raw = (
                connection.execute(
                    sa.text(
                        """
                        SELECT id, source_row_number, decoded_fields, row_digest
                        FROM parsed_source_rows
                        WHERE parse_attempt_id = :parse_attempt_id
                        ORDER BY source_row_number, id
                        """
                    ),
                    {"parse_attempt_id": int(descriptor["parse_attempt_id"])},
                )
                .mappings()
                .all()
            )
            source_rows: list[SourceRowEvidence] = []
            header: tuple[str, ...] | None = None
            for source_row in source_rows_raw:
                decoded = _json_mapping(
                    source_row["decoded_fields"],
                    "decoded source row",
                )
                raw_header = decoded.get("header")
                raw_values = decoded.get("values")
                if (
                    set(decoded) != {"header", "values"}
                    or not isinstance(raw_header, list)
                    or not all(isinstance(item, str) for item in raw_header)
                    or not isinstance(raw_values, list)
                    or not all(isinstance(item, str) for item in raw_values)
                ):
                    raise ValidationEvidenceError(
                        "decoded source row has an invalid shape"
                    )
                row_header = tuple(cast(list[str], raw_header))
                if header is None:
                    header = row_header
                elif header != row_header:
                    raise ValidationEvidenceError(
                        "decoded source row headers are inconsistent"
                    )
                source_rows.append(
                    SourceRowEvidence(
                        source_row_id=int(source_row["id"]),
                        source_row_number=int(source_row["source_row_number"]),
                        raw_values=tuple(cast(list[str], raw_values)),
                        row_digest=_as_bytes(
                            source_row["row_digest"],
                            length=32,
                            label="source row digest",
                        ).hex(),
                    )
                )
            if header is None:
                header = mapping.source_header
            if header != mapping.source_header:
                raise ValidationEvidenceError(
                    "source header differs from the field mapping"
                )
            baseline_rows_raw = (
                connection.execute(
                    sa.text(
                        f"""
                        SELECT baseline_rows.id, baseline_rows.parsed_source_row_id,
                               baseline_rows.row_ordinal, baseline_rows.row_digest,
                               {selected_values}
                        FROM parse_baseline_rows AS baseline_rows
                        INNER JOIN {typed_table} AS typed
                            ON typed.parse_baseline_id = baseline_rows.parse_baseline_id
                           AND typed.parse_baseline_row_id = baseline_rows.id
                        WHERE baseline_rows.parse_baseline_id = :parse_baseline_id
                          AND baseline_rows.parse_attempt_id = :parse_attempt_id
                        ORDER BY baseline_rows.row_ordinal, baseline_rows.id
                        """
                    ),
                    {
                        "parse_baseline_id": int(descriptor["parse_baseline_id"]),
                        "parse_attempt_id": int(descriptor["parse_attempt_id"]),
                    },
                )
                .mappings()
                .all()
            )
            baseline_rows = tuple(
                BaselineRowEvidence(
                    baseline_row_id=int(row["id"]),
                    source_row_id=int(row["parsed_source_row_id"]),
                    row_ordinal=int(row["row_ordinal"]),
                    values=tuple(
                        (name, cls._field_value(row[f"value_{name}"]))
                        for name in contract.field_names
                    ),
                    row_digest=_as_bytes(
                        row["row_digest"],
                        length=32,
                        label="baseline row digest",
                    ).hex(),
                )
                for row in baseline_rows_raw
            )
            totals_payload = _json_mapping(
                descriptor["totals_json"],
                "parse baseline totals",
            )
            totals: list[tuple[str, str]] = []
            for name, value in totals_payload.items():
                if not isinstance(value, str):
                    raise ValidationEvidenceError(
                        "parse baseline total value is invalid"
                    )
                totals.append((name, value))
            settings = ParseSettings(
                report_type=scope.report_type,
                encoding=cast(SupportedEncoding, encoding),
                source_timezone=(
                    str(descriptor["source_timezone"])
                    if scope.report_type == "return_report"
                    else None
                ),
            )
            evidence = ParseFidelityEvidence(
                report_type=scope.report_type,
                parser_version=str(descriptor["parser_version"]),
                ruleset_version=str(descriptor["ruleset_version"]),
                settings=settings,
                header=header,
                source_rows=tuple(source_rows),
                baseline_rows=baseline_rows,
                field_mapping=mapping,
                stored_source_row_count=int(descriptor["source_row_count"]),
                stored_baseline_row_count=int(descriptor["row_count"]),
                stored_totals=tuple(sorted(totals)),
                stored_data_digest=_as_bytes(
                    descriptor["data_digest"],
                    length=32,
                    label="parse baseline data digest",
                ).hex(),
            )
            inputs.append(
                ParseFidelityInput(
                    import_batch_id=int(descriptor["batch_id"]),
                    parse_attempt_id=int(descriptor["parse_attempt_id"]),
                    parse_baseline_id=int(descriptor["parse_baseline_id"]),
                    evidence=evidence,
                )
            )
        return tuple(inputs)

    @classmethod
    def _load_version_rows(
        cls,
        connection: Connection,
        *,
        scope: _LockedValidationScope,
        base: bool,
    ) -> tuple[DraftRow, ...]:
        contract = get_report_field_contract(
            scope.report_type,
            scope.ruleset_version,
        )
        if base:
            generic_table = "version_base_rows"
            typed_table = (
                "business_version_base_rows"
                if scope.report_type == "business_report"
                else "return_version_base_rows"
            )
            typed_id = "version_base_row_id"
            base_id_sql = "stored_rows.id"
            row_id_sql = "current_rows.id"
            source_batch_sql = "source_attempt.batch_id"
            joins = """
                LEFT JOIN version_rows AS current_rows
                    ON current_rows.version_id = stored_rows.version_id
                   AND current_rows.base_row_id = stored_rows.id
                LEFT JOIN parse_baseline_rows AS source_baseline
                    ON source_baseline.id = stored_rows.source_parse_baseline_row_id
                LEFT JOIN parse_attempts AS source_attempt
                    ON source_attempt.id = source_baseline.parse_attempt_id
            """
        else:
            generic_table = "version_rows"
            typed_table = (
                "business_report_rows"
                if scope.report_type == "business_report"
                else "return_report_rows"
            )
            typed_id = "version_row_id"
            base_id_sql = "stored_rows.base_row_id"
            row_id_sql = "stored_rows.id"
            source_batch_sql = """
                COALESCE(
                    source_attempt.batch_id,
                    (
                        SELECT additions.source_batch_id
                        FROM row_changes AS additions
                        WHERE additions.version_id = stored_rows.version_id
                          AND additions.row_id = stored_rows.id
                          AND additions.operation = 'add'
                        ORDER BY additions.id
                        LIMIT 1
                    )
                )
            """
            joins = """
                LEFT JOIN version_base_rows AS source_base
                    ON source_base.version_id = stored_rows.version_id
                   AND source_base.id = stored_rows.base_row_id
                LEFT JOIN parse_baseline_rows AS source_baseline
                    ON source_baseline.id =
                       source_base.source_parse_baseline_row_id
                LEFT JOIN parse_attempts AS source_attempt
                    ON source_attempt.id = source_baseline.parse_attempt_id
            """
        selected_values = ", ".join(
            f"typed.{name} AS value_{name}" for name in contract.field_names
        )
        rows = (
            connection.execute(
                sa.text(
                    f"""
                    SELECT {row_id_sql} AS id, stored_rows.logical_row_id,
                           stored_rows.row_ordinal, stored_rows.row_state,
                           {base_id_sql} AS base_row_id,
                           stored_rows.original_parsed_source_row_id,
                           source_baseline.id AS parse_baseline_row_id,
                           {source_batch_sql} AS source_batch_id,
                           {selected_values}
                    FROM {generic_table} AS stored_rows
                    INNER JOIN {typed_table} AS typed
                        ON typed.version_id = stored_rows.version_id
                       AND typed.{typed_id} = stored_rows.id
                    {joins}
                    WHERE stored_rows.version_id = :version_id
                      AND stored_rows.report_type = :report_type
                    ORDER BY stored_rows.row_ordinal, stored_rows.id
                    """
                ),
                {
                    "version_id": scope.version_id,
                    "report_type": scope.report_type,
                },
            )
            .mappings()
            .all()
        )
        result: list[DraftRow] = []
        for row in rows:
            if row["id"] is None:
                raise ValidationEvidenceError(
                    "base snapshot row has no materialised version row"
                )
            logical = _as_bytes(
                row["logical_row_id"],
                length=16,
                label="logical row identity",
            )
            row_state = str(row["row_state"])
            if row_state not in {"active", "excluded", "deleted"}:
                raise ValidationEvidenceError("version row state is invalid")
            result.append(
                DraftRow(
                    row_id=int(row["id"]),
                    logical_row_id=UUID(bytes=logical),
                    row_ordinal=int(row["row_ordinal"]),
                    row_state=cast(Any, row_state),
                    values=tuple(
                        (name, cls._field_value(row[f"value_{name}"]))
                        for name in contract.field_names
                    ),
                    base_row_id=(
                        int(row["base_row_id"])
                        if row["base_row_id"] is not None
                        else None
                    ),
                    source_parse_baseline_row_id=(
                        int(row["original_parsed_source_row_id"])
                        if row["original_parsed_source_row_id"] is not None
                        else None
                    ),
                    source_batch_id=(
                        int(row["source_batch_id"])
                        if row["source_batch_id"] is not None
                        else None
                    ),
                    parse_baseline_row_id=(
                        int(row["parse_baseline_row_id"])
                        if row["parse_baseline_row_id"] is not None
                        else None
                    ),
                )
            )
        return tuple(result)

    @staticmethod
    def _decode_event_row(
        value: object,
        *,
        label: str,
    ) -> DraftRow | None:
        payload = _json_value(value, label)
        if payload is None:
            return None
        if not isinstance(payload, Mapping) or set(payload) != {
            "row_id",
            "logical_row_id",
            "row_ordinal",
            "row_state",
            "base_row_id",
            "source_parse_baseline_row_id",
            "source_batch_id",
            "values",
        }:
            raise ValidationEvidenceError(f"{label} has an invalid shape")
        raw_values = payload["values"]
        if not isinstance(raw_values, Mapping) or not all(
            isinstance(name, str) for name in raw_values
        ):
            raise ValidationEvidenceError(f"{label} values have an invalid shape")
        try:
            logical_row_id = UUID(str(payload["logical_row_id"]))
            values = tuple(
                (name, decode_field_value(field_payload))
                for name, field_payload in raw_values.items()
            )
        except (ValueError, FieldValueError) as error:
            raise ValidationEvidenceError(f"{label} contains invalid values") from error

        def optional_id(name: str) -> int | None:
            raw: object = payload[name]
            if raw is None:
                return None
            if isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
                raise ValidationEvidenceError(f"{label} contains an invalid ID")
            return raw

        row_id = payload["row_id"]
        row_ordinal = payload["row_ordinal"]
        row_state = payload["row_state"]
        if (
            isinstance(row_id, bool)
            or not isinstance(row_id, int)
            or row_id < 1
            or isinstance(row_ordinal, bool)
            or not isinstance(row_ordinal, int)
            or row_ordinal < 1
            or row_state not in {"active", "excluded", "deleted"}
        ):
            raise ValidationEvidenceError(f"{label} contains invalid row identity")
        return DraftRow(
            row_id=row_id,
            logical_row_id=logical_row_id,
            row_ordinal=row_ordinal,
            row_state=cast(Any, row_state),
            values=values,
            base_row_id=optional_id("base_row_id"),
            source_parse_baseline_row_id=optional_id("source_parse_baseline_row_id"),
            source_batch_id=optional_id("source_batch_id"),
        )

    @classmethod
    def _load_events(
        cls,
        connection: Connection,
        scope: _LockedValidationScope,
    ) -> tuple[DataChangeEvent, ...]:
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT events.id, events.sequence_number,
                           events.data_revision, events.event_kind,
                           fields.id AS field_change_id,
                           fields.row_id AS field_row_id,
                           fields.field_name, fields.operation AS field_operation,
                           fields.before_value_json AS field_before_json,
                           fields.after_value_json AS field_after_json,
                           fields.restored_field_change_id,
                           fields.restored_parent_version_id,
                           fields.restored_source_row_id,
                           row_events.id AS row_change_id,
                           row_events.row_id AS changed_row_id,
                           row_events.operation AS row_operation,
                           row_events.before_value_json AS row_before_json,
                           row_events.after_value_json AS row_after_json
                    FROM data_change_events AS events
                    LEFT JOIN field_changes AS fields
                        ON fields.version_id = events.version_id
                       AND fields.id = events.id
                    LEFT JOIN row_changes AS row_events
                        ON row_events.version_id = events.version_id
                       AND row_events.id = events.id
                    WHERE events.version_id = :version_id
                    ORDER BY events.sequence_number, events.id
                    """
                ),
                {"version_id": scope.version_id},
            )
            .mappings()
            .all()
        )
        events: list[DataChangeEvent] = []
        for row in rows:
            event_kind = str(row["event_kind"])
            change: FieldChange | RowChange | None
            if event_kind == "field" and row["field_change_id"] is not None:
                try:
                    before = decode_field_value(
                        _json_value(row["field_before_json"], "field before value")
                    )
                    after = decode_field_value(
                        _json_value(row["field_after_json"], "field after value")
                    )
                except FieldValueError as error:
                    raise ValidationEvidenceError(
                        "field change contains invalid typed JSON"
                    ) from error
                change = FieldChange(
                    row_id=int(row["field_row_id"]),
                    field_name=str(row["field_name"]),
                    operation=cast(Any, str(row["field_operation"])),
                    before_value=before,
                    after_value=after,
                    restored_field_change_id=(
                        int(row["restored_field_change_id"])
                        if row["restored_field_change_id"] is not None
                        else None
                    ),
                    restored_parent_version_id=(
                        int(row["restored_parent_version_id"])
                        if row["restored_parent_version_id"] is not None
                        else None
                    ),
                    restored_source_row_id=(
                        int(row["restored_source_row_id"])
                        if row["restored_source_row_id"] is not None
                        else None
                    ),
                )
            elif event_kind == "row" and row["row_change_id"] is not None:
                change = RowChange(
                    operation=cast(Any, str(row["row_operation"])),
                    row_id=int(row["changed_row_id"]),
                    before_row=cls._decode_event_row(
                        row["row_before_json"],
                        label="row change before image",
                    ),
                    after_row=cls._decode_event_row(
                        row["row_after_json"],
                        label="row change after image",
                    ),
                )
            else:
                change = None
            if event_kind not in {"field", "row"}:
                raise ValidationEvidenceError("data change event kind is invalid")
            events.append(
                DataChangeEvent(
                    event_id=int(row["id"]),
                    sequence_number=int(row["sequence_number"]),
                    data_revision=int(row["data_revision"]),
                    event_kind=cast(Any, event_kind),
                    change=change,
                )
            )
        return tuple(events)

    @classmethod
    def _load_restore_values(
        cls,
        connection: Connection,
        *,
        scope: _LockedValidationScope,
        current_rows: tuple[DraftRow, ...],
        events: tuple[DataChangeEvent, ...],
    ) -> tuple[RestoreValueEvidence, ...]:
        contract = get_report_field_contract(
            scope.report_type,
            scope.ruleset_version,
        )
        allowed_fields = set(contract.field_names)
        typed_current_table = (
            "business_report_rows"
            if scope.report_type == "business_report"
            else "return_report_rows"
        )
        typed_source_table = (
            "business_parse_baseline_rows"
            if scope.report_type == "business_report"
            else "return_parse_baseline_rows"
        )
        rows_by_id = {row.row_id: row for row in current_rows}
        field_changes = {
            event.event_id: event.change
            for event in events
            if isinstance(event.change, FieldChange)
        }
        evidence: dict[tuple[str, int, int, str], RestoreValueEvidence] = {}
        for event in events:
            change = event.change
            if not isinstance(change, FieldChange):
                continue
            field_name = change.field_name
            if change.operation == "restore_previous":
                reference_id = change.restored_field_change_id
                referenced = (
                    field_changes.get(reference_id)
                    if reference_id is not None
                    else None
                )
                if reference_id is None or referenced is None:
                    continue
                value = referenced.before_value
                kind = "previous"
            elif change.operation == "restore_parent":
                reference_id = change.restored_parent_version_id
                row = rows_by_id.get(change.row_id)
                if (
                    reference_id is None
                    or row is None
                    or field_name not in allowed_fields
                ):
                    continue
                found = (
                    connection.execute(
                        sa.text(
                            f"""
                            SELECT typed.{field_name} AS restore_value
                            FROM version_parent_versions AS lineage
                            INNER JOIN version_rows AS parent_rows
                                ON parent_rows.version_id =
                                   lineage.parent_version_id
                               AND parent_rows.logical_row_id = :logical_row_id
                               AND parent_rows.report_type = :report_type
                            INNER JOIN {typed_current_table} AS typed
                                ON typed.version_id = parent_rows.version_id
                               AND typed.version_row_id = parent_rows.id
                            WHERE lineage.child_version_id = :version_id
                              AND lineage.parent_version_id = :parent_version_id
                            LIMIT 1
                            """
                        ),
                        {
                            "logical_row_id": row.logical_row_id.bytes,
                            "report_type": scope.report_type,
                            "version_id": scope.version_id,
                            "parent_version_id": reference_id,
                        },
                    )
                    .mappings()
                    .first()
                )
                if found is None:
                    continue
                value = cls._field_value(found["restore_value"])
                kind = "parent"
            elif change.operation == "restore_source":
                reference_id = change.restored_source_row_id
                row = rows_by_id.get(change.row_id)
                if (
                    reference_id is None
                    or row is None
                    or row.source_parse_baseline_row_id != reference_id
                    or field_name not in allowed_fields
                ):
                    continue
                found = (
                    connection.execute(
                        sa.text(
                            f"""
                            SELECT typed.{field_name} AS restore_value
                            FROM version_rows AS current_rows
                            INNER JOIN version_base_rows AS base_rows
                                ON base_rows.version_id = current_rows.version_id
                               AND base_rows.id = current_rows.base_row_id
                            INNER JOIN parse_baseline_rows AS source_rows
                                ON source_rows.id =
                                   base_rows.source_parse_baseline_row_id
                            INNER JOIN {typed_source_table} AS typed
                                ON typed.parse_baseline_id =
                                   source_rows.parse_baseline_id
                               AND typed.parse_baseline_row_id = source_rows.id
                            WHERE current_rows.version_id = :version_id
                              AND current_rows.id = :row_id
                              AND source_rows.parsed_source_row_id = :source_row_id
                            LIMIT 1
                            """
                        ),
                        {
                            "version_id": scope.version_id,
                            "row_id": change.row_id,
                            "source_row_id": reference_id,
                        },
                    )
                    .mappings()
                    .first()
                )
                if found is None:
                    continue
                value = cls._field_value(found["restore_value"])
                kind = "source"
            else:
                continue
            key = (kind, reference_id, change.row_id, field_name)
            evidence[key] = RestoreValueEvidence(
                kind=cast(Any, kind),
                reference_id=reference_id,
                row_id=change.row_id,
                field_name=field_name,
                value=value,
            )
        return tuple(evidence[key] for key in sorted(evidence))

    @classmethod
    def _load_evidence(
        cls,
        connection: Connection,
        scope: _LockedValidationScope,
    ) -> FullValidationEvidence:
        parse_inputs = cls._load_parse_inputs(connection, scope)
        base_rows = cls._load_version_rows(
            connection,
            scope=scope,
            base=True,
        )
        current_rows = cls._load_version_rows(
            connection,
            scope=scope,
            base=False,
        )
        events = cls._load_events(connection, scope)
        restore_values = cls._load_restore_values(
            connection,
            scope=scope,
            current_rows=current_rows,
            events=events,
        )
        draft = DraftReplayEvidence(
            report_type=scope.report_type,
            ruleset_version=scope.ruleset_version,
            base_rows=base_rows,
            events=events,
            current_rows=current_rows,
            data_revision=scope.data_revision,
            restore_values=restore_values,
        )
        return FullValidationEvidence(
            dataset_id=scope.dataset_id,
            version_id=scope.version_id,
            version_status=scope.version_status,
            data_revision=scope.data_revision,
            review_revision=scope.review_revision,
            report_date=scope.report_date,
            report_type=scope.report_type,
            ruleset_version=scope.ruleset_version,
            parse_inputs=parse_inputs,
            draft=draft,
        )

    @staticmethod
    def _record_evaluation(
        connection: Connection,
        *,
        actor: _Actor,
        command: RunValidationCommand,
        scope: _LockedValidationScope,
        evaluation: FullValidationEvaluation,
        occurred_at: datetime,
    ) -> ValidationRunReceipt:
        if actor.user_id != command.actor_user_id:
            raise ValidationPermissionDenied("validation actor identity changed")
        outcome: ValidationRunOutcome = (
            "passed" if evaluation.result.passed else "failed"
        )
        data_digest = bytes.fromhex(evaluation.result.data_digest)
        inserted_run = connection.execute(
            sa.text(
                """
                INSERT INTO validation_runs (
                    version_id, run_type, data_revision, ruleset_version,
                    status, result, data_digest, summary_json,
                    started_at, completed_at
                ) VALUES (
                    :version_id, 'full', :data_revision, :ruleset_version,
                    'succeeded', :result, :data_digest, :summary_json,
                    :started_at, :completed_at
                )
                """
            ),
            {
                "version_id": scope.version_id,
                "data_revision": scope.data_revision,
                "ruleset_version": scope.ruleset_version,
                "result": outcome,
                "data_digest": data_digest,
                "summary_json": _canonical_json(evaluation.summary.as_payload()),
                "started_at": occurred_at,
                "completed_at": occurred_at,
            },
        )
        if inserted_run.lastrowid is None:
            raise ValidationPersistenceError(
                "database did not return a validation run ID"
            )
        validation_run_id = int(inserted_run.lastrowid)
        for persisted in evaluation.issues:
            issue = persisted.issue
            source_value_json = (
                _canonical_json(encode_field_value(issue.source_value))
                if issue.source_value is not None
                else None
            )
            processed_value_json = (
                _canonical_json(encode_field_value(issue.processed_value))
                if issue.processed_value is not None
                else None
            )
            inserted_issue = connection.execute(
                sa.text(
                    """
                    INSERT INTO validation_issues (
                        validation_run_id, version_id, row_id,
                        severity, rule_code, field_name, message,
                        source_value_json, processed_value_json,
                        details_json, requires_note, created_at,
                        import_batch_id, parse_attempt_id,
                        parsed_source_row_id, parse_baseline_id,
                        parse_baseline_row_id
                    ) VALUES (
                        :validation_run_id, :version_id, :row_id,
                        :severity, :rule_code, :field_name, :message,
                        :source_value_json, :processed_value_json,
                        :details_json, :requires_note, :created_at,
                        :import_batch_id, :parse_attempt_id,
                        :parsed_source_row_id, :parse_baseline_id,
                        :parse_baseline_row_id
                    )
                    """
                ),
                {
                    "validation_run_id": validation_run_id,
                    "version_id": scope.version_id,
                    "row_id": persisted.version_row_id,
                    "severity": issue.severity,
                    "rule_code": issue.code,
                    "field_name": issue.field_name,
                    "message": issue.message,
                    "source_value_json": source_value_json,
                    "processed_value_json": processed_value_json,
                    "details_json": _canonical_json(
                        {
                            "schema_version": 1,
                            "stage": issue.stage,
                            "source_row_number": issue.source_row_number,
                        }
                    ),
                    "requires_note": issue.requires_note,
                    "created_at": occurred_at,
                    "import_batch_id": persisted.import_batch_id,
                    "parse_attempt_id": persisted.parse_attempt_id,
                    "parsed_source_row_id": persisted.parsed_source_row_id,
                    "parse_baseline_id": persisted.parse_baseline_id,
                    "parse_baseline_row_id": persisted.parse_baseline_row_id,
                },
            )
            if inserted_issue.rowcount != 1:
                raise ValidationPersistenceError("validation issue was not stored")
        inserted_result = connection.execute(
            sa.text(
                """
                INSERT INTO review_operation_results (
                    operation_token, operation_kind, operation_digest,
                    actor_user_id, result_kind, result_import_batch_id,
                    result_dataset_id, result_version_id, result_status,
                    result_data_revision, result_review_revision,
                    affected_row_id, data_change_event_id,
                    issue_review_event_id, validation_run_id,
                    version_review_event_id, note_id, completed_at
                ) VALUES (
                    :operation_token, 'run_validation', :operation_digest,
                    :actor_user_id, 'applied', NULL,
                    :dataset_id, :version_id, :version_status,
                    :data_revision, :review_revision,
                    NULL, NULL, NULL, :validation_run_id,
                    NULL, NULL, :completed_at
                )
                """
            ),
            {
                "operation_token": command.operation_token.bytes,
                "operation_digest": command.operation_digest,
                "actor_user_id": actor.user_id,
                "dataset_id": scope.dataset_id,
                "version_id": scope.version_id,
                "version_status": scope.version_status,
                "data_revision": scope.data_revision,
                "review_revision": scope.review_revision,
                "validation_run_id": validation_run_id,
                "completed_at": occurred_at,
            },
        )
        if inserted_result.rowcount != 1:
            raise ValidationPersistenceError(
                "validation operation result was not stored"
            )
        completed_at = (
            occurred_at.replace(tzinfo=UTC)
            if occurred_at.tzinfo is None
            else occurred_at.astimezone(UTC)
        )
        return ValidationRunReceipt(
            operation_token=command.operation_token,
            validation_run_id=validation_run_id,
            dataset_id=scope.dataset_id,
            version_id=scope.version_id,
            version_status=scope.version_status,
            data_revision=scope.data_revision,
            review_revision=scope.review_revision,
            ruleset_version=scope.ruleset_version,
            status="succeeded",
            result=outcome,
            data_digest=data_digest,
            summary=evaluation.summary,
            completed_at=completed_at,
        )
