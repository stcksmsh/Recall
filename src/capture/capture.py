"""Episodic capture (Tier 1). Instant, append-only, no model calls."""

from __future__ import annotations

import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from src.config import BRAIN_ROOT
EPISODIC_ROOT = BRAIN_ROOT / "episodic"


def _detect_project(cwd: Path | None = None) -> str | None:
    """Deterministic project/repo signal for the eventual `scope` field (src/consolidate/run.py)
    -- the git work-tree root's directory name, or None outside a git repo. Local `git` only, no
    network call, so this stays consistent with capture()'s own "instant, no model/network calls"
    contract.
    """
    cwd = cwd or Path.cwd()
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return Path(top).name if top else None


def capture(
    text: str,
    source: str = "cli",
    *,
    brain_root: Path = BRAIN_ROOT,
    project: str | None = None,
    extra: dict | None = None,
) -> Path:
    """Write a new timestamped episodic capture and return its path.

    Never edits or deletes an existing file — every call produces a new file.

    `project` defaults to the git repo name detected from the current working directory
    (`_detect_project`) — this is the "capture context already implies it" deterministic signal
    consolidation uses as `scope` (src/consolidate/run.py), rather than guessing an entity's
    context from content alone. Pass it explicitly to override or (in a non-git context, e.g. a
    historical import) supply a stand-in value.

    `extra` merges additional frontmatter fields verbatim (e.g. an importer's own provenance
    tags) — capture() stays the single write path so nothing bypasses it with a second file edit.
    """
    now = datetime.now(timezone.utc)
    capture_id = str(uuid.uuid4())

    year_dir = brain_root / "episodic" / f"{now:%Y}" / f"{now:%m}"
    year_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = now.strftime("%Y-%m-%dT%H-%M-%S")
    path = year_dir / f"{timestamp_str}_capture.md"
    # Guard against two captures in the same second colliding on filename.
    suffix = 1
    while path.exists():
        path = year_dir / f"{timestamp_str}_capture-{suffix}.md"
        suffix += 1

    if project is None:
        project = _detect_project()

    post = frontmatter.Post(text)
    post["id"] = capture_id
    post["captured_at"] = now.isoformat()
    post["source"] = source
    post["project"] = project
    for key, value in (extra or {}).items():
        post[key] = value

    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path
