"""A plan that sells "1 GB index" has to be able to say when a project passed it.

`plans.max_index_bytes` has been sold since 2026-08-31 (`base` $199 / 1 GB, `scale` 2 GB,
`team` 5 GB, `enterprise` unlimited) and `estimate_index_bytes` has existed beside it —
called from a test and from nothing else. So the tier copy made a promise, the column
held the number, and no code compared the two.

**D5, decided 2026-09-08: option (a) — warn, do not block.** Exceeding the quota puts a
line on the rail and logs; nothing is refused. That is the same shape as the rest of the
billing seam: degradation open and named rather than a silent stop. It also means this
needs no permission from anybody — a warning does not ask whether it may proceed — which
is why the four-method `Entitlements` protocol is **not** widened here. Its own guard
(`test_entitlements_seam.py::test_it_has_four_methods_and_no_more`) demands a written
argument for a fifth, and "so a warning can read a number" is not one.

The figure is fetched by a module helper shaped exactly like `may_run_scheduled_work`:
ask through the registry, never a provider directly, and degrade **open** — a provider
that cannot answer yields `0`, which means unlimited everywhere else in this table and
therefore no warning. A billing lookup that raises must not put a false "you are over
quota" on somebody's rail.

Anchor for the numbers: `esim-php`, the one real project, measured ~460 MB against
`base`'s 1 GB — so the meter places a real project comfortably inside a real tier rather
than being tuned to fire.
"""

from __future__ import annotations

from app.services.plan_catalogue import GB, estimate_index_bytes


class TestTheMeter:
    def test_it_counts_every_store_the_index_spans(self) -> None:
        """Built from row counts rather than a storage query, because the index spans
        Postgres, a vector store that may be pgvector or Chroma, and gzip snapshots on an
        ephemeral disk — no single engine can be asked how big it is."""
        n = estimate_index_bytes(docs_bytes=1_000, symbols=10, edges=20, embeddings=5)
        assert n > 1_000, "the code graph and the embeddings contribute nothing"

    def test_an_empty_project_measures_nothing(self) -> None:
        assert estimate_index_bytes(docs_bytes=0, symbols=0, edges=0, embeddings=0) == 0


class TestTheWarningRule:
    def test_unlimited_never_warns(self) -> None:
        """`0` means unlimited in every other column of `plans`, and it has to mean the
        same here or `enterprise` would be permanently over quota."""
        from app.services.attention_service import index_quota_exceeded

        assert not index_quota_exceeded(used_bytes=99 * GB, quota_bytes=0)

    def test_under_the_quota_is_silent(self) -> None:
        from app.services.attention_service import index_quota_exceeded

        assert not index_quota_exceeded(used_bytes=460 * 1024**2, quota_bytes=1 * GB), (
            "esim-php measures ~460 MB against base's 1 GB and must not warn; a meter "
            "that fires on the only real project is a meter nobody keeps"
        )

    def test_over_the_quota_warns(self) -> None:
        from app.services.attention_service import index_quota_exceeded

        assert index_quota_exceeded(used_bytes=2 * GB, quota_bytes=1 * GB)

    def test_exactly_at_the_quota_is_not_over_it(self) -> None:
        from app.services.attention_service import index_quota_exceeded

        assert not index_quota_exceeded(used_bytes=GB, quota_bytes=GB)

    def test_an_unknown_usage_does_not_warn(self) -> None:
        """Degrade open. A measurement that could not be taken is not evidence of a
        breach, and a rail line saying "over quota" that nobody can verify is worse than
        no line."""
        from app.services.attention_service import index_quota_exceeded

        assert not index_quota_exceeded(used_bytes=None, quota_bytes=GB)


class TestTheProtocolIsNotWidened:
    def test_the_surface_is_still_four_methods(self) -> None:
        """The fifth would need the argument its guard asks for in writing, and a warning
        does not need permission — so the figure is read through a module helper instead,
        the same way `may_run_scheduled_work` handles a provider that cannot answer."""
        from app.entitlements import Entitlements

        assert {m for m in dir(Entitlements) if not m.startswith("_")} == {
            "enforce_project_quota",
            "enforce_connection_quota",
            "effective_token_limits",
            "may_run_scheduled_work",
        }

    async def test_a_provider_that_cannot_answer_yields_unlimited(self) -> None:
        """`UnlimitedEntitlements` has no `get_entitlements`, which is exactly the shape
        of a private package built before this question existed."""
        from app.entitlements import index_quota_bytes, reset_entitlements

        reset_entitlements()
        assert await index_quota_bytes(None, "u1") == 0

    async def test_a_provider_that_raises_yields_unlimited_and_says_so(self, caplog) -> None:
        """Not a false alarm and not silence: logged, and no warning raised on the rail."""
        import logging

        from app.entitlements import index_quota_bytes, reset_entitlements, set_entitlements

        class Exploding:
            async def enforce_project_quota(self, db, user_id): ...
            async def enforce_connection_quota(self, db, user_id): ...
            async def effective_token_limits(self, db, user_id):
                return (0, 0)

            async def may_run_scheduled_work(self, db, user_id):
                return True

            async def get_entitlements(self, db, user_id):
                raise RuntimeError("billing is down")

        set_entitlements(Exploding())
        try:
            with caplog.at_level(logging.WARNING):
                assert await index_quota_bytes(None, "u1") == 0
            assert any("index_quota" in r.message for r in caplog.records)
        finally:
            reset_entitlements()

    async def test_a_provider_that_answers_is_believed(self) -> None:
        from app.entitlements import index_quota_bytes, reset_entitlements, set_entitlements

        class Priced:
            async def enforce_project_quota(self, db, user_id): ...
            async def enforce_connection_quota(self, db, user_id): ...
            async def effective_token_limits(self, db, user_id):
                return (0, 0)

            async def may_run_scheduled_work(self, db, user_id):
                return True

            async def get_entitlements(self, db, user_id):
                class E:
                    max_index_bytes = 2 * GB

                return E()

        set_entitlements(Priced())
        try:
            assert await index_quota_bytes(None, "u1") == 2 * GB
        finally:
            reset_entitlements()


class TestTheRailCarriesIt:
    def test_it_is_a_named_source_so_a_failure_is_reported(self) -> None:
        """`AttentionService.for_project` names each source it could not read, because
        "could not check" and "nothing needs you" must not look alike. A source added
        outside that loop would lose the distinction."""
        import inspect

        from app.services.attention_service import AttentionService

        src = inspect.getsource(AttentionService.for_project)
        assert '"index_size"' in src, "the quota source is not in the named-source loop"
