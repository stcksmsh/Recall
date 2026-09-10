"""Consolidation loop orchestration: wires classifier -> executor -> flush for each
not-yet-consolidated episodic capture. Manual trigger only (`recall consolidate run`) — no
scheduled/automatic trigger yet, per BUILD_PLAN.md §7 (explicitly out of scope for v1).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.consolidate.blast_radius import DEFAULT_K, candidate_facts
from src.consolidate.classifier import Capture, classify
from src.consolidate.executor import DEFAULT_CONFIDENCE_THRESHOLD, decide
from src.index.build import build
from src.index.flush import flush

BRAIN_ROOT = Path("brain")


@dataclass
class ConsolidationSummary:
    processed: int = 0
    by_action: dict = field(default_factory=dict)

    def record(self, action: str) -> None:
        self.processed += 1
        self.by_action[action] = self.by_action.get(action, 0) + 1


def _unconsolidated_captures(index_db: Path) -> list[Capture]:
    """Captures with no corresponding semantic fact or review-queue item yet. Derived entirely
    from the (rebuildable) index, not from separate untracked state."""
    conn = sqlite3.connect(index_db)
    try:
        rows = conn.execute(
            """
            SELECT id, captured_at, body FROM episodic_captures
            WHERE id NOT IN (SELECT source_capture_id FROM semantic_facts WHERE source_capture_id IS NOT NULL)
              AND id NOT IN (SELECT capture_id FROM review_queue WHERE capture_id IS NOT NULL)
            ORDER BY captured_at ASC
            """
        ).fetchall()
    finally:
        conn.close()

    return [Capture(id=row[0], captured_at=row[1], content=row[2]) for row in rows]


def run(
    *,
    brain_root: Path = BRAIN_ROOT,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    k: int = DEFAULT_K,
) -> ConsolidationSummary:
    index_db = build(brain_root=brain_root)
    captures = _unconsolidated_captures(index_db)

    summary = ConsolidationSummary()
    for capture in captures:
        candidates = candidate_facts(index_db, k=k)
        result = classify(capture, candidates)
        decision = decide(result, capture_id=capture.id, confidence_threshold=confidence_threshold)
        candidate_dicts = [
            {"id": f.id, "valid_at": f.valid_at, "content": f.content} for f in candidates
        ]
        flush(
            decision,
            capture_content=capture.content,
            captured_at=capture.captured_at,
            brain_root=brain_root,
            candidate_facts=candidate_dicts,
        )
        summary.record(decision.action.value)
        index_db = build(brain_root=brain_root)

    return summary
