"""Cheap "is this retrieval complete enough" gate (BUILD_PLAN.md §2.3).

Simple heuristic per the spec: graduate to something smarter only if this proves insufficient in
practice. Right now: no facts at all, or an entity/scope match came up empty while similarity
search only found weak matches, both count as insufficient.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.retrieve.hybrid import RetrievedFact

WEAK_SCORE_THRESHOLD = 0.02


@dataclass
class SufficiencyResult:
    sufficient: bool
    reason: str


def check(
    *, entity_matches: list[RetrievedFact], similarity_matches: list[RetrievedFact]
) -> SufficiencyResult:
    if not entity_matches and not similarity_matches:
        return SufficiencyResult(False, "no facts found via entity/scope or similarity search")

    if not entity_matches and similarity_matches:
        best_score = max(f.score for f in similarity_matches)
        if best_score < WEAK_SCORE_THRESHOLD:
            return SufficiencyResult(
                False,
                f"no entity/scope match; best similarity score ({best_score:.4f}) is weak",
            )

    return SufficiencyResult(True, "sufficient")
