import json

import frontmatter
import pytest

import src.consolidate.run as run_module
from src.capture.aiw_import import import_done_tasks
from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide as real_decide
from src.index.build import build
from src.retrieve.hybrid import search


def _write_state(path, tasks: dict) -> None:
    path.write_text(json.dumps({"schema_version": 1, "tasks": tasks}), encoding="utf-8")


def _done_task(title="Some finished task", result="It works.", source_hash="abc123"):
    return {
        "title": title,
        "status": "done",
        "result": result,
        "evidence": {"source_hash": source_hash, "success": True},
    }


def test_import_writes_one_capture_per_done_task(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, {"task-a": _done_task(), "task-b": {"title": "not done yet", "status": "pending"}})
    brain_root = tmp_path / "brain"

    paths = import_done_tasks(state_path=state_path, brain_root=brain_root)

    assert len(paths) == 1
    post = frontmatter.load(paths[0])
    assert post["source"] == "aiw"
    assert post["aiw_task_id"] == "task-a"
    assert post["aiw_revision"] == "abc123"
    assert "AIW recorded task" in post.content
    assert "done" in post.content
    # Framed as a recorded observation, not asserted as a present-tense fact.
    assert "It works." in post.content


def test_import_is_idempotent_for_the_same_revision(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, {"task-a": _done_task()})
    brain_root = tmp_path / "brain"

    first = import_done_tasks(state_path=state_path, brain_root=brain_root)
    second = import_done_tasks(state_path=state_path, brain_root=brain_root)

    assert len(first) == 1
    assert second == []


def test_import_writes_a_new_observation_on_revision_change(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path, {"task-a": _done_task(source_hash="rev1")})
    brain_root = tmp_path / "brain"

    import_done_tasks(state_path=state_path, brain_root=brain_root)

    _write_state(state_path, {"task-a": _done_task(source_hash="rev2", result="Now it also does X.")})
    second = import_done_tasks(state_path=state_path, brain_root=brain_root)

    assert len(second) == 1
    assert frontmatter.load(second[0])["aiw_revision"] == "rev2"


def test_imported_observation_is_classified_through_decide_not_a_direct_insert(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _write_state(state_path, {"task-a": _done_task()})
    brain_root = tmp_path / "brain"

    import_done_tasks(state_path=state_path, brain_root=brain_root)

    calls = {"n": 0}

    def counting_decide(*args, **kwargs):
        calls["n"] += 1
        return real_decide(*args, **kwargs)

    monkeypatch.setattr(run_module, "decide", counting_decide)
    monkeypatch.setattr(
        run_module, "classify",
        lambda *a, **k: ClassificationResult("new", 0.95, "no overlap", None),
    )

    summary = run_module.run(brain_root=brain_root)

    assert calls["n"] == 1
    assert summary.by_action == {"write_new": 1}
    facts = list((brain_root / "semantic" / "facts").rglob("*.md"))
    assert len(facts) == 1
    fact_post = frontmatter.load(facts[0])
    assert fact_post["justification"]["classification"] == "new"


def test_invalidated_imported_fact_is_excluded_from_retrieval_like_any_other(tmp_path, monkeypatch):
    state_path = tmp_path / "state.json"
    _write_state(state_path, {"task-a": _done_task(title="Ship the widget", result="Widget shipped via aiwidgetimport.")})
    brain_root = tmp_path / "brain"

    import_done_tasks(state_path=state_path, brain_root=brain_root)

    calls = {"n": 0}

    def fake_classify(new_capture, existing_facts, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return ClassificationResult("new", 0.95, "no overlap", None)
        return ClassificationResult("update", 0.95, "superseded", existing_facts[0].id)

    monkeypatch.setattr(run_module, "classify", fake_classify)
    run_module.run(brain_root=brain_root, verify_decisions=False)

    from src.capture.capture import capture
    capture("aiwidgetimport actually shipped broken and was rolled back.", brain_root=brain_root)
    run_module.run(brain_root=brain_root, verify_decisions=False)

    index_db = build(brain_root=brain_root)
    results = search(index_db, "aiwidgetimport widget shipped", k=10)
    assert all("Widget shipped via aiwidgetimport" not in r.body for r in results)
