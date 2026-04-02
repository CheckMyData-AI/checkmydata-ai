#!/usr/bin/env python3
"""Audit and clean up Agent Learnings in the production database.

Usage:
    # Dry-run (default): show problems without changing anything
    python scripts/audit_learnings.py

    # Apply fixes: deactivate bad learnings
    python scripts/audit_learnings.py --apply

    # Delete (instead of deactivate) bad learnings
    python scripts/audit_learnings.py --apply --delete

Requires DATABASE_URL environment variable (e.g. from Heroku config).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.services.agent_learning_service import SUBJECT_BLOCKLIST  # noqa: E402

MIN_LESSON_LENGTH = 15


def _non_ascii_ratio(text: str) -> float:
    if not text:
        return 0.0
    non_ascii = sum(1 for c in text if ord(c) > 127)
    return non_ascii / len(text)


def diagnose(subject: str, lesson: str) -> list[str]:
    """Return a list of quality issues found."""
    issues: list[str] = []
    if subject.lower() in SUBJECT_BLOCKLIST:
        issues.append(f"blocklisted subject '{subject}'")
    if len(lesson.strip()) < MIN_LESSON_LENGTH:
        issues.append(f"lesson too short ({len(lesson.strip())} chars)")
    ratio = _non_ascii_ratio(lesson)
    if ratio > 0.5:
        issues.append(f"mostly non-ASCII ({ratio:.0%})")
    elif ratio > 0.3:
        issues.append(f"high non-ASCII ({ratio:.0%})")
    return issues


def _prepare_url(raw: str) -> str:
    """Convert a raw DATABASE_URL into an asyncpg-compatible connection string."""
    url = raw
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "sslmode" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


async def main(apply: bool = False, delete_bad: bool = False) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is required.")
        print("  export DATABASE_URL=$(heroku config:get DATABASE_URL -a checkmydata-ai)")
        sys.exit(1)

    database_url = _prepare_url(database_url)

    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

    engine = create_async_engine(database_url, echo=False)

    try:
        async with AsyncSession(engine) as session:
            result = await session.execute(
                text(
                    "SELECT id, connection_id, category, subject, lesson, confidence, "
                    "times_confirmed, times_applied, is_active, created_at, updated_at "
                    "FROM agent_learnings ORDER BY connection_id, category, confidence DESC"
                )
            )
            rows = result.fetchall()
    except Exception as exc:
        print(f"ERROR: Could not connect to database: {exc}")
        await engine.dispose()
        sys.exit(1)

    print(f"\n{'='*80}")
    print(f"AGENT LEARNINGS AUDIT — {len(rows)} total rows")
    print(f"{'='*80}\n")

    active = [r for r in rows if r.is_active]
    inactive = [r for r in rows if not r.is_active]
    print(f"Active: {len(active)}  |  Inactive: {len(inactive)}")

    cat_counts = Counter(r.category for r in active)
    print(f"\nActive by category:")
    for cat, cnt in cat_counts.most_common():
        print(f"  {cat:25s} {cnt:4d}")

    subj_counts = Counter(r.subject for r in active)
    print(f"\nTop 20 subjects (active):")
    for subj, cnt in subj_counts.most_common(20):
        flag = " *** BLOCKLISTED" if subj.lower() in SUBJECT_BLOCKLIST else ""
        print(f"  {subj:40s} {cnt:4d}{flag}")

    bad_rows: list[tuple] = []
    for r in active:
        issues = diagnose(r.subject, r.lesson)
        if issues:
            bad_rows.append((r, issues))

    print(f"\n{'='*80}")
    print(f"QUALITY ISSUES FOUND: {len(bad_rows)} learnings with problems")
    print(f"{'='*80}\n")

    if bad_rows:
        for r, issues in bad_rows[:50]:
            print(f"  [{r.id[:8]}] cat={r.category} subj={r.subject}")
            print(f"    lesson: {r.lesson[:120]}")
            print(f"    issues: {', '.join(issues)}")
            print(f"    confidence={r.confidence} confirmed={r.times_confirmed} applied={r.times_applied}")
            print()

        if len(bad_rows) > 50:
            print(f"  ... and {len(bad_rows) - 50} more\n")

    if not apply:
        print("DRY RUN — no changes made. Pass --apply to fix.")
        await engine.dispose()
        return

    if not bad_rows:
        print("No bad learnings to fix.")
        await engine.dispose()
        return

    print(f"\n{'='*80}")
    action = "DELETING" if delete_bad else "DEACTIVATING"
    print(f"{action} {len(bad_rows)} bad learnings...")
    print(f"{'='*80}\n")

    from sqlalchemy import text as sql_text

    affected_connections: set[str] = set()
    try:
        async with AsyncSession(engine) as session:
            for r, issues in bad_rows:
                affected_connections.add(r.connection_id)
                if delete_bad:
                    await session.execute(
                        sql_text("DELETE FROM agent_learnings WHERE id = :id"),
                        {"id": r.id},
                    )
                else:
                    await session.execute(
                        sql_text(
                            "UPDATE agent_learnings SET is_active = false, "
                            "updated_at = NOW() WHERE id = :id"
                        ),
                        {"id": r.id},
                    )

            for conn_id in affected_connections:
                await session.execute(
                    sql_text(
                        "UPDATE agent_learning_summaries SET compiled_prompt = NULL "
                        "WHERE connection_id = :cid"
                    ),
                    {"cid": conn_id},
                )

            await session.commit()
    except Exception as exc:
        print(f"ERROR: Failed to apply fixes: {exc}")
        await engine.dispose()
        sys.exit(1)

    print(f"Done. {len(bad_rows)} learnings {'deleted' if delete_bad else 'deactivated'}.")
    print(f"Invalidated compiled prompts for {len(affected_connections)} connection(s).")

    await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit and clean up Agent Learnings")
    parser.add_argument("--apply", action="store_true", help="Apply fixes (default is dry-run)")
    parser.add_argument("--delete", action="store_true", help="Delete bad learnings instead of deactivating")
    args = parser.parse_args()

    asyncio.run(main(apply=args.apply, delete_bad=args.delete))
