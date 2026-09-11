from unittest.mock import MagicMock

import pytest

from src.consolidate.classifier import (
    Capture, ExistingFact, PROVIDERS, _build_prompt, classify, parse_response,
)


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


def test_parse_response_extracts_json_wrapped_in_prose():
    # Local models often emit a sentence before/after the JSON object.
    raw = ('Here is my analysis:\n'
           '{"classification": "contradiction", "confidence": 0.7, "reasoning": "conflict", '
           '"conflicting_fact_id": "f2"}\n'
           'Let me know if you need more detail.')

    result = parse_response(raw)

    assert result.classification == "contradiction"
    assert result.conflicting_fact_id == "f2"


def test_parse_response_rejects_unknown_classification():
    with pytest.raises(ValueError, match="invalid classification"):
        parse_response('{"classification": "maybe", "confidence": 0.5}')


# --- provider-portability (provider is a "str -> str" callable, not an Anthropic-specific type) ---

def test_classify_accepts_a_fake_provider_function():
    """The adapter seam: `provider` can be any prompt-in/text-out callable, not just an
    anthropic.Anthropic client. No network, no ANTHROPIC_API_KEY needed."""
    calls = []

    def fake_provider(prompt: str) -> str:
        calls.append(prompt)
        return '{"classification": "new", "confidence": 0.99, "reasoning": "fake", "conflicting_fact_id": null}'

    cap = Capture(id="c1", captured_at="2026-08-01", content="fresh content")

    result = classify(cap, [], provider=fake_provider)

    assert result.classification == "new"
    assert len(calls) == 1
    assert "fresh content" in calls[0]


def test_classify_unknown_named_provider_names_it_in_the_error():
    cap = Capture(id="c1", captured_at="2026-08-01", content="text")

    with pytest.raises(ValueError, match="not-a-real-provider"):
        classify(cap, [], provider="not-a-real-provider")


def test_anthropic_provider_error_names_the_provider_not_an_absolute_claim(monkeypatch):
    """Regression guard: the error must name the configured provider and must not claim, as an
    absolute, that no other provider is supported (a second provider now exists: PROVIDERS)."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cap = Capture(id="c1", captured_at="2026-08-01", content="text")

    with pytest.raises(RuntimeError) as exc_info:
        classify(cap, [], provider="anthropic", client=None)

    message = str(exc_info.value)
    assert "anthropic" in message
    assert "no local classifier is supported" not in message


def test_providers_registry_has_anthropic_default_and_a_second_provider():
    assert "anthropic" in PROVIDERS
    assert len(PROVIDERS) >= 2  # at least one real alternative path exists
