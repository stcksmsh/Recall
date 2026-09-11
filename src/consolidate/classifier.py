"""Classifier (Tier 3, probabilistic). The only place model judgment happens in the write path.

Per ARCHITECTURE.md §2: this module emits a classification + confidence + reasoning. It never
applies any consequence itself — that's executor.py's job, deterministically, once this is wired
into the pipeline in Phase 3. Right now this is exercised in isolation via eval/run_eval.py.

Phase 2 follow-up: a prompt revision adding a `prior_fact_was_valid_when_recorded` field to
force the "retracted-as-error vs. aged-out" distinction was tried in three variants and every
one was a net regression on the 46-case real set (see eval/PHASE2_FOLLOWUP_FINDINGS.md). The
prompt below is the Phase 2 baseline, unchanged. `parse_response` is split out so the model
comparison in run_eval.py can reuse the exact same parsing for local models.

Provider portability: `classify()` doesn't hardcode the Anthropic SDK — it sends the built
prompt through a `ProviderFn` (`str -> str`), selected by name (`PROVIDERS`, config via
RECALL_CLASSIFIER_PROVIDER) or passed directly as any such callable. Anthropic stays the
default; a second real backend (`local_gguf_provider`) and its measured accuracy are in
eval/PROVIDER_PORTABILITY.md. This does not change the prompt or DEFAULT_CONFIDENCE_THRESHOLD.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Callable

import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"

# Provider/model selection is config, not a code branch: RECALL_CLASSIFIER_PROVIDER picks the
# named backend (see PROVIDERS below); classify()'s `provider` argument overrides it per call,
# and also accepts an arbitrary ProviderFn directly (the adapter seam), e.g. for tests.
DEFAULT_PROVIDER = os.environ.get("RECALL_CLASSIFIER_PROVIDER", "anthropic")

# A provider is just "prompt in, raw model text out" — everything downstream (parse_response)
# is provider-agnostic. This is the same shape eval/run_eval.py's backends already used; the
# seam is lifted here so the write path (this module) and the eval harness share one adapter.
ProviderFn = Callable[[str], str]

VALID_CLASSIFICATIONS = {"new", "update", "contradiction", "context_dependent_both"}

PROMPT_TEMPLATE = """You are comparing a NEW captured fact against EXISTING stored facts about the same
entity/scope. Classify the relationship as exactly one of:
- "new": no meaningful overlap with existing facts
- "update": the new fact supersedes an existing fact (the old one was true, now isn't)
- "contradiction": the new and existing facts cannot both be true, and it's not simply
  that one is newer (genuine conflict, not evolution)
- "context_dependent_both": both facts can be true simultaneously in different contexts/scopes

Existing facts:
{existing_facts_block}

New captured fact:
<capture id="{capture_id}" captured_at="{captured_at}">{capture_content}</capture>

Respond with JSON only, no other text: {{"classification": "...", "confidence": 0.0-1.0,
"reasoning": "...", "conflicting_fact_id": "..." or null}}"""


@dataclass
class ExistingFact:
    id: str
    valid_at: str
    content: str


@dataclass
class Capture:
    id: str
    captured_at: str
    content: str


@dataclass
class ClassificationResult:
    classification: str
    confidence: float
    reasoning: str
    conflicting_fact_id: str | None


def _build_prompt(new_capture: Capture, existing_facts: list[ExistingFact]) -> str:
    existing_facts_block = "\n".join(
        f'<fact id="{f.id}" valid_at="{f.valid_at}">{f.content}</fact>' for f in existing_facts
    ) or "(none)"
    return PROMPT_TEMPLATE.format(
        existing_facts_block=existing_facts_block,
        capture_id=new_capture.id,
        captured_at=new_capture.captured_at,
        capture_content=new_capture.content,
    )


def anthropic_provider(*, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None) -> ProviderFn:
    """Hosted API backend (the default). `client` is itself already an adapter seam — pass a
    fake with a `.messages.create()` shape to test without a network call."""

    def call(prompt: str) -> str:
        nonlocal client
        if client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY")
            if not api_key:
                raise RuntimeError(
                    "ANTHROPIC_API_KEY is not set for classifier provider 'anthropic'. Set "
                    "RECALL_CLASSIFIER_PROVIDER=local (with a model_path) to use a different "
                    "configured provider, or set the key."
                )
            client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model, max_tokens=512, messages=[{"role": "user", "content": prompt}],
        )
        text_blocks = [block.text for block in response.content if block.type == "text"]
        if not text_blocks:
            raise ValueError(f"Classifier response had no text block: {response.content!r}")
        return text_blocks[0]

    return call


def local_gguf_provider(*, model_path: str, n_ctx: int = 4096, n_threads: int | None = None) -> ProviderFn:
    """CPU-local GGUF backend via llama-cpp-python (optional extra `local-eval`; lazy import so
    the rest of this module doesn't require it installed). Measured accuracy is materially worse
    than the default and not recommended for real use — Qwen2.5-7B-Q4 scored 13/46 = 28.3% on
    the real eval set, 0/8 contradiction recall (`eval/PHASE2_FOLLOWUP_FINDINGS.md`). Kept as a
    genuine second provider path, not a hidden fallback."""
    from llama_cpp import Llama

    llm = Llama(model_path=model_path, n_ctx=n_ctx, n_threads=n_threads, verbose=False, n_gpu_layers=0)

    def call(prompt: str) -> str:
        out = llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512, temperature=0.0,
            response_format={"type": "json_object"},
        )
        return out["choices"][0]["message"]["content"]

    return call


# Named providers classify(provider=...) can select by string. "anthropic" is handled inline in
# classify() (it needs `model`/`client` threaded through, not just provider_kwargs); registered
# here too so callers can introspect what's configured.
PROVIDERS: dict[str, Callable[..., ProviderFn]] = {
    "anthropic": anthropic_provider,
    "local": local_gguf_provider,
}


def classify(
    new_capture: Capture,
    existing_facts: list[ExistingFact],
    *,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
    provider: str | ProviderFn = DEFAULT_PROVIDER,
    **provider_kwargs,
) -> ClassificationResult:
    """Send one classification call through the configured provider and parse its response.

    `provider` is either a registered name (PROVIDERS; default from RECALL_CLASSIFIER_PROVIDER,
    itself defaulting to "anthropic") or any ProviderFn — a `str -> str` callable — for a fully
    custom or fake backend. Raises if the resolved provider can't run (e.g. missing API key) or
    the response is malformed.
    """
    if callable(provider):
        provider_fn = provider
    elif provider == "anthropic":
        provider_fn = anthropic_provider(model=model, client=client)
    elif provider in PROVIDERS:
        provider_fn = PROVIDERS[provider](**provider_kwargs)
    else:
        raise ValueError(f"Unknown classifier provider: {provider!r}. Known: {sorted(PROVIDERS)}")

    prompt = _build_prompt(new_capture, existing_facts)
    raw_text = provider_fn(prompt)
    return parse_response(raw_text)


def parse_response(raw_text: str) -> ClassificationResult:
    """Parse a model's raw text into a ClassificationResult.

    Shared by the hosted-API path and by eval/run_eval.py's local-model path — anything that can
    produce the JSON contract in PROMPT_TEMPLATE can reuse this.
    """
    raw_text = raw_text.strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[len("json"):]
        raw_text = raw_text.strip()
    # Local models often wrap the JSON in prose; take the outermost {...}.
    if not raw_text.startswith("{") and "{" in raw_text and "}" in raw_text:
        raw_text = raw_text[raw_text.index("{"): raw_text.rindex("}") + 1]

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Classifier returned non-JSON response: {raw_text!r}") from e

    classification = parsed.get("classification")
    if classification not in VALID_CLASSIFICATIONS:
        raise ValueError(f"Classifier returned invalid classification: {classification!r}")

    return ClassificationResult(
        classification=classification,
        confidence=float(parsed.get("confidence", 0.0)),
        reasoning=parsed.get("reasoning", ""),
        conflicting_fact_id=parsed.get("conflicting_fact_id"),
    )
