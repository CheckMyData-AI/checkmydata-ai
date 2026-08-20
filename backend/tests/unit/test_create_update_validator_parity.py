"""A field guarded on create and free on PATCH — the shape, not the instance.

Three of these landed in two days, each found while fixing something else:

* `ConnectionUpdate.db_type` — a demo connection repointed at the app's own database
* `ConnectionUpdate.db_name` — the same, by the other field
* `UpdateRepoRequest.branch` — `validate_git_ref` on create, nothing on PATCH, and the
  branch reaches `repo.git.checkout()` as argv (F-GIT-08)

A create-side validator reads as *this field is handled*. Nothing in the file points at
the sibling model that copied the field and not the rule, and nothing fails when the copy
is made — which is why the fourth one would have shipped too. This test is the thing that
points.

It compares by AST rather than by pydantic introspection deliberately: the question is
whether the **source** declares the rule in both places, and an inherited validator (the
fix this test drove) satisfies both readings while a forgotten one satisfies neither.
"""

from __future__ import annotations

import ast
import collections
import pathlib
import re

import pytest

ROUTES = pathlib.Path(__file__).resolve().parents[2] / "app" / "api" / "routes"

#: Known asymmetries that are correct. Each needs a reason, not just an entry — an
#: allow-list nobody has to justify is how a ratchet becomes a formality.
ACCEPTED: dict[tuple[str, str, str], str] = {}


def _models(tree: ast.Module) -> dict[str, tuple[set[str], set[str]]]:
    """class name -> (declared fields, fields carrying a validator), inheritance included."""
    classes = {node.name: node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}

    def bases_of(node: ast.ClassDef) -> list[str]:
        return [getattr(b, "id", getattr(b, "attr", "")) for b in node.bases]

    def collect(name: str, seen: set[str]) -> tuple[set[str], set[str]]:
        if name in seen or name not in classes:
            return set(), set()
        seen.add(name)
        node = classes[name]
        fields: set[str] = set()
        validated: set[str] = set()
        for base in bases_of(node):
            bf, bv = collect(base, seen)
            fields |= bf
            validated |= bv
        for item in node.body:
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                fields.add(item.target.id)
            if isinstance(item, ast.FunctionDef):
                for dec in item.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    fn = dec.func
                    label = getattr(fn, "id", None) or getattr(fn, "attr", None)
                    if label in ("field_validator", "validator"):
                        validated |= {a.value for a in dec.args if isinstance(a, ast.Constant)}
        return fields, validated

    out = {}
    for name, node in classes.items():
        if not any(b == "BaseModel" for b in bases_of(node)) and not any(
            b in classes for b in bases_of(node)
        ):
            continue
        out[name] = collect(name, set())
    return out


_AFFIX = re.compile(
    r"^(Create|Add|New|Update|Patch|Edit)|(Create|Add|New|Update|Patch|Edit|Request|Body)$"
)


def _stem(name: str) -> str:
    return _AFFIX.sub("", name).lower()


def test_a_field_in_both_a_create_and_an_update_model_carries_the_same_rule() -> None:
    gaps: list[str] = []

    for path in sorted(ROUTES.rglob("*.py")):
        models = _models(ast.parse(path.read_text(encoding="utf-8")))
        by_stem: dict[str, list[str]] = collections.defaultdict(list)
        for name in models:
            by_stem[_stem(name)].append(name)

        for group in by_stem.values():
            if len(group) < 2:
                continue
            for i, first in enumerate(sorted(group)):
                for second in sorted(group)[i + 1 :]:
                    f_fields, f_valid = models[first]
                    s_fields, s_valid = models[second]
                    for field in sorted(f_fields & s_fields):
                        in_first, in_second = field in f_valid, field in s_valid
                        if in_first == in_second:
                            continue
                        guarded, free = (first, second) if in_first else (second, first)
                        key = (path.name, field, free)
                        if key in ACCEPTED:
                            continue
                        gaps.append(
                            f"{path.name}: '{field}' is validated in {guarded} but not in {free}"
                        )

    assert not gaps, (
        "a field is guarded on one model and free on its sibling — the shape behind "
        "F-GIT-08 and the two connection findings before it. Share the validator "
        "(a mixin both models inherit) rather than copying it, or add the pair to "
        "ACCEPTED with a reason:\n  " + "\n  ".join(gaps)
    )


class TestTheRulesActuallyApplyOnUpdate:
    """The ratchet checks that the source declares the rule in both places. These check
    that the rule *runs* — a shared mixin that pydantic never wires up would satisfy the
    AST and change nothing at runtime."""

    def test_mcp_env_is_bounded_on_update(self):
        """Unbounded before: `update()` encrypts and stores whatever dict arrives
        (`connection_service.py:216-218`), into a Text column, and hands it to a spawned
        MCP subprocess."""
        import pydantic

        from app.api.routes.connections import ConnectionUpdate

        with pytest.raises(pydantic.ValidationError):
            ConnectionUpdate(mcp_env={f"K{i}": "v" for i in range(51)})

        with pytest.raises(pydantic.ValidationError):
            ConnectionUpdate(mcp_env={"K": "v" * 4097})

    def test_a_reasonable_mcp_env_still_passes_on_update(self):
        from app.api.routes.connections import ConnectionUpdate

        assert ConnectionUpdate(mcp_env={"TOKEN": "abc"}).mcp_env == {"TOKEN": "abc"}

    def test_strings_are_stripped_on_update(self):
        """`_sanitize_strings` covers `name` downstream but not `connection_string`, so
        a DSN kept its trailing newline into `encrypt()` and failed to connect later in
        a way that pointed nowhere."""
        from app.api.routes.connections import ConnectionUpdate

        body = ConnectionUpdate(name="  spaced  ", connection_string="postgres://h/db\n")

        assert body.name == "spaced"
        assert body.connection_string == "postgres://h/db"

    def test_pre_commands_are_still_allow_listed_on_update(self):
        """Already present before the mixin — asserted so the refactor cannot drop it."""
        import pydantic

        from app.api.routes.connections import ConnectionUpdate

        with pytest.raises(pydantic.ValidationError):
            ConnectionUpdate(ssh_pre_commands=["rm -rf /"])

    def test_create_kept_every_rule_it_had(self):
        import pydantic

        from app.api.routes.connections import ConnectionCreate

        with pytest.raises(pydantic.ValidationError):
            ConnectionCreate(
                project_id="p",
                name="n",
                db_type="postgres",
                db_host="h",
                db_name="d",
                mcp_env={f"K{i}": "v" for i in range(51)},
            )
        assert (
            ConnectionCreate(
                project_id="p", name="  n  ", db_type="postgres", db_host="h", db_name="d"
            ).name
            == "n"
        )
