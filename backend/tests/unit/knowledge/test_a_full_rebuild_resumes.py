"""PRJ-06 (T12a): a full rebuild interrupted part-way continues, against its own tree.

Before 2026-09-26 every full rebuild started over: the route created a fresh checkpoint
whenever `force_full` was set, and `CheckpointService.create` deletes the old one. So a
dyno restart at 63% of a 12 000 s rebuild paid for the whole rebuild again; observed on
2026-09-09 as three consecutive rebuilds orphaned at 63%, 33% and 33%.

A resume is only sound against the tree its checkpoint describes (S-11): `clone_or_pull`
moves the clone to the branch's current head, while the restored changed-file list,
profile and cross-file analysis describe the checkpoint's head.
"""

from __future__ import annotations

import pytest
from git import Repo
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.api.routes.repos import resume_checkpoint
from app.knowledge.pipeline_runner import pin_to_tree
from app.models.base import Base
from app.models.indexing_checkpoint import IndexingCheckpointDoc, IndexingCheckpointStep
from app.models.project import Project
from app.services.checkpoint_service import CheckpointService


@pytest.mark.parametrize(
    ("checkpoint", "run", "resumes"),
    [
        (True, True, True),  # the fix: a full rebuild continues a full rebuild
        (False, False, True),  # unchanged: incremental continues incremental
        (True, False, False),  # KNOW-08: a full checkpoint is not an incremental diff
        (False, True, False),  # a full run must not inherit an incremental diff
        (None, True, False),  # written before the column existed: unknown
        (None, False, False),
    ],
)
def test_only_like_continues_like(checkpoint, run, resumes):
    assert resume_checkpoint(checkpoint, run) is resumes


def _repo_with_two_commits(tmp_path):
    repo = Repo.init(tmp_path)
    with repo.config_writer() as cw:
        cw.set_value("user", "name", "t").set_value("user", "email", "t@t")
    (tmp_path / "a.py").write_text("x = 1\n")
    repo.index.add(["a.py"])
    first = repo.index.commit("first").hexsha
    (tmp_path / "b.py").write_text("y = 2\n")
    repo.index.add(["b.py"])
    second = repo.index.commit("second").hexsha
    return repo, first, second


def test_a_resume_is_pinned_to_the_checkpoint_tree(tmp_path):
    repo, first, second = _repo_with_two_commits(tmp_path)
    assert repo.head.commit.hexsha == second
    assert pin_to_tree(tmp_path, first) is True
    assert repo.head.commit.hexsha == first
    assert not (tmp_path / "b.py").exists(), "the working tree must be the checkpoint's"


def test_pinning_to_the_current_head_changes_nothing(tmp_path):
    repo, _first, second = _repo_with_two_commits(tmp_path)
    assert pin_to_tree(tmp_path, second) is True
    assert not repo.head.is_detached


def test_a_commit_that_is_gone_refuses_the_pin(tmp_path):
    repo, _first, second = _repo_with_two_commits(tmp_path)
    assert pin_to_tree(tmp_path, "0" * 40) is False
    assert repo.head.commit.hexsha == second, "a failed pin must leave the clone as it was"


@pytest.mark.asyncio
async def test_reset_progress_forgets_the_work_and_keeps_the_checkpoint():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    svc = CheckpointService()
    async with sm() as s:
        s.add(Project(id="p1", name="x", repo_url="https://x/y.git"))
        await s.commit()
        cp = await svc.create(s, "p1", "wf", head_sha="", force_full=True)
        await svc.complete_step(s, cp.id, "detect_changes", head_sha="a" * 40)
        await svc.mark_docs_batch_processed(s, cp.id, ["a.py", "b.py"])

        await svc.reset_progress(s, cp.id)

        assert await svc.get_completed_steps(s, cp.id) == set()
        assert await svc.get_processed_doc_paths(s, cp.id) == set()
        steps = (await s.execute(select(IndexingCheckpointStep))).scalars().all()
        docs = (await s.execute(select(IndexingCheckpointDoc))).scalars().all()
        assert steps == [] and docs == []
        await s.refresh(cp)
        assert cp.head_sha == "" and cp.force_full is True
    await engine.dispose()
