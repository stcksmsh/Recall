"""Consolidation loop orchestration: wires classifier -> executor -> flush for each
not-yet-consolidated episodic capture. Manual trigger only (`recall consolidate run`) — no
scheduled/automatic trigger yet, per BUILD_PLAN.md §7 (explicitly out of scope for v1).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from src.consolidate.blast_radius import DEFAULT_K, candidate_facts
from src.consolidate.classifier import Capture, classify
from src.consolidate.entity_extract import extract_entity
from src.consolidate.executor import DEFAULT_CONFIDENCE_THRESHOLD, Action, Decision, decide
from src.index.build import build
from src.index.flush import UNSORTED_ENTITY, flush
from src.verify import verify

from src.config import BRAIN_ROOT

# Decisions that write an invalidation or a second retained fact — the destructive auto-applies
# Phase 6 verification guards. WRITE_NEW is additive and REVIEW is already safe.
_VERIFIED_ACTIONS = frozenset({Action.SUPERSEDE, Action.DUAL_RETAIN})

# Decisions that write an actual semantic fact (as opposed to a review-queue item) — these are
# the ones that need a real entity, not just a real classification.
_FACT_ACTIONS = frozenset({Action.WRITE_NEW, Action.SUPERSEDE, Action.DUAL_RETAIN})


@dataclass
class ConsolidationSummary:
    processed: int = 0
    by_action: dict = field(default_factory=dict)
    verifier_flagged: int = 0

    def record(self, action: str) -> None:
        self.processed += 1
        self.by_action[action] = self.by_action.get(action, 0) + 1


def _unconsolidated_captures(index_db: Path) -> list[tuple[Capture, str | None]]:
    """Captures with no corresponding semantic fact or review-queue item yet, paired with the
    project each was captured under (src/capture/capture.py's deterministic `project` field,
    read back from the already-stored frontmatter_json rather than a new index column). Derived
    entirely from the (rebuildable) index, not from separate untracked state."""
    conn = sqlite3.connect(index_db)
    try:
        rows = conn.execute(
            """
            SELECT id, captured_at, body, frontmatter_json FROM episodic_captures
            WHERE id NOT IN (SELECT source_capture_id FROM semantic_facts WHERE source_capture_id IS NOT NULL)
              AND id NOT IN (SELECT capture_id FROM review_queue WHERE capture_id IS NOT NULL)
            ORDER BY captured_at ASC
            """
        ).fetchall()
    finally:
        conn.close()

    return [
        (Capture(id=row[0], captured_at=row[1], content=row[2]), json.loads(row[3]).get("project"))
        for row in rows
    ]


def run(
    *,
    brain_root: Path = BRAIN_ROOT,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    k: int = DEFAULT_K,
    verify_decisions: bool = True,
) -> ConsolidationSummary:
    index_db = build(brain_root=brain_root)
    captures = _unconsolidated_captures(index_db)

    summary = ConsolidationSummary()
    for capture, project in captures:
        candidates = candidate_facts(index_db, k=k)
        result = classify(capture, candidates)
        decision = decide(result, capture_id=capture.id, confidence_threshold=confidence_threshold)

        if verify_decisions and decision.action in _VERIFIED_ACTIONS:
            vres = verify([f.content for f in candidates], capture.content, result.classification)
            if vres.flagged:
                justification = dict(decision.justification)
                justification["verifier_flag"] = {
                    "stage": vres.stage, "reason": vres.reason, "signals": vres.signals,
                    "original_action": decision.action.value,
                }
                decision = Decision(Action.REVIEW, decision.capture_id,
                                    decision.conflicting_fact_id, justification)
                summary.verifier_flagged += 1

        # Entity extraction only matters for a decision that's actually about to write a fact —
        # a decision already routed to review doesn't need one. A genuinely ambiguous extraction
        # (see entity_extract.py) is not guessed: it reroutes to review the same way a verifier
        # flag does, rather than inventing a second, ungated way to decide what happens next.
        entity = UNSORTED_ENTITY
        if decision.action in _FACT_ACTIONS:
            extraction = extract_entity(capture.content)
            if extraction.ambiguous:
                justification = dict(decision.justification)
                justification["entity_extraction_flag"] = {
                    "reason": "ambiguous entity candidates (tied lexical frequency)",
                    "candidates": extraction.candidates,
                }
                decision = Decision(Action.REVIEW, decision.capture_id,
                                    decision.conflicting_fact_id, justification)
            else:
                entity = extraction.entity

        candidate_dicts = [
            {"id": f.id, "valid_at": f.valid_at, "content": f.content} for f in candidates
        ]
        flush(
            decision,
            capture_content=capture.content,
            captured_at=capture.captured_at,
            brain_root=brain_root,
            entity=entity,
            scope=project,
            project=project,
            candidate_facts=candidate_dicts,
        )
        summary.record(decision.action.value)
        index_db = build(brain_root=brain_root)

    return summary
