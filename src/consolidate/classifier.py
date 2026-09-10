"""Classifier (Tier 3, probabilistic). The only place model judgment happens in the write path.

Per ARCHITECTURE.md §2: this module emits a classification + confidence + reasoning. It never
applies any consequence itself — that's executor.py's job, deterministically, once this is wired
into the pipeline in Phase 3. Right now this is exercised in isolation via eval/run_eval.py.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import anthropic
from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODEL = "claude-sonnet-5"

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


def classify(
    new_capture: Capture,
    existing_facts: list[ExistingFact],
    *,
    model: str = DEFAULT_MODEL,
    client: anthropic.Anthropic | None = None,
) -> ClassificationResult:
    """Send one classification call. Raises if the API key is missing or the response is malformed."""
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. The classifier requires a hosted strong-model API "
                "per BUILD_PLAN.md §3 — no local classifier is supported."
            )
        client = anthropic.Anthropic(api_key=api_key)

    prompt = _build_prompt(new_capture, existing_facts)
    response = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    text_blocks = [block.text for block in response.content if block.type == "text"]
    if not text_blocks:
        raise ValueError(f"Classifier response had no text block: {response.content!r}")
    raw_text = text_blocks[0].strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        if raw_text.startswith("json"):
            raw_text = raw_text[len("json"):]
        raw_text = raw_text.strip()

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
