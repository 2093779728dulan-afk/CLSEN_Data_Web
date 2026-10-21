"""Stable failures raised by published analytics queries."""


class PublishedAnalyticsError(RuntimeError):
    """Base class for failures safe to map at the HTTP boundary."""


class InvalidAnalyticsDateRange(PublishedAnalyticsError):
    """The requested start date is after the end date."""


class AnalyticsDateRangeTooLarge(PublishedAnalyticsError):
    """The requested range exceeds the bounded analytics query window."""


class InvalidReturnBasis(PublishedAnalyticsError):
    """The return query requested an unsupported date basis."""


class MissingSiteConfiguration(PublishedAnalyticsError):
    """A published dataset has no current versioned site configuration."""


class InvalidSiteConfiguration(PublishedAnalyticsError):
    """A current site configuration contains an invalid IANA timezone."""
