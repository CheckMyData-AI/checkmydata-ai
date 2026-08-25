"""Coverage has to follow SQLAlchemy's greenlet, or it measures the wrong thing.

`[tool.coverage.run]` carried no `concurrency` setting, so coverage used its default
(`thread`). SQLAlchemy's async layer switches through a **greenlet** (`greenlet_spawn`),
and coverage does not follow a greenlet switch unless told to — so every statement after
the first `await` against the database, inside the same frame, executed and was reported
as **uncovered**. That is most of the body of most routes.

Measured on `tests/integration`, 673 tests, the identical run twice on 2026-08-25:

    without concurrency → app/api/routes/chat.py  35%  (493 statements missing)
    with  greenlet      → app/api/routes/chat.py  46%  (405 missing)

Eighty-eight statements on one file, running the whole time, counted as untested.

Two consequences worth naming, because both were acted on before the cause was known:

* An audit reported "chat.py 35%" as a finding, and it was partly an artefact of the
  measurement rather than a property of the tests.
* `fail_under` compares against a number that was systematically low, so the gate was
  looser than its value suggests — a gate can only be as honest as its input.

The proof that the code *ran* while coverage said otherwise: a test asserted `429` from
the token-budget gate at `chat.py:247`, planting a defect there turned it red, and
coverage still listed `247-598` as missing. With `greenlet` the same list starts at
`251`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT = Path(__file__).resolve().parents[3] / "pyproject.toml"


def _coverage_run_config() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["coverage"]["run"]


def test_pyproject_is_readable() -> None:
    """A parse failure would make every assertion below vacuous."""
    assert _coverage_run_config()


def test_coverage_follows_the_greenlet() -> None:
    concurrency = _coverage_run_config().get("concurrency", [])
    assert "greenlet" in concurrency, (
        "coverage will stop tracing at the first `await` into SQLAlchemy and report "
        "every line after it as uncovered — 88 statements on chat.py alone. Removing "
        "this does not make anything fail; it makes the coverage number quietly wrong, "
        "and the `fail_under` gate quietly loose."
    )


def test_thread_concurrency_is_kept_alongside_it() -> None:
    """`concurrency` replaces the default rather than adding to it, so naming only
    `greenlet` would lose the thread tracing that was there before — and this codebase
    runs work in threads (`asyncio.to_thread` in the pipeline runner and at boot)."""
    concurrency = _coverage_run_config().get("concurrency", [])
    assert "thread" in concurrency, (
        "setting `concurrency` overrides the default `['thread']`; naming greenlet alone "
        "trades one blind spot for another"
    )


def test_greenlet_is_actually_installed() -> None:
    """The setting is inert without the package, and inert configuration reads as
    working configuration."""
    import importlib.util

    assert importlib.util.find_spec("greenlet") is not None
