"""Index transaction -> Markdown writes. The MD write is the durable commit; SQLite (if used
during consolidation) only ever wraps the decision-making, never holds anything unique.

Consumes an executor.Decision and writes the resulting Markdown under brain/semantic/ per the
frontmatter schema in brain/semantic/SCHEMA.md.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from src.consolidate.executor import Action, Decision

from src.config import BRAIN_ROOT
UNSORTED_ENTITY = "unsorted"


def _new_fact_path(brain_root: Path, entity: str, fact_id: str) -> Path:
    directory = brain_root / "semantic" / "facts" / entity
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{fact_id}.md"


def _write_fact(
    *,
    brain_root: Path,
    entity: str,
    scope: str | None,
    valid_at: str,
    body: str,
    source_capture_id: str,
    justification: dict,
    links: list[str],
) -> Path:
    fact_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    post = frontmatter.Post(body)
    post["id"] = fact_id
    post["entity"] = entity
    post["scope"] = scope
    post["valid_at"] = valid_at
    post["invalid_at"] = None
    post["created_at"] = now
    post["expired_at"] = None
    post["links"] = links
    post["source_capture_id"] = source_capture_id
    post["justification"] = justification

    path = _new_fact_path(brain_root, entity, fact_id)
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path


def _invalidate_fact(fact_path: Path) -> None:
    """Bitemporal invalidation: edit frontmatter in place, never delete. The fact remains
    historically-valid-until-X; only its validity window closes."""
    post = frontmatter.load(fact_path)
    now = datetime.now(timezone.utc).isoformat()
    post["invalid_at"] = now
    post["expired_at"] = now
    fact_path.write_bytes(frontmatter.dumps(post).encode("utf-8"))


def _find_fact_path(brain_root: Path, fact_id: str) -> Path | None:
    for path in (brain_root / "semantic" / "facts").rglob("*.md"):
        if frontmatter.load(path).get("id") == fact_id:
            return path
    return None


def _write_review_item(
    *,
    brain_root: Path,
    capture_id: str,
    capture_content: str,
    captured_at: str,
    justification: dict,
    candidate_facts: list[dict],
    project: str | None = None,
) -> Path:
    """Persist everything a later human accept/override needs to be self-contained: the
    candidate facts the classifier actually saw, not just the one conflicting_fact_id. This is
    what makes the correction record in ARCHITECTURE.md §7 (facts_in, classification_given,
    confidence_given, correct_classification) possible without re-deriving retrieval state.

    `project` carries forward the capture-time deterministic scope signal (src/capture/capture.py)
    so that if this item is later accepted/overridden into a real fact
    (src/consolidate/review.py), that fact still gets a real `scope` instead of losing it because
    it passed through the review queue.
    """
    directory = brain_root / "semantic" / "review_queue"
    directory.mkdir(parents=True, exist_ok=True)
    review_id = str(uuid.uuid4())

    post = frontmatter.Post(capture_content)
    post["id"] = review_id
    post["status"] = "pending"
    post["capture_id"] = capture_id
    post["captured_at"] = captured_at
    post["justification"] = justification
    post["candidate_facts"] = candidate_facts
    post["correct_classification"] = None
    post["resolved_at"] = None
    post["project"] = project

    path = directory / f"{review_id}.md"
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path


def flush(
    decision: Decision,
    *,
    capture_content: str,
    captured_at: str,
    brain_root: Path = BRAIN_ROOT,
    entity: str = UNSORTED_ENTITY,
    scope: str | None = None,
    candidate_facts: list[dict] | None = None,
    project: str | None = None,
) -> Path:
    """Apply one executor Decision, writing the resulting Markdown file(s). Returns the path of
    the primary file written (the new fact, or the review-queue item)."""
    if decision.action == Action.WRITE_NEW:
        return _write_fact(
            brain_root=brain_root,
            entity=entity,
            scope=scope,
            valid_at=captured_at,
            body=capture_content,
            source_capture_id=decision.capture_id,
            justification=decision.justification,
            links=[],
        )

    if decision.action == Action.SUPERSEDE:
        old_path = _find_fact_path(brain_root, decision.conflicting_fact_id)
        links = []
        if old_path is not None:
            _invalidate_fact(old_path)
            links = [decision.conflicting_fact_id]
        return _write_fact(
            brain_root=brain_root,
            entity=entity,
            scope=scope,
            valid_at=captured_at,
            body=capture_content,
            source_capture_id=decision.capture_id,
            justification=decision.justification,
            links=links,
        )

    if decision.action == Action.DUAL_RETAIN:
        links = [decision.conflicting_fact_id] if decision.conflicting_fact_id else []
        return _write_fact(
            brain_root=brain_root,
            entity=entity,
            scope=scope,
            valid_at=captured_at,
            body=capture_content,
            source_capture_id=decision.capture_id,
            justification=decision.justification,
            links=links,
        )

    if decision.action == Action.REVIEW:
        return _write_review_item(
            brain_root=brain_root,
            capture_id=decision.capture_id,
            capture_content=capture_content,
            captured_at=captured_at,
            justification=decision.justification,
            candidate_facts=candidate_facts or [],
            project=project,
        )

    raise ValueError(f"Unhandled action: {decision.action!r}")
