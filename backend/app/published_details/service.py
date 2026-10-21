"""Read exact current publication scopes and their versioned column schemas."""

from __future__ import annotations

import json
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from math import ceil
from typing import Any, Final, Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.analytics.models import PublicationReference
from app.auth.sessions import Principal
from app.imports.types import ReportType
from app.published_details.models import (
    PublishedDateSummary,
    PublishedDetailCell,
    PublishedDetailColumn,
    PublishedDetailPagination,
    PublishedDetailRow,
    PublishedDetailScope,
    PublishedRangeResponse,
)
from app.published_details.query_builder import (
    InvalidPublishedSortDirection,
    VisibleColumnResolver,
)
from app.published_details.scope import PublishedScopeCodec

_REPORT_TYPES: Final[frozenset[str]] = frozenset({"business_report", "return_report"})


class PublishedDetailServiceError(RuntimeError):
    """Base error with a stable machine-readable service code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class PublishedSiteConfigurationError(PublishedDetailServiceError):
    """The local single-active-site invariant is unavailable or ambiguous."""

    def __init__(self) -> None:
        super().__init__(
            "published_site_configuration_invalid",
            "Exactly one active site with a current configuration is required.",
        )


class PublishedSchemaIntegrityError(PublishedDetailServiceError):
    """A frozen published schema is missing or internally inconsistent."""

    def __init__(self, message: str) -> None:
        super().__init__("published_schema_integrity_error", message)


class PublicationScopeChanged(PublishedDetailServiceError):
    """At least one current publication pointer no longer matches the scope."""

    def __init__(self) -> None:
        super().__init__(
            "publication_scope_changed",
            "The current publication scope changed; resolve a new scope.",
        )


class InvalidPublishedReportDate(PublishedDetailServiceError):
    """The optional one-day expansion is outside the token's fixed range."""

    def __init__(self) -> None:
        super().__init__(
            "invalid_published_report_date",
            "report_date must be inside the publication scope range.",
        )


@dataclass(frozen=True, slots=True)
class PublishedSummaryPage:
    """A bounded, date-level summary page produced from one publication scope."""

    summaries: list[PublishedDateSummary]
    pagination: PublishedDetailPagination


@dataclass(frozen=True, slots=True)
class PublishedRowsPage:
    """A bounded raw-row page with its role-visible union schema."""

    columns: list[PublishedDetailColumn]
    rows: list[PublishedDetailRow]
    pagination: PublishedDetailPagination


@dataclass(frozen=True, slots=True)
class _PublishedRowsQueryPlan:
    """One role-visible, current-publication row query shared by pages and CSV."""

    resolver: VisibleColumnResolver
    parameters: dict[str, object]
    from_clause: str
    where: str
    rows_sql: str
    standard_aliases: dict[UUID, str]
    extension_values_alias: str | None
    count_expanding_parameter_names: tuple[str, ...]
    expanding_parameter_names: tuple[str, ...]


class PublishedDetailQueryService:
    """Resolve current publication pointers without accepting caller version IDs."""

    def __init__(
        self,
        database_session: Session,
        scope_codec: PublishedScopeCodec,
    ) -> None:
        self._database_session = database_session
        self._scope_codec = scope_codec

    def resolve_publication_scope(
        self,
        principal: Principal,
        report_type: ReportType,
        from_date: date,
        to_date: date,
    ) -> PublishedDetailScope:
        """Snapshot the exact current pointers for one site, type, and date range."""

        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        _validate_report_type(report_type)
        _validate_date_range(from_date, to_date)
        site_id = self._current_site_id()
        publications = self._publication_references(
            site_id=site_id,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
        )
        issued_at, expires_at = self._scope_codec.issue_timestamps()
        return PublishedDetailScope(
            user_id=principal.user_id,
            roles=tuple(sorted(principal.roles)),
            site_id=site_id,
            report_type=report_type,
            from_date=from_date,
            to_date=to_date,
            issued_at=issued_at,
            expires_at=expires_at,
            publications=tuple(publications),
        )

    def resolve_full_range(
        self,
        principal: Principal,
        report_type: ReportType,
        today: date,
    ) -> PublishedRangeResponse:
        """Return the earliest current publication through today for one type."""

        if not isinstance(principal, Principal):
            raise TypeError("principal must be a Principal")
        _validate_report_type(report_type)
        if not isinstance(today, date):
            raise TypeError("today must be a date")
        site_id = self._current_site_id()
        rows = (
            self._database_session.execute(
                sa.text(
                    """
                    SELECT MIN(datasets.report_date) AS from_date
                    FROM daily_datasets AS datasets
                    INNER JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    INNER JOIN dataset_versions AS versions
                        ON versions.dataset_id = publications.dataset_id
                       AND versions.id = publications.version_id
                       AND versions.status = 'published'
                    WHERE datasets.site_id = :site_id
                      AND datasets.report_type = :report_type
                      AND datasets.report_date <= :today
                    """
                ),
                {
                    "site_id": site_id,
                    "report_type": report_type,
                    "today": today,
                },
            )
            .mappings()
            .all()
        )
        earliest = rows[0]["from_date"] if rows else None
        if earliest is None:
            return PublishedRangeResponse(from_date=None, to_date=None)
        if not isinstance(earliest, date):
            raise RuntimeError("database returned an invalid publication date")
        return PublishedRangeResponse(from_date=earliest, to_date=today)

    def compose_published_schema(
        self,
        scope: PublishedDetailScope,
    ) -> list[PublishedDetailColumn]:
        """Union frozen schemas in report-date/display-order first-seen order."""

        if not isinstance(scope, PublishedDetailScope):
            raise TypeError("scope must be a PublishedDetailScope")
        if not scope.publications:
            return []
        publications_by_version = {
            publication.version_id: publication for publication in scope.publications
        }
        if len(publications_by_version) != len(scope.publications):
            raise PublishedSchemaIntegrityError(
                "A publication scope contains a repeated version ID."
            )
        version_ids = tuple(publications_by_version)
        version_ids_parameter: sa.BindParameter[object] = sa.bindparam(
            "version_ids", expanding=True
        )
        rows = (
            self._database_session.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.site_id,
                           datasets.report_date, datasets.report_type,
                           versions.id AS version_id, columns.column_id,
                           columns.source_header, columns.display_order,
                           columns.value_kind, columns.standard_field_name,
                           columns.is_key, columns.participates_in_statistics
                    FROM version_table_columns AS columns
                    INNER JOIN dataset_versions AS versions
                        ON versions.id = columns.version_id
                    INNER JOIN daily_datasets AS datasets
                        ON datasets.id = versions.dataset_id
                    WHERE columns.version_id IN :version_ids
                    ORDER BY datasets.report_date, columns.display_order
                    """
                ).bindparams(version_ids_parameter),
                {"version_ids": version_ids},
            )
            .mappings()
            .all()
        )
        result: list[PublishedDetailColumn] = []
        columns_by_id: dict[UUID, PublishedDetailColumn] = {}
        seen_versions: set[int] = set()
        for row in rows:
            version_id = int(row["version_id"])
            publication = publications_by_version.get(version_id)
            if publication is None or not _row_matches_publication(row, publication):
                raise PublishedSchemaIntegrityError(
                    "A versioned schema does not match its publication scope."
                )
            seen_versions.add(version_id)
            column = _published_column(row)
            existing = columns_by_id.get(column.column_id)
            if existing is None:
                union_column = column.model_copy(
                    update={"display_order": len(result) + 1}
                )
                columns_by_id[column.column_id] = union_column
                result.append(union_column)
            elif _stable_metadata(existing) != _stable_metadata(column):
                raise PublishedSchemaIntegrityError(
                    f"Stable column ID {column.column_id} has conflicting metadata."
                )
        if seen_versions != set(version_ids):
            raise PublishedSchemaIntegrityError(
                "A published version has no versioned table schema."
            )
        return result

    def assert_scope_current(self, scope: PublishedDetailScope) -> None:
        """Reject any exact pointer-set difference before downstream row reads."""

        if not isinstance(scope, PublishedDetailScope):
            raise TypeError("scope must be a PublishedDetailScope")
        try:
            current_site_id = self._current_site_id()
        except PublishedSiteConfigurationError as error:
            raise PublicationScopeChanged() from error
        if scope.site_id != current_site_id:
            raise PublicationScopeChanged()
        current = self._publication_references(
            site_id=current_site_id,
            report_type=scope.report_type,
            from_date=scope.from_date,
            to_date=scope.to_date,
        )
        expected_pointers = [_pointer_identity(item) for item in scope.publications]
        current_pointers = [_pointer_identity(item) for item in current]
        if current_pointers != expected_pointers:
            raise PublicationScopeChanged()

    def query_date_summaries(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        page: int,
        page_size: int,
    ) -> PublishedSummaryPage:
        """Return matching publication dates and their unfiltered daily metrics."""

        _validate_scope(scope)
        _validate_pagination(page, page_size)
        search_value = _normalised_search(search)
        self.assert_scope_current(scope)
        resolver = self._visible_column_resolver(scope)
        parameters = self._scope_parameters(scope)
        scoped_where = self._scoped_row_where()
        matching_where = scoped_where
        if search_value is not None:
            search_sql, search_parameters = resolver.search(search_value)
            matching_where = f"{matching_where} AND {search_sql}"
            parameters.update(search_parameters)

        full_metrics = _summary_metric_columns(scope.report_type)
        typed_table = resolver.typed_table
        from_clause = self._scoped_row_from(typed_table)
        common_ctes = f"""
            WITH full_day AS (
                SELECT datasets.id AS dataset_id,
                       datasets.report_date,
                       versions.id AS version_id,
                       versions.version_no,
                       publications.published_at,
                       COUNT(row_records.id) AS total_row_count,
                       {full_metrics}
                {from_clause}
                WHERE {scoped_where}
                GROUP BY datasets.id, datasets.report_date, versions.id,
                         versions.version_no, publications.published_at
            ), matching_day AS (
                SELECT datasets.id AS dataset_id,
                       COUNT(row_records.id) AS matching_row_count
                {from_clause}
                WHERE {matching_where}
                GROUP BY datasets.id
            )
        """
        expanding_names = _expanding_parameter_names(parameters)
        total_items = int(
            self._database_session.scalar(
                _published_text(
                    common_ctes + " SELECT COUNT(*) FROM matching_day",
                    expanding_names,
                ),
                parameters,
            )
            or 0
        )
        statement = _published_text(
            common_ctes
            + """
            SELECT full_day.report_date, full_day.version_id, full_day.version_no,
                   full_day.published_at, full_day.total_row_count,
                   matching_day.matching_row_count, full_day.sales,
                   full_day.units_ordered, full_day.sessions,
                   full_day.return_quantity
            FROM full_day
            INNER JOIN matching_day ON matching_day.dataset_id = full_day.dataset_id
            ORDER BY full_day.report_date DESC
            LIMIT :limit OFFSET :offset
            """,
            expanding_names,
        )
        query_parameters = {
            **parameters,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        raw_rows = (
            self._database_session.execute(statement, query_parameters).mappings().all()
        )
        publications = {item.version_id: item for item in scope.publications}
        summaries: list[PublishedDateSummary] = []
        for row in raw_rows:
            version_id = int(row["version_id"])
            publication = publications.get(version_id)
            if publication is None:
                raise PublishedSchemaIntegrityError(
                    "A summary row does not belong to the publication scope."
                )
            summaries.append(
                PublishedDateSummary(
                    report_date=_report_date(row["report_date"]),
                    version_id=version_id,
                    version_no=int(row["version_no"]),
                    published_at=_utc_timestamp(row["published_at"]),
                    total_row_count=int(row["total_row_count"]),
                    matching_row_count=int(row["matching_row_count"]),
                    sales=_decimal_text_or_none(row["sales"]),
                    units_ordered=_int_or_none(row["units_ordered"]),
                    sessions=_int_or_none(row["sessions"]),
                    return_quantity=_int_or_none(row["return_quantity"]),
                    publication=publication,
                )
            )
        return PublishedSummaryPage(
            summaries=summaries,
            pagination=_pagination(page, page_size, total_items),
        )

    def query_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: Literal["asc", "desc"] | str,
        page: int,
        page_size: int,
        report_date: date | None = None,
    ) -> PublishedRowsPage:
        """Return one bounded raw-row page from the token's exact current pointers."""

        _validate_pagination(page, page_size)
        plan = self._published_rows_query_plan(
            scope,
            search,
            sort_column_id,
            direction,
            report_date,
        )
        count_statement = _published_text(
            f"SELECT COUNT(*) {plan.from_clause} WHERE {plan.where}",
            plan.count_expanding_parameter_names,
        )
        total_items = int(
            self._database_session.scalar(count_statement, plan.parameters) or 0
        )
        rows_statement = _published_text(
            f"{plan.rows_sql} LIMIT :limit OFFSET :offset",
            plan.expanding_parameter_names,
        )
        row_parameters = {
            **plan.parameters,
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        raw_rows = (
            self._database_session.execute(rows_statement, row_parameters)
            .mappings()
            .all()
        )
        return PublishedRowsPage(
            columns=list(plan.resolver.visible_columns),
            rows=self._published_rows_from_raw(plan, raw_rows),
            pagination=_pagination(page, page_size, total_items),
        )

    def stream_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: Literal["asc", "desc"] | str,
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Generator[PublishedDetailRow],
    ]:
        """Prepare a server-side row stream in this service's existing session.

        The schema returned with the iterator is resolved from the same scope,
        role boundary, search predicate, and sort plan used by paged rows.
        Callers must consume or close the iterator so its result cursor is closed.
        """

        columns, row_source = self.prepare_published_rows(
            scope,
            search,
            sort_column_id,
            direction,
            report_date,
            batch_size=batch_size,
        )
        return columns, row_source()

    def prepare_published_rows(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: Literal["asc", "desc"] | str,
        report_date: date | None = None,
        *,
        batch_size: int = 100,
    ) -> tuple[
        tuple[PublishedDetailColumn, ...],
        Callable[[], Generator[PublishedDetailRow]],
    ]:
        """Resolve one shared row plan without acquiring its result cursor.

        CSV validates its requested visible columns from these exact role-visible
        columns before calling the returned source factory.  The factory is the
        only operation that opens the server-side SQLAlchemy result.
        """

        _validate_stream_batch_size(batch_size)
        plan = self._published_rows_query_plan(
            scope,
            search,
            sort_column_id,
            direction,
            report_date,
        )
        return (
            tuple(plan.resolver.visible_columns),
            lambda: self._iter_published_rows(plan, batch_size),
        )

    def _published_rows_query_plan(
        self,
        scope: PublishedDetailScope,
        search: str | None,
        sort_column_id: UUID | None,
        direction: Literal["asc", "desc"] | str,
        report_date: date | None,
    ) -> _PublishedRowsQueryPlan:
        """Resolve all trusted SQL fragments once for rows and CSV streaming."""

        _validate_scope(scope)
        if direction not in {"asc", "desc"}:
            raise InvalidPublishedSortDirection()
        if report_date is not None and (
            not isinstance(report_date, date)
            or not scope.from_date <= report_date <= scope.to_date
        ):
            raise InvalidPublishedReportDate()
        search_value = _normalised_search(search)
        self.assert_scope_current(scope)
        resolver = self._visible_column_resolver(scope)
        parameters = self._scope_parameters(scope)
        if report_date is not None:
            parameters["selected_report_date"] = report_date
        where = self._scoped_row_where(report_date is not None)
        if search_value is not None:
            search_sql, search_parameters = resolver.search(search_value)
            where = f"{where} AND {search_sql}"
            parameters.update(search_parameters)

        sort_join = ""
        if sort_column_id is None:
            order_sql = "datasets.report_date DESC, row_records.row_ordinal ASC"
        else:
            order = resolver.order_by(sort_column_id, direction)
            sort_join = order.join_sql
            parameters.update(order.parameters)
            order_sql = (
                f"{order.expression_sql}, datasets.report_date DESC, "
                "row_records.row_ordinal ASC"
            )

        standard_expressions: list[str] = []
        standard_aliases: dict[UUID, str] = {}
        for index, column in enumerate(resolver.standard_columns):
            alias = f"standard_value_{index}"
            expression, expression_parameters = resolver.typed_value_expression(
                column.column_id,
                bind_name=f"selected_standard_column_{index}",
            )
            standard_expressions.append(f"{expression} AS {alias}")
            standard_aliases[column.column_id] = alias
            parameters.update(expression_parameters)
        values_sql = (
            ", " + ", ".join(standard_expressions) if standard_expressions else ""
        )
        extension_values_alias: str | None = None
        extension_values_sql = ""
        if resolver.extension_columns:
            extension_values_alias = "extension_values_json"
            parameters["selected_extension_column_ids"] = tuple(
                column.column_id.bytes for column in resolver.extension_columns
            )
            extension_values_sql = """
                , (
                    SELECT COALESCE(
                        JSON_OBJECTAGG(
                            HEX(export_extension_cells.column_id),
                            export_extension_cells.current_value
                        ),
                        JSON_OBJECT()
                    )
                    FROM version_extension_cells AS export_extension_cells
                    WHERE export_extension_cells.version_id = row_records.version_id
                      AND export_extension_cells.row_id = row_records.id
                      AND export_extension_cells.column_id
                          IN :selected_extension_column_ids
                ) AS extension_values_json
            """
        from_clause = self._scoped_row_from(resolver.typed_table, sort_join)
        rows_sql = f"""
            SELECT datasets.report_date, versions.id AS version_id,
                   versions.version_no, publications.published_at,
                   row_records.id AS row_id, row_records.row_ordinal{values_sql}
                   {extension_values_sql}
            {from_clause}
            WHERE {where}
            ORDER BY {order_sql}
        """
        return _PublishedRowsQueryPlan(
            resolver=resolver,
            parameters=parameters,
            from_clause=from_clause,
            where=where,
            rows_sql=rows_sql,
            standard_aliases=standard_aliases,
            extension_values_alias=extension_values_alias,
            count_expanding_parameter_names=tuple(
                name
                for name in _expanding_parameter_names(parameters)
                if name != "selected_extension_column_ids"
            ),
            expanding_parameter_names=_expanding_parameter_names(parameters),
        )

    def _iter_published_rows(
        self,
        plan: _PublishedRowsQueryPlan,
        batch_size: int,
    ) -> Generator[PublishedDetailRow]:
        """Yield bounded row batches and always close the DBAPI result cursor."""

        statement = _published_text(
            plan.rows_sql,
            plan.expanding_parameter_names,
        ).execution_options(stream_results=True, yield_per=batch_size)
        result = self._database_session.execute(statement, plan.parameters)
        try:
            mappings = result.mappings().yield_per(batch_size)
            while raw_rows := mappings.fetchmany(batch_size):
                yield from self._published_rows_from_raw(plan, raw_rows)
        finally:
            result.close()

    def _published_rows_from_raw(
        self,
        plan: _PublishedRowsQueryPlan,
        raw_rows: Sequence[RowMapping],
    ) -> list[PublishedDetailRow]:
        """Build only one already-bounded page or streamed batch of public cells."""

        rows: list[PublishedDetailRow] = []
        for raw_row in raw_rows:
            version_id = int(raw_row["version_id"])
            extension_values = _row_extension_values(plan, raw_row)
            cells: list[PublishedDetailCell] = []
            for column in plan.resolver.visible_columns:
                if column.standard_field_name is not None:
                    value = raw_row[plan.standard_aliases[column.column_id]]
                else:
                    value = extension_values.get(column.column_id)
                cells.append(
                    PublishedDetailCell(
                        column_id=column.column_id,
                        value=_published_cell_value(value, column.value_kind),
                    )
                )
            rows.append(
                PublishedDetailRow(
                    report_date=_report_date(raw_row["report_date"]),
                    version_id=version_id,
                    version_no=int(raw_row["version_no"]),
                    published_at=_utc_timestamp(raw_row["published_at"]),
                    row_ordinal=int(raw_row["row_ordinal"]),
                    cells=cells,
                )
            )
        return rows

    def _visible_column_resolver(
        self,
        scope: PublishedDetailScope,
    ) -> VisibleColumnResolver:
        return VisibleColumnResolver(
            scope.report_type,
            self.compose_published_schema(scope),
            scope.roles,
        )

    @staticmethod
    def _scope_parameters(scope: PublishedDetailScope) -> dict[str, object]:
        return {
            "scope_version_ids": tuple(
                publication.version_id for publication in scope.publications
            ),
            "scope_site_id": scope.site_id,
            "scope_report_type": scope.report_type,
            "scope_from_date": scope.from_date,
            "scope_to_date": scope.to_date,
        }

    @staticmethod
    def _scoped_row_from(typed_table: str, additional_join: str = "") -> str:
        return f"""
            FROM daily_datasets AS datasets
            INNER JOIN dataset_publications AS publications
                ON publications.dataset_id = datasets.id
            INNER JOIN dataset_versions AS versions
                ON versions.dataset_id = publications.dataset_id
               AND versions.id = publications.version_id
               AND versions.status = 'published'
            INNER JOIN version_rows AS row_records
                ON row_records.version_id = versions.id
               AND row_records.report_type = datasets.report_type
               AND row_records.row_state = 'active'
            INNER JOIN {typed_table} AS typed
                ON typed.version_id = row_records.version_id
               AND typed.version_row_id = row_records.id
            {additional_join}
        """

    @staticmethod
    def _scoped_row_where(single_date: bool = False) -> str:
        clauses = [
            "versions.id IN :scope_version_ids",
            "datasets.site_id = :scope_site_id",
            "datasets.report_type = :scope_report_type",
            "datasets.report_date BETWEEN :scope_from_date AND :scope_to_date",
        ]
        if single_date:
            clauses.append("datasets.report_date = :selected_report_date")
        return " AND ".join(clauses)

    def _current_site_id(self) -> int:
        rows = (
            self._database_session.execute(
                sa.text(
                    """
                    SELECT sites.id AS site_id,
                           current_configs.current_config_version_id,
                           configs.id AS config_id
                    FROM sites AS sites
                    LEFT JOIN site_current_configs AS current_configs
                        ON current_configs.site_id = sites.id
                    LEFT JOIN site_config_versions AS configs
                        ON configs.site_id = current_configs.site_id
                       AND configs.id = current_configs.current_config_version_id
                    WHERE sites.status = 'active'
                    ORDER BY sites.id
                    LIMIT 2
                    """
                )
            )
            .mappings()
            .all()
        )
        if len(rows) != 1:
            raise PublishedSiteConfigurationError()
        row = rows[0]
        site_id = int(row["site_id"])
        if (
            site_id <= 0
            or row["current_config_version_id"] is None
            or row["config_id"] is None
        ):
            raise PublishedSiteConfigurationError()
        return site_id

    def _publication_references(
        self,
        *,
        site_id: int,
        report_type: ReportType,
        from_date: date,
        to_date: date,
    ) -> list[PublicationReference]:
        rows = (
            self._database_session.execute(
                sa.text(
                    """
                    SELECT datasets.id AS dataset_id, datasets.site_id,
                           datasets.report_date, datasets.report_type,
                           publications.version_id, publications.published_at
                    FROM daily_datasets AS datasets
                    INNER JOIN dataset_publications AS publications
                        ON publications.dataset_id = datasets.id
                    INNER JOIN dataset_versions AS versions
                        ON versions.dataset_id = publications.dataset_id
                       AND versions.id = publications.version_id
                       AND versions.status = 'published'
                    WHERE datasets.site_id = :site_id
                      AND datasets.report_type = :report_type
                      AND datasets.report_date BETWEEN :from_date AND :to_date
                    ORDER BY datasets.report_date
                    """
                ),
                {
                    "site_id": site_id,
                    "report_type": report_type,
                    "from_date": from_date,
                    "to_date": to_date,
                },
            )
            .mappings()
            .all()
        )
        publications = [_publication_reference(row) for row in rows]
        if any(publication.site_id != site_id for publication in publications):
            raise RuntimeError("database returned a publication for another site")
        if any(publication.report_type != report_type for publication in publications):
            raise RuntimeError(
                "database returned a publication for another report type"
            )
        return publications


def _published_text(sql: str, expanding_names: tuple[str, ...]) -> sa.TextClause:
    bind_parameters: list[sa.BindParameter[Any]] = [
        sa.bindparam(name, expanding=True) for name in expanding_names
    ]
    return sa.text(sql).bindparams(*bind_parameters)


def _expanding_parameter_names(parameters: dict[str, object]) -> tuple[str, ...]:
    return tuple(name for name, value in parameters.items() if isinstance(value, tuple))


def _validate_scope(scope: object) -> None:
    if not isinstance(scope, PublishedDetailScope):
        raise TypeError("scope must be a PublishedDetailScope")


def _validate_pagination(page: object, page_size: object) -> None:
    if isinstance(page, bool) or not isinstance(page, int) or page < 1:
        raise ValueError("page must be a positive integer")
    if (
        isinstance(page_size, bool)
        or not isinstance(page_size, int)
        or not 1 <= page_size <= 100
    ):
        raise ValueError("page_size must be between 1 and 100")


def _validate_stream_batch_size(batch_size: object) -> None:
    if (
        isinstance(batch_size, bool)
        or not isinstance(batch_size, int)
        or not 1 <= batch_size <= 1_000
    ):
        raise ValueError("batch_size must be between 1 and 1000")


def _normalised_search(search: str | None) -> str | None:
    if search is None:
        return None
    if not isinstance(search, str):
        raise TypeError("search must be a string or None")
    value = search.strip()
    return value or None


def _summary_metric_columns(report_type: ReportType) -> str:
    if report_type == "business_report":
        return """
            COALESCE(SUM(typed.ordered_product_sales), 0) AS sales,
            COALESCE(SUM(typed.units_ordered), 0) AS units_ordered,
            COALESCE(SUM(typed.sessions_total), 0) AS sessions,
            NULL AS return_quantity
        """
    if report_type == "return_report":
        return """
            NULL AS sales,
            NULL AS units_ordered,
            NULL AS sessions,
            COALESCE(SUM(typed.quantity), 0) AS return_quantity
        """
    raise ValueError("unsupported report type")


def _pagination(
    page: int,
    page_size: int,
    total_items: int,
) -> PublishedDetailPagination:
    return PublishedDetailPagination(
        page=page,
        page_size=page_size,
        total_items=total_items,
        total_pages=ceil(total_items / page_size) if total_items else 0,
    )


def _report_date(value: object) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise RuntimeError("database returned an invalid report date")
    return value


def _decimal_text_or_none(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    try:
        return format(Decimal(str(value)), "f")
    except (ArithmeticError, ValueError) as error:
        raise RuntimeError("database returned an invalid decimal metric") from error


def _int_or_none(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise RuntimeError("database returned an invalid integer metric")
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError) as error:
        raise RuntimeError("database returned an invalid integer metric") from error


def _published_cell_value(
    value: object,
    value_kind: Literal["text", "integer", "decimal", "utc_datetime"],
) -> str | int | Decimal | datetime | None:
    if value is None:
        return None
    if value_kind == "text":
        if not isinstance(value, str):
            raise RuntimeError("database returned an invalid text cell")
        return value
    if value_kind == "integer":
        if isinstance(value, bool):
            raise RuntimeError("database returned an invalid integer cell")
        try:
            return int(cast(Any, value))
        except (TypeError, ValueError) as error:
            raise RuntimeError("database returned an invalid integer cell") from error
    if value_kind == "decimal":
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value))
        except (ArithmeticError, ValueError) as error:
            raise RuntimeError("database returned an invalid decimal cell") from error
    if value_kind == "utc_datetime":
        return _utc_timestamp(value)
    raise RuntimeError("database returned an invalid published cell kind")


def _row_extension_values(
    plan: _PublishedRowsQueryPlan,
    raw_row: RowMapping,
) -> dict[UUID, object]:
    """Decode only this row's correlated extension JSON value bundle."""

    if plan.extension_values_alias is None:
        return {}
    value = raw_row[plan.extension_values_alias]
    if value is None:
        return {}
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PublishedSchemaIntegrityError(
                "A published extension-value bundle is not valid UTF-8."
            ) from error
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise PublishedSchemaIntegrityError(
                "A published extension-value bundle is invalid JSON."
            ) from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PublishedSchemaIntegrityError(
            "A published extension-value bundle has an invalid shape."
        )
    return {
        column.column_id: value.get(column.column_id.hex.upper())
        for column in plan.resolver.extension_columns
    }


def _publication_reference(row: RowMapping) -> PublicationReference:
    report_type = _report_type(row["report_type"])
    report_date = row["report_date"]
    if not isinstance(report_date, date):
        raise RuntimeError("database returned an invalid publication date")
    return PublicationReference(
        dataset_id=int(row["dataset_id"]),
        site_id=int(row["site_id"]),
        report_date=report_date,
        report_type=report_type,
        version_id=int(row["version_id"]),
        published_at=_utc_timestamp(row["published_at"]),
    )


def _row_matches_publication(
    row: RowMapping,
    publication: PublicationReference,
) -> bool:
    return (
        int(row["dataset_id"]) == publication.dataset_id
        and int(row["site_id"]) == publication.site_id
        and row["report_date"] == publication.report_date
        and row["report_type"] == publication.report_type
        and int(row["version_id"]) == publication.version_id
    )


def _published_column(row: RowMapping) -> PublishedDetailColumn:
    value_kind = str(row["value_kind"])
    if value_kind not in {"text", "integer", "decimal", "utc_datetime"}:
        raise PublishedSchemaIntegrityError("A column has an invalid value kind.")
    standard_field_name = row["standard_field_name"]
    if standard_field_name is not None:
        standard_field_name = str(standard_field_name)
    return PublishedDetailColumn(
        column_id=_column_uuid(row["column_id"]),
        source_header=str(row["source_header"]),
        display_order=int(row["display_order"]),
        value_kind=cast(
            Literal["text", "integer", "decimal", "utc_datetime"],
            value_kind,
        ),
        standard_field_name=standard_field_name,
        is_key=bool(row["is_key"]),
        participates_in_statistics=bool(row["participates_in_statistics"]),
    )


def _stable_metadata(column: PublishedDetailColumn) -> tuple[object, ...]:
    return (
        column.source_header,
        column.value_kind,
        column.standard_field_name,
        column.is_key,
        column.participates_in_statistics,
    )


def _column_uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytearray):
        value = bytes(value)
    if not isinstance(value, bytes) or len(value) != 16:
        raise PublishedSchemaIntegrityError("A column has an invalid stable ID.")
    return UUID(bytes=value)


def _pointer_identity(
    publication: PublicationReference,
) -> tuple[int, int, datetime]:
    return (
        publication.dataset_id,
        publication.version_id,
        _utc_timestamp(publication.published_at),
    )


def _report_type(value: object) -> ReportType:
    if not isinstance(value, str) or value not in _REPORT_TYPES:
        raise RuntimeError("database returned an invalid report type")
    return cast(ReportType, value)


def _validate_report_type(report_type: object) -> None:
    if not isinstance(report_type, str) or report_type not in _REPORT_TYPES:
        raise ValueError("unsupported report type")


def _validate_date_range(from_date: date, to_date: date) -> None:
    if not isinstance(from_date, date) or not isinstance(to_date, date):
        raise TypeError("from_date and to_date must be dates")
    if from_date > to_date:
        raise ValueError("from_date must not be after to_date")


def _utc_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("database returned an invalid timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
