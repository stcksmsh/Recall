"""Markdown -> SQLite index build (Tier 2 derived index).

`.brainindex/index.db` is disposable and gitignored. This module is the *only* way it gets
created — `rm -rf brain/.brainindex && recall index build` must always reproduce a
query-equivalent index. Never write information into the index that isn't recoverable from the
Markdown under `brain/`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import frontmatter

from src.config import BRAIN_ROOT
INDEX_DIR = BRAIN_ROOT / ".brainindex"
INDEX_DB = INDEX_DIR / "index.db"

SCHEMA = """
CREATE TABLE episodic_captures (
    id TEXT PRIMARY KEY,
    captured_at TEXT NOT NULL,
    source TEXT,
    path TEXT NOT NULL,
    body TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL
);

CREATE TABLE semantic_facts (
    id TEXT PRIMARY KEY,
    entity TEXT,
    scope TEXT,
    valid_at TEXT,
    invalid_at TEXT,
    created_at TEXT,
    expired_at TEXT,
    source_capture_id TEXT,
    links_json TEXT NOT NULL,
    path TEXT NOT NULL,
    body TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL
);

CREATE VIRTUAL TABLE semantic_facts_fts USING fts5(id UNINDEXED, body);

CREATE TABLE review_queue (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    capture_id TEXT,
    path TEXT NOT NULL,
    body TEXT NOT NULL,
    frontmatter_json TEXT NOT NULL
);

CREATE INDEX idx_episodic_captured_at ON episodic_captures(captured_at);
CREATE INDEX idx_semantic_entity ON semantic_facts(entity);
CREATE INDEX idx_semantic_scope ON semantic_facts(scope);
CREATE INDEX idx_review_queue_status ON review_queue(status);
"""


def _iter_markdown_files(root: Path):
    if not root.exists():
        return
    for path in sorted(root.rglob("*.md")):
        yield path


def build(*, brain_root: Path = BRAIN_ROOT, index_db: Path | None = None) -> Path:
    """Full rebuild: walk brain/episodic and brain/semantic, populate a fresh SQLite index.

    Idempotent — always drops and recreates the DB file rather than mutating an existing one,
    so the result only ever depends on the current state of the Markdown tree.
    """
    index_db = index_db or (brain_root / ".brainindex" / "index.db")
    index_db.parent.mkdir(parents=True, exist_ok=True)
    if index_db.exists():
        index_db.unlink()

    conn = sqlite3.connect(index_db)
    try:
        conn.executescript(SCHEMA)

        for path in _iter_markdown_files(brain_root / "episodic"):
            post = frontmatter.load(path)
            fm = dict(post.metadata)
            conn.execute(
                "INSERT INTO episodic_captures "
                "(id, captured_at, source, path, body, frontmatter_json) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fm.get("id"),
                    fm.get("captured_at"),
                    fm.get("source"),
                    str(path.relative_to(brain_root)),
                    post.content,
                    json.dumps(fm, default=str, sort_keys=True),
                ),
            )

        for path in _iter_markdown_files(brain_root / "semantic" / "facts"):
            post = frontmatter.load(path)
            fm = dict(post.metadata)
            conn.execute(
                "INSERT INTO semantic_facts "
                "(id, entity, scope, valid_at, invalid_at, created_at, expired_at, source_capture_id, links_json, path, body, frontmatter_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fm.get("id"),
                    fm.get("entity"),
                    fm.get("scope"),
                    fm.get("valid_at"),
                    fm.get("invalid_at"),
                    fm.get("created_at"),
                    fm.get("expired_at"),
                    fm.get("source_capture_id"),
                    json.dumps(fm.get("links") or [], sort_keys=True),
                    str(path.relative_to(brain_root)),
                    post.content,
                    json.dumps(fm, default=str, sort_keys=True),
                ),
            )
            conn.execute(
                "INSERT INTO semantic_facts_fts (id, body) VALUES (?, ?)",
                (fm.get("id"), post.content),
            )

        for path in _iter_markdown_files(brain_root / "semantic" / "review_queue"):
            post = frontmatter.load(path)
            fm = dict(post.metadata)
            conn.execute(
                "INSERT INTO review_queue (id, status, capture_id, path, body, frontmatter_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    fm.get("id"),
                    fm.get("status"),
                    fm.get("capture_id"),
                    str(path.relative_to(brain_root)),
                    post.content,
                    json.dumps(fm, default=str, sort_keys=True),
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return index_db
