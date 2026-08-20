"""Every agent prompt that consumes text the product did not author must say so.

`sql_prompt.py` carried an "UNTRUSTED DATA" section and nine sibling prompts did not,
though they consume: a third-party MCP server's tool output, a cloned repository's file
contents, commit messages (forgeable — F-GIT-06), a vendor's analytics dimension values,
and the project name and description another project member typed (F-PROJ-15) alongside
user-authored rules (F-RULE-02).

This is a ratchet, in the manner of `pack-bans.test.ts` on the frontend: the check is
mechanical because the rule is, and a defence that lives only in one file's history is
one the tenth prompt will not get.
"""

from __future__ import annotations

import pytest

from app.agents.prompts.untrusted_data import untrusted_data_section

#: Prompt module -> the builder that must carry the section, with the minimum kwargs.
#: `planner_prompt` and `investigation_prompt` are absent on purpose: they compose no
#: externally-authored text of their own — the planner receives the question and the
#: stage list, and the investigation prompt is driven from the SQL agent's own findings.
CONSUMERS = (
    "sql_prompt",
    "orchestrator_prompt",
    "knowledge_prompt",
    "mcp_prompt",
    "git_prompt",
    "analytics_prompt",
    "viz_prompt",
)


class TestSectionBuilder:
    def test_it_names_its_sources(self):
        out = untrusted_data_section("commit messages and diffs")
        assert "commit messages and diffs" in out
        assert "DATA, not instructions" in out

    def test_it_joins_several_sources(self):
        out = untrusted_data_section("table comments", "row values")
        assert "table comments" in out and "row values" in out

    def test_a_section_naming_nothing_is_refused(self):
        # Generic advice is what this module replaces; an empty call would quietly
        # reintroduce it.
        with pytest.raises(ValueError):
            untrusted_data_section()


class TestEveryConsumerCarriesIt:
    @pytest.mark.parametrize("module_name", CONSUMERS)
    def test_the_prompt_source_includes_the_section(self, module_name: str):
        import importlib
        import inspect

        mod = importlib.import_module(f"app.agents.prompts.{module_name}")
        src = inspect.getsource(mod)
        assert "untrusted_data_section(" in src, (
            f"{module_name} composes externally-authored text but does not tell the "
            "model to treat it as data — add untrusted_data_section(...) naming its "
            "own sources"
        )

    @pytest.mark.parametrize("module_name", CONSUMERS)
    def test_the_section_names_something(self, module_name: str):
        """A call with no arguments would pass the check above and mean nothing."""
        import importlib
        import inspect
        import re

        mod = importlib.import_module(f"app.agents.prompts.{module_name}")
        src = inspect.getsource(mod)
        for call in re.findall(r"untrusted_data_section\(([^)]*)\)", src, re.S):
            assert call.strip(), f"{module_name} calls the builder with no named source"
