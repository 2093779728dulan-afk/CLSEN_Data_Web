"""Queries over current publication pointers only.

This service is the single analytics boundary used by both HTTP dashboard routes
and the future read-only agent adapter.  It never accepts SQL or version IDs from
callers: every version is resolved through ``dataset_publications``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal, TypedDict, cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.engine import RowMapping
from sqlalchemy.orm import Session

from app.analytics.errors import (
    AnalyticsDateRangeTooLarge,
    InvalidAnalyticsDateRange,
    InvalidReturnBasis,
    InvalidSiteConfiguration,
    MissingSiteConfiguration,
)
from app.analytics.models import (
    DashboardMetric,
    DashboardSummary,
    DateRange,
    ProductDashboard,
    ProductMetric,
    PublicationReference,
    ReturnBreakdown,
    ReturnDashboard,
    SiteConfigurationReference,
)

type ReturnBasis = Literal["report_date", "event_date"]

MAX_ANALYTICS_DATE_RANGE_DAYS = 366


class _SummaryAccumulator(TypedDict):
    sales: Decimal
    units_ordered: int
    sessions: int
    return_quantity: int
    business_version_id: int | None
    return_version_id: int | None


class PublishedAnalyticsQueryService:
    """Read redacted analytics from the exact versions currently published."""

    def __init__(self, database_session: Session) -> None:
        self._database_session = database_session

    def publication_references(
        self,
        from_date: date,
        to_date: date,
        *,
        report_types: tuple[Literal["business_report", "return_report"], ...],
    ) -> list[PublicationReference]:
        """Expose exact current pointers to sibling published-only queries."""

        _date_range(from_date, to_date)
        return self._publication_references(
            from_date=from_date,
            to_date=to_date,
            report_types=report_types,
        )

    def site_configuration_references(
        self,
        site_ids: set[int],
    ) -> list[SiteConfigurationReference]:
        return self._current_site_configurations(site_ids)

    def summary(self, from_date: date, to_date: date) -> DashboardSummary:
        requested_range = _date_range(from_date, to_date)
        values: dict[date, _SummaryAccumulator] = {
            date.fromordinal(ordinal): {
                "sales": Decimal(0),
                "units_ordered": 0,
                "sessions": 0,
                "return_quantity": 0,
                "business_version_id": None,
                "return_version_id": None,
            }
            for ordinal in range(from_date.toordinal(), to_date.toordinal() + 1)
        }

        business_rows = self._database_session.execute(
            sa.text(
                """
                SELECT datasets.report_date, publications.version_id,
                       COALESCE(SUM(report_rows.ordered_product_sales), 0) AS sales,
                       COALESCE(SUM(report_rows.units_ordered), 0) AS units_ordered,
                       COALESCE(SUM(report_rows.sessions_total), 0) AS sessions
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN business_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                WHERE datasets.report_type = 'business_report'
                  AND datasets.report_date BETWEEN :from_date AND :to_date
                GROUP BY datasets.report_date, publications.version_id
                ORDER BY datasets.report_date
                """
            ),
            {"from_date": from_date, "to_date": to_date},
        ).mappings()
        for row in business_rows:
            report_date = cast(date, row["report_date"])
            values[report_date].update(
                {
                    "sales": Decimal(str(row["sales"])),
                    "units_ordered": int(row["units_ordered"]),
                    "sessions": int(row["sessions"]),
                    "business_version_id": int(row["version_id"]),
                }
            )

        return_rows = self._database_session.execute(
            sa.text(
                """
                SELECT datasets.report_date, publications.version_id,
                       COALESCE(SUM(report_rows.quantity), 0) AS return_quantity
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN return_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                WHERE datasets.report_type = 'return_report'
                  AND datasets.report_date BETWEEN :from_date AND :to_date
                GROUP BY datasets.report_date, publications.version_id
                ORDER BY datasets.report_date
                """
            ),
            {"from_date": from_date, "to_date": to_date},
        ).mappings()
        for row in return_rows:
            report_date = cast(date, row["report_date"])
            values[report_date].update(
                {
                    "return_quantity": int(row["return_quantity"]),
                    "return_version_id": int(row["version_id"]),
                }
            )

        publications = self._publication_references(
            from_date=from_date,
            to_date=to_date,
            report_types=("business_report", "return_report"),
        )
        return DashboardSummary(
            range=requested_range,
            metrics=[
                DashboardMetric(
                    report_date=report_date,
                    sales=_decimal_text(value["sales"]),
                    units_ordered=value["units_ordered"],
                    sessions=value["sessions"],
                    conversion_rate=(
                        _decimal_text(
                            Decimal(value["units_ordered"]) / Decimal(value["sessions"])
                        )
                        if value["sessions"]
                        else None
                    ),
                    return_quantity=value["return_quantity"],
                    business_version_id=value["business_version_id"],
                    return_version_id=value["return_version_id"],
                )
                for report_date, value in values.items()
            ],
            publications=publications,
            site_config_versions=self._current_site_configurations(
                {reference.site_id for reference in publications}
            ),
        )

    def products(
        self,
        from_date: date,
        to_date: date,
        *,
        limit: int,
    ) -> ProductDashboard:
        requested_range = _date_range(from_date, to_date)
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        rows = self._database_session.execute(
            sa.text(
                """
                SELECT report_rows.sku, report_rows.child_asin AS asin,
                       COALESCE(SUM(report_rows.ordered_product_sales), 0) AS sales,
                       COALESCE(SUM(report_rows.units_ordered), 0) AS units_ordered,
                       COALESCE(SUM(report_rows.sessions_total), 0) AS sessions
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN business_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                WHERE datasets.report_type = 'business_report'
                  AND datasets.report_date BETWEEN :from_date AND :to_date
                GROUP BY report_rows.sku, report_rows.child_asin
                ORDER BY sales DESC, units_ordered DESC, report_rows.sku
                LIMIT :limit
                """
            ),
            {"from_date": from_date, "to_date": to_date, "limit": limit},
        ).mappings()
        metrics: list[ProductMetric] = []
        for row in rows:
            sessions = int(row["sessions"])
            units = int(row["units_ordered"])
            metrics.append(
                ProductMetric(
                    sku=cast(str | None, row["sku"]),
                    asin=cast(str | None, row["asin"]),
                    sales=_decimal_text(row["sales"]),
                    units_ordered=units,
                    sessions=sessions,
                    conversion_rate=(
                        _decimal_text(Decimal(units) / Decimal(sessions))
                        if sessions
                        else None
                    ),
                )
            )
        publications = self._publication_references(
            from_date=from_date,
            to_date=to_date,
            report_types=("business_report",),
        )
        return ProductDashboard(
            range=requested_range,
            rows=metrics,
            publications=publications,
            site_config_versions=self._current_site_configurations(
                {reference.site_id for reference in publications}
            ),
        )

    def returns(
        self,
        from_date: date,
        to_date: date,
        *,
        basis: ReturnBasis,
    ) -> ReturnDashboard:
        requested_range = _date_range(from_date, to_date)
        if basis not in {"report_date", "event_date"}:
            raise InvalidReturnBasis
        query_parameters: dict[str, object] = {
            "from_date": from_date,
            "to_date": to_date,
        }
        if basis == "report_date":
            range_predicate = "AND datasets.report_date BETWEEN :from_date AND :to_date"
        else:
            published_site_ids = self._published_site_ids("return_report")
            published_site_configurations = self._current_site_configurations(
                published_site_ids
            )
            if not published_site_configurations:
                return ReturnDashboard(
                    basis=basis,
                    range=requested_range,
                    rows=[],
                    publications=[],
                    site_config_versions=[],
                )
            predicates: list[str] = []
            for index, configuration in enumerate(published_site_configurations):
                timezone = _reporting_timezone(configuration)
                lower_bound, upper_bound = _event_date_utc_bounds(
                    from_date,
                    to_date,
                    timezone,
                )
                site_predicates = [
                    f"datasets.site_id = :event_site_id_{index}",
                    (
                        "current_configs.current_config_version_id "
                        f"= :event_config_id_{index}"
                    ),
                ]
                query_parameters[f"event_site_id_{index}"] = configuration.site_id
                query_parameters[f"event_config_id_{index}"] = (
                    configuration.site_config_version_id
                )
                if lower_bound is not None:
                    site_predicates.append(
                        f"report_rows.return_date >= :event_from_utc_{index}"
                    )
                    query_parameters[f"event_from_utc_{index}"] = lower_bound
                if upper_bound is not None:
                    site_predicates.append(
                        f"report_rows.return_date < :event_to_utc_{index}"
                    )
                    query_parameters[f"event_to_utc_{index}"] = upper_bound
                predicates.append(f"({' AND '.join(site_predicates)})")
            range_predicate = f"AND ({' OR '.join(predicates)})"
        rows = self._database_session.execute(
            sa.text(
                f"""
                SELECT datasets.id AS dataset_id, datasets.site_id,
                       datasets.report_date, datasets.report_type,
                       publications.version_id, publications.published_at,
                       report_rows.return_date, report_rows.sku,
                       report_rows.asin, report_rows.reason,
                       report_rows.detailed_disposition, report_rows.quantity,
                       sites.code AS site_code,
                       current_configs.current_config_version_id AS config_id,
                       configs.source_timezone, configs.reporting_timezone,
                       configs.currency_code
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                INNER JOIN version_rows AS version_rows
                    ON version_rows.version_id = publications.version_id
                   AND version_rows.row_state = 'active'
                INNER JOIN return_report_rows AS report_rows
                    ON report_rows.version_row_id = version_rows.id
                   AND report_rows.version_id = publications.version_id
                INNER JOIN sites AS sites ON sites.id = datasets.site_id
                LEFT JOIN site_current_configs AS current_configs
                    ON current_configs.site_id = datasets.site_id
                LEFT JOIN site_config_versions AS configs
                    ON configs.site_id = current_configs.site_id
                   AND configs.id = current_configs.current_config_version_id
                WHERE datasets.report_type = 'return_report'
                  {range_predicate}
                ORDER BY datasets.id, version_rows.row_ordinal
                """
            ),
            query_parameters,
        ).mappings()

        grouped: defaultdict[
            tuple[
                date,
                str | None,
                str | None,
                str | None,
                str | None,
                str,
                int,
            ],
            int,
        ]
        grouped = defaultdict(int)
        references: dict[tuple[int, int], PublicationReference] = {}
        configurations: dict[int, SiteConfigurationReference] = {}
        for row in rows:
            configuration = _site_configuration_from_row(row)
            timezone = _reporting_timezone(configuration)

            report_date = cast(date, row["report_date"])
            if basis == "event_date":
                event_value = row["return_date"]
                if not isinstance(event_value, datetime):
                    continue
                bucket_date = _as_utc(event_value).astimezone(timezone).date()
                if not from_date <= bucket_date <= to_date:
                    continue
            else:
                bucket_date = report_date

            reference = _publication_reference_from_row(row)
            references[(reference.dataset_id, reference.version_id)] = reference
            configurations[configuration.site_config_version_id] = configuration
            grouped[
                (
                    bucket_date,
                    cast(str | None, row["sku"]),
                    cast(str | None, row["asin"]),
                    cast(str | None, row["reason"]),
                    cast(str | None, row["detailed_disposition"]),
                    configuration.reporting_timezone,
                    configuration.site_config_version_id,
                )
            ] += int(row["quantity"] or 0)

        return ReturnDashboard(
            basis=basis,
            range=requested_range,
            rows=[
                ReturnBreakdown(
                    bucket_date=bucket_date,
                    sku=sku,
                    asin=asin,
                    reason=reason,
                    disposition=disposition,
                    quantity=quantity,
                    reporting_timezone=timezone_name,
                    site_config_version_id=config_id,
                )
                for (
                    bucket_date,
                    sku,
                    asin,
                    reason,
                    disposition,
                    timezone_name,
                    config_id,
                ), quantity in sorted(
                    grouped.items(),
                    key=lambda item: (
                        item[0][0],
                        item[0][1] or "",
                        item[0][2] or "",
                        item[0][3] or "",
                        item[0][4] or "",
                        item[0][5],
                        item[0][6],
                    ),
                )
            ],
            publications=sorted(
                references.values(),
                key=lambda item: (item.report_date, item.dataset_id, item.version_id),
            ),
            site_config_versions=sorted(
                configurations.values(),
                key=lambda item: (item.site_id, item.site_config_version_id),
            ),
        )

    def _publication_references(
        self,
        *,
        from_date: date,
        to_date: date,
        report_types: tuple[str, ...],
    ) -> list[PublicationReference]:
        report_type_bind: sa.BindParameter[Any] = sa.bindparam(
            "report_types",
            expanding=True,
        )
        rows = self._database_session.execute(
            sa.text(
                """
                SELECT datasets.id AS dataset_id, datasets.site_id,
                       datasets.report_date, datasets.report_type,
                       publications.version_id, publications.published_at
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                WHERE datasets.report_date BETWEEN :from_date AND :to_date
                  AND datasets.report_type IN :report_types
                ORDER BY datasets.report_date, datasets.report_type, datasets.id
                """
            ).bindparams(report_type_bind),
            {
                "from_date": from_date,
                "to_date": to_date,
                "report_types": report_types,
            },
        ).mappings()
        return [_publication_reference_from_row(row) for row in rows]

    def _current_site_configurations(
        self,
        site_ids: set[int],
    ) -> list[SiteConfigurationReference]:
        if not site_ids:
            return []
        statement = sa.text(
            """
            SELECT sites.id AS site_id, sites.code AS site_code,
                   configs.id AS config_id, configs.source_timezone,
                   configs.reporting_timezone, configs.currency_code
            FROM sites AS sites
            INNER JOIN site_current_configs AS current_configs
                ON current_configs.site_id = sites.id
            INNER JOIN site_config_versions AS configs
                ON configs.site_id = current_configs.site_id
               AND configs.id = current_configs.current_config_version_id
            WHERE sites.status = 'active'
              AND sites.id IN :site_ids
            ORDER BY sites.id
            """
        ).bindparams(sa.bindparam("site_ids", expanding=True))
        parameters: dict[str, object] = {
            "site_ids": tuple(sorted(site_ids)),
        }
        rows = self._database_session.execute(statement, parameters).mappings().all()
        configurations = [_site_configuration_from_row(row) for row in rows]
        if site_ids and {item.site_id for item in configurations} != site_ids:
            raise MissingSiteConfiguration
        return configurations

    def _published_site_ids(self, report_type: str) -> set[int]:
        rows = self._database_session.execute(
            sa.text(
                """
                SELECT DISTINCT datasets.site_id
                FROM daily_datasets AS datasets
                INNER JOIN dataset_publications AS publications
                    ON publications.dataset_id = datasets.id
                WHERE datasets.report_type = :report_type
                ORDER BY datasets.site_id
                """
            ),
            {"report_type": report_type},
        ).scalars()
        return {int(site_id) for site_id in rows}


def _date_range(from_date: date, to_date: date) -> DateRange:
    if from_date > to_date:
        raise InvalidAnalyticsDateRange
    if (to_date - from_date).days + 1 > MAX_ANALYTICS_DATE_RANGE_DAYS:
        raise AnalyticsDateRangeTooLarge
    return DateRange(from_date=from_date, to_date=to_date)


def _reporting_timezone(configuration: SiteConfigurationReference) -> ZoneInfo:
    try:
        return ZoneInfo(configuration.reporting_timezone)
    except ZoneInfoNotFoundError as error:
        raise InvalidSiteConfiguration from error


def _event_date_utc_bounds(
    from_date: date,
    to_date: date,
    timezone: ZoneInfo,
) -> tuple[datetime | None, datetime | None]:
    """Return a safe UTC envelope for an inclusive local calendar range.

    Both ``fold`` values are considered so midnight transitions in unusual IANA
    zones can only widen the SQL prefilter.  Python still performs the exact
    local-date check after rows are loaded from this bounded UTC window.
    """

    lower_candidates = _local_midnight_utc_candidates(from_date, timezone)
    lower_bound = min(lower_candidates) if lower_candidates else None
    try:
        end_date = to_date + timedelta(days=1)
    except OverflowError:
        upper_candidates: tuple[datetime, ...] = ()
    else:
        upper_candidates = _local_midnight_utc_candidates(end_date, timezone)
    upper_bound = max(upper_candidates) if upper_candidates else None
    if lower_bound is None and upper_bound is None:
        raise InvalidSiteConfiguration
    return lower_bound, upper_bound


def _local_midnight_utc_candidates(
    local_date: date,
    timezone: ZoneInfo,
) -> tuple[datetime, ...]:
    local_midnight = datetime.combine(local_date, time.min, timezone)
    candidates: set[datetime] = set()
    for fold in (0, 1):
        try:
            utc_value = local_midnight.replace(fold=fold).astimezone(UTC)
        except OverflowError, ValueError:
            continue
        candidates.add(utc_value.replace(tzinfo=None))
    return tuple(candidates)


def _decimal_text(value: object) -> str:
    if value is None:
        return "0"
    if isinstance(value, Decimal):
        return format(value, "f")
    return format(Decimal(str(value)), "f")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    if value.utcoffset() is None:
        raise ValueError("datetime has invalid timezone information")
    return value.astimezone(UTC)


def _publication_reference_from_row(row: RowMapping) -> PublicationReference:
    report_type = str(row["report_type"])
    if report_type not in {"business_report", "return_report"}:
        raise ValueError(f"unsupported published report type: {report_type}")
    published_at = row["published_at"]
    if not isinstance(published_at, datetime):
        raise ValueError("published_at is not a datetime")
    return PublicationReference(
        dataset_id=int(row["dataset_id"]),
        site_id=int(row["site_id"]),
        report_date=cast(date, row["report_date"]),
        report_type=cast(Literal["business_report", "return_report"], report_type),
        version_id=int(row["version_id"]),
        published_at=_as_utc(published_at),
    )


def _site_configuration_from_row(row: RowMapping) -> SiteConfigurationReference:
    config_id = row["config_id"]
    values = (
        row["site_id"],
        row["site_code"],
        config_id,
        row["source_timezone"],
        row["reporting_timezone"],
        row["currency_code"],
    )
    if config_id is None or any(value is None for value in values):
        raise MissingSiteConfiguration
    return SiteConfigurationReference(
        site_id=int(row["site_id"]),
        site_code=str(row["site_code"]),
        site_config_version_id=int(config_id),
        source_timezone=str(row["source_timezone"]),
        reporting_timezone=str(row["reporting_timezone"]),
        currency_code=str(row["currency_code"]),
    )
