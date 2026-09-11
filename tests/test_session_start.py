"""aiw-readonly-integration: recall inject --for-session must read only brain/semantic/, make
zero network/model calls, write nothing, and stay fast at ~100 facts."""

from __future__ import annotations

import time
from pathlib import Path

import frontmatter
from typer.testing import CliRunner

from src.cli import app
from src.inject.session_start import active_facts, render_for_session

runner = CliRunner()


def _write_fact(brain_root: Path, *, fact_id: str, body: str, invalid_at: str | None = None,
                 scope: str | None = None, valid_at: str = "2026-01-01") -> Path:
    directory = brain_root / "semantic" / "facts" / "unsorted"
    directory.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body)
    post["id"] = fact_id
    post["valid_at"] = valid_at
    post["invalid_at"] = invalid_at
    post["scope"] = scope
    path = directory / f"{fact_id}.md"
    path.write_bytes(frontmatter.dumps(post).encode("utf-8"))
    return path


def test_active_facts_skips_invalidated_ones(tmp_path):
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, fact_id="f1", body="still true")
    _write_fact(brain_root, fact_id="f2", body="superseded", invalid_at="2026-02-01")

    facts = active_facts(brain_root=brain_root)

    assert [f.id for f in facts] == ["f1"]


def test_active_facts_empty_when_no_semantic_dir(tmp_path):
    assert active_facts(brain_root=tmp_path / "brain") == []


def test_render_for_session_produces_injection_formatted_context(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, fact_id="f1", body="User uses Kotlin at work.", scope="work")

    out = render_for_session(brain_root=brain_root, repo_root=tmp_path)

    assert '<fact id="f1"' in out
    assert "User uses Kotlin at work." in out
    assert "source_commit=" in out


def test_reading_touches_no_files_and_no_index(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    for i in range(5):
        _write_fact(brain_root, fact_id=f"f{i}", body=f"fact number {i}")

    before = {p: p.stat().st_mtime_ns for p in brain_root.rglob("*") if p.is_file()}

    render_for_session(brain_root=brain_root, repo_root=tmp_path)

    assert not (brain_root / ".brainindex").exists(), "must not build/write the derived index"
    after = {p: p.stat().st_mtime_ns for p in brain_root.rglob("*") if p.is_file()}
    assert before == after, "read-only path must not touch any brain/ file (no new/changed files)"


def test_module_makes_no_anthropic_import(monkeypatch):
    """Zero model/network calls by construction: the module never imports the SDK that would
    make them, so there's nothing to call even accidentally."""
    import src.inject.session_start as mod

    assert "anthropic" not in vars(mod)


def test_cli_inject_for_session_exits_zero_and_prints_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    _write_fact(brain_root, fact_id="f1", body="a fact for the session")

    result = runner.invoke(app, ["inject", "--for-session"])

    assert result.exit_code == 0, result.output
    assert "a fact for the session" in result.output


def test_cli_inject_without_flag_errors_instead_of_guessing():
    result = runner.invoke(app, ["inject"])
    assert result.exit_code != 0


def test_render_for_session_under_150ms_with_100_facts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    brain_root = tmp_path / "brain"
    for i in range(100):
        _write_fact(brain_root, fact_id=f"fact-{i:03d}", body=f"Fact content number {i} " * 5)

    t0 = time.perf_counter()
    out = render_for_session(brain_root=brain_root, repo_root=tmp_path)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    assert out.count("<fact ") == 100
    assert elapsed_ms < 150, f"took {elapsed_ms:.1f}ms, must be <150ms per acceptance"
