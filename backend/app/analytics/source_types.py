"""The one definition of "this connection is an analytics vendor" (T14).

Membership in :data:`ANALYTICS_SOURCE_TYPES` is what four unrelated subsystems
gate on — the hourly collect wave (:mod:`app.main`), the collect service, the
orchestrator's tool availability (via
:meth:`~app.agents.context_loader.ContextLoader.has_analytics_sources`) and the
tool dispatcher's connection resolution. It used to be spelled out twice, once
per side of that split; adding a vendor to one copy would have left the other
half of the system unable to see connections the first half happily created.

This module exists rather than the constant living in
:mod:`app.services.analytics_collect_service` because that module imports the
GA4 adapter and the Google API client libraries. The tool-definition module and
the orchestrator's per-request capability probe need the *name* of the vendor
family, not the machinery to talk to it, and making them pay that import (and
risk a cycle back through the agent package) is the reason the second copy was
written in the first place. Nothing but the standard library may be imported
here — a test enforces it.

A tuple, not a set: the values reach SQLAlchemy's ``Column.in_()`` in the cron
dispatcher, which documents a sequence, and a fixed order keeps generated
``IN`` lists and log lines reproducible. Three items make membership cost
nothing either way.
"""

from __future__ import annotations

#: ``Connection.source_type`` values served by the analytics agent.
#: ``appstore``/``googleplay`` are reserved for m1/m2; they are listed here
#: because connection *gating* is vendor-agnostic — the agent itself refuses a
#: vendor it has no report catalogue for, with a message that says which.
ANALYTICS_SOURCE_TYPES: tuple[str, ...] = ("ga4", "appstore", "googleplay")
