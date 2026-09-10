from unittest.mock import MagicMock

import pytest

from src.consolidate.classifier import Capture, ExistingFact, _build_prompt, classify


def test_build_prompt_includes_capture_and_facts():
    cap = Capture(id="c1", captured_at="2026-08-01", content="new fact text")
    facts = [ExistingFact(id="f1", valid_at="2026-01-01", content="old fact text")]

    prompt = _build_prompt(cap, facts)

    assert "new fact text" in prompt
    assert "old fact text" in prompt
    assert "f1" in prompt
    assert "c1" in prompt


def test_build_prompt_handles_no_existing_facts():
    cap = Capture(id="c1", captured_at="2026-08-01", content="new fact text")

    prompt = _build_prompt(cap, [])

    assert "(none)" in prompt


def test_classify_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cap = Capture(id="c1", captured_at="2026-08-01", content="text")

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        classify(cap, [])


def _fake_client(raw_text: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.type = "text"
    message.text = raw_text
    client.messages.create.return_value.content = [message]
    return client


def test_classify_strips_markdown_code_fences():
    raw = '```json\n{"classification": "new", "confidence": 1.0, "reasoning": "x", "conflicting_fact_id": null}\n```'
    cap = Capture(id="c1", captured_at="2026-08-01", content="text")

    result = classify(cap, [], client=_fake_client(raw))

    assert result.classification == "new"
    assert result.confidence == 1.0


def test_classify_parses_plain_json():
    raw = '{"classification": "update", "confidence": 0.8, "reasoning": "x", "conflicting_fact_id": "f1"}'
    cap = Capture(id="c1", captured_at="2026-08-01", content="text")

    result = classify(cap, [], client=_fake_client(raw))

    assert result.classification == "update"
    assert result.conflicting_fact_id == "f1"
