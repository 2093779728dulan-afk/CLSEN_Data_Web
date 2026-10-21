"""MySQL persistence for append-only parse attempts and typed baselines."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import fields
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.catalog.normalization import seller_sku_match_v1
from app.imports.types import ReportType
from app.parsers import PARSER_VERSION, REPORT_RULES
from app.parsers.types import (
    BusinessReportRow,
    ParsedReport,
    RecognitionResult,
    ReturnReportRow,
)
from app.parsers.workflow import (
    BatchSource,
    ChangeReportDateCommand,
    ConfirmAndParseCommand,
    ConfirmedParseContext,
    FailedParse,
    ParseFailure,
    SuccessfulParse,
)

_REPORT_DATE_CHANGE_EVENT = "import_report_date_change_applied"
_PARSE_TOKEN_BATCH_CONFLICT = "operation token belongs to another import batch"
_PARSE_TOKEN_COMMAND_CONFLICT = (
    "operation token was reused with different parse choices"
)
_DATE_TOKEN_BATCH_CONFLICT = (
    "date-change operation token belongs to another import batch"
)
_DATE_TOKEN_COMMAND_CONFLICT = (
    "date-change operation token was reused with different command fields"
)


class ParseRepositoryError(RuntimeError):
    """Base class for persistence failures with no partial committed result."""


class BatchNotFound(ParseRepositoryError):
    """The requested import batch does not exist."""


class BatchSourceUnavailable(ParseRepositoryError):
    """The batch source object is not currently safe to parse."""


class ParseAlreadyRunning(ParseRepositoryError):
    """A non-stale processing lease already owns the batch."""


class ParseStateConflict(ParseRepositoryError):
    """The batch no longer matches the frozen parse context."""


class ParseCommitOutcomeUnknown(ParseRepositoryError):
    """A parser-domain write may have committed but could not be recovered."""


def _mysql_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("database timestamps must be timezone-aware")
    return value.astimezone(UTC).replace(tzinfo=None)


def _is_pymysql_duplicate_key(error: IntegrityError) -> bool:
    """Recognize only PyMySQL's duplicate-key error, never another constraint."""

    original = error.orig
    if original is None:
        return False
    original_type = type(original)
    return (
        original_type.__module__ == "pymysql.err"
        and original_type.__name__ == "IntegrityError"
        and bool(original.args)
        and original.args[0] == 1062
    )


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _source_row_digest(source_row_number: int, values: tuple[str, ...]) -> bytes:
    return hashlib.sha256(
        _canonical_json(
            {
                "source_row_number": source_row_number,
                "raw_values": values,
            }
        ).encode("utf-8")
    ).digest()


def _decoded_fields(
    header: tuple[str, ...],
    values: tuple[str, ...],
) -> str:
    # Keep the two ordered arrays separate.  A failed attempt may contain a
    # short or long row; preserving that exact structural defect is the point
    # of the immutable source snapshot.
    return _canonical_json(
        {
            "header": header,
            "values": values,
        }
    )


def _field_mapping(report_type: ReportType, header: tuple[str, ...]) -> str:
    rule = REPORT_RULES[report_type]
    normalised_header = tuple(value.strip() for value in header)
    if len(normalised_header) != len(set(normalised_header)):
        raise ParseRepositoryError("parsed header contains duplicates")
    source_by_normalised = dict(zip(normalised_header, header, strict=True))
    if not set(rule.normalised_header) <= set(source_by_normalised):
        raise ParseRepositoryError("parsed header does not match the persisted rule")
    return _canonical_json(
        {
            "source_header": header,
            "fields": [
                {
                    "source": source_by_normalised[field.source_name.strip()],
                    "target": field.target_name,
                    "kind": field.kind.value,
                }
                for field in rule.fields
            ],
        }
    )


def _redacted_detection_summary(result: RecognitionResult) -> str:
    return _canonical_json(
        {
            "status": result.status,
            "encoding": result.encoding,
            "ruleset_version": result.ruleset_version,
            "header": result.header,
            "issue_codes": [issue.code for issue in result.issues],
        }
    )


class MySqlParseRepository:
    """Use short transactions and terminal inserts for immutable parse history."""

    def __init__(
        self,
        engine: Engine,
        *,
        processing_timeout: timedelta = timedelta(minutes=30),
    ) -> None:
        if processing_timeout <= timedelta(0):
            raise ValueError("processing_timeout must be positive")
        self._engine = engine
        self._processing_timeout = processing_timeout

    def get_batch_source(self, batch_id: int) -> BatchSource:
        if batch_id < 1:
            raise ValueError("batch_id must be positive")
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT batches.id, files.original_filename,
                           files.storage_key, HEX(files.sha256) AS sha256_hex,
                           files.size_bytes, integrity.status AS integrity_status
                    FROM import_batches AS batches
                    INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
                    LEFT JOIN raw_file_integrity_statuses AS integrity
                        ON integrity.raw_file_id = files.id
                    WHERE batches.id = :batch_id
                    LIMIT 1
                    """
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .first()
            )
        if row is None:
            raise BatchNotFound("import batch does not exist")
        if row["integrity_status"] != "available":
            raise BatchSourceUnavailable("batch source integrity is not available")
        return self._batch_source(row)

    def record_recognition(
        self,
        *,
        batch_id: int,
        result: RecognitionResult,
        detector_version: str,
        detected_at: datetime,
    ) -> None:
        timestamp = _mysql_datetime(detected_at)
        summary = _redacted_detection_summary(result)
        with self._engine.begin() as connection:
            batch = (
                connection.execute(
                    sa.text(
                        """
                    SELECT site_id, status
                    FROM import_batches
                    WHERE id = :batch_id
                    FOR UPDATE
                    """
                    ),
                    {"batch_id": batch_id},
                )
                .mappings()
                .first()
            )
            if batch is None:
                raise BatchNotFound("import batch does not exist")
            if batch["status"] == "rejected":
                raise ParseStateConflict("a rejected batch cannot be inspected")
            connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET detected_report_type = :detected_report_type,
                        detected_report_date = :detected_report_date,
                        candidate_report_date = COALESCE(
                            :detected_report_date,
                            candidate_report_date
                        ),
                        detector_version = :detector_version,
                        detection_summary = :detection_summary,
                        detected_at = :detected_at,
                        updated_at = :detected_at
                    WHERE id = :batch_id
                    """
                ),
                {
                    "batch_id": batch_id,
                    "detected_report_type": result.report_type,
                    "detected_report_date": result.detected_report_date,
                    "detector_version": detector_version,
                    "detection_summary": summary,
                    "detected_at": timestamp,
                },
            )
            self._insert_audit(
                connection,
                site_id=int(batch["site_id"]),
                actor_user_id=None,
                event_type="import_report_detected",
                batch_id=batch_id,
                payload={
                    "detector_version": detector_version,
                    "status": result.status,
                    "report_type": result.report_type,
                    "detected_report_date": (
                        result.detected_report_date.isoformat()
                        if result.detected_report_date is not None
                        else None
                    ),
                    "encoding": result.encoding,
                    "ruleset_version": result.ruleset_version,
                    "issue_codes": [issue.code for issue in result.issues],
                },
                occurred_at=timestamp,
            )

    def change_report_date(
        self,
        *,
        command: ChangeReportDateCommand,
        changed_at: datetime,
    ) -> None:
        """Change the human-owned batch date without creating a parse attempt."""

        try:
            self._change_report_date(command=command, changed_at=changed_at)
        except DBAPIError as error:
            if not error.connection_invalidated:
                raise
            self._recover_report_date_change_after_unknown_commit(
                command,
                original_error=error,
            )

    def _change_report_date(
        self,
        *,
        command: ChangeReportDateCommand,
        changed_at: datetime,
    ) -> None:
        timestamp = _mysql_datetime(changed_at)
        with self._engine.begin() as connection:
            row = self._lock_report_date_batch(connection, command.batch_id)
            registered = self._claim_report_date_operation(
                connection,
                command=command,
                registered_at=timestamp,
            )
            if not registered:
                self._recover_report_date_change_on_connection(connection, command)
                return
            if row["status"] == "processing":
                raise ParseAlreadyRunning(
                    "report date cannot change while parsing is active"
                )
            if row["status"] == "rejected":
                raise ParseStateConflict("a rejected batch date cannot be changed")
            # A future materialization service must take this same batch row lock
            # before inserting version_input_batches, so this check cannot race it.
            materialized = connection.scalar(
                sa.text(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM version_input_batches
                        WHERE batch_id = :batch_id
                    )
                    """
                ),
                {"batch_id": command.batch_id},
            )
            if materialized == 1:
                raise ParseStateConflict(
                    "a materialized batch report date cannot be changed"
                )

            previous_date = row["report_date"]
            changed = previous_date != command.report_date
            if changed:
                updated = connection.execute(
                    sa.text(
                        """
                        UPDATE import_batches
                        SET report_date = :report_date,
                            candidate_report_date = :report_date,
                            updated_at = :changed_at
                        WHERE id = :batch_id
                        """
                    ),
                    {
                        "batch_id": command.batch_id,
                        "report_date": command.report_date,
                        "changed_at": timestamp,
                    },
                )
                if updated.rowcount != 1:
                    raise ParseStateConflict("batch date changed concurrently")
            self._insert_audit(
                connection,
                site_id=int(row["site_id"]),
                actor_user_id=command.actor_user_id,
                event_type=_REPORT_DATE_CHANGE_EVENT,
                batch_id=command.batch_id,
                payload={
                    "status": "applied",
                    "operation_digest": command.operation_digest.hex(),
                    "previous_report_date": (
                        previous_date.isoformat()
                        if isinstance(previous_date, date)
                        else None
                    ),
                    "report_date": command.report_date.isoformat(),
                    "changed": changed,
                },
                occurred_at=timestamp,
                request_id=str(command.operation_token),
            )

    @classmethod
    def _claim_report_date_operation(
        cls,
        connection: Connection,
        *,
        command: ChangeReportDateCommand,
        registered_at: datetime,
    ) -> bool:
        """Atomically reserve a date-change token before any business mutation."""

        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO report_date_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :operation_token, :batch_id,
                        :operation_digest, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": command.operation_token.bytes,
                    "batch_id": command.batch_id,
                    "operation_digest": command.operation_digest,
                    "registered_at": registered_at,
                },
            )
        except IntegrityError as error:
            savepoint.rollback()
            if not _is_pymysql_duplicate_key(error):
                raise
        else:
            savepoint.commit()
            return True

        registration = cls._lock_report_date_operation_registration(
            connection,
            command.operation_token,
        )
        if registration is None:
            raise ParseStateConflict(
                "date-change operation token registration disappeared"
            )
        cls._validate_operation_registration(
            registration,
            expected_batch_id=command.batch_id,
            operation_digest=command.operation_digest,
            batch_conflict=_DATE_TOKEN_BATCH_CONFLICT,
            command_conflict=_DATE_TOKEN_COMMAND_CONFLICT,
        )
        return False

    @staticmethod
    def _lock_report_date_operation_registration(
        connection: Connection,
        operation_token: UUID,
    ) -> RowMapping | None:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT batch_id, operation_digest
                    FROM report_date_operation_tokens
                    WHERE operation_token = :operation_token
                    FOR UPDATE
                    """
                ),
                {"operation_token": operation_token.bytes},
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _validate_operation_registration(
        registration: RowMapping,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
        batch_conflict: str,
        command_conflict: str,
    ) -> None:
        if int(registration["batch_id"]) != expected_batch_id:
            raise ParseStateConflict(batch_conflict)
        stored_digest = registration["operation_digest"]
        if not isinstance(stored_digest, (bytes, bytearray, memoryview)) or not (
            hmac.compare_digest(bytes(stored_digest), operation_digest)
        ):
            raise ParseStateConflict(command_conflict)

    @staticmethod
    def _lock_report_date_batch(
        connection: Connection,
        batch_id: int,
    ) -> RowMapping:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT site_id, status, report_date
                FROM import_batches
                WHERE id = :batch_id
                FOR UPDATE
                """
                ),
                {"batch_id": batch_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise BatchNotFound("import batch does not exist")
        return row

    def _recover_report_date_change_on_connection(
        self,
        connection: Connection,
        command: ChangeReportDateCommand,
    ) -> bool:
        registration = self._lock_report_date_operation_registration(
            connection,
            command.operation_token,
        )
        if registration is None:
            return False
        self._validate_operation_registration(
            registration,
            expected_batch_id=command.batch_id,
            operation_digest=command.operation_digest,
            batch_conflict=_DATE_TOKEN_BATCH_CONFLICT,
            command_conflict=_DATE_TOKEN_COMMAND_CONFLICT,
        )
        rows = (
            connection.execute(
                sa.text(
                    """
                    SELECT actor_user_id, object_type, object_id,
                           redacted_payload
                    FROM audit_events
                    WHERE event_type = :event_type
                      AND request_id = :request_id
                    ORDER BY id
                    LIMIT 2
                    """
                ),
                {
                    "event_type": _REPORT_DATE_CHANGE_EVENT,
                    "request_id": str(command.operation_token),
                },
            )
            .mappings()
            .all()
        )
        if not rows:
            raise ParseStateConflict(
                "date-change operation token has no terminal audit event"
            )
        if len(rows) != 1:
            raise ParseStateConflict(
                "date-change operation token has multiple terminal audit events"
            )

        row = rows[0]
        payload = self._json_object(row["redacted_payload"])
        stored_digest = payload.get("operation_digest")
        if not isinstance(stored_digest, str) or not hmac.compare_digest(
            stored_digest,
            command.operation_digest.hex(),
        ):
            raise ParseStateConflict(_DATE_TOKEN_COMMAND_CONFLICT)
        if (
            row["object_type"] != "import_batch"
            or row["object_id"] != str(command.batch_id)
            or row["actor_user_id"] != command.actor_user_id
            or payload.get("status") != "applied"
            or payload.get("report_date") != command.report_date.isoformat()
        ):
            raise ParseStateConflict(
                "date-change terminal audit does not match its operation digest"
            )
        return True

    def _recover_report_date_change_after_unknown_commit(
        self,
        command: ChangeReportDateCommand,
        *,
        original_error: DBAPIError,
    ) -> None:
        try:
            with self._engine.begin() as connection:
                self._lock_report_date_batch(connection, command.batch_id)
                recovered = self._recover_report_date_change_on_connection(
                    connection,
                    command,
                )
        except Exception as recovery_error:
            raise ParseCommitOutcomeUnknown(
                "report-date commit acknowledgement was lost and recovery failed"
            ) from recovery_error
        if not recovered:
            raise ParseCommitOutcomeUnknown(
                "report-date commit acknowledgement was lost and no result was found"
            ) from original_error

    def begin_parse(
        self,
        *,
        command: ConfirmAndParseCommand,
        processing_token: UUID,
        started_at: datetime,
    ) -> ConfirmedParseContext | SuccessfulParse | FailedParse:
        if processing_token != command.operation_token:
            raise ValueError("processing token must match the command operation token")
        try:
            return self._begin_parse(
                command=command,
                processing_token=processing_token,
                started_at=started_at,
            )
        except DBAPIError as error:
            if not error.connection_invalidated:
                raise
            try:
                return self._begin_parse(
                    command=command,
                    processing_token=processing_token,
                    started_at=started_at,
                )
            except DBAPIError as recovery_error:
                raise ParseCommitOutcomeUnknown(
                    "begin-parse commit acknowledgement was lost and recovery failed"
                ) from recovery_error

    def _begin_parse(
        self,
        *,
        command: ConfirmAndParseCommand,
        processing_token: UUID,
        started_at: datetime,
    ) -> ConfirmedParseContext | SuccessfulParse | FailedParse:
        timestamp = _mysql_datetime(started_at)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    sa.text(
                        """
                    SELECT batches.id, batches.site_id, batches.status,
                           batches.site_config_version_id,
                           batches.processing_started_at,
                           batches.processing_token,
                           batches.processing_operation_digest,
                           batches.confirmation_revision,
                           batches.confirmed_report_type,
                           batches.report_date,
                           files.original_filename, files.storage_key,
                           HEX(files.sha256) AS sha256_hex, files.size_bytes,
                           integrity.status AS integrity_status,
                           configs.source_timezone
                    FROM import_batches AS batches
                    INNER JOIN raw_files AS files ON files.id = batches.raw_file_id
                    LEFT JOIN raw_file_integrity_statuses AS integrity
                        ON integrity.raw_file_id = files.id
                    INNER JOIN site_config_versions AS configs
                        ON configs.site_id = batches.site_id
                       AND configs.id = batches.site_config_version_id
                    WHERE batches.id = :batch_id
                    FOR UPDATE OF batches
                    """
                    ),
                    {"batch_id": command.batch_id},
                )
                .mappings()
                .first()
            )
            if row is None:
                if self._batch_exists(connection, command.batch_id):
                    raise ParseStateConflict(
                        "the batch site configuration is unavailable"
                    )
                raise BatchNotFound("import batch does not exist")

            frozen_site_config_version_id = int(row["site_config_version_id"])
            if command.site_config_version_id != frozen_site_config_version_id:
                raise ParseStateConflict(
                    "requested site configuration does not match the frozen batch "
                    "configuration"
                )

            registered = self._claim_parse_operation(
                connection,
                processing_token=processing_token,
                batch_id=command.batch_id,
                operation_digest=command.operation_digest,
                registered_at=timestamp,
            )
            if not registered:
                terminal = self._recover_terminal_on_connection(
                    connection,
                    processing_token,
                    expected_batch_id=command.batch_id,
                    operation_digest=command.operation_digest,
                    lock_rows=True,
                )
                if terminal is not None:
                    return terminal
                active_token = row["processing_token"]
                if active_token is None or not hmac.compare_digest(
                    bytes(active_token),
                    processing_token.bytes,
                ):
                    raise ParseStateConflict(
                        "operation token no longer owns an active parse lease"
                    )
                active_digest = row["processing_operation_digest"]
                if active_digest is None or not hmac.compare_digest(
                    bytes(active_digest),
                    command.operation_digest,
                ):
                    raise ParseStateConflict(_PARSE_TOKEN_COMMAND_CONFLICT)
                if row["status"] != "processing":
                    raise ParseStateConflict(
                        "operation token is not attached to an active parse"
                    )
                active_started_at = row["processing_started_at"]
                if not isinstance(active_started_at, datetime):
                    raise ParseStateConflict(
                        "active parse has no valid processing timestamp"
                    )
                return ConfirmedParseContext(
                    source=self._batch_source(row),
                    site_id=int(row["site_id"]),
                    site_config_version_id=frozen_site_config_version_id,
                    source_timezone=(
                        str(row["source_timezone"])
                        if row["source_timezone"] is not None
                        else None
                    ),
                    report_type=command.report_type,
                    report_date=command.report_date,
                    encoding=command.encoding,
                    confirmation_revision=int(row["confirmation_revision"]),
                    actor_user_id=command.actor_user_id,
                    processing_token=processing_token,
                    operation_digest=command.operation_digest,
                    started_at=active_started_at.replace(tzinfo=UTC),
                )

            if row["integrity_status"] != "available":
                raise BatchSourceUnavailable("batch source integrity is not available")
            if row["status"] == "rejected":
                raise ParseStateConflict("a rejected batch cannot be parsed")

            reclaimed = self._require_available_processing_lease(row, timestamp)
            confirmation_revision = int(row["confirmation_revision"]) + 1
            if reclaimed:
                previous_started_at = row["processing_started_at"]
                self._insert_audit(
                    connection,
                    site_id=int(row["site_id"]),
                    actor_user_id=command.actor_user_id,
                    event_type="parse_processing_abandoned",
                    batch_id=command.batch_id,
                    payload={
                        "confirmation_revision": int(row["confirmation_revision"]),
                        "report_type": row["confirmed_report_type"],
                        "started_at": (
                            previous_started_at.isoformat(timespec="microseconds")
                            if isinstance(previous_started_at, datetime)
                            else None
                        ),
                    },
                    occurred_at=timestamp,
                )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET confirmed_report_type = :report_type,
                        report_date = :report_date,
                        candidate_report_date = :report_date,
                        confirmation_revision = :confirmation_revision,
                        confirmed_by_user_id = :actor_user_id,
                        confirmed_at = :started_at,
                        status = 'processing',
                        processing_token = :processing_token,
                        processing_operation_digest = :operation_digest,
                        processing_started_at = :started_at,
                        error_summary = NULL,
                        updated_at = :started_at
                    WHERE id = :batch_id
                    """
                ),
                {
                    "batch_id": command.batch_id,
                    "report_type": command.report_type,
                    "report_date": command.report_date,
                    "confirmation_revision": confirmation_revision,
                    "actor_user_id": command.actor_user_id,
                    "processing_token": processing_token.bytes,
                    "operation_digest": command.operation_digest,
                    "started_at": timestamp,
                },
            )
            if updated.rowcount != 1:
                raise ParseStateConflict("batch confirmation changed concurrently")

            payload: dict[str, object] = {
                "confirmation_revision": confirmation_revision,
                "report_type": command.report_type,
                "report_date": command.report_date.isoformat(),
                "encoding": command.encoding,
                "site_config_version_id": frozen_site_config_version_id,
            }
            if reclaimed:
                payload["reclaimed_stale_processing"] = True
            self._insert_audit(
                connection,
                site_id=int(row["site_id"]),
                actor_user_id=command.actor_user_id,
                event_type="import_selection_confirmed",
                batch_id=command.batch_id,
                payload=payload,
                occurred_at=timestamp,
            )

            source = self._batch_source(row)
            source_timezone_value = row["source_timezone"]
            source_timezone = (
                str(source_timezone_value)
                if source_timezone_value is not None
                else None
            )
            return ConfirmedParseContext(
                source=source,
                site_id=int(row["site_id"]),
                site_config_version_id=frozen_site_config_version_id,
                source_timezone=source_timezone,
                report_type=command.report_type,
                report_date=command.report_date,
                encoding=command.encoding,
                confirmation_revision=confirmation_revision,
                actor_user_id=command.actor_user_id,
                processing_token=processing_token,
                operation_digest=command.operation_digest,
                started_at=started_at,
            )

    @classmethod
    def _claim_parse_operation(
        cls,
        connection: Connection,
        *,
        processing_token: UUID,
        batch_id: int,
        operation_digest: bytes,
        registered_at: datetime,
    ) -> bool:
        """Reserve a globally unique parse token inside a savepoint."""

        savepoint = connection.begin_nested()
        try:
            connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_operation_tokens (
                        operation_token, batch_id,
                        operation_digest, registered_at
                    ) VALUES (
                        :operation_token, :batch_id,
                        :operation_digest, :registered_at
                    )
                    """
                ),
                {
                    "operation_token": processing_token.bytes,
                    "batch_id": batch_id,
                    "operation_digest": operation_digest,
                    "registered_at": registered_at,
                },
            )
        except IntegrityError as error:
            savepoint.rollback()
            if not _is_pymysql_duplicate_key(error):
                raise
        else:
            savepoint.commit()
            return True

        registration = cls._lock_parse_operation_registration(
            connection,
            processing_token,
        )
        if registration is None:
            raise ParseStateConflict("operation token registration disappeared")
        cls._validate_operation_registration(
            registration,
            expected_batch_id=batch_id,
            operation_digest=operation_digest,
            batch_conflict=_PARSE_TOKEN_BATCH_CONFLICT,
            command_conflict=_PARSE_TOKEN_COMMAND_CONFLICT,
        )
        return False

    @staticmethod
    def _lock_parse_operation_registration(
        connection: Connection,
        processing_token: UUID,
    ) -> RowMapping | None:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT batch_id, operation_digest
                    FROM parse_operation_tokens
                    WHERE operation_token = :processing_token
                    FOR SHARE
                    """
                ),
                {"processing_token": processing_token.bytes},
            )
            .mappings()
            .first()
        )

    @staticmethod
    def _read_parse_operation_registration(
        connection: Connection,
        processing_token: UUID,
    ) -> RowMapping | None:
        return (
            connection.execute(
                sa.text(
                    """
                    SELECT batch_id, operation_digest
                    FROM parse_operation_tokens
                    WHERE operation_token = :processing_token
                    """
                ),
                {"processing_token": processing_token.bytes},
            )
            .mappings()
            .first()
        )

    def finish_success(
        self,
        *,
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
        completed_at: datetime,
    ) -> SuccessfulParse:
        recovered = self.recover_terminal(
            context.processing_token,
            expected_batch_id=context.source.batch_id,
            operation_digest=context.operation_digest,
        )
        if recovered is not None:
            if isinstance(recovered, SuccessfulParse):
                return recovered
            raise ParseStateConflict(
                "processing token already resolved to a failed parse attempt"
            )
        try:
            return self._finish_success(
                context=context,
                parsed_report=parsed_report,
                completed_at=completed_at,
            )
        except ParseStateConflict:
            recovered = self.recover_terminal(
                context.processing_token,
                expected_batch_id=context.source.batch_id,
                operation_digest=context.operation_digest,
            )
            if isinstance(recovered, SuccessfulParse):
                return recovered
            raise
        except DBAPIError as error:
            if not error.connection_invalidated:
                raise
            recovered = self._recover_after_unknown_commit(
                context.processing_token,
                expected_batch_id=context.source.batch_id,
                operation_digest=context.operation_digest,
                original_error=error,
            )
            if isinstance(recovered, SuccessfulParse):
                return recovered
            raise ParseCommitOutcomeUnknown(
                "processing token resolved to a failed parse attempt"
            ) from error

    def _finish_success(
        self,
        *,
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
        completed_at: datetime,
    ) -> SuccessfulParse:
        self._validate_success(context, parsed_report)
        completed_timestamp = _mysql_datetime(completed_at)
        with self._engine.begin() as connection:
            self._lock_owned_context(connection, context)
            attempt_number = self._next_attempt_number(
                connection,
                context.source.batch_id,
            )
            attempt_id = self._insert_successful_attempt(
                connection,
                context=context,
                parsed_report=parsed_report,
                attempt_number=attempt_number,
                completed_at=completed_timestamp,
            )
            source_row_ids = self._insert_source_rows(
                connection,
                attempt_id=attempt_id,
                header=parsed_report.header,
                rows=tuple(
                    (
                        row.source_row_number,
                        row.raw_values,
                        bytes.fromhex(row.row_digest),
                    )
                    for row in parsed_report.source_rows
                ),
            )
            baseline_id = self._insert_baseline(
                connection,
                attempt_id=attempt_id,
                parsed_report=parsed_report,
            )
            self._insert_typed_baseline_rows(
                connection,
                attempt_id=attempt_id,
                baseline_id=baseline_id,
                source_row_ids=source_row_ids,
                parsed_report=parsed_report,
            )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET report_type = :report_type,
                        current_successful_parse_attempt_id = :attempt_id,
                        source_row_count = :source_row_count,
                        status = 'staged',
                        processing_token = NULL,
                        processing_operation_digest = NULL,
                        processing_started_at = NULL,
                        error_summary = NULL,
                        updated_at = :completed_at
                    WHERE id = :batch_id
                      AND processing_token = :processing_token
                      AND confirmation_revision = :confirmation_revision
                    """
                ),
                {
                    "batch_id": context.source.batch_id,
                    "report_type": context.report_type,
                    "attempt_id": attempt_id,
                    "source_row_count": parsed_report.summary.row_count,
                    "processing_token": context.processing_token.bytes,
                    "confirmation_revision": context.confirmation_revision,
                    "completed_at": completed_timestamp,
                },
            )
            if updated.rowcount != 1:
                raise ParseStateConflict("processing ownership changed before success")
            self._insert_audit(
                connection,
                site_id=context.site_id,
                actor_user_id=context.actor_user_id,
                event_type="parse_attempt_succeeded",
                batch_id=context.source.batch_id,
                payload={
                    "parse_attempt_id": attempt_id,
                    "parse_baseline_id": baseline_id,
                    "confirmation_revision": context.confirmation_revision,
                    "report_type": context.report_type,
                    "row_count": parsed_report.summary.row_count,
                    "data_digest": parsed_report.summary.data_digest,
                },
                occurred_at=completed_timestamp,
            )
        return SuccessfulParse(
            batch_id=context.source.batch_id,
            parse_attempt_id=attempt_id,
            parse_baseline_id=baseline_id,
            confirmation_revision=context.confirmation_revision,
            report_type=context.report_type,
            source_row_count=parsed_report.summary.row_count,
        )

    def finish_failure(
        self,
        *,
        context: ConfirmedParseContext,
        failure: ParseFailure,
        completed_at: datetime,
    ) -> FailedParse:
        recovered = self.recover_terminal(
            context.processing_token,
            expected_batch_id=context.source.batch_id,
            operation_digest=context.operation_digest,
        )
        if recovered is not None:
            if isinstance(recovered, FailedParse):
                return recovered
            raise ParseStateConflict(
                "processing token already resolved to a successful parse attempt"
            )
        try:
            return self._finish_failure(
                context=context,
                failure=failure,
                completed_at=completed_at,
            )
        except ParseStateConflict:
            recovered = self.recover_terminal(
                context.processing_token,
                expected_batch_id=context.source.batch_id,
                operation_digest=context.operation_digest,
            )
            if isinstance(recovered, FailedParse):
                return recovered
            raise
        except DBAPIError as error:
            if not error.connection_invalidated:
                raise
            recovered = self._recover_after_unknown_commit(
                context.processing_token,
                expected_batch_id=context.source.batch_id,
                operation_digest=context.operation_digest,
                original_error=error,
            )
            if isinstance(recovered, FailedParse):
                return recovered
            raise ParseCommitOutcomeUnknown(
                "processing token resolved to a successful parse attempt"
            ) from error

    def _finish_failure(
        self,
        *,
        context: ConfirmedParseContext,
        failure: ParseFailure,
        completed_at: datetime,
    ) -> FailedParse:
        completed_timestamp = _mysql_datetime(completed_at)
        with self._engine.begin() as connection:
            self._lock_owned_context(connection, context)
            attempt_number = self._next_attempt_number(
                connection,
                context.source.batch_id,
            )
            source_row_count = (
                len(failure.decoded_rows)
                if failure.decoded_header is not None
                else None
            )
            error_summary = {
                "code": failure.code,
                "source_row_number": failure.source_row_number,
                "field_name": failure.field_name,
            }
            attempt = connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_attempts (
                        batch_id, site_id, processing_token, operation_digest,
                        site_config_version_id, report_type,
                        confirmation_revision, attempt_number,
                        parser_version, ruleset_version, encoding, delimiter,
                        field_mapping, status, source_row_count,
                        result_summary, error_summary, created_by_user_id,
                        started_at, completed_at
                    ) VALUES (
                        :batch_id, :site_id, :processing_token, :operation_digest,
                        :site_config_version_id, :report_type,
                        :confirmation_revision, :attempt_number,
                        :parser_version, :ruleset_version, :encoding, ',',
                        :field_mapping, 'failed', :source_row_count,
                        NULL, :error_summary, :created_by_user_id,
                        :started_at, :completed_at
                    )
                    """
                ),
                {
                    "batch_id": context.source.batch_id,
                    "site_id": context.site_id,
                    "processing_token": context.processing_token.bytes,
                    "operation_digest": context.operation_digest,
                    "site_config_version_id": context.site_config_version_id,
                    "report_type": context.report_type,
                    "confirmation_revision": context.confirmation_revision,
                    "attempt_number": attempt_number,
                    "parser_version": PARSER_VERSION,
                    "ruleset_version": REPORT_RULES[context.report_type].version,
                    "encoding": context.encoding,
                    "field_mapping": self._failure_field_mapping(
                        context.report_type,
                        failure.decoded_header,
                    ),
                    "source_row_count": source_row_count,
                    "error_summary": _canonical_json(error_summary),
                    "created_by_user_id": context.actor_user_id,
                    "started_at": _mysql_datetime(context.started_at),
                    "completed_at": completed_timestamp,
                },
            )
            if attempt.lastrowid is None:
                raise ParseRepositoryError(
                    "database did not return the parse attempt ID"
                )
            attempt_id = int(attempt.lastrowid)
            if failure.decoded_header is not None:
                self._insert_source_rows(
                    connection,
                    attempt_id=attempt_id,
                    header=failure.decoded_header,
                    rows=tuple(
                        (
                            source_row_number,
                            values,
                            _source_row_digest(source_row_number, values),
                        )
                        for source_row_number, values in enumerate(
                            failure.decoded_rows,
                            start=2,
                        )
                    ),
                )
            updated = connection.execute(
                sa.text(
                    """
                    UPDATE import_batches
                    SET status = 'processing_failed',
                        processing_token = NULL,
                        processing_operation_digest = NULL,
                        processing_started_at = NULL,
                        error_summary = :error_summary,
                        updated_at = :completed_at
                    WHERE id = :batch_id
                      AND processing_token = :processing_token
                      AND confirmation_revision = :confirmation_revision
                    """
                ),
                {
                    "batch_id": context.source.batch_id,
                    "processing_token": context.processing_token.bytes,
                    "confirmation_revision": context.confirmation_revision,
                    "error_summary": _canonical_json(error_summary),
                    "completed_at": completed_timestamp,
                },
            )
            if updated.rowcount != 1:
                raise ParseStateConflict("processing ownership changed before failure")
            self._insert_audit(
                connection,
                site_id=context.site_id,
                actor_user_id=context.actor_user_id,
                event_type="parse_attempt_failed",
                batch_id=context.source.batch_id,
                payload={
                    "parse_attempt_id": attempt_id,
                    "confirmation_revision": context.confirmation_revision,
                    "report_type": context.report_type,
                    **error_summary,
                },
                occurred_at=completed_timestamp,
            )
        return FailedParse(
            batch_id=context.source.batch_id,
            parse_attempt_id=attempt_id,
            confirmation_revision=context.confirmation_revision,
            error_code=failure.code,
        )

    def recover_terminal(
        self,
        processing_token: UUID,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
    ) -> SuccessfulParse | FailedParse | None:
        """Recover an idempotent result after a lost response or commit ack."""

        if len(operation_digest) != 32:
            raise ValueError("operation_digest must be a SHA-256 digest")
        with self._engine.connect() as connection:
            return self._recover_terminal_on_connection(
                connection,
                processing_token,
                expected_batch_id=expected_batch_id,
                operation_digest=operation_digest,
            )

    def _recover_terminal_on_connection(
        self,
        connection: Connection,
        processing_token: UUID,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
        lock_rows: bool = False,
    ) -> SuccessfulParse | FailedParse | None:
        registration = (
            self._lock_parse_operation_registration(connection, processing_token)
            if lock_rows
            else self._read_parse_operation_registration(connection, processing_token)
        )
        if registration is None:
            return None
        self._validate_operation_registration(
            registration,
            expected_batch_id=expected_batch_id,
            operation_digest=operation_digest,
            batch_conflict=_PARSE_TOKEN_BATCH_CONFLICT,
            command_conflict=_PARSE_TOKEN_COMMAND_CONFLICT,
        )
        # Token registrations and terminal results are append-only. A shared
        # current read preserves retry visibility without granting UPDATE.
        locking_clause = " FOR SHARE" if lock_rows else ""
        row = (
            connection.execute(
                sa.text(
                    """
                    SELECT attempts.id, attempts.batch_id,
                           attempts.operation_digest,
                           attempts.confirmation_revision,
                           attempts.report_type, attempts.status,
                           attempts.source_row_count,
                           attempts.error_summary,
                           baselines.id AS baseline_id
                    FROM parse_attempts AS attempts
                    LEFT JOIN parse_baselines AS baselines
                        ON baselines.parse_attempt_id = attempts.id
                    WHERE attempts.processing_token = :processing_token
                    LIMIT 1
                    """
                    + locking_clause
                ),
                {"processing_token": processing_token.bytes},
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        if int(row["batch_id"]) != expected_batch_id:
            raise ParseStateConflict(_PARSE_TOKEN_BATCH_CONFLICT)
        stored_digest = row["operation_digest"]
        if stored_digest is None or not hmac.compare_digest(
            bytes(stored_digest),
            operation_digest,
        ):
            raise ParseStateConflict(_PARSE_TOKEN_COMMAND_CONFLICT)
        status = str(row["status"])
        if status == "succeeded":
            if row["baseline_id"] is None or row["source_row_count"] is None:
                raise ParseStateConflict(
                    "successful parse attempt has no complete baseline result"
                )
            return SuccessfulParse(
                batch_id=int(row["batch_id"]),
                parse_attempt_id=int(row["id"]),
                parse_baseline_id=int(row["baseline_id"]),
                confirmation_revision=int(row["confirmation_revision"]),
                report_type=cast(ReportType, str(row["report_type"])),
                source_row_count=int(row["source_row_count"]),
            )
        if status == "failed":
            summary = self._json_object(row["error_summary"])
            code = summary.get("code")
            return FailedParse(
                batch_id=int(row["batch_id"]),
                parse_attempt_id=int(row["id"]),
                confirmation_revision=int(row["confirmation_revision"]),
                error_code=str(code) if code is not None else "parse_failed",
            )
        raise ParseStateConflict("processing token belongs to a non-terminal attempt")

    def _recover_after_unknown_commit(
        self,
        processing_token: UUID,
        *,
        expected_batch_id: int,
        operation_digest: bytes,
        original_error: DBAPIError,
    ) -> SuccessfulParse | FailedParse:
        try:
            recovered = self.recover_terminal(
                processing_token,
                expected_batch_id=expected_batch_id,
                operation_digest=operation_digest,
            )
        except Exception as recovery_error:
            raise ParseCommitOutcomeUnknown(
                "terminal commit acknowledgement was lost and recovery failed"
            ) from recovery_error
        if recovered is None:
            raise ParseCommitOutcomeUnknown(
                "terminal commit acknowledgement was lost and no result was found"
            ) from original_error
        return recovered

    @staticmethod
    def _batch_source(row: RowMapping) -> BatchSource:
        return BatchSource(
            batch_id=int(row["id"]),
            original_filename=str(row["original_filename"]),
            storage_key=str(row["storage_key"]),
            sha256_hex=str(row["sha256_hex"]).lower(),
            size_bytes=int(row["size_bytes"]),
        )

    @staticmethod
    def _json_object(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return {str(key): item for key, item in value.items()}
        if isinstance(value, (bytes, bytearray, memoryview)):
            value = bytes(value).decode("utf-8")
        if isinstance(value, str):
            decoded: object = json.loads(value)
            if isinstance(decoded, dict):
                return {str(key): item for key, item in decoded.items()}
        return {}

    @staticmethod
    def _batch_exists(connection: Connection, batch_id: int) -> bool:
        return bool(
            connection.scalar(
                sa.text("SELECT EXISTS(SELECT 1 FROM import_batches WHERE id=:id)"),
                {"id": batch_id},
            )
            == 1
        )

    def _require_available_processing_lease(
        self,
        row: RowMapping,
        started_at: datetime,
    ) -> bool:
        if row["status"] != "processing":
            return False
        existing_started_at = row["processing_started_at"]
        if not isinstance(existing_started_at, datetime):
            raise ParseStateConflict("processing batch has no valid start time")
        if started_at - existing_started_at < self._processing_timeout:
            raise ParseAlreadyRunning("a parse is already running for this batch")
        return True

    @staticmethod
    def _lock_owned_context(
        connection: Connection,
        context: ConfirmedParseContext,
    ) -> None:
        row = (
            connection.execute(
                sa.text(
                    """
                SELECT site_id, site_config_version_id, status, processing_token,
                       processing_operation_digest,
                       confirmation_revision, confirmed_report_type,
                       report_date
                FROM import_batches
                WHERE id = :batch_id
                FOR UPDATE
                """
                ),
                {"batch_id": context.source.batch_id},
            )
            .mappings()
            .first()
        )
        if row is None:
            raise BatchNotFound("import batch does not exist")
        token = row["processing_token"]
        token_bytes = (
            bytes(token) if isinstance(token, (bytes, bytearray, memoryview)) else None
        )
        operation_digest = row["processing_operation_digest"]
        operation_digest_bytes = (
            bytes(operation_digest)
            if isinstance(operation_digest, (bytes, bytearray, memoryview))
            else None
        )
        if (
            row["status"] != "processing"
            or token_bytes != context.processing_token.bytes
            or operation_digest_bytes is None
            or not hmac.compare_digest(
                operation_digest_bytes,
                context.operation_digest,
            )
            or int(row["confirmation_revision"]) != context.confirmation_revision
            or row["confirmed_report_type"] != context.report_type
            or row["report_date"] != context.report_date
            or int(row["site_id"]) != context.site_id
            or int(row["site_config_version_id"]) != context.site_config_version_id
        ):
            raise ParseStateConflict("processing ownership or confirmation changed")

    @staticmethod
    def _next_attempt_number(connection: Connection, batch_id: int) -> int:
        value = connection.scalar(
            sa.text(
                """
                SELECT COALESCE(MAX(attempt_number), 0) + 1
                FROM parse_attempts
                WHERE batch_id = :batch_id
                """
            ),
            {"batch_id": batch_id},
        )
        if value is None:
            raise ParseRepositoryError("could not allocate a parse attempt number")
        return int(value)

    @staticmethod
    def _insert_successful_attempt(
        connection: Connection,
        *,
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
        attempt_number: int,
        completed_at: datetime,
    ) -> int:
        attempt = connection.execute(
            sa.text(
                """
                INSERT INTO parse_attempts (
                    batch_id, site_id, processing_token, operation_digest,
                    site_config_version_id, report_type,
                    confirmation_revision, attempt_number,
                    parser_version, ruleset_version, encoding, delimiter,
                    field_mapping, status, source_row_count,
                    result_summary, error_summary, created_by_user_id,
                    started_at, completed_at
                ) VALUES (
                    :batch_id, :site_id, :processing_token, :operation_digest,
                    :site_config_version_id, :report_type,
                    :confirmation_revision, :attempt_number,
                    :parser_version, :ruleset_version, :encoding, :delimiter,
                    :field_mapping, 'succeeded', :source_row_count,
                    :result_summary, NULL, :created_by_user_id,
                    :started_at, :completed_at
                )
                """
            ),
            {
                "batch_id": context.source.batch_id,
                "site_id": context.site_id,
                "processing_token": context.processing_token.bytes,
                "operation_digest": context.operation_digest,
                "site_config_version_id": context.site_config_version_id,
                "report_type": context.report_type,
                "confirmation_revision": context.confirmation_revision,
                "attempt_number": attempt_number,
                "parser_version": parsed_report.parser_version,
                "ruleset_version": parsed_report.ruleset_version,
                "encoding": parsed_report.encoding,
                "delimiter": parsed_report.delimiter,
                "field_mapping": _field_mapping(
                    parsed_report.report_type,
                    parsed_report.header,
                ),
                "source_row_count": parsed_report.summary.row_count,
                "result_summary": _canonical_json(
                    {
                        "data_digest": parsed_report.summary.data_digest,
                        "totals": dict(parsed_report.summary.totals),
                    }
                ),
                "created_by_user_id": context.actor_user_id,
                "started_at": _mysql_datetime(context.started_at),
                "completed_at": completed_at,
            },
        )
        if attempt.lastrowid is None:
            raise ParseRepositoryError("database did not return the parse attempt ID")
        return int(attempt.lastrowid)

    @staticmethod
    def _insert_source_rows(
        connection: Connection,
        *,
        attempt_id: int,
        header: tuple[str, ...],
        rows: tuple[tuple[int, tuple[str, ...], bytes], ...],
    ) -> tuple[int, ...]:
        row_ids: list[int] = []
        for source_row_number, values, row_digest in rows:
            inserted = connection.execute(
                sa.text(
                    """
                    INSERT INTO parsed_source_rows (
                        parse_attempt_id, source_row_number,
                        decoded_fields, row_digest
                    ) VALUES (
                        :attempt_id, :source_row_number,
                        :decoded_fields, :row_digest
                    )
                    """
                ),
                {
                    "attempt_id": attempt_id,
                    "source_row_number": source_row_number,
                    "decoded_fields": _decoded_fields(header, values),
                    "row_digest": row_digest,
                },
            )
            if inserted.lastrowid is None:
                raise ParseRepositoryError("database did not return a source row ID")
            row_ids.append(int(inserted.lastrowid))
        return tuple(row_ids)

    @staticmethod
    def _insert_baseline(
        connection: Connection,
        *,
        attempt_id: int,
        parsed_report: ParsedReport,
    ) -> int:
        baseline = connection.execute(
            sa.text(
                """
                INSERT INTO parse_baselines (
                    parse_attempt_id, report_type, attempt_status,
                    parser_version, ruleset_version, data_digest,
                    row_count, totals_json
                ) VALUES (
                    :attempt_id, :report_type, 'succeeded',
                    :parser_version, :ruleset_version, :data_digest,
                    :row_count, :totals_json
                )
                """
            ),
            {
                "attempt_id": attempt_id,
                "report_type": parsed_report.report_type,
                "parser_version": parsed_report.parser_version,
                "ruleset_version": parsed_report.ruleset_version,
                "data_digest": bytes.fromhex(parsed_report.summary.data_digest),
                "row_count": parsed_report.summary.row_count,
                "totals_json": _canonical_json(dict(parsed_report.summary.totals)),
            },
        )
        if baseline.lastrowid is None:
            raise ParseRepositoryError("database did not return the parse baseline ID")
        return int(baseline.lastrowid)

    @classmethod
    def _insert_typed_baseline_rows(
        cls,
        connection: Connection,
        *,
        attempt_id: int,
        baseline_id: int,
        source_row_ids: tuple[int, ...],
        parsed_report: ParsedReport,
    ) -> None:
        if len(source_row_ids) != len(parsed_report.rows):
            raise ParseRepositoryError("source and typed row counts differ")
        for ordinal, (source_row_id, row) in enumerate(
            zip(source_row_ids, parsed_report.rows, strict=True),
            start=1,
        ):
            # Freeze validation on the same algorithm later persisted by the
            # dataset/source-key sidecar transaction.
            seller_sku_match_v1(row.sku)
            generic = connection.execute(
                sa.text(
                    """
                    INSERT INTO parse_baseline_rows (
                        parse_baseline_id, parse_attempt_id,
                        parsed_source_row_id, report_type,
                        row_ordinal, row_digest
                    ) VALUES (
                        :baseline_id, :attempt_id,
                        :source_row_id, :report_type,
                        :row_ordinal, :row_digest
                    )
                    """
                ),
                {
                    "baseline_id": baseline_id,
                    "attempt_id": attempt_id,
                    "source_row_id": source_row_id,
                    "report_type": parsed_report.report_type,
                    "row_ordinal": ordinal,
                    "row_digest": bytes.fromhex(row.typed_digest),
                },
            )
            if generic.lastrowid is None:
                raise ParseRepositoryError("database did not return a baseline row ID")
            baseline_row_id = int(generic.lastrowid)
            if isinstance(row, BusinessReportRow):
                cls._insert_business_row(
                    connection,
                    baseline_id=baseline_id,
                    baseline_row_id=baseline_row_id,
                    row=row,
                )
            elif isinstance(row, ReturnReportRow):
                cls._insert_return_row(
                    connection,
                    baseline_id=baseline_id,
                    baseline_row_id=baseline_row_id,
                    row=row,
                )
            else:  # pragma: no cover - ParsedRow is a closed union
                raise ParseRepositoryError("unsupported typed parse row")

    @staticmethod
    def _insert_business_row(
        connection: Connection,
        *,
        baseline_id: int,
        baseline_row_id: int,
        row: BusinessReportRow,
    ) -> None:
        values = {
            field.name: getattr(row, field.name)
            for field in fields(row)
            if field.name not in {"source", "typed_digest"}
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO business_parse_baseline_rows (
                    parse_baseline_row_id, parse_baseline_id,
                    parent_asin, child_asin, title, sku,
                    sessions_total, sessions_b2b,
                    conversion_rate_total, session_percentage_b2b,
                    page_views_total, page_views_b2b,
                    page_view_percentage_total, page_view_percentage_b2b,
                    featured_offer_percentage, featured_offer_percentage_b2b,
                    units_ordered, units_ordered_b2b,
                    unit_session_percentage, unit_session_percentage_b2b,
                    ordered_product_sales, ordered_product_sales_b2b,
                    currency_code, total_order_items, total_order_items_b2b
                ) VALUES (
                    :parse_baseline_row_id, :parse_baseline_id,
                    :parent_asin, :child_asin, :title, :sku,
                    :sessions_total, :sessions_b2b,
                    :conversion_rate_total, :session_percentage_b2b,
                    :page_views_total, :page_views_b2b,
                    :page_view_percentage_total, :page_view_percentage_b2b,
                    :featured_offer_percentage, :featured_offer_percentage_b2b,
                    :units_ordered, :units_ordered_b2b,
                    :unit_session_percentage, :unit_session_percentage_b2b,
                    :ordered_product_sales, :ordered_product_sales_b2b,
                    :currency_code, :total_order_items, :total_order_items_b2b
                )
                """
            ),
            {
                "parse_baseline_row_id": baseline_row_id,
                "parse_baseline_id": baseline_id,
                **values,
            },
        )

    @staticmethod
    def _insert_return_row(
        connection: Connection,
        *,
        baseline_id: int,
        baseline_row_id: int,
        row: ReturnReportRow,
    ) -> None:
        return_date = row.return_date
        values = {
            field.name: getattr(row, field.name)
            for field in fields(row)
            if field.name not in {"source", "typed_digest", "return_date"}
        }
        connection.execute(
            sa.text(
                """
                INSERT INTO return_parse_baseline_rows (
                    parse_baseline_row_id, parse_baseline_id,
                    return_date, order_id, sku, asin, fnsku, product_name,
                    quantity, fulfillment_center_id, detailed_disposition,
                    reason, status, license_plate_number, customer_comments
                ) VALUES (
                    :parse_baseline_row_id, :parse_baseline_id,
                    :return_date, :order_id, :sku, :asin, :fnsku, :product_name,
                    :quantity, :fulfillment_center_id, :detailed_disposition,
                    :reason, :status, :license_plate_number, :customer_comments
                )
                """
            ),
            {
                "parse_baseline_row_id": baseline_row_id,
                "parse_baseline_id": baseline_id,
                "return_date": _mysql_datetime(return_date),
                **values,
            },
        )

    @staticmethod
    def _failure_field_mapping(
        report_type: ReportType,
        header: tuple[str, ...] | None,
    ) -> str | None:
        if header is None:
            return None
        try:
            return _field_mapping(report_type, header)
        except ParseRepositoryError:
            return _canonical_json({"source_header": header})

    @staticmethod
    def _validate_success(
        context: ConfirmedParseContext,
        parsed_report: ParsedReport,
    ) -> None:
        if parsed_report.report_type != context.report_type:
            raise ParseRepositoryError("parsed report type differs from confirmation")
        if parsed_report.encoding != context.encoding:
            raise ParseRepositoryError("parsed encoding differs from confirmation")
        if parsed_report.parser_version != PARSER_VERSION:
            raise ParseRepositoryError("parser version is not the active version")
        if parsed_report.ruleset_version != REPORT_RULES[context.report_type].version:
            raise ParseRepositoryError("ruleset version is not the confirmed version")
        if parsed_report.summary.row_count != len(parsed_report.rows) or len(
            parsed_report.rows
        ) != len(parsed_report.source_rows):
            raise ParseRepositoryError("parsed report row counts are inconsistent")
        if any(
            row.source != source
            for row, source in zip(
                parsed_report.rows,
                parsed_report.source_rows,
                strict=True,
            )
        ):
            raise ParseRepositoryError(
                "typed rows do not reference their corresponding source rows"
            )

    @staticmethod
    def _insert_audit(
        connection: Connection,
        *,
        site_id: int,
        actor_user_id: int | None,
        event_type: str,
        batch_id: int,
        payload: dict[str, object],
        occurred_at: datetime,
        request_id: str | None = None,
    ) -> None:
        connection.execute(
            sa.text(
                """
                INSERT INTO audit_events (
                    site_id, actor_user_id, event_type, object_type,
                    object_id, request_id, redacted_payload, occurred_at
                ) VALUES (
                    :site_id, :actor_user_id, :event_type, 'import_batch',
                    :object_id, :request_id, :redacted_payload, :occurred_at
                )
                """
            ),
            {
                "site_id": site_id,
                "actor_user_id": actor_user_id,
                "event_type": event_type,
                "object_id": str(batch_id),
                "request_id": request_id,
                "redacted_payload": _canonical_json(payload),
                "occurred_at": occurred_at,
            },
        )
