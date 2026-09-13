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
see src/capture/capture.py) -- consolidation's classifier then decides for itself whether that new
observation is a "new" fact, an "update" superseding the earlier one, or a contradiction, exactly
as it would for any other pair of captures about the same thing.

Scope is an explicit, required, per-invocation choice (`mode=`) -- NOT a default baked into this
module. AIW currently has ~18 done tasks with no capture()/consolidate history of their own; a
naive "import everything done" default would silently backfill all of them the first time this
runs. Two modes, and nothing runs if neither is chosen:
- `mode="all"`: import every currently-done task (full backfill), still deduplicated by the
  (task_id, revision) idempotency key in `_already_imported`.
- `mode="since-revision"` (+ `since_revision=<git sha>`): only tasks that are done now but were
  NOT YET done in `.ai/state.json` as of that git revision (`_done_task_ids_at_revision` reads
  the file's content at that revision via `git show <rev>:<path>`, no working-tree checkout).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import frontmatter

from src.capture.capture import capture as do_capture
from src.config import BRAIN_ROOT

DEFAULT_STATE_PATH = Path(".ai/state.json")
SOURCE = "aiw"
MODES = frozenset({"all", "since-revision"})


def _load_done_tasks(state_path: Path) -> dict[str, dict]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    tasks = state.get("tasks", {})
    return {task_id: task for task_id, task in tasks.items() if task.get("status") == "done"}


def _revision_for(task: dict) -> str | None:
    evidence = task.get("evidence") or {}
    return evidence.get("source_hash") or evidence.get("contract_hash")


def _done_task_ids_at_revision(repo_root: Path, revision: str, state_path: Path) -> set[str]:
    """Task ids already `done` in `.ai/state.json` as of `revision`, read via `git show` (no
    working-tree checkout, no mutation of the repo). Raises if the revision or path can't be
    read -- an unresolvable `--since-revision` should fail loudly, not silently import everything
    or nothing.
    """
    rel_path = state_path if not state_path.is_absolute() else state_path.relative_to(repo_root.resolve())
    result = subprocess.run(
        ["git", "-C", str(repo_root), "show", f"{revision}:{rel_path.as_posix()}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Could not read {rel_path} at revision {revision!r}: {result.stderr.strip()}"
        )
    state = json.loads(result.stdout)
    tasks = state.get("tasks", {})
    return {task_id for task_id, task in tasks.items() if task.get("status") == "done"}


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
    *,
    mode: str,
    since_revision: str | None = None,
    state_path: Path = DEFAULT_STATE_PATH,
    brain_root: Path = BRAIN_ROOT,
    repo_root: Path = Path("."),
) -> list[Path]:
    """Capture one new episodic observation per AIW task in scope (per `mode`) that isn't already
    imported at its current revision. Read-only with respect to `.ai/` -- never writes there.

    `mode` has no default -- the caller (src/cli.py's `recall import-aiw`) must pass exactly one
    of "all" or "since-revision", so whether historical done tasks get backfilled is a choice made
    at invocation time, not a behavior baked into this function.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {sorted(MODES)}, got {mode!r}")
    if mode == "since-revision" and not since_revision:
        raise ValueError('since_revision is required when mode="since-revision"')

    if not state_path.exists():
        return []

    done_tasks = _load_done_tasks(state_path)
    if mode == "since-revision":
        already_done_ids = _done_task_ids_at_revision(repo_root, since_revision, state_path)
        done_tasks = {tid: t for tid, t in done_tasks.items() if tid not in already_done_ids}

    written: list[Path] = []
    for task_id, task in sorted(done_tasks.items()):
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
