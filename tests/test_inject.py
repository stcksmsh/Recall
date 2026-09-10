from src.inject.format import format_facts
from src.inject.provenance import current_commit_hash, stamp
from src.retrieve.hybrid import RetrievedFact


def test_format_facts_wraps_each_fact_in_xml_with_id_and_commit(tmp_path):
    facts = [RetrievedFact(id="f1", body="User uses Kotlin at work.", score=1.0, valid_at="2026-01-01", scope="work")]

    formatted = format_facts(facts, repo_root=tmp_path)

    assert '<fact id="f1"' in formatted
    assert 'valid_at="2026-01-01"' in formatted
    assert 'scope="work"' in formatted
    assert "User uses Kotlin at work." in formatted
    assert "source_commit=" in formatted


def test_format_facts_handles_empty_results_honestly(tmp_path):
    formatted = format_facts([], repo_root=tmp_path)
    assert "No stored facts were found" in formatted


def test_provenance_reports_no_history_for_non_git_dir(tmp_path):
    assert current_commit_hash(repo_root=tmp_path) is None
    assert "uncommitted" in stamp(repo_root=tmp_path)
