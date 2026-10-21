"""Repeatable-read MySQL repository for stable catalog-backed analytics."""

from __future__ import annotations

import hmac
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.analytics import style_sql
from app.analytics.readiness import read_readiness
from app.analytics.style_models import (
    AnalyticsPermissions,
    AnalyticsProvenance,
    AvailableSeries,
    CoverageBlock,
    FactBasis,
    MetricName,
    MetricTotals,
    PublicationDay,
    PublicationRefs,
    ReturnBasis,
    SafeSourceRef,
    SeriesDimension,
    SiteCoverage,
    SourceReportCoverage,
    StyleCardResponse,
    StyleIdentity,
    StyleLedgerResponse,
    StyleLedgerRow,
    StyleSummary,
    StyleVariant,
    TrendSeries,
)
from app.analytics.style_service import (
    CoverageFacts,
    MetricAggregate,
    build_metric_values,
    build_site_reconciliation,
    build_style_reconciliation,
    build_trend_point,
    money_text,
    rate_text,
    stable_series_key,
)
from app.catalog.return_dedup_repository import (
    FrozenPublicationMember,
    publication_set_digest,
)

type LedgerSort = Literal[
    "style_code",
    "standard_name",
    "units",
    "sales",
    "returns",
    "sessions",
    "conversion",
]
type SortDirection = Literal["asc", "desc"]


class StyleAnalyticsError(RuntimeError):
    code = "style_analytics_unavailable"

    def __init__(self) -> None:
        super().__init__(self.code)


class AnalyticsSourceScopeRequired(StyleAnalyticsError):
    code = "analytics_source_scope_required"


class AnalyticsCatalogRequired(StyleAnalyticsError):
    code = "analytics_catalog_required"


class AnalyticsReturnSnapshotRequired(StyleAnalyticsError):
    code = "analytics_return_snapshot_required"


class AnalyticsSnapshotStale(StyleAnalyticsError):
    code = "analytics_snapshot_stale"


class AnalyticsDateRangeInvalid(StyleAnalyticsError):
    code = "analytics_date_range_invalid"


class AnalyticsCatalogVersionRequired(StyleAnalyticsError):
    code = "analytics_catalog_version_required"


class AnalyticsIdentityFactCombinationInvalid(StyleAnalyticsError):
    code = "analytics_identity_fact_combination_invalid"


class CatalogSnapshotRangeOutOfBounds(StyleAnalyticsError):
    code = "catalog_snapshot_range_out_of_bounds"


class CatalogStyleNotFound(StyleAnalyticsError):
    code = "catalog_style_not_found"


class AnalyticsSeriesInvalid(StyleAnalyticsError):
    code = "analytics_series_invalid"


class AnalyticsDimensionParameterInvalid(StyleAnalyticsError):
    code = "analytics_dimension_parameter_invalid"


class CatalogColorNotFound(StyleAnalyticsError):
    code = "catalog_color_not_found"


def _default_permissions() -> AnalyticsPermissions:
    return AnalyticsPermissions(
        can_view_catalog_history=False,
        can_manage_catalog=False,
        can_view_evidence_history=False,
        can_download_original=False,
        can_submit=False,
        can_approve_normal=False,
        can_approve_high_risk=False,
    )


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise StyleAnalyticsError()
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise StyleAnalyticsError()
    return value.astimezone(UTC)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise StyleAnalyticsError()
    return value


def _bytes(value: object, length: int) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise StyleAnalyticsError()
    result = bytes(value)
    if len(result) != length:
        raise StyleAnalyticsError()
    return result


def _date(value: object) -> date:
    if not isinstance(value, date) or isinstance(value, datetime):
        raise StyleAnalyticsError()
    return value


@dataclass(frozen=True, slots=True)
class _ResolvedContext:
    site_id: int
    catalog_version_id: int
    catalog_version: int
    report_source_scope_id: int
    publication_snapshot_id: int | None
    return_dedup_snapshot_id: int
    site_config_version_id: int
    reporting_timezone: str
    consistent_as_of: datetime
    fact_cutoff_at: datetime
    fact_basis: FactBasis
    all_members: tuple[PublicationDay, ...]
    business_version_ids: tuple[int, ...]
    return_version_ids: tuple[int, ...]


@dataclass(slots=True)
class _Bucket:
    units: int = 0
    sales: Decimal = Decimal(0)
    returns: int = 0
    sessions: int = 0
    business_rows: int = 0
    return_rows: int = 0

    def aggregate(self) -> MetricAggregate:
        return MetricAggregate(
            units=self.units,
            sales=self.sales,
            returns=self.returns,
            sessions=self.sessions,
            business_fact_rows=self.business_rows,
            return_fact_rows=self.return_rows,
        )


@dataclass(frozen=True, slots=True)
class _CoverageAndBuckets:
    coverage: SiteCoverage
    buckets: Mapping[str, _Bucket]
    unresolved_mapped_rows: int


def _date_span(from_date: date, to_date: date) -> int:
    return (to_date - from_date).days + 1


def _validate_range(from_date: date, to_date: date) -> int:
    span = _date_span(from_date, to_date)
    if span < 1 or span > 366:
        raise AnalyticsDateRangeInvalid()
    return span


def _event_bounds(
    from_date: date,
    to_date: date,
    timezone_name: str,
) -> tuple[datetime, datetime]:
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as error:
        raise StyleAnalyticsError() from error
    start = datetime.combine(from_date, time.min, tzinfo=zone).astimezone(UTC)
    end = datetime.combine(
        to_date + timedelta(days=1), time.min, tzinfo=zone
    ).astimezone(UTC)
    return start.replace(tzinfo=None), end.replace(tzinfo=None)


def _rows_to_members(rows: Iterable[RowMapping]) -> list[PublicationDay]:
    result: list[PublicationDay] = []
    for row in rows:
        status = str(row["report_status"])
        if status not in {"published", "missing"}:
            raise StyleAnalyticsError()
        report_type = str(row["report_type"])
        if report_type not in {"business_report", "return_report"}:
            raise StyleAnalyticsError()
        result.append(
            PublicationDay(
                report_type=cast(Any, report_type),
                report_date=_date(row["report_date"]),
                report_status=cast(Any, status),
                dataset_id=(
                    None if row["dataset_id"] is None else str(row["dataset_id"])
                ),
                published_version_id=(
                    None
                    if row["published_version_id"] is None
                    else str(row["published_version_id"])
                ),
                snapshot_member_id=(
                    None
                    if row["snapshot_member_id"] is None
                    else str(row["snapshot_member_id"])
                ),
                pointer_revision=(
                    None
                    if row["pointer_revision"] is None
                    else int(row["pointer_revision"])
                ),
            )
        )
    return result


def _complete_member_band(
    members: Iterable[PublicationDay],
    *,
    from_date: date,
    to_date: date,
    snapshot: bool,
) -> tuple[PublicationDay, ...]:
    by_key = {(member.report_type, member.report_date): member for member in members}
    result: list[PublicationDay] = []
    current = from_date
    while current <= to_date:
        for report_type in ("business_report", "return_report"):
            member = by_key.get((report_type, current))
            if member is None:
                if snapshot:
                    raise CatalogSnapshotRangeOutOfBounds()
                member = PublicationDay(
                    report_type=report_type,
                    report_date=current,
                    report_status="missing",
                    dataset_id=None,
                    published_version_id=None,
                    snapshot_member_id=None,
                    pointer_revision=0,
                )
            result.append(member)
        current += timedelta(days=1)
    return tuple(result)


def _member_versions(
    members: Iterable[PublicationDay],
    report_type: str,
) -> tuple[int, ...]:
    return tuple(
        sorted(
            {
                int(member.published_version_id)
                for member in members
                if member.report_type == report_type
                and member.published_version_id is not None
            }
        )
    )


class MySqlStyleAnalyticsRepository:
    """Run every response inside one read-only consistent MySQL snapshot."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def ledger(
        self,
        *,
        site_id: int,
        from_date: date,
        to_date: date,
        category_id: int | None = None,
        search: str | None = None,
        sort: LedgerSort = "units",
        direction: SortDirection = "desc",
        page: int = 1,
        page_size: int = 50,
        catalog_version_id: int | None = None,
        fact_basis: FactBasis = "current",
        return_basis: ReturnBasis = "event_date",
        permissions: AnalyticsPermissions | None = None,
    ) -> StyleLedgerResponse:
        _positive(site_id)
        _validate_range(from_date, to_date)
        if page < 1 or not 1 <= page_size <= 100:
            raise AnalyticsDateRangeInvalid()
        normalized_search = (search or "").strip()
        if len(normalized_search) > 100:
            raise AnalyticsDateRangeInvalid()
        connection = self._begin()
        try:
            context = self._resolve(
                connection,
                site_id=site_id,
                from_date=from_date,
                to_date=to_date,
                catalog_version_id=catalog_version_id,
                fact_basis=fact_basis,
                return_basis=return_basis,
            )
            parameters = self._parameters(context, from_date, to_date)
            escaped_search = normalized_search.replace("%", r"\%").replace("_", r"\_")
            parameters.update(
                {
                    "category_id": category_id,
                    "search_pattern": (
                        None if not normalized_search else f"%{escaped_search}%"
                    ),
                    "page_size": page_size,
                    "offset": (page - 1) * page_size,
                }
            )
            rows = (
                connection.execute(
                    style_sql.style_page_sql(
                        sort=sort,
                        direction=direction,
                        return_basis=return_basis,
                    ),
                    parameters,
                )
                .mappings()
                .all()
            )
            if rows:
                coverage_and_buckets = self._coverage_and_buckets_from_ledger_row(
                    rows[0],
                    context=context,
                    from_date=from_date,
                    to_date=to_date,
                    return_basis=return_basis,
                )
                unresolved_by_style = {
                    int(row["style_id"]): int(row["unresolved_return_rows"] or 0)
                    for row in rows
                }
            else:
                coverage_and_buckets = self._coverage_and_buckets(
                    connection,
                    context=context,
                    from_date=from_date,
                    to_date=to_date,
                    return_basis=return_basis,
                )
                unresolved_by_style, _unresolved_by_sku = self._style_unresolved(
                    connection,
                    parameters=parameters,
                    return_basis=return_basis,
                )
            total_rows = int(
                connection.scalar(style_sql.STYLE_COUNT_SQL, parameters) or 0
            )
            business_coverage = self._coverage_facts(
                context.all_members, "business_report", from_date, to_date
            )
            return_coverage = self._coverage_facts(
                context.all_members, "return_report", from_date, to_date
            )
            result_rows = [
                self._ledger_row(
                    row,
                    business_coverage=business_coverage,
                    return_coverage=return_coverage,
                    return_basis=return_basis,
                    unresolved_return_rows=unresolved_by_style.get(
                        int(row["style_id"]), 0
                    ),
                )
                for row in rows
            ]
            reconciliation = self._site_reconciliation(
                coverage_and_buckets,
                business_coverage=business_coverage,
                return_coverage=return_coverage,
                return_basis=return_basis,
            )
            contributing = self._contributing_dates(
                connection,
                context=context,
                from_date=from_date,
                to_date=to_date,
                return_basis=return_basis,
            )
            provenance = self._provenance(
                context,
                from_date=from_date,
                to_date=to_date,
                return_basis=return_basis,
                contributing_dates=contributing,
                trend_metric=None,
            )
            connection.commit()
            return StyleLedgerResponse(
                filtered_sales_total=(
                    format(rows[0]["filtered_sales_total"], ".2f")
                    if rows and business_coverage.observed_days
                    else None
                ),
                rows=result_rows,
                total_rows=total_rows,
                page=page,
                page_size=page_size,
                sort=sort,
                direction=direction,
                coverage=coverage_and_buckets.coverage,
                reconciliation=reconciliation,
                provenance=provenance,
                permissions=permissions or _default_permissions(),
            )
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def card(
        self,
        *,
        site_id: int,
        style_id: int,
        from_date: date,
        to_date: date,
        metric: MetricName = "units",
        dimension: SeriesDimension = "color",
        color_key: str | None = None,
        series: Sequence[str] | None = None,
        catalog_version_id: int | None = None,
        fact_basis: FactBasis = "current",
        return_basis: ReturnBasis = "event_date",
        permissions: AnalyticsPermissions | None = None,
    ) -> StyleCardResponse:
        _positive(style_id)
        _validate_range(from_date, to_date)
        if (dimension == "size") != (color_key is not None):
            raise AnalyticsDimensionParameterInvalid()
        if series is not None and (
            not 1 <= len(series) <= 8 or len(set(series)) != len(series)
        ):
            raise AnalyticsSeriesInvalid()
        connection = self._begin()
        try:
            context = self._resolve(
                connection,
                site_id=site_id,
                from_date=from_date,
                to_date=to_date,
                catalog_version_id=catalog_version_id,
                fact_basis=fact_basis,
                return_basis=return_basis,
            )
            parameters = self._parameters(context, from_date, to_date)
            parameters["style_id"] = style_id
            identity_row = (
                connection.execute(style_sql.STYLE_IDENTITY_SQL, parameters)
                .mappings()
                .one_or_none()
            )
            if identity_row is None:
                raise CatalogStyleNotFound()
            variant_rows = (
                connection.execute(style_sql.STYLE_VARIANTS_SQL, parameters)
                .mappings()
                .all()
            )
            aliases = self._aliases(connection, parameters)
            business_rows = (
                connection.execute(style_sql.STYLE_DAILY_SQL, parameters)
                .mappings()
                .all()
            )
            return_clause = (
                style_sql.STYLE_RETURN_DAILY_EVENT_DATE_SQL
                if return_basis == "event_date"
                else style_sql.STYLE_RETURN_DAILY_REPORT_DATE_SQL
            )
            return_rows = connection.execute(return_clause, parameters).mappings().all()
            _unresolved_by_style, unresolved_by_sku = self._style_unresolved(
                connection,
                parameters=parameters,
                return_basis=return_basis,
            )
            business_coverage = self._coverage_facts(
                context.all_members, "business_report", from_date, to_date
            )
            return_coverage = self._coverage_facts(
                context.all_members, "return_report", from_date, to_date
            )
            response = self._compose_card(
                context=context,
                identity_row=identity_row,
                variant_rows=variant_rows,
                aliases=aliases,
                business_rows=business_rows,
                return_rows=return_rows,
                from_date=from_date,
                to_date=to_date,
                metric=metric,
                dimension=dimension,
                color_key=color_key,
                requested_series=series,
                return_basis=return_basis,
                business_coverage=business_coverage,
                return_coverage=return_coverage,
                unresolved_by_sku=unresolved_by_sku,
                permissions=permissions or _default_permissions(),
            )
            connection.commit()
            return response
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _begin(self) -> Connection:
        connection = self._engine.connect()
        try:
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"
            )
            connection.exec_driver_sql(
                "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY"
            )
        except BaseException:
            connection.close()
            raise
        return connection

    def _resolve(
        self,
        connection: Connection,
        *,
        site_id: int,
        from_date: date,
        to_date: date,
        catalog_version_id: int | None,
        fact_basis: FactBasis,
        return_basis: ReturnBasis,
    ) -> _ResolvedContext:
        consistent = _utc(connection.scalar(sa.text("SELECT UTC_TIMESTAMP(6)")))
        if fact_basis == "catalog_snapshot" and catalog_version_id is None:
            raise AnalyticsCatalogVersionRequired()
        clause = (
            style_sql.CURRENT_CONTEXT_SQL
            if fact_basis == "current"
            else style_sql.SNAPSHOT_CONTEXT_SQL
        )
        row = (
            connection.execute(
                clause,
                {"site_id": site_id, "catalog_version_id": catalog_version_id},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            if fact_basis == "current":
                readiness = read_readiness(connection, site_id)
                if not readiness.source_scope_confirmed:
                    raise AnalyticsSourceScopeRequired()
                if not readiness.catalog_approved:
                    raise AnalyticsCatalogRequired()
                if not readiness.return_snapshot_present:
                    raise AnalyticsReturnSnapshotRequired()
            raise StyleAnalyticsError()
        actual_catalog_id = _positive(row["catalog_version_id"])
        if (
            fact_basis == "current"
            and catalog_version_id is not None
            and catalog_version_id != actual_catalog_id
        ):
            raise AnalyticsIdentityFactCombinationInvalid()
        timezone_name = str(row["reporting_timezone"])
        try:
            today = consistent.astimezone(ZoneInfo(timezone_name)).date()
        except ZoneInfoNotFoundError as error:
            raise StyleAnalyticsError() from error
        if to_date > today:
            raise AnalyticsDateRangeInvalid()
        scope_id = _positive(row["report_source_scope_id"])
        snapshot_id = (
            None
            if row.get("publication_snapshot_id") is None
            else _positive(row["publication_snapshot_id"])
        )
        fact_cutoff = (
            consistent if fact_basis == "current" else _utc(row["fact_cutoff_at"])
        )
        if fact_basis == "catalog_snapshot":
            cutoff_day = fact_cutoff.astimezone(ZoneInfo(timezone_name)).date()
            if (
                from_date < _date(row["coverage_start_date"])
                or to_date > _date(row["coverage_end_date"])
                or to_date > cutoff_day
            ):
                raise CatalogSnapshotRangeOutOfBounds()
            member_rows = (
                connection.execute(
                    style_sql.SNAPSHOT_MEMBERS_SQL,
                    {
                        "site_id": site_id,
                        "publication_snapshot_id": snapshot_id,
                        "member_from_date": _date(row["coverage_start_date"]),
                        "member_to_date": _date(row["coverage_end_date"]),
                    },
                )
                .mappings()
                .all()
            )
            all_members = tuple(_rows_to_members(member_rows))
            _complete_member_band(
                all_members,
                from_date=from_date,
                to_date=to_date,
                snapshot=True,
            )
        else:
            member_rows = (
                connection.execute(
                    style_sql.CURRENT_MEMBERS_SQL,
                    {
                        "site_id": site_id,
                        "report_source_scope_id": scope_id,
                        "member_from_date": from_date,
                        "member_to_date": to_date,
                    },
                )
                .mappings()
                .all()
            )
            requested = _complete_member_band(
                _rows_to_members(member_rows),
                from_date=from_date,
                to_date=to_date,
                snapshot=False,
            )
            all_return_rows = (
                connection.execute(
                    style_sql.ALL_CURRENT_RETURN_MEMBERS_SQL,
                    {"site_id": site_id, "report_source_scope_id": scope_id},
                )
                .mappings()
                .all()
            )
            frozen = tuple(
                FrozenPublicationMember(
                    dataset_id=int(item["dataset_id"]),
                    published_version_id=int(item["published_version_id"]),
                    publication_revision=int(item["pointer_revision"]),
                    version_data_revision=int(item["data_revision"]),
                    report_date=_date(item["report_date"]),
                )
                for item in all_return_rows
            )
            if not hmac.compare_digest(
                publication_set_digest(frozen),
                _bytes(row["return_publication_set_digest"], 32),
            ):
                raise AnalyticsSnapshotStale()
            extra_return_members = [
                PublicationDay(
                    report_type="return_report",
                    report_date=_date(item["report_date"]),
                    report_status="published",
                    dataset_id=str(item["dataset_id"]),
                    published_version_id=str(item["published_version_id"]),
                    snapshot_member_id=None,
                    pointer_revision=int(item["pointer_revision"]),
                )
                for item in all_return_rows
                if not from_date <= _date(item["report_date"]) <= to_date
            ]
            all_members = requested + tuple(extra_return_members)
        requested_members = tuple(
            member
            for member in all_members
            if from_date <= member.report_date <= to_date
        )
        business_versions = _member_versions(requested_members, "business_report")
        return_member_source = (
            all_members if return_basis == "event_date" else requested_members
        )
        return_versions = _member_versions(return_member_source, "return_report")
        return _ResolvedContext(
            site_id=site_id,
            catalog_version_id=actual_catalog_id,
            catalog_version=_positive(row["catalog_version"]),
            report_source_scope_id=scope_id,
            publication_snapshot_id=snapshot_id,
            return_dedup_snapshot_id=_positive(row["return_dedup_snapshot_id"]),
            site_config_version_id=_positive(row["site_config_version_id"]),
            reporting_timezone=timezone_name,
            consistent_as_of=consistent,
            fact_cutoff_at=fact_cutoff,
            fact_basis=fact_basis,
            all_members=all_members,
            business_version_ids=business_versions,
            return_version_ids=return_versions,
        )

    @staticmethod
    def _parameters(
        context: _ResolvedContext,
        from_date: date,
        to_date: date,
    ) -> dict[str, object]:
        event_from, event_to = _event_bounds(
            from_date, to_date, context.reporting_timezone
        )
        return {
            "site_id": context.site_id,
            "catalog_version_id": context.catalog_version_id,
            "report_source_scope_id": context.report_source_scope_id,
            "return_dedup_snapshot_id": context.return_dedup_snapshot_id,
            "from_date": from_date,
            "to_date": to_date,
            "event_from_utc": event_from,
            "event_to_utc": event_to,
            "reporting_timezone": context.reporting_timezone,
            "business_version_ids": context.business_version_ids,
            "return_version_ids": context.return_version_ids,
        }

    @staticmethod
    def _coverage_facts(
        members: Iterable[PublicationDay],
        report_type: str,
        from_date: date,
        to_date: date,
    ) -> CoverageFacts:
        relevant = {
            member.report_date: member
            for member in members
            if member.report_type == report_type
            and from_date <= member.report_date <= to_date
        }
        expected = _date_span(from_date, to_date)
        observed = sum(
            member.report_status == "published" for member in relevant.values()
        )
        return CoverageFacts(expected_days=expected, observed_days=observed)

    def _coverage_and_buckets(
        self,
        connection: Connection,
        *,
        context: _ResolvedContext,
        from_date: date,
        to_date: date,
        return_basis: ReturnBasis,
    ) -> _CoverageAndBuckets:
        parameters = self._parameters(context, from_date, to_date)
        business_rows = (
            connection.execute(style_sql.BUSINESS_BUCKETS_SQL, parameters)
            .mappings()
            .all()
        )
        return_clause = (
            style_sql.RETURN_BUCKETS_EVENT_DATE_SQL
            if return_basis == "event_date"
            else style_sql.RETURN_BUCKETS_REPORT_DATE_SQL
        )
        return_rows = connection.execute(return_clause, parameters).mappings().all()
        buckets = {
            name: _Bucket()
            for name in ("mapped", "unmatched", "excluded", "duplicate", "unresolved")
        }
        business_identity: defaultdict[str, int] = defaultdict(int)
        for row in business_rows:
            name = str(row["result_bucket"])
            if name not in {"mapped", "unmatched", "excluded"}:
                raise StyleAnalyticsError()
            bucket = buckets[name]
            count = int(row["fact_rows"])
            bucket.units += int(row["units"] or 0)
            bucket.sales += Decimal(str(row["sales"] or 0))
            bucket.sessions += int(row["sessions"] or 0)
            bucket.business_rows += count
            business_identity[name] += count
        return_identity: defaultdict[str, int] = defaultdict(int)
        dedup_counts: defaultdict[str, int] = defaultdict(int)
        unresolved_mapped = 0
        for row in return_rows:
            name = str(row["result_bucket"])
            if name not in buckets:
                raise StyleAnalyticsError()
            count = int(row["fact_rows"])
            buckets[name].returns += int(row["returns"] or 0)
            buckets[name].return_rows += count
            return_identity[str(row["identity_bucket"])] += count
            dedup_counts[str(row["dedup_bucket"])] += count
            if name == "unresolved" and row["identity_bucket"] == "mapped":
                unresolved_mapped += count
        business_coverage = self._coverage_facts(
            context.all_members, "business_report", from_date, to_date
        )
        return_coverage = self._coverage_facts(
            context.all_members, "return_report", from_date, to_date
        )
        coverage = SiteCoverage(
            business=self._coverage_block(
                report_type="business_report",
                from_date=from_date,
                to_date=to_date,
                coverage=business_coverage,
                identity=business_identity,
                dedup=None,
            ),
            returns=self._coverage_block(
                report_type="return_report",
                from_date=from_date,
                to_date=to_date,
                coverage=return_coverage,
                identity=return_identity,
                dedup=dedup_counts,
            ),
        )
        return _CoverageAndBuckets(
            coverage=coverage,
            buckets=buckets,
            unresolved_mapped_rows=unresolved_mapped,
        )

    def _coverage_and_buckets_from_ledger_row(
        self,
        row: RowMapping,
        *,
        context: _ResolvedContext,
        from_date: date,
        to_date: date,
        return_basis: ReturnBasis,
    ) -> _CoverageAndBuckets:
        buckets = {
            name: _Bucket()
            for name in ("mapped", "unmatched", "excluded", "duplicate", "unresolved")
        }
        for name in ("mapped", "unmatched", "excluded"):
            bucket = buckets[name]
            bucket.business_rows = int(row[f"business_{name}_rows"] or 0)
            bucket.units = int(row[f"business_{name}_units"] or 0)
            bucket.sales = Decimal(str(row[f"business_{name}_sales"] or 0))
            bucket.sessions = int(row[f"business_{name}_sessions"] or 0)
        return_column_names = {
            "mapped": ("return_mapped_rows", "return_mapped_quantity"),
            "unmatched": ("return_unmatched_rows", "return_unmatched_quantity"),
            "excluded": ("return_excluded_rows", "return_excluded_quantity"),
            "duplicate": ("return_duplicate_rows", "return_duplicate_quantity"),
            "unresolved": (
                "return_unresolved_bucket_rows",
                "return_unresolved_quantity",
            ),
        }
        for name, (rows_column, quantity_column) in return_column_names.items():
            bucket = buckets[name]
            bucket.return_rows = int(row[rows_column] or 0)
            bucket.returns = int(row[quantity_column] or 0)
        business_identity = {
            name: int(row[f"business_{name}_rows"] or 0)
            for name in ("mapped", "unmatched", "excluded")
        }
        return_identity = {
            name: int(row[f"return_identity_{name}_rows"] or 0)
            for name in ("mapped", "unmatched", "excluded")
        }
        dedup_counts = {
            name: int(row[f"return_{name}_rows"] or 0)
            for name in (
                "unique",
                "confirmed_distinct",
                "duplicate_of",
                "unresolved",
            )
        }
        business_coverage = self._coverage_facts(
            context.all_members, "business_report", from_date, to_date
        )
        return_coverage = self._coverage_facts(
            context.all_members, "return_report", from_date, to_date
        )
        coverage = SiteCoverage(
            business=self._coverage_block(
                report_type="business_report",
                from_date=from_date,
                to_date=to_date,
                coverage=business_coverage,
                identity=business_identity,
                dedup=None,
            ),
            returns=self._coverage_block(
                report_type="return_report",
                from_date=from_date,
                to_date=to_date,
                coverage=return_coverage,
                identity=return_identity,
                dedup=dedup_counts,
            ),
        )
        return _CoverageAndBuckets(
            coverage=coverage,
            buckets=buckets,
            unresolved_mapped_rows=int(row["unresolved_mapped_rows"] or 0),
        )

    @staticmethod
    def _style_unresolved(
        connection: Connection,
        *,
        parameters: Mapping[str, object],
        return_basis: ReturnBasis,
    ) -> tuple[dict[int, int], dict[int, int]]:
        clause = (
            style_sql.STYLE_UNRESOLVED_EVENT_DATE_SQL
            if return_basis == "event_date"
            else style_sql.STYLE_UNRESOLVED_REPORT_DATE_SQL
        )
        by_style: defaultdict[int, int] = defaultdict(int)
        by_sku: dict[int, int] = {}
        for row in connection.execute(clause, parameters).mappings():
            style_id = int(row["style_id"])
            sku_id = int(row["sku_id"])
            count = int(row["unresolved_rows"])
            by_style[style_id] += count
            by_sku[sku_id] = count
        return dict(by_style), by_sku

    @staticmethod
    def _coverage_block(
        *,
        report_type: Literal["business_report", "return_report"],
        from_date: date,
        to_date: date,
        coverage: CoverageFacts,
        identity: Mapping[str, int],
        dedup: Mapping[str, int] | None,
    ) -> CoverageBlock:
        mapped = identity.get("mapped", 0)
        unmatched = identity.get("unmatched", 0)
        excluded = identity.get("excluded", 0)
        eligible = mapped + unmatched + excluded
        identity_status = (
            "not_applicable"
            if coverage.observed_days == 0
            else ("partial" if unmatched else "complete")
        )
        if dedup is None:
            unique = confirmed = duplicate = unresolved = None
            dedup_rate = None
            dedup_status = "not_applicable"
        else:
            unique = dedup.get("unique", 0)
            confirmed = dedup.get("confirmed_distinct", 0)
            duplicate = dedup.get("duplicate_of", 0)
            unresolved = dedup.get("unresolved", 0)
            dedup_rate = rate_text(unique + confirmed + duplicate, eligible)
            dedup_status = (
                "not_applicable"
                if coverage.observed_days == 0
                else ("partial" if unresolved else "complete")
            )
        return CoverageBlock(
            report_type=report_type,
            coverage_from=from_date,
            coverage_to=to_date,
            expected_days=coverage.expected_days,
            published_days=coverage.observed_days,
            missing_days=coverage.expected_days - coverage.observed_days,
            eligible_rows=eligible,
            mapped_rows=mapped,
            unmatched_rows=unmatched,
            excluded_rows=excluded,
            unique_rows=unique,
            confirmed_distinct_rows=confirmed,
            duplicate_of_rows=duplicate,
            unresolved_rows=unresolved,
            report_coverage_rate=rate_text(
                coverage.observed_days, coverage.expected_days
            ),
            identity_decision_rate=rate_text(mapped + excluded, eligible),
            mapping_rate=rate_text(mapped, eligible),
            dedup_decision_rate=dedup_rate,
            identity_status=cast(Any, identity_status),
            dedup_status=cast(Any, dedup_status),
        )

    @staticmethod
    def _ledger_row(
        row: RowMapping,
        *,
        business_coverage: CoverageFacts,
        return_coverage: CoverageFacts,
        return_basis: ReturnBasis,
        unresolved_return_rows: int,
    ) -> StyleLedgerRow:
        aggregate = MetricAggregate(
            units=int(row["units"] or 0),
            sales=Decimal(str(row["sales"] or 0)),
            returns=int(row["returns"] or 0),
            sessions=int(row["sessions"] or 0),
            business_fact_rows=int(row["business_fact_rows"] or 0),
            return_fact_rows=int(row["return_fact_rows"] or 0),
        )
        status = str(row["status"])
        if status not in {"enabled", "disabled"}:
            raise StyleAnalyticsError()
        return StyleLedgerRow(
            style_id=str(row["style_id"]),
            style_code=str(row["style_code"]),
            standard_name=str(row["standard_name"]),
            status=cast(Any, status),
            sku_count=int(row["sku_count"]),
            color_count=int(row["color_count"]),
            size_count=int(row["size_count"]),
            source_title_count=int(row["source_title_count"]),
            latest_report_date=(
                None
                if row["latest_report_date"] is None
                else _date(row["latest_report_date"])
            ),
            metrics=build_metric_values(
                aggregate,
                business_coverage=business_coverage,
                return_coverage=return_coverage,
                return_basis=return_basis,
                unresolved_return_rows=unresolved_return_rows,
            ),
        )

    @staticmethod
    def _totals(
        bucket: _Bucket,
        *,
        business_evaluable: bool,
        returns_evaluable: bool,
        business_applicable: bool = True,
    ) -> MetricTotals:
        return MetricTotals(
            units=(
                bucket.units if business_evaluable and business_applicable else None
            ),
            sales=(
                money_text(bucket.sales)
                if business_evaluable and business_applicable
                else None
            ),
            returns=bucket.returns if returns_evaluable else None,
            sessions=(
                bucket.sessions if business_evaluable and business_applicable else None
            ),
            conversion_numerator=(
                bucket.units if business_evaluable and business_applicable else None
            ),
            conversion_denominator=(
                bucket.sessions if business_evaluable and business_applicable else None
            ),
        )

    def _site_reconciliation(
        self,
        data: _CoverageAndBuckets,
        *,
        business_coverage: CoverageFacts,
        return_coverage: CoverageFacts,
        return_basis: ReturnBasis,
    ) -> Any:
        business_evaluable = business_coverage.observed_days > 0
        returns_evaluable = (
            return_basis == "event_date" or return_coverage.observed_days > 0
        )
        source = _Bucket()
        for bucket in data.buckets.values():
            source.units += bucket.units
            source.sales += bucket.sales
            source.returns += bucket.returns
            source.sessions += bucket.sessions
        return build_site_reconciliation(
            source=self._totals(
                source,
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            ),
            mapped=self._totals(
                data.buckets["mapped"],
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            ),
            unmatched=self._totals(
                data.buckets["unmatched"],
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            ),
            excluded=self._totals(
                data.buckets["excluded"],
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            ),
            duplicate=self._totals(
                data.buckets["duplicate"],
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
                business_applicable=False,
            ),
            unresolved=self._totals(
                data.buckets["unresolved"],
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
                business_applicable=False,
            ),
        )

    def _contributing_dates(
        self,
        connection: Connection,
        *,
        context: _ResolvedContext,
        from_date: date,
        to_date: date,
        return_basis: ReturnBasis,
    ) -> tuple[date, ...]:
        if return_basis == "report_date" or not context.return_version_ids:
            return ()
        rows = connection.scalars(
            style_sql.CONTRIBUTING_RETURN_DATES_SQL,
            self._parameters(context, from_date, to_date),
        ).all()
        return tuple(_date(value) for value in rows)

    @staticmethod
    def _provenance(
        context: _ResolvedContext,
        *,
        from_date: date,
        to_date: date,
        return_basis: ReturnBasis,
        contributing_dates: Sequence[date],
        trend_metric: MetricName | None,
    ) -> AnalyticsProvenance:
        dates = set(contributing_dates)
        members = [
            member
            for member in context.all_members
            if from_date <= member.report_date <= to_date
            or (member.report_type == "return_report" and member.report_date in dates)
        ]
        refs = PublicationRefs.build(
            mode=context.fact_basis,
            snapshot_id=context.publication_snapshot_id,
            members=members,
        )
        return AnalyticsProvenance(
            catalog_version_id=str(context.catalog_version_id),
            catalog_version=context.catalog_version,
            fact_basis=context.fact_basis,
            identity_version_id=str(context.catalog_version_id),
            publication_refs=refs,
            return_dedup_snapshot_id=str(context.return_dedup_snapshot_id),
            site_config_version_id=str(context.site_config_version_id),
            reporting_timezone=context.reporting_timezone,
            consistent_as_of=context.consistent_as_of,
            fact_cutoff_at=context.fact_cutoff_at,
            from_date=from_date,
            to_date=to_date,
            return_basis=return_basis,
            effective_return_basis=return_basis,
            trend_effective_return_basis=(
                return_basis if trend_metric == "returns" else None
            ),
        )

    @staticmethod
    def _aliases(
        connection: Connection,
        parameters: Mapping[str, object],
    ) -> dict[int, list[SafeSourceRef]]:
        result: dict[int, list[SafeSourceRef]] = defaultdict(list)
        rows = connection.execute(style_sql.STYLE_ALIASES_SQL, parameters).mappings()
        for row in rows:
            result[int(row["sku_id"])].append(
                SafeSourceRef(
                    source_ref_id=str(row["source_ref_id"]),
                    preview=str(row["safe_preview"]),
                    sha256="sha256:" + _bytes(row["raw_sha256"], 32).hex(),
                    is_unsafe=bool(row["is_unsafe"]),
                    is_truncated=bool(row["is_truncated"]),
                )
            )
        return result

    def _compose_card(
        self,
        *,
        context: _ResolvedContext,
        identity_row: RowMapping,
        variant_rows: Sequence[RowMapping],
        aliases: Mapping[int, list[SafeSourceRef]],
        business_rows: Sequence[RowMapping],
        return_rows: Sequence[RowMapping],
        from_date: date,
        to_date: date,
        metric: MetricName,
        dimension: SeriesDimension,
        color_key: str | None,
        requested_series: Sequence[str] | None,
        return_basis: ReturnBasis,
        business_coverage: CoverageFacts,
        return_coverage: CoverageFacts,
        unresolved_by_sku: Mapping[int, int],
        permissions: AnalyticsPermissions,
    ) -> StyleCardResponse:
        by_sku_day: dict[tuple[int, date], _Bucket] = defaultdict(_Bucket)
        for row in business_rows:
            bucket = by_sku_day[(int(row["sku_id"]), _date(row["metric_date"]))]
            bucket.units += int(row["units"] or 0)
            bucket.sales += Decimal(str(row["sales"] or 0))
            bucket.sessions += int(row["sessions"] or 0)
            bucket.business_rows += int(row["business_fact_rows"] or 0)
        contributing_dates: set[date] = set()
        for row in return_rows:
            bucket = by_sku_day[(int(row["sku_id"]), _date(row["metric_date"]))]
            bucket.returns += int(row["returns"] or 0)
            bucket.return_rows += int(row["return_fact_rows"] or 0)
            if row["contributing_report_date_from"] is not None:
                contributing_dates.add(_date(row["contributing_report_date_from"]))
                contributing_dates.add(_date(row["contributing_report_date_to"]))
        variant_meta: dict[int, RowMapping] = {
            int(row["sku_id"]): row for row in variant_rows
        }
        sku_totals: dict[int, _Bucket] = {sku_id: _Bucket() for sku_id in variant_meta}
        for (sku_id, _day), bucket in by_sku_day.items():
            total = sku_totals.setdefault(sku_id, _Bucket())
            self._add_bucket(total, bucket)
        variants: list[StyleVariant] = []
        for sku_id, row in variant_meta.items():
            aggregate = sku_totals[sku_id].aggregate()
            status = str(row["status"])
            if status not in {"enabled", "disabled"}:
                raise StyleAnalyticsError()
            variants.append(
                StyleVariant(
                    sku_id=str(sku_id),
                    standard_color=str(row["standard_color"]),
                    standard_size=str(row["standard_size"]),
                    internal_display_sku=str(row["internal_display_sku"]),
                    status=cast(Any, status),
                    seller_sku_aliases=list(aliases.get(sku_id, [])),
                    metrics=build_metric_values(
                        aggregate,
                        business_coverage=business_coverage,
                        return_coverage=return_coverage,
                        return_basis=return_basis,
                        unresolved_return_rows=unresolved_by_sku.get(sku_id, 0),
                    ),
                )
            )
        whole = _Bucket()
        for total in sku_totals.values():
            self._add_bucket(whole, total)
        summary_metrics = build_metric_values(
            whole.aggregate(),
            business_coverage=business_coverage,
            return_coverage=return_coverage,
            return_basis=return_basis,
            unresolved_return_rows=sum(unresolved_by_sku.values()),
        )
        series_groups, selected_color_total = self._series_groups(
            context=context,
            style_id=int(identity_row["style_id"]),
            dimension=dimension,
            color_key=color_key,
            variant_meta=variant_meta,
            sku_totals=sku_totals,
        )
        ranked = self._rank_series(
            series_groups,
            metric=metric,
            business_coverage=business_coverage,
            return_coverage=return_coverage,
            return_basis=return_basis,
            unresolved_by_sku=unresolved_by_sku,
        )
        available_keys = {item[0] for item in ranked}
        active_keys = (
            [item[0] for item in ranked[:8]]
            if requested_series is None
            else list(requested_series)
        )
        if not active_keys or any(key not in available_keys for key in active_keys):
            raise AnalyticsSeriesInvalid()
        available = [
            AvailableSeries(
                key=key,
                label=label,
                dimension=dimension,
                total=metrics.model_dump()[metric],
                active=key in active_keys,
                sort_order=index,
            )
            for index, (key, label, _members, metrics) in enumerate(ranked, start=1)
        ]
        trend_series: list[TrendSeries] = []
        report_type = "return_report" if metric == "returns" else "business_report"
        published_by_day = {
            member.report_date: member.report_status == "published"
            for member in context.all_members
            if member.report_type == report_type
            and from_date <= member.report_date <= to_date
        }
        for key in active_keys:
            group = next(item for item in ranked if item[0] == key)
            sku_ids = group[2]
            points = []
            current = from_date
            while current <= to_date:
                daily = _Bucket()
                for sku_id in sku_ids:
                    self._add_bucket(
                        daily,
                        by_sku_day.get((sku_id, current), _Bucket()),
                    )
                value: int | Decimal | None
                if metric == "sales":
                    value = daily.sales
                elif metric == "returns":
                    value = daily.returns
                elif metric == "sessions":
                    value = daily.sessions
                elif metric == "units":
                    value = daily.units
                else:
                    value = None
                points.append(
                    build_trend_point(
                        report_date=current,
                        metric=metric,
                        value=value,
                        contributing_rows=(
                            daily.return_rows
                            if metric == "returns"
                            else daily.business_rows
                        ),
                        report_published=published_by_day.get(current, False),
                        return_basis=return_basis,
                        numerator=(daily.units if metric == "conversion" else None),
                        denominator=(
                            daily.sessions if metric == "conversion" else None
                        ),
                    )
                )
                current += timedelta(days=1)
            trend_series.append(TrendSeries(key=key, points=points))
        business_evaluable = business_coverage.observed_days > 0
        returns_evaluable = (
            return_basis == "event_date" or return_coverage.observed_days > 0
        )
        summary_totals = self._totals(
            whole,
            business_evaluable=business_evaluable,
            returns_evaluable=returns_evaluable,
        )
        series_total = _Bucket()
        for _key, _label, members, _metrics in ranked:
            for sku_id in members:
                self._add_bucket(series_total, sku_totals[sku_id])
        selected_totals_model = (
            None
            if selected_color_total is None
            else self._totals(
                selected_color_total,
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            )
        )
        style_reconciliation = build_style_reconciliation(
            summary=summary_totals,
            variants=summary_totals,
            series=self._totals(
                series_total,
                business_evaluable=business_evaluable,
                returns_evaluable=returns_evaluable,
            ),
            dimension=dimension,
            selected_color=selected_totals_model,
        )
        days = [
            member
            for member in context.all_members
            if from_date <= member.report_date <= to_date
        ]
        source_coverage = SourceReportCoverage(
            coverage_from=from_date,
            coverage_to=to_date,
            days=sorted(days, key=lambda item: (item.report_type, item.report_date)),
            contributing_report_date_from=(
                min(contributing_dates) if contributing_dates else None
            ),
            contributing_report_date_to=(
                max(contributing_dates) if contributing_dates else None
            ),
        )
        provenance = self._provenance(
            context,
            from_date=from_date,
            to_date=to_date,
            return_basis=return_basis,
            contributing_dates=tuple(contributing_dates),
            trend_metric=metric,
        )
        identity_status = str(identity_row["status"])
        return StyleCardResponse(
            style=StyleIdentity(
                style_id=str(identity_row["style_id"]),
                style_code=str(identity_row["style_code"]),
                standard_name=str(identity_row["standard_name"]),
                status=cast(Any, identity_status),
                sku_count=int(identity_row["sku_count"]),
                color_count=int(identity_row["color_count"]),
                size_count=int(identity_row["size_count"]),
            ),
            summary=StyleSummary(metrics=summary_metrics),
            available_series=available,
            series=trend_series,
            variants=variants,
            effective_return_basis=return_basis,
            trend_effective_return_basis=(
                return_basis if metric == "returns" else None
            ),
            source_report_coverage=source_coverage,
            style_reconciliation=style_reconciliation,
            provenance=provenance,
            permissions=permissions,
        )

    @staticmethod
    def _add_bucket(target: _Bucket, source: _Bucket) -> None:
        target.units += source.units
        target.sales += source.sales
        target.returns += source.returns
        target.sessions += source.sessions
        target.business_rows += source.business_rows
        target.return_rows += source.return_rows

    def _series_groups(
        self,
        *,
        context: _ResolvedContext,
        style_id: int,
        dimension: SeriesDimension,
        color_key: str | None,
        variant_meta: Mapping[int, RowMapping],
        sku_totals: Mapping[int, _Bucket],
    ) -> tuple[list[tuple[str, str, tuple[int, ...], _Bucket]], _Bucket | None]:
        groups: dict[tuple[bytes, str], list[int]] = defaultdict(list)
        selected_color_bytes: bytes | None = None
        if dimension == "total":
            groups[(b"total", "全部")] = list(variant_meta)
        elif dimension == "sku":
            for sku_id, row in variant_meta.items():
                if row["status"] == "enabled" or self._has_facts(sku_totals[sku_id]):
                    group_key = (
                        str(sku_id).encode("ascii"),
                        str(row["internal_display_sku"]),
                    )
                    groups[group_key].append(sku_id)
        elif dimension == "color":
            for sku_id, row in variant_meta.items():
                group_key = (
                    _bytes_any(row["color_key_bytes"]),
                    str(row["standard_color"]),
                )
                groups[group_key].append(sku_id)
        else:
            for row in variant_meta.values():
                candidate = stable_series_key(
                    catalog_version_id=context.catalog_version_id,
                    style_id=style_id,
                    dimension="color",
                    normalized_value=_bytes_any(row["color_key_bytes"]),
                )
                if candidate == color_key:
                    selected_color_bytes = _bytes_any(row["color_key_bytes"])
                    break
            if selected_color_bytes is None:
                raise CatalogColorNotFound()
            for sku_id, row in variant_meta.items():
                if _bytes_any(row["color_key_bytes"]) == selected_color_bytes:
                    group_key = (
                        _bytes_any(row["size_key_bytes"]),
                        str(row["standard_size"]),
                    )
                    groups[group_key].append(sku_id)
        result: list[tuple[str, str, tuple[int, ...], _Bucket]] = []
        for (normalized, label), sku_ids in groups.items():
            key = (
                "total"
                if dimension == "total"
                else stable_series_key(
                    catalog_version_id=context.catalog_version_id,
                    style_id=style_id,
                    dimension=dimension,
                    normalized_value=normalized,
                    normalized_color=(
                        selected_color_bytes if dimension == "size" else None
                    ),
                )
            )
            total = _Bucket()
            for sku_id in sku_ids:
                self._add_bucket(total, sku_totals[sku_id])
            result.append((key, label, tuple(sku_ids), total))
        selected_total: _Bucket | None = None
        if dimension == "size":
            selected_total = _Bucket()
            for _key, _label, _members, total in result:
                self._add_bucket(selected_total, total)
        return result, selected_total

    @staticmethod
    def _has_facts(bucket: _Bucket) -> bool:
        return bucket.business_rows > 0 or bucket.return_rows > 0

    @staticmethod
    def _rank_series(
        groups: Sequence[tuple[str, str, tuple[int, ...], _Bucket]],
        *,
        metric: MetricName,
        business_coverage: CoverageFacts,
        return_coverage: CoverageFacts,
        return_basis: ReturnBasis,
        unresolved_by_sku: Mapping[int, int],
    ) -> list[tuple[str, str, tuple[int, ...], Any]]:
        values = []
        for key, label, members, bucket in groups:
            metrics = build_metric_values(
                bucket.aggregate(),
                business_coverage=business_coverage,
                return_coverage=return_coverage,
                return_basis=return_basis,
                unresolved_return_rows=sum(
                    unresolved_by_sku.get(sku_id, 0) for sku_id in members
                ),
            )
            values.append((key, label, members, metrics))
        values.sort(key=lambda item: (item[1].encode("utf-8"), item[0]))

        def value_key(
            item: tuple[str, str, tuple[int, ...], Any],
        ) -> tuple[int, Decimal]:
            value = getattr(item[3], metric).value
            return (value is not None, Decimal(str(value or 0)))

        values.sort(key=value_key, reverse=True)
        return values


def _bytes_any(value: object) -> bytes:
    if not isinstance(value, (bytes, bytearray, memoryview)):
        raise StyleAnalyticsError()
    result = bytes(value)
    if not result:
        raise StyleAnalyticsError()
    return result


__all__ = (
    "AnalyticsCatalogVersionRequired",
    "AnalyticsDateRangeInvalid",
    "AnalyticsDimensionParameterInvalid",
    "AnalyticsIdentityFactCombinationInvalid",
    "AnalyticsSeriesInvalid",
    "CatalogColorNotFound",
    "CatalogSnapshotRangeOutOfBounds",
    "CatalogStyleNotFound",
    "MySqlStyleAnalyticsRepository",
    "StyleAnalyticsError",
)
