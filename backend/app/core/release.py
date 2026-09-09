"""Which release this process is running.

One function, in its own module, because both `RunCoordinator` (which stamps it on a run)
and `StaleRunReaper` (which compares against it) need it, and importing either from the
other is a cycle.
"""

from __future__ import annotations

import os
import uuid


def current_release() -> str:
    """The release this process is running, or ``""`` when there is no such notion.

    `HEROKU_RELEASE_VERSION` is populated by the `runtime-dyno-metadata` lab, enabled on
    this deployment (verified 2026-09-09). A self-hosted install has nothing here, and the
    empty string is the honest answer — callers treat "cannot tell" as "count it", never
    as "this is a restart".
    """
    return os.environ.get("HEROKU_RELEASE_VERSION", "") or ""


#: Identifies THIS process. Regenerated on every import, which means on every start of
#: every dyno — a deploy and a platform dyno-cycle produce a new one alike, and that is
#: the point: `HEROKU_RELEASE_VERSION` only changes on the first.
BOOT_ID = uuid.uuid4().hex


def owner() -> str:
    """Which process type this is — ``"worker"``, ``"web"``, or ``""`` when unknown.

    Read from Heroku's `DYNO` ("worker.1"). It matters because `index_repo` runs on both:
    the queue path executes on the worker, the manual route on the web dyno. A worker that
    swept the web dyno's runs would kill an index that is running perfectly.
    """
    return (os.environ.get("DYNO", "") or "").split(".")[0]
