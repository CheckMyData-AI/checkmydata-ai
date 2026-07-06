import importlib.util
from pathlib import Path

_MIG = (
    Path(__file__).resolve().parents[3]
    / "alembic"
    / "versions"
    / "d5e6f7a8b9c0_add_deploy_state.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("mig_deploy_state", _MIG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_seed_picks_old_when_projects_exist():
    mod = _load()
    assert mod.pick_seed_fingerprint(True) == "all-MiniLM-L6-v2|256"


def test_seed_picks_current_when_no_projects():
    mod = _load()
    assert mod.pick_seed_fingerprint(False) == "BAAI/bge-base-en-v1.5|512"


def test_migration_chains_single_head():
    mod = _load()
    assert mod.down_revision == "c9b8a7f6e5d4"
    assert mod.revision == "d5e6f7a8b9c0"
