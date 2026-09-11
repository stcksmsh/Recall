"""`recall status` — a read-only snapshot of the store. No model calls, no writes.

Rebuilds the derived index (cheap, same as the retrieve path) and reads counts back from it, so
the numbers always reflect the current Markdown, never a stale index.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.consolidate.run import _unconsolidated_captures
from src.index.build import build

from src.config import BRAIN_ROOT

RETRACTION_CAVEAT = (
    "The Phase 6 verifier catches first-person retraction phrasing only. A confident retraction "
    "with no lexical cue can still auto-apply undetected — see LIMITATIONS.md."
)


@dataclass
class Status:
    captures: int = 0
    unconsolidated: int = 0
    last_capture_at: str | None = None
    facts_active: int = 0
    facts_invalidated: int = 0
    last_fact_at: str | None = None
    review_pending: int = 0
    review_by_classification: dict[str, int] = field(default_factory=dict)
    corrections: int = 0


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def gather(*, brain_root: Path = BRAIN_ROOT) -> Status:
    index_db = build(brain_root=brain_root)
    conn = sqlite3.connect(index_db)
    try:
        s = Status()
        s.captures = _scalar(conn, "SELECT COUNT(*) FROM episodic_captures")
        s.unconsolidated = len(_unconsolidated_captures(index_db))
        s.last_capture_at = conn.execute(
            "SELECT MAX(captured_at) FROM episodic_captures"
        ).fetchone()[0]

        s.facts_active = _scalar(
            conn, "SELECT COUNT(*) FROM semantic_facts WHERE invalid_at IS NULL"
        )
        s.facts_invalidated = _scalar(
            conn, "SELECT COUNT(*) FROM semantic_facts WHERE invalid_at IS NOT NULL"
        )
        s.last_fact_at = conn.execute(
            "SELECT MAX(created_at) FROM semantic_facts"
        ).fetchone()[0]

        s.review_pending = _scalar(
            conn, "SELECT COUNT(*) FROM review_queue WHERE status = 'pending'"
        )
    finally:
        conn.close()

    # classification breakdown + correction count come straight off the Markdown — small dirs,
    # and the index doesn't carry the parsed justification / corrections tree.
    from src.consolidate.review import list_pending

    for item in list_pending(brain_root=brain_root):
        key = item.classification_given or "unknown"
        s.review_by_classification[key] = s.review_by_classification.get(key, 0) + 1

    corrections_dir = brain_root / "semantic" / "corrections"
    s.corrections = len(list(corrections_dir.glob("*.md"))) if corrections_dir.exists() else 0

    return s


def render(s: Status) -> str:
    lines = ["recall status", ""]
    unconsolidated = (
        f"  ({s.unconsolidated} not yet consolidated — run `recall consolidate run`)"
        if s.unconsolidated
        else "  (all consolidated)"
    )
    lines.append(f"  episodic captures    {s.captures:>4}{unconsolidated}")
    lines.append(
        f"  semantic facts       {s.facts_active:>4} active"
        + (f", {s.facts_invalidated} invalidated" if s.facts_invalidated else "")
    )
    if s.review_pending:
        breakdown = ", ".join(
            f"{k}: {v}" for k, v in sorted(s.review_by_classification.items())
        )
        lines.append(f"  review queue         {s.review_pending:>4} pending   ({breakdown})")
        lines.append("                            resolve with `recall review list` then accept/override")
    else:
        lines.append(f"  review queue         {s.review_pending:>4} pending")
    lines.append(f"  corrections logged   {s.corrections:>4}")
    lines.append("")
    if s.last_capture_at:
        lines.append(f"  last capture   {s.last_capture_at}")
    if s.last_fact_at:
        lines.append(f"  last fact      {s.last_fact_at}")
    lines.append("")
    lines.append(f"  {RETRACTION_CAVEAT}")
    return "\n".join(lines)
