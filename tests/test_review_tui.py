"""Textual review TUI: same accept/override data path as the CLI, plus the TUI-specific
navigation/skip/summary behavior. Uses asyncio.run() directly (no pytest-asyncio dependency
added) to drive textual's Pilot harness.
"""

from __future__ import annotations

import asyncio

import frontmatter
from typer.testing import CliRunner

from src.cli import app as cli_app

from src.consolidate.classifier import ClassificationResult
from src.consolidate.executor import decide
from src.consolidate.review import accept as cli_accept
from src.consolidate.review import list_pending
from src.index.flush import flush
from src.review_tui.app import ReviewApp, resolve_item
from src.review_tui.detail import load_detail

CANDIDATES = [{"id": "f1", "valid_at": "2026-01-01", "content": "the original claim"}]


def _make_review_item(brain_root, *, classification="update", confidence=0.5, capture_id="c1",
                       content="disputed capture content", extractor_note=None):
    decision = decide(
        ClassificationResult(classification, confidence, "because reasons", "f1"),
        capture_id=capture_id,
    )
    if extractor_note:
        # extractor_note lives on the source episodic capture, not the review item itself.
        from src.capture.capture import capture as do_capture
        path = do_capture(content, source="test", brain_root=brain_root)
        post = frontmatter.load(path)
        post["id"] = capture_id
        post["extractor_note"] = extractor_note
        path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    flush(
        decision, capture_content=content, captured_at="2026-08-01", brain_root=brain_root,
        candidate_facts=CANDIDATES,
    )
    return list_pending(brain_root=brain_root)[-1]


def _only_correction(brain_root):
    files = sorted((brain_root / "semantic" / "corrections").glob("*.md"))
    assert len(files) == 1, files
    return frontmatter.load(files[0])


def test_resolve_item_unchanged_selection_accepts(tmp_path):
    brain_root = tmp_path / "brain"
    item = _make_review_item(brain_root, classification="update", confidence=0.5)

    outcome = resolve_item(item, "update", brain_root=brain_root)

    assert outcome == "accepted"
    assert list_pending(brain_root=brain_root) == []
    c = _only_correction(brain_root)
    assert c["classification_given"] == "update"
    assert c["correct_classification"] == "update"


def test_resolve_item_changed_selection_overrides(tmp_path):
    brain_root = tmp_path / "brain"
    item = _make_review_item(brain_root, classification="update", confidence=0.5)

    outcome = resolve_item(item, "contradiction", brain_root=brain_root)

    assert outcome == "overridden"
    c = _only_correction(brain_root)
    assert c["classification_given"] == "update"
    assert c["correct_classification"] == "contradiction"


def test_cli_accept_and_tui_resolve_item_produce_structurally_identical_corrections(tmp_path):
    """The before/after check: one item resolved the old way (review.accept, what `recall
    review accept` calls), one resolved the TUI way (resolve_item with the unchanged selection)
    -- same shape, same values, modulo the correction's own id/timestamp."""
    brain_root = tmp_path / "brain"
    old_way = _make_review_item(brain_root, classification="update", confidence=0.5, capture_id="c-old")
    cli_accept(old_way.id, brain_root=brain_root)
    old_correction = _only_correction(brain_root)

    brain_root2 = tmp_path / "brain2"
    new_way = _make_review_item(brain_root2, classification="update", confidence=0.5, capture_id="c-new")
    resolve_item(new_way, "update", brain_root=brain_root2)
    new_correction = _only_correction(brain_root2)

    ignore = {"id", "recorded_at", "capture_id", "review_item_id"}
    old_fields = {k: v for k, v in old_correction.metadata.items() if k not in ignore}
    new_fields = {k: v for k, v in new_correction.metadata.items() if k not in ignore}
    assert old_fields == new_fields
    assert old_correction.content == new_correction.content


def test_load_detail_surfaces_extractor_note_and_live_fact_scope(tmp_path):
    brain_root = tmp_path / "brain"
    # a real fact with a scope, to prove load_detail fetches it live (candidate_facts has none)
    new_decision = decide(ClassificationResult("new", 0.9, "no overlap", None), capture_id="c0")
    flush(new_decision, capture_content="original", captured_at="2026-01-01",
          brain_root=brain_root, entity="work", scope="work")
    fact_id = frontmatter.load(next((brain_root / "semantic" / "facts" / "work").glob("*.md")))["id"]

    review_decision = decide(
        ClassificationResult("update", 0.5, "reasoning text", fact_id), capture_id="c1"
    )
    flush(
        review_decision, capture_content="disputed", captured_at="2026-08-01",
        brain_root=brain_root,
        candidate_facts=[{"id": fact_id, "valid_at": "2026-01-01", "content": "original"}],
    )
    item = list_pending(brain_root=brain_root)[0]

    # extractor_note comes from the source episodic capture, not the review item -- create one
    # with a matching id (flush() alone never touches brain/episodic/).
    from src.capture.capture import capture as do_capture
    ep_path = do_capture("disputed", source="test", brain_root=brain_root)
    ep_post = frontmatter.load(ep_path)
    ep_post["id"] = "c1"
    ep_post["extractor_note"] = "a side observation"
    ep_path.write_bytes(frontmatter.dumps(ep_post).encode("utf-8"))

    detail = load_detail(item, brain_root=brain_root)

    assert detail.reasoning == "reasoning text"
    assert detail.extractor_note == "a side observation"
    assert detail.conflicting_fact.scope == "work"
    assert detail.conflicting_fact.content == "original"


async def _drive_confirm_then_skip_then_quit(app: ReviewApp):
    async with app.run_test() as pilot:
        # item 1: confirm unchanged selection (classifier's own proposal) -> accept
        await pilot.press("c")
        # item 2: skip -> stays pending, advances
        await pilot.press("s")
        # queue exhausted (2 items) -> app should have exited on its own; nothing more to do


def test_tui_confirm_then_skip_end_to_end(tmp_path):
    brain_root = tmp_path / "brain"
    _make_review_item(brain_root, classification="update", confidence=0.5, capture_id="c1",
                       content="first disputed capture")
    _make_review_item(brain_root, classification="contradiction", confidence=0.99, capture_id="c2",
                       content="second disputed capture")

    items = list_pending(brain_root=brain_root)  # order is by review-id filename, not insertion
    first_id, second_id = items[0].capture_id, items[1].capture_id
    app = ReviewApp(items, brain_root=brain_root)

    asyncio.run(_drive_confirm_then_skip_then_quit(app))

    assert app.summary.accepted == 1
    assert app.summary.overridden == 0
    assert app.summary.skipped_or_pending == 1
    remaining = list_pending(brain_root=brain_root)
    assert len(remaining) == 1
    assert remaining[0].capture_id == second_id  # items[0] was confirmed, items[1] skipped


async def _drive_change_selection_then_confirm(app: ReviewApp):
    from textual.widgets import Select

    async with app.run_test() as pilot:
        select = app.query_one("#classification_select", Select)
        select.value = "contradiction"
        await pilot.pause()
        await pilot.press("c")


def test_tui_changing_selection_before_confirm_overrides(tmp_path):
    brain_root = tmp_path / "brain"
    _make_review_item(brain_root, classification="update", confidence=0.5, capture_id="c1")

    items = list_pending(brain_root=brain_root)
    app = ReviewApp(items, brain_root=brain_root)

    asyncio.run(_drive_change_selection_then_confirm(app))

    assert app.summary.overridden == 1
    assert app.summary.accepted == 0
    c = _only_correction(brain_root)
    assert c["classification_given"] == "update"
    assert c["correct_classification"] == "contradiction"


runner = CliRunner()


def test_cli_review_no_subcommand_launches_tui_not_a_real_terminal(monkeypatch):
    """`recall review` (bare) must route to review_tui.launch(), not require an actual TTY to
    even be exercised in CI. Patches launch() itself -- the routing is what's under test, the
    TUI's own behavior is covered by the ReviewApp/Pilot tests above."""
    from src.review_tui.app import SessionSummary

    calls = []

    def fake_launch(**kwargs):
        calls.append(kwargs)
        return SessionSummary(total=3, accepted=2, overridden=1)

    monkeypatch.setattr("src.review_tui.launch", fake_launch)

    result = runner.invoke(cli_app, ["review"])

    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "2 accepted" in result.output
    assert "1 overridden" in result.output


def test_cli_review_list_subcommand_still_bypasses_tui(monkeypatch):
    """A real subcommand must not trigger the TUI launch path at all."""
    calls = []
    monkeypatch.setattr("src.review_tui.launch", lambda **kw: calls.append(kw))

    result = runner.invoke(cli_app, ["review", "list"])

    assert result.exit_code == 0, result.output
    assert calls == []
