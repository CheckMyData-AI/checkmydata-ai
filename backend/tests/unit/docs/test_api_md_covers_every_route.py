"""`API.md` names every route the application serves.

On 2026-08-23 the application served 173 paths across 210 operations; `API.md` named 130,
and **27 were not mentioned at all** — not by path, not by last segment, not in prose.
Whole groups were missing: the five per-connection learnings endpoints, the three run
controls (`GET`/`cancel`/`retry`), the query-failure log, `/api/chat/search`,
`/api/chat/explain-sql`, `/api/projects/access-requests`.

None of that was neglect. A route is added in Python and the document lives somewhere
else, so the only thing tying them together was somebody remembering. Documentation whose
synchrony is proved by an exit code does not drift; documentation maintained by intention
drifts at exactly the rate features are added.

**Why the check is deliberately shallow.** It asserts that the path appears in `API.md`.
It does not read the description, check the method, or verify the prose is true — the
suite does the first two badly and a human does the third. What it stops is a route
existing that the document has never heard of, which is the failure that actually
happened.

`EXEMPT` exists for paths that are genuinely not part of the documented surface, and it
is **empty**: every route the application declares is now in `API.md`. It is not a snooze
button — an entry there is a claim that the route should never be documented — and the
test below requires each one to still be served, so a stale exemption cannot hide a route
that quietly comes back under the same name.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
API_MD = REPO / "API.md"

#: Served, but deliberately outside the documented HTTP surface. **Empty, and worth
#: keeping empty.** The obvious candidates — `/docs`, `/redoc`, `/openapi.json` — never
#: reach this check at all: FastAPI mounts them outside the schema, so they are not in
#: `app.openapi()["paths"]`. Every route the application declares is documented, and an
#: exemption is a claim that one never should be.
EXEMPT: dict[str, str] = {}


def _normalise(path: str) -> str:
    """`/api/x/{project_id}` and `/api/x/{id}` are the same shape.

    `API.md` names parameters for the reader (`{project_id}`, `{connection_id}`,
    `{id}`), FastAPI names them for the handler, and the two disagree constantly. The
    document is for a person; forcing it to match the code's spelling would be the
    wrong direction of accommodation.
    """
    return re.sub(r"\{[^}]+\}", "{}", path.rstrip("/")) or "/"


@pytest.fixture(scope="module")
def served() -> set[str]:
    from app.main import app

    return set(app.openapi()["paths"])


@pytest.fixture(scope="module")
def documented() -> set[str]:
    text = API_MD.read_text(encoding="utf-8")
    return {_normalise(m.group(1)) for m in re.finditer(r"(/(?:api|docs|redoc)[\w\-/{}.]*)", text)}


def test_there_is_a_surface_to_check(served: set[str]) -> None:
    """A comparison against an empty set passes for the wrong reason."""
    assert len(served) > 100, f"only {len(served)} paths — the app did not build"
    assert API_MD.exists()


def test_every_served_path_appears_in_api_md(served: set[str], documented: set[str]) -> None:
    missing = sorted(p for p in served if p not in EXEMPT and _normalise(p) not in documented)
    assert not missing, (
        f"{len(missing)} route(s) the application serves are absent from API.md. A route "
        "the document has never heard of is not an oversight to fix later — it is the "
        "state 27 endpoints were in on 2026-08-23:\n  " + "\n  ".join(missing)
    )


def test_no_exemption_outlives_its_route(served: set[str]) -> None:
    """An exemption for a path that no longer exists is a hole waiting for a route to
    reappear under the same name — and it would be exempt on arrival."""
    stale = sorted(p for p in EXEMPT if p not in served)
    assert not stale, f"exempt but no longer served: {stale}"


def test_the_normaliser_ignores_parameter_names_and_nothing_else() -> None:
    assert _normalise("/api/x/{project_id}") == _normalise("/api/x/{id}")
    assert _normalise("/api/x/") == "/api/x"
    assert _normalise("/api/x/{id}/y") != _normalise("/api/x/{id}")
    assert _normalise("/api/x") != _normalise("/api/y")
