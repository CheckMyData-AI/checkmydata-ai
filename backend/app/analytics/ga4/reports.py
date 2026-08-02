"""The five GA4 reports, pinned to the five ``ga4_*` fact tables (spec §1.4).

Each :class:`GA4ReportSpec` is the single place where three things are stated
together, so they cannot drift apart:

1. the **GA4 API names** to request (``sessions``, ``activeUsers``, …),
2. the **fact-table column** each one lands in (``sessions``, ``active_users``, …),
3. the **Python type** the value must be coerced to before it is written.

That last point is not cosmetic. GA4 returns every metric as a *string*; writing
``"1234.56"`` into a ``Numeric(18, 4)`` column or a count as a float is how revenue
quietly stops adding up. The kind is declared per field, next to the name, rather
than inferred from the response header — a vendor that changes a header type must
not silently change our storage type.

``columns`` starts with ``property_id`` and then the dimensions in request order
followed by the metrics, which is exactly the natural-key-then-payload order of
the fact tables. The collect service maps positionally against it.

**Δ2 (``keep_empty_rows``)**: every report here is a time series keyed on ``date``,
so all five request it. Without it GA4 omits rows whose metrics are all zero, and a
dead day arrives as a *gap* — which a chart then interpolates straight over,
turning "nobody visited" into "we don't know". Requesting empty rows costs nothing
(GA4 only re-includes combinations that already exist in the data) and buys an
honest zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.analytics.base import Grain, ReportSpec

#: How a raw GA4 string value is turned into the fact tables' Python type.
FieldKind = Literal["str", "date", "int", "decimal"]


@dataclass(frozen=True)
class GA4Field:
    """One dimension or metric: vendor name, storage column, storage type."""

    api_name: str
    column: str
    kind: FieldKind


@dataclass(frozen=True)
class GA4ReportSpec:
    """A GA4 report definition and its mapping onto a ``ga4_*`` fact table."""

    name: str
    grain: Grain
    description: str
    dimensions: tuple[GA4Field, ...]
    metrics: tuple[GA4Field, ...]
    #: Δ2 — ask GA4 to keep all-zero rows so a dead day is a zero, not a gap.
    keep_empty_rows: bool = True
    #: When set, the ``event_names`` knob restricts this dimension via an IN filter.
    filter_dimension: str | None = None

    @property
    def fields(self) -> tuple[GA4Field, ...]:
        """Dimensions then metrics — the order values arrive and are stored in."""
        return self.dimensions + self.metrics

    @property
    def columns(self) -> list[str]:
        """Fact-table payload columns, ``property_id`` first. T7's upsert contract."""
        return ["property_id", *(field.column for field in self.fields)]

    @property
    def dimension_names(self) -> list[str]:
        return [field.api_name for field in self.dimensions]

    @property
    def metric_names(self) -> list[str]:
        return [field.api_name for field in self.metrics]

    def to_spec(self) -> ReportSpec:
        """The vendor-neutral view returned by ``available_reports()``."""
        return ReportSpec(name=self.name, grain=self.grain, description=self.description)


_DATE = GA4Field("date", "date", "date")
_SESSIONS = GA4Field("sessions", "sessions", "int")
_ACTIVE_USERS = GA4Field("activeUsers", "active_users", "int")


OVERVIEW = GA4ReportSpec(
    name="overview",
    grain="daily",
    description=(
        "Property-wide daily totals: sessions, active and new users, page/screen "
        "views, total events and total revenue."
    ),
    dimensions=(_DATE,),
    metrics=(
        _SESSIONS,
        _ACTIVE_USERS,
        GA4Field("newUsers", "new_users", "int"),
        GA4Field("screenPageViews", "screen_page_views", "int"),
        GA4Field("eventCount", "event_count", "int"),
        GA4Field("totalRevenue", "total_revenue", "decimal"),
    ),
)

GEO = GA4ReportSpec(
    name="geo",
    grain="daily",
    description="Daily sessions and active users broken down by country.",
    dimensions=(_DATE, GA4Field("country", "country", "str")),
    metrics=(_SESSIONS, _ACTIVE_USERS),
)

PLATFORM = GA4ReportSpec(
    name="platform",
    grain="daily",
    description=(
        "Daily sessions and active users by platform (web/iOS/Android) and device "
        "category (desktop/mobile/tablet)."
    ),
    dimensions=(
        _DATE,
        GA4Field("platform", "platform", "str"),
        GA4Field("deviceCategory", "device_category", "str"),
    ),
    metrics=(_SESSIONS, _ACTIVE_USERS),
)

TREND = GA4ReportSpec(
    name="trend",
    grain="daily",
    description=(
        "Daily acquisition trend by default channel group (Organic Search, Paid "
        "Social, Direct, …), with key events."
    ),
    # ``sessionDefaultChannelGroup`` is the current core-API name; the UA-era
    # ``defaultChannelGrouping`` is deprecated.
    dimensions=(_DATE, GA4Field("sessionDefaultChannelGroup", "channel_group", "str")),
    metrics=(_SESSIONS, _ACTIVE_USERS, GA4Field("keyEvents", "key_events", "int")),
)

EVENTS = GA4ReportSpec(
    name="events",
    grain="daily",
    description=(
        "Daily counts and active users for individual events, restricted to the "
        "event names configured on the connection."
    ),
    dimensions=(_DATE, GA4Field("eventName", "event_name", "str")),
    metrics=(GA4Field("eventCount", "event_count", "int"), _ACTIVE_USERS),
    filter_dimension="eventName",
)


#: Catalogue order — the order ``available_reports()``/``list_entities()`` return,
#: and the order the collect service walks. Overview first so a run that dies
#: partway has at least collected the headline numbers.
GA4_REPORTS: tuple[GA4ReportSpec, ...] = (OVERVIEW, GEO, PLATFORM, TREND, EVENTS)

#: Report names in catalogue order.
REPORT_NAMES: tuple[str, ...] = tuple(report.name for report in GA4_REPORTS)

#: Name -> spec lookup for ``fetch(report, period)``.
REPORTS_BY_NAME: dict[str, GA4ReportSpec] = {report.name: report for report in GA4_REPORTS}
