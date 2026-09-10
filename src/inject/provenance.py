"""Stamps the current Git commit hash of `brain/` at injection time — what makes a session
replayable (`git checkout <hash>` reconstructs exactly what the model saw).

Per the core thesis (ARCHITECTURE.md §0): never wrong silently. If `brain/` has no commit history
yet, or has uncommitted changes, this says so explicitly rather than stamping a hash that doesn't
actually cover what was injected.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def current_commit_hash(*, repo_root: Path = Path(".")) -> str | None:
    """Returns the current HEAD commit hash, or None if there's no commit yet."""
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def has_uncommitted_changes(*, repo_root: Path = Path(".")) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain", "brain/"],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def stamp(*, repo_root: Path = Path(".")) -> str:
    """A human-readable provenance stamp: the commit hash, or an honest statement that there
    isn't one / it doesn't fully cover the current state."""
    commit_hash = current_commit_hash(repo_root=repo_root)
    if commit_hash is None:
        return "uncommitted (no git history yet for this brain/)"
    if has_uncommitted_changes(repo_root=repo_root):
        return f"{commit_hash} (with uncommitted changes to brain/ — not fully covered by this commit)"
    return commit_hash
