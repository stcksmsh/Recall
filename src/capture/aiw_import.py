"""Read-only importer: AIW's `.ai/state.json` -> Recall episodic captures (Tier 1).

AIW is Recall's sibling task tracker; `.ai/decisions/0006` draws a hard boundary -- Recall only
ever *reads* AIW's tracked files, never writes `.ai/`. Until now the only link between the two
was a human manually running `recall capture --source <task-id>` after finishing a task
(CLAUDE.md's dogfooding instruction). This module automates the discovery half of that (which
tasks are done and not yet captured) without inventing a second write path: it only ever calls
`capture()`, so an imported observation goes through the exact same
episodic -> consolidate -> classify -> executor.decide() -> flush() pipeline as any other
capture (src/consolidate/run.py). There is no direct/ungated insert into the semantic tier here.

An imported `done` task means "AIW recorded this as done, at this revision" -- not "true in
every checkout, forever". The capture body is phrased as that recorded observation, and the
revision (AIW's own `evidence.source_hash`, falling back to `contract_hash`) rides along in
frontmatter so a later change to the same task produces a new, distinguishable observation
rather than silently being treated as the same fact (the episodic tier is immutable/append-only;
see src/capture/capture.py) — consolidation's classifier then decides for itself whether that new
observation is a "new" fact, an "update" superseding the earlier one, or a contradiction, exactly
as it would for any other pair of captures about the same thing.
"""

from __future__ import annotations

import json
from pathlib import Path

import frontmatter

from src.capture.capture import capture as do_capture
from src.config import BRAIN_ROOT

DEFAULT_STATE_PATH = Path(".ai/state.json")
SOURCE = "aiw"


def _load_done_tasks(state_path: Path) -> dict[str, dict]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks", {})
    return {task_id: task for task_id, task in tasks.items() if task.get("status") == "done"}


def _revision_for(task: dict) -> str | None:
    evidence = task.get("evidence") or {}
    return evidence.get("source_hash") or evidence.get("contract_hash")


def _already_imported(brain_root: Path, task_id: str, revision: str | None) -> bool:
    """An observation for this exact (task_id, revision) pair already exists -- derived by
    scanning episodic frontmatter rather than kept as separate tracking state, the same style
    src/consolidate/run.py uses to derive "unconsolidated" from the store itself."""
    episodic_root = brain_root / "episodic"
    if not episodic_root.exists():
        return False
    for path in episodic_root.rglob("*.md"):
        fm = frontmatter.load(path)
        if (
            fm.get("source") == SOURCE
            and fm.get("aiw_task_id") == task_id
            and fm.get("aiw_revision") == revision
        ):
            return True
    return False


def _observation_text(task_id: str, task: dict) -> str:
    title = task.get("title", "")
    result = task.get("result") or "(no result recorded)"
    return f"AIW recorded task {task_id!r} ({title!r}) as done. Result: {result}"


def import_done_tasks(
    *, state_path: Path = DEFAULT_STATE_PATH, brain_root: Path = BRAIN_ROOT,
) -> list[Path]:
    """Capture one new episodic observation per AIW task newly recorded `done` since the last
    import (identified by task id + revision, so a later re-completion is a new observation, not
    a silent no-op or an overwrite). Read-only with respect to `.ai/` -- never writes there."""
    if not state_path.exists():
        return []

    written: list[Path] = []
    for task_id, task in sorted(_load_done_tasks(state_path).items()):
        revision = _revision_for(task)
        if _already_imported(brain_root, task_id, revision):
            continue
        text = _observation_text(task_id, task)
        path = do_capture(
            text,
            source=SOURCE,
            brain_root=brain_root,
            extra={
                "aiw_task_id": task_id,
                "aiw_revision": revision,
                "aiw_state_path": str(state_path),
            },
        )
        written.append(path)
    return written
