"""Data investigation endpoints (T24).

Split out of ``data_validation.py`` — this router owns the
investigation lifecycle: start, poll, confirm-fix. The background
runner and a couple of tiny SQL helpers live here as well because
they're only used by these endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.rate_limit import limiter
from app.models.chat_session import ChatMessage as ChatMessageModel
from app.models.data_validation import DataInvestigation
from app.services.connection_service import ConnectionService
from app.services.membership_service import MembershipService


class StartInvestigationResponse(BaseModel):
    ok: bool = True
    investigation_id: str
    status: str


class InvestigationDetail(BaseModel):
    id: str
    status: str
    phase: str | None = None
    current_step: str | None = None
    original_query: str
    original_result_summary: str | None = None
    user_complaint_type: str
    user_complaint_detail: str | None = None
    user_expected_value: str | None = None
    problematic_column: str | None = None
    corrected_query: str | None = None
    corrected_result_json: str | None = None
    root_cause: str | None = None
    root_cause_category: str | None = None
    investigation_log: list[dict] = []
    created_at: str | None = None
    completed_at: str | None = None


class ConfirmFixResponse(BaseModel):
    ok: bool = True
    status: str
    learnings_created: list[str] = []
    notes_created: list[str] = []

logger = logging.getLogger(__name__)

router = APIRouter()
_membership_svc = MembershipService()
_conn_svc = ConnectionService()


class InvestigateRequest(BaseModel):
    project_id: str = Field(..., max_length=64)
    connection_id: str = Field(..., max_length=64)
    session_id: str = Field(..., max_length=64)
    message_id: str = Field(..., max_length=64)
    complaint_type: str = Field(..., max_length=100)
    complaint_detail: str | None = Field(None, max_length=2000)
    expected_value: str | None = Field(None, max_length=500)
    problematic_column: str | None = Field(None, max_length=200)


@router.post("/investigate", response_model=StartInvestigationResponse)
@limiter.limit("5/minute")
async def start_investigation(
    request: Request,
    body: InvestigateRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    from app.services.investigation_service import InvestigationService

    inv_svc = InvestigationService()

    original_query = ""
    original_result_summary = "{}"

    result = await db.execute(
        select(ChatMessageModel).where(ChatMessageModel.id == body.message_id)
    )
    msg = result.scalar_one_or_none()
    if msg and msg.metadata_json:
        try:
            meta = json.loads(msg.metadata_json)
            original_query = meta.get("query", "")
            raw_result = meta.get("raw_result")
            if raw_result:
                original_result_summary = json.dumps(raw_result)[:2000]
        except (json.JSONDecodeError, TypeError):
            pass

    investigation = await inv_svc.create_investigation(
        db,
        connection_id=body.connection_id,
        session_id=body.session_id,
        trigger_message_id=body.message_id,
        original_query=original_query,
        original_result_summary=original_result_summary,
        user_complaint_type=body.complaint_type,
        user_complaint_detail=body.complaint_detail,
        user_expected_value=body.expected_value,
        problematic_column=body.problematic_column,
    )
    await db.commit()

    def _on_task_done(t: asyncio.Task[None]) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc:
            logger.error(
                "Investigation %s failed: %s",
                investigation.id,
                exc,
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    task = asyncio.create_task(
        _run_investigation_background(
            investigation_id=investigation.id,
            project_id=body.project_id,
            connection_id=body.connection_id,
            original_query=original_query,
            original_result_summary=original_result_summary,
            user_complaint_type=body.complaint_type,
            user_complaint_detail=body.complaint_detail or "",
            user_expected_value=body.expected_value or "",
            problematic_column=body.problematic_column or "",
        )
    )
    task.add_done_callback(_on_task_done)

    return {
        "ok": True,
        "investigation_id": investigation.id,
        "status": investigation.status,
    }


@router.get("/investigate/{investigation_id}", response_model=InvestigationDetail)
async def get_investigation(
    investigation_id: str,
    project_id: str,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, project_id, user["user_id"], "viewer")

    from app.services.investigation_service import InvestigationService

    svc = InvestigationService()
    inv = await svc.get_investigation(db, investigation_id)

    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    conn = await _conn_svc.get(db, inv.connection_id)
    if not conn or conn.project_id != project_id:
        raise HTTPException(status_code=404, detail="Investigation not found")

    return {
        "id": inv.id,
        "status": inv.status,
        "phase": inv.phase,
        "current_step": inv.current_step,
        "original_query": inv.original_query,
        "original_result_summary": inv.original_result_summary,
        "user_complaint_type": inv.user_complaint_type,
        "user_complaint_detail": inv.user_complaint_detail,
        "user_expected_value": inv.user_expected_value,
        "problematic_column": inv.problematic_column,
        "corrected_query": inv.corrected_query,
        "corrected_result_json": inv.corrected_result_json,
        "root_cause": inv.root_cause,
        "root_cause_category": inv.root_cause_category,
        "investigation_log": json.loads(inv.investigation_log_json or "[]"),
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "completed_at": inv.completed_at.isoformat() if inv.completed_at else None,
    }


class ConfirmFixRequest(BaseModel):
    accepted: bool
    project_id: str


@router.post(
    "/investigate/{investigation_id}/confirm-fix",
    response_model=ConfirmFixResponse,
)
async def confirm_investigation_fix(
    investigation_id: str,
    body: ConfirmFixRequest,
    db: AsyncSession = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    await _membership_svc.require_role(db, body.project_id, user["user_id"], "viewer")

    from app.services.agent_learning_service import AgentLearningService
    from app.services.investigation_service import InvestigationService
    from app.services.session_notes_service import SessionNotesService

    inv_svc = InvestigationService()
    learning_svc = AgentLearningService()
    notes_svc = SessionNotesService()

    inv = await inv_svc.get_investigation(db, investigation_id)
    if not inv:
        raise HTTPException(status_code=404, detail="Investigation not found")

    conn = await _conn_svc.get(db, inv.connection_id)
    if not conn or conn.project_id != body.project_id:
        raise HTTPException(status_code=404, detail="Investigation not found")

    if not body.accepted:
        await inv_svc.update_phase(
            db,
            investigation_id,
            "collecting_info",
            "collect_info",
            log_entry="User rejected the proposed fix.",
        )
        await db.commit()
        return {"ok": True, "status": "reopened"}

    learnings_created: list[str] = []
    notes_created: list[str] = []

    if inv.root_cause and inv.root_cause_category:
        try:
            learning = await learning_svc.create_learning(
                db,
                connection_id=inv.connection_id,
                category=_map_root_cause_to_learning_category(inv.root_cause_category),
                subject=_extract_table_from_query(inv.original_query),
                lesson=inv.root_cause,
                confidence=0.9,
                source_query=inv.original_query,
                source_error=f"Investigation: {inv.user_complaint_type}",
            )
            learnings_created.append(learning.id)
        except ValueError:
            logger.warning(
                "Skipped learning from investigation %s (quality check failed)",
                investigation_id,
            )

        note = await notes_svc.create_note(
            db,
            connection_id=inv.connection_id,
            project_id=body.project_id,
            category="data_observation",
            subject=_extract_table_from_query(inv.original_query),
            note=f"Investigation finding: {inv.root_cause}",
            confidence=0.9,
            is_verified=True,
        )
        notes_created.append(note.id)

    if inv.root_cause_category in ("missing_filter", "column_format"):
        await _enrich_sync_from_investigation(db, inv)

    await inv_svc.complete_investigation(
        db,
        investigation_id,
        learnings_created=learnings_created,
        notes_created=notes_created,
    )
    await db.commit()

    return {
        "ok": True,
        "status": "resolved",
        "learnings_created": learnings_created,
        "notes_created": notes_created,
    }


async def _enrich_sync_from_investigation(
    db: AsyncSession,
    inv: DataInvestigation,
) -> None:
    """Push investigation findings into Code-DB sync filters/mappings."""
    from app.services.code_db_sync_service import CodeDbSyncService

    try:
        sync_svc = CodeDbSyncService()
        table = _extract_table_from_query(inv.original_query)
        if table == "unknown_table":
            return

        if inv.root_cause_category == "missing_filter":
            await sync_svc.add_runtime_enrichment(
                db,
                connection_id=inv.connection_id,
                table_name=table,
                field="required_filters_json",
                value=json.dumps({"source": "investigation", "filter": inv.root_cause}),
            )
        elif inv.root_cause_category == "column_format":
            await sync_svc.add_runtime_enrichment(
                db,
                connection_id=inv.connection_id,
                table_name=table,
                field="conversion_warnings",
                value=inv.root_cause or "",
            )
    except Exception:
        logger.debug(
            "Failed to enrich sync from investigation (non-critical)",
            exc_info=True,
        )


async def _run_investigation_background(
    *,
    investigation_id: str,
    project_id: str,
    connection_id: str,
    original_query: str,
    original_result_summary: str,
    user_complaint_type: str,
    user_complaint_detail: str,
    user_expected_value: str,
    problematic_column: str,
) -> None:
    """Launch InvestigationAgent in the background and update status as it runs."""
    from app.agents.base import AgentContext
    from app.agents.investigation_agent import InvestigationAgent
    from app.core.workflow_tracker import tracker as singleton_tracker
    from app.llm.router import LLMRouter
    from app.models.base import async_session_factory
    from app.models.connection import Connection
    from app.services.connection_service import ConnectionService
    from app.services.investigation_service import InvestigationService

    inv_svc = InvestigationService()

    try:
        async with async_session_factory() as session:
            await inv_svc.update_phase(
                session,
                investigation_id,
                "investigating",
                "investigate",
                log_entry="Agent started investigation.",
            )
            await session.commit()

        conn_svc = ConnectionService()
        async with async_session_factory() as session:
            result = await session.execute(
                select(Connection).where(Connection.id == connection_id)
            )
            conn = result.scalar_one_or_none()
            if not conn:
                raise RuntimeError(f"Connection {connection_id} not found")
            cfg = await conn_svc.to_config(session, conn)

        wf_id = await singleton_tracker.begin(
            "investigation",
            context={"project_id": project_id, "investigation_id": investigation_id},
        )

        ctx = AgentContext(
            project_id=project_id,
            connection_config=cfg,
            user_question="",
            chat_history=[],
            llm_router=LLMRouter(),
            tracker=singleton_tracker,
            workflow_id=wf_id,
        )

        agent = InvestigationAgent()
        inv_result = await agent.run(
            ctx,
            investigation_id=investigation_id,
            original_query=original_query,
            original_result_summary=original_result_summary,
            user_complaint_type=user_complaint_type,
            user_complaint_detail=user_complaint_detail,
            user_expected_value=user_expected_value,
            problematic_column=problematic_column,
        )

        if inv_result.status == "success" and inv_result.corrected_query:
            corrected_json = (
                json.dumps(inv_result.corrected_result)
                if inv_result.corrected_result
                else None
            )
            async with async_session_factory() as session:
                await inv_svc.record_finding(
                    session,
                    investigation_id=investigation_id,
                    corrected_query=inv_result.corrected_query,
                    corrected_result_json=corrected_json,
                    root_cause=inv_result.root_cause,
                    root_cause_category=inv_result.root_cause_category,
                )
                await session.commit()
            logger.info("Investigation %s: fix found", investigation_id)
        else:
            async with async_session_factory() as session:
                await inv_svc.fail_investigation(
                    session,
                    investigation_id,
                    reason=inv_result.root_cause or "Agent could not identify a fix.",
                )
                await session.commit()
            logger.info("Investigation %s: no fix found", investigation_id)

    except Exception:
        logger.exception("Investigation %s failed", investigation_id)
        try:
            async with async_session_factory() as session:
                await inv_svc.fail_investigation(
                    session,
                    investigation_id,
                    reason="Internal error during investigation.",
                )
                await session.commit()
        except Exception:
            logger.exception(
                "Failed to mark investigation %s as failed", investigation_id
            )


def _map_root_cause_to_learning_category(root_cause_category: str) -> str:
    mapping = {
        "column_format": "data_format",
        "missing_filter": "schema_gotcha",
        "wrong_join": "schema_gotcha",
        "wrong_table": "table_preference",
        "aggregation_error": "query_pattern",
        "timezone_issue": "data_format",
        "currency_unit": "data_format",
    }
    return mapping.get(root_cause_category, "schema_gotcha")


def _extract_table_from_query(query: str) -> str:
    """Best-effort table name extraction from a SQL query."""
    match = re.search(r"\bFROM\s+[`\"']?(\w+)", query, re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown_table"
