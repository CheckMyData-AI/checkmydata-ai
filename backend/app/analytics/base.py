"""The vendor-neutral analytics-source contract (spec §2.3).

An analytics source is not a database: there is no query language to send, no
schema to introspect, and the vendor decides what shapes of data exist. What it
*does* offer is a fixed catalogue of **reports**, each fetched for one **period**.
:class:`AnalyticsSourceAdapter` narrows :class:`~app.connectors.base.DataSourceAdapter`
to exactly that shape, so an analytics vendor plugs into the same connection
plumbing as PostgreSQL without pretending to be one.

Two invariants live here rather than in each vendor adapter:

* ``query()`` **raises** :class:`NotImplementedError`. Nothing may hand an
  analytics source a query string — the agent reads the collected fact tables
  instead (spec §3.3, "no free-form SQL").
* ``list_entities()`` is derived from ``available_reports()``, so the report
  catalogue can never disagree with the entity list.

:class:`AnalyticsReport` carries ``truncated``/``degraded`` next to the rows
because partial data that *looks* complete is the failure mode this whole module
exists to prevent (docs-study Δ1): whoever fetched the rows is the only layer that
knows they were capped, so it is the layer that must say so.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from app.connectors.base import ConnectionConfig, DataSourceAdapter, QueryResult

#: Reporting grains an analytics report can have. Daily is a ``YYYY-MM-DD``
#: period; monthly is ``YYYY-MM``.
Grain = Literal["daily", "monthly"]


@dataclass(frozen=True)
class ReportSpec:
    """One report a source can produce.

    Frozen because the catalogue is a constant: a report's identity must not
    change under a caller that is iterating it.

    Attributes:
        name: Stable identifier, used as the journal's ``report`` value and as
            the fact table's discriminator. Never localised.
        grain: ``"daily"`` or ``"monthly"`` — decides the period format.
        description: One line the agent shows the user when listing what a
            connection can answer from.
    """

    name: str
    grain: Grain
    description: str


@dataclass
class AnalyticsReport:
    """The parsed result of one ``fetch(report, period)``.

    Attributes:
        columns: Column names in row order. This is the upsert contract with the
            fact tables — the collect service maps positionally.
        rows: Row values, already coerced to the fact tables' Python types
            (``date`` for dates, ``int`` for counts, ``Decimal`` for money).
        truncated: ``True`` when a vendor cap was still hit after paging, i.e.
            more data exists than these rows represent. Never inferred later —
            only the fetch knows.
        degraded: Human-readable reason the data is partial, surfaced verbatim in
            the answer's caveat. ``None`` when the report is complete.
    """

    columns: list[str] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    truncated: bool = False
    degraded: str | None = None


class AnalyticsSourceAdapter(DataSourceAdapter):
    """Base class for every analytics vendor adapter (GA4, App Store, Play)."""

    @property
    @abstractmethod
    def source_type(self) -> str:
        """The ``Connection.source_type`` value this adapter serves, e.g. ``"ga4"``."""

    @abstractmethod
    async def connect(self, config: ConnectionConfig) -> None:
        """Prepare the vendor client from ``config`` (credentials + knobs)."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Release the vendor client."""

    @abstractmethod
    async def test_connection(self) -> bool:
        """Probe the vendor cheaply. ``False`` — never an exception — on failure."""

    @abstractmethod
    def available_reports(self) -> list[ReportSpec]:
        """The report catalogue this source can produce. Constant, not I/O."""

    @abstractmethod
    async def fetch(self, report: str, period: str) -> AnalyticsReport:
        """Fetch one report for one period.

        Args:
            report: A ``ReportSpec.name`` from :meth:`available_reports`.
            period: ``YYYY-MM-DD`` for a daily report, ``YYYY-MM`` for monthly.

        Returns:
            The parsed rows, flagged ``truncated`` when the vendor capped them.

        Raises:
            AnalyticsEmpty: the period holds no data (a normal outcome).
            AnalyticsAuthError, AnalyticsPermissionError: configuration errors.
            AnalyticsTransientError, QuotaExhaustedError: retryable failures.
            ValueError: ``report`` is not in the catalogue (a programming error).
        """

    async def list_entities(self) -> list[str]:
        """The report names — the ``DataSourceAdapter`` view of the catalogue."""
        return [report.name for report in self.available_reports()]

    async def query(self, query: str, params: dict[str, Any] | None = None) -> QueryResult:
        """Always raises: analytics sources have no query language.

        The agent answers from the collected fact tables via parameterised reads,
        so no user string is ever assembled into a vendor request (spec §3.3).
        """
        raise NotImplementedError("analytics sources are not queried with a query language")
