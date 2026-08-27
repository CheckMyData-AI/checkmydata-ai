"""The code↔DB map is what a repo index produces, not an ingestion automation.

`auto_sync_after_index` sat in the ingestion-automation group in `config.py`, under this
project's house rule: *nothing calls out on a schedule unasked*. It was therefore `False`
by default and was unset in production on 2026-08-25 along with eight other flags of that
family.

The consequence surfaced on 2026-08-27: a full re-index rebuilt the code graph — 25 491
symbols, 2 134 edges — and the code↔DB map **did not move**. Its rows still carried
`updated_at` from the previous night. For a product whose value is that map's freshness,
"the index ran and the map did not" is the wrong default, and grouping decided it.

**The grouping was wrong on the facts.** Measured against
`app/knowledge/code_db_sync_pipeline.py`: zero references to `adapter`, `connector`,
`execute_query`, `introspect`, `httpx`, `requests.` or `aiohttp`. The sync opens no
connection to anything. It reads the stored `DbIndex` and the code knowledge — both
already in this project's own database — and derives a map. It calls out to nowhere, so
the rule that exists to stop unasked outward calls has no claim on it.

**A switch still earns its place, for a different reason.** The sync runs an LLM
(`CodeDbSyncAnalyzer` — `analyze_table`, `analyze_table_batch`, `generate_summary`), so it
costs tokens per run. That is a real reason an operator might want it off, and it is not
the reason it was off. The flag stays; what changes is its default, its group, and the
sentence next to it.
"""

from __future__ import annotations

from pathlib import Path

from app.config import Settings

PIPELINE = Path(__file__).resolve().parents[3] / "app" / "knowledge" / "code_db_sync_pipeline.py"
REPOS_ROUTE = Path(__file__).resolve().parents[3] / "app" / "api" / "routes" / "repos.py"


class TestTheSyncCallsOutToNothing:
    """The measurement that moves it out of the ingestion-automation family. If this ever
    fails, the sync has grown an outward call and the classification must be revisited —
    which is the point of asserting it rather than asserting the flag alone."""

    def test_it_opens_no_connection(self) -> None:
        source = PIPELINE.read_text(encoding="utf-8")
        outward = {
            token: source.count(token)
            for token in ("adapter", "connector", "execute_query", "introspect", "httpx", "aiohttp")
        }
        assert all(n == 0 for n in outward.values()), outward

    def test_it_reads_what_is_already_stored(self) -> None:
        """`load_db_index` and `load_code_knowledge` are the inputs — both local."""
        source = PIPELINE.read_text(encoding="utf-8")
        assert "load_db_index" in source
        assert "load_code_knowledge" in source


class TestTheChainRunsByDefault:
    def test_the_flag_defaults_on(self) -> None:
        """A map that lags the index it belongs to is the failure this default prevents."""
        assert Settings.model_fields["auto_sync_after_index"].default is True

    def test_the_flag_still_exists(self) -> None:
        """Removing it would be the other mistake: the sync costs LLM tokens per run, and
        an operator who wants that off has a real reason the previous grouping never
        named."""
        assert "auto_sync_after_index" in Settings.model_fields

    def test_the_default_is_documented_by_its_real_cost(self) -> None:
        """The comment beside a flag is what the next person reads instead of measuring.
        It said "closes the index→sync gap"; it did not say why the flag was off, and the
        reason recorded elsewhere — ingestion automation — was wrong."""
        source = (Path(__file__).resolve().parents[3] / "app" / "config.py").read_text("utf-8")
        idx = source.index("auto_sync_after_index")
        window = source[max(0, idx - 1400) : idx]
        lowered = window.lower()
        assert "llm" in lowered or "token" in lowered, (
            "the flag's real cost — LLM tokens per sync — is not stated next to it"
        )
        assert "calls out" in lowered or "outward" in lowered or "local" in lowered, (
            "nothing next to the flag records that the sync reaches nothing outward, "
            "which is why it is not ingestion automation"
        )


class TestTheGateStillGates:
    def test_the_chain_reads_the_flag(self) -> None:
        """Default-on is not the same as ungated. An operator setting it false must still
        get an index with no sync."""
        source = REPOS_ROUTE.read_text(encoding="utf-8")
        chain = source[source.index("async def _maybe_autostart_sync_chain") :][:1600]
        assert "auto_sync_after_index" in chain

    def test_a_disabled_chain_says_so_rather_than_failing_quietly(self) -> None:
        source = REPOS_ROUTE.read_text(encoding="utf-8")
        chain = source[source.index("async def _maybe_autostart_sync_chain") :][:1600]
        assert "flag_off" in chain, "a skipped chain must be visible in the log"


def test_the_ingestion_automation_family_no_longer_claims_it() -> None:
    """`CLAUDE.md` lists the family by name. Leaving this flag in that list would keep
    the wrong reason on the record even after the default changed — and the record is what
    the next audit reads."""
    claude_md = Path(__file__).resolve().parents[4] / "CLAUDE.md"
    text = claude_md.read_text(encoding="utf-8")
    marker = "**Ingestion automation"
    assert marker in text, "the family heading moved; this check needs re-pointing"
    # Membership is the LIST, not the prose around it. A first attempt read a
    # character window and tripped on the paragraph that explains the flag *left* the
    # family — which is exactly the text that should be there.
    after = text[text.index(marker) :]
    listing = next(line for line in after.splitlines()[1:] if line.strip().startswith("`"))
    assert "auto_sync_after_index" not in listing, (
        "the flag is still listed as ingestion automation, which is the classification "
        f"that made an index leave its own map stale: {listing}"
    )
    # And the departure has to be recorded, or the next reader re-adds it.
    assert "auto_sync_after_index" in after[: len(marker) + 1200], (
        "nothing near the family says the flag left it, or why"
    )
