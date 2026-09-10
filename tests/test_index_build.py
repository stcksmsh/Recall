import sqlite3

from src.capture.capture import capture
from src.index.build import build


def _rows(db_path, query):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(query).fetchall()
    finally:
        conn.close()


def test_build_indexes_episodic_captures(tmp_path):
    brain_root = tmp_path / "brain"
    capture("alpha", brain_root=brain_root)
    capture("beta", brain_root=brain_root)

    db_path = build(brain_root=brain_root)

    rows = _rows(db_path, "SELECT body FROM episodic_captures ORDER BY captured_at")
    assert [r[0] for r in rows] == ["alpha", "beta"]


def test_build_handles_empty_semantic_tier(tmp_path):
    brain_root = tmp_path / "brain"
    capture("only episodic so far", brain_root=brain_root)

    db_path = build(brain_root=brain_root)

    count = _rows(db_path, "SELECT COUNT(*) FROM semantic_facts")[0][0]
    assert count == 0


def test_rebuild_is_query_equivalent(tmp_path):
    """The core trust claim: rm -rf .brainindex && rebuild must reproduce an equivalent index."""
    brain_root = tmp_path / "brain"
    capture("first entry", brain_root=brain_root)
    capture("second entry", brain_root=brain_root)
    capture("third entry", brain_root=brain_root)

    db_path = build(brain_root=brain_root)
    before = _rows(db_path, "SELECT id, captured_at, source, path, body FROM episodic_captures ORDER BY captured_at")

    db_path.unlink()
    assert not db_path.exists()

    db_path = build(brain_root=brain_root)
    after = _rows(db_path, "SELECT id, captured_at, source, path, body FROM episodic_captures ORDER BY captured_at")

    assert before == after


def test_semantic_facts_source_capture_id_is_queryable(tmp_path):
    """Regression: source_capture_id must be a real column, not just buried in frontmatter_json —
    the consolidation loop's anti-join against it depends on this."""
    from src.consolidate.classifier import ClassificationResult
    from src.consolidate.executor import decide
    from src.index.flush import flush

    brain_root = tmp_path / "brain"
    decision = decide(
        ClassificationResult("new", 0.9, "why", None), capture_id="c1", confidence_threshold=0.75
    )
    flush(decision, capture_content="body", captured_at="2026-01-01", brain_root=brain_root)

    db_path = build(brain_root=brain_root)
    rows = _rows(db_path, "SELECT source_capture_id FROM semantic_facts")
    assert rows == [("c1",)]


def test_build_is_idempotent_when_run_twice_without_changes(tmp_path):
    brain_root = tmp_path / "brain"
    capture("stable entry", brain_root=brain_root)

    db_path = build(brain_root=brain_root)
    first = _rows(db_path, "SELECT * FROM episodic_captures")

    db_path = build(brain_root=brain_root)
    second = _rows(db_path, "SELECT * FROM episodic_captures")

    assert first == second
