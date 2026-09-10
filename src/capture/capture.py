"""Episodic capture (Tier 1). Instant, append-only, no model calls."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

BRAIN_ROOT = Path("brain")
EPISODIC_ROOT = BRAIN_ROOT / "episodic"


def capture(text: str, source: str = "cli", *, brain_root: Path = BRAIN_ROOT) -> Path:
    """Write a new timestamped episodic capture and return its path.

    Never edits or deletes an existing file — every call produces a new file.
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

    post = frontmatter.Post(text)
    post["id"] = capture_id
    post["captured_at"] = now.isoformat()
    post["source"] = source

    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path
