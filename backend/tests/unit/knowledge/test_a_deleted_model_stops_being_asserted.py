"""KNOW-06: a model deleted from a file that still exists was asserted forever.

`_incremental_update` copies every cached entity whose name is not in the fresh set,
and removes only entities whose `file_path` is in `deleted_files`. Delete
`class LegacyOrder` from `app/Models/Legacy.php` while the file remains, and the commit
puts that path in `changed_files`, not `deleted_files`: the entity satisfies neither
condition, survives, and is re-copied from the cache on every subsequent run. It then
travels into `project_caches`, into `generate_summary_doc`, into every document's
`enrichment_context`, and into `graph_db_bridge`'s lineage. Only a full rebuild removes
it.

**Why the audit's own fix direction was refused, and what replaces it.** The code
carries a paragraph explaining that "drop entities absent from the fresh set" deletes
live entities, because the fresh set is empty when no schemas were passed to a run — it
cannot tell *the file stopped defining it* from *nothing was scanned*. That reasoning
was right, and it named what was missing: a per-file model re-scan.

So the rule here is positive rather than negative. An entity is dropped only when its
own defining file was re-read **and that file no longer declares its name**. Everything
else is kept, including an entity whose file could not be read: absence of evidence is
not evidence of absence, which is the rule this codebase applies everywhere else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.knowledge.entity_extractor import EntityInfo, ProjectKnowledge, _incremental_update


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "app" / "Models").mkdir(parents=True)
    return tmp_path


def _cached(**entities: str) -> ProjectKnowledge:
    """A cache holding `name -> file_path` entities, as a previous run left it."""
    knowledge = ProjectKnowledge()
    for name, file_path in entities.items():
        knowledge.entities[name] = EntityInfo(
            name=name, file_path=file_path, table_name=f"{name.lower()}s"
        )
    return knowledge


class TestAnEntityWhoseFileNoLongerDeclaresIt:
    def test_is_dropped(self, repo: Path) -> None:
        (repo / "app/Models/Legacy.php").write_text("<?php\nclass CurrentOrder {}\n")
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(LegacyOrder="app/Models/Legacy.php"),
            changed_files=["app/Models/Legacy.php"],
        )
        assert "LegacyOrder" not in result.entities, (
            "the class was deleted from a file that still exists, so the path landed in "
            "`changed_files` rather than `deleted_files` and the entity satisfied "
            "neither removal condition — it was asserted on every run thereafter, with "
            "its inferred table name, columns and relationships (KNOW-06)"
        )

    def test_a_sibling_still_declared_in_that_file_survives(self, repo: Path) -> None:
        """Precision: the file changed, but this class is still in it."""
        (repo / "app/Models/Legacy.php").write_text("<?php\nclass CurrentOrder {}\n")
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(
                LegacyOrder="app/Models/Legacy.php", CurrentOrder="app/Models/Legacy.php"
            ),
            changed_files=["app/Models/Legacy.php"],
        )
        assert "CurrentOrder" in result.entities
        assert "LegacyOrder" not in result.entities


class TestWhatMustNotBeDropped:
    """The measured failure of the audit's own fix direction, kept as tests."""

    def test_an_entity_whose_file_did_not_change(self, repo: Path) -> None:
        """The unchanged file EXISTS and has lost the class — and is still not read.

        The first draft pointed `Untouched` at a path that was not on disk, so it
        passed through the unreadable-file branch and proved nothing about
        `changed_files`. A plant that scanned every file regardless of the changed set
        went green against it.
        """
        (repo / "app/Models/Legacy.php").write_text("<?php\nclass CurrentOrder {}\n")
        (repo / "app/Models/Other.php").write_text("<?php\nclass SomethingElse {}\n")
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(Untouched="app/Models/Other.php"),
            changed_files=["app/Models/Legacy.php"],
        )
        assert "Untouched" in result.entities, (
            "a file that did not change did not change its declarations, so re-reading "
            "it is both wasted work and a chance to delete something on stale evidence"
        )

    def test_an_entity_with_no_defining_file(self, repo: Path) -> None:
        """`file_path` is where a matching model was once found — often nowhere.

        `changed_files` carries `""` so the membership test alone would not save it.
        What this pins is the OUTCOME, not the mechanism: with the empty-path guard
        removed the entity still survives, because `repo_dir / ""` is the directory
        itself and reading it raises. The guard is belt over braces — cheap,
        self-documenting, and one fewer filesystem call — and saying that is better
        than a test that claims to prove a line it cannot distinguish.
        """
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(FromSchemaOnly=""),
            changed_files=["", "a.php"],
        )
        assert "FromSchemaOnly" in result.entities, (
            "an entity that came from the database schema has no defining file to "
            "re-read, so there is no evidence here to act on either way"
        )

    def test_an_entity_whose_file_cannot_be_read(self, repo: Path) -> None:
        """Absence of evidence is not evidence of absence — the rule used everywhere."""
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(Ghost="app/Models/Vanished.php"),
            changed_files=["app/Models/Vanished.php"],
        )
        assert "Ghost" in result.entities, (
            "the file is in `changed_files` but is not on disk — which is a deletion "
            "the caller failed to report, an unreadable file, or a race. `deleted_files` "
            "is how a deletion is stated; guessing one from a failed read would delete "
            "live entities whenever a working tree is mid-checkout"
        )

    def test_the_whole_cache_survives_a_run_that_scanned_nothing(self, repo: Path) -> None:
        """The case that made the audit's fix direction wrong, exercised directly.

        Note what this does NOT pin: the early `if not changed_files: return` is an
        optimisation, not the guard. With an empty changed set the membership test
        already keeps every entity, so removing the early exit leaves behaviour
        identical — as a planted defect confirmed. The assertion is about the
        behaviour, which is the thing worth holding.
        """
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(A="app/Models/A.php", B="app/Models/B.php", C=""),
            changed_files=[],
        )
        assert set(result.entities) == {"A", "B", "C"}, (
            "'absent from the fresh set' cannot distinguish 'the file stopped defining "
            "it' from 'no schemas were passed to this run', and dropping on that basis "
            "empties the cache"
        )


class TestADeletedFileStillRemovesItsEntities:
    """The behaviour that already worked must keep working."""

    def test_deleted_file_entities_removed(self, repo: Path) -> None:
        result = _incremental_update(
            repo,
            schemas=[],
            cached=_cached(Gone="app/Models/Gone.php"),
            changed_files=[],
            deleted_files=["app/Models/Gone.php"],
        )
        assert "Gone" not in result.entities
