"""Tests for ORCH-PR01: de-dup reconciliation guidance + stale self-description fix.

Covers:
- test_reconciliation_guidance_not_in_principles: the reconciliation sentence
  ("do NOT claim an earlier query was wrong") must NOT appear in the built
  system prompt (it lives only in the synthesis-moment messages in orchestrator.py
  and response_builder.py, NOT in the always-on PRINCIPLES block).
- test_self_description_not_router: module docstring must no longer say
  "focuses on *routing*"; the built prompt keeps "coordinate specialized sub-agents".
- test_language_caveat_present: regression guard — the LANGUAGE mirroring
  instruction must still be present in PRINCIPLES after the cleanup.
"""

from __future__ import annotations

import app.agents.prompts.orchestrator_prompt as _module
from app.agents.prompts.orchestrator_prompt import build_orchestrator_system_prompt


class TestOrchestratorPromptDedup:
    """ORCH-PR01 — reconciliation sentence removed from always-on PRINCIPLES."""

    def test_reconciliation_guidance_not_in_principles(self):
        """The per-synthesis reconciliation sentence must NOT appear in the
        system prompt (it is paid on every token budget — the single canonical
        statement lives at the synthesis moment only)."""
        prompt = build_orchestrator_system_prompt(has_connection=True, db_type="postgres")
        assert "do NOT claim an earlier query was wrong" not in prompt

    def test_reconciliation_guidance_absent_without_connection_too(self):
        """Same constraint regardless of connection state."""
        prompt = build_orchestrator_system_prompt(has_connection=False)
        assert "do NOT claim an earlier query was wrong" not in prompt


class TestOrchestratorSelfDescription:
    """ORCH-PR01 — stale 'routing' self-description fixed."""

    def test_self_description_not_router_docstring(self):
        """Module docstring must no longer describe the orchestrator as a
        pure router / 'focuses on *routing*'."""
        assert "focuses on *routing*" not in (_module.__doc__ or "")

    def test_built_prompt_retains_coordinate_sub_agents(self):
        """The built prompt must still say the orchestrator coordinates
        sub-agents (the correct description after the unified-loop refactor)."""
        prompt = build_orchestrator_system_prompt(has_connection=True, db_type="postgres")
        assert "coordinate specialized sub-agents" in prompt


class TestOrchestratorLanguageCaveatRegression:
    """PR04 regression guard: LANGUAGE mirroring instruction must survive the cleanup."""

    def test_language_caveat_present(self):
        prompt = build_orchestrator_system_prompt(has_connection=True, db_type="postgres")
        assert "LANGUAGE:" in prompt
        assert "internally in English" in prompt
        assert "SAME language" in prompt
