"""NLI verification (Phase 6, stage 2). CPU-local, runs on what deterministic.py doesn't catch.

BUILD_PLAN.md 3 specifies AlignScore (355M) or MiniCheck, CPU. AlignScore gives a single
0-1 factual-alignment score, which cannot separate "the capture contradicts the fact" from "the
capture is unrelated to the fact" — and this verifier needs exactly that distinction. So the
model here is a 3-way MNLI classifier of the same size class: `roberta-large-mnli` (355M,
BPE tokenizer, no sentencepiece, CPU-runnable). Swap `MODEL` for a MiniCheck/AlignScore
checkpoint if a later eval shows this one misses.

Premise = an existing stored fact. Hypothesis = the new capture. High P(contradiction) means
the capture asserts the fact is false — a retraction the classifier must not auto-apply.
"""

from __future__ import annotations

import functools
import time
from dataclasses import dataclass, field

from src.verify.deterministic import RISKY_LABELS

MODEL = "roberta-large-mnli"
# roberta-large-mnli label order.
_LABELS = ("contradiction", "neutral", "entailment")


@functools.lru_cache(maxsize=1)
def _pipe():
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL)
    model.eval()
    torch.set_num_threads(torch.get_num_threads())  # use all CPU cores

    def run(premise: str, hypothesis: str) -> dict[str, float]:
        enc = tok(premise, hypothesis, return_tensors="pt", truncation=True, max_length=512)
        with torch.no_grad():
            logits = model(**enc).logits[0]
        probs = logits.softmax(-1).tolist()
        return dict(zip(_LABELS, probs))

    return run


@dataclass
class NLIVerdict:
    flagged: bool
    contradiction_score: float = 0.0
    reason: str = ""
    per_fact: list[float] = field(default_factory=list)
    latency_s: float = 0.0


def nli(premise: str, hypothesis: str) -> dict[str, float]:
    """Raw 3-way NLI probabilities. Loads the model on first call."""
    return _pipe()(premise, hypothesis)


def check(
    existing_facts: list[str],
    new_capture: str,
    classification: str,
    *,
    threshold: float = 0.55,
) -> NLIVerdict:
    """Flag when the capture contradicts one of the existing facts yet the classifier gave an
    auto-applying label. Checks both directions per fact and takes the max — a capture that
    reframes a fact often reads as premise, not hypothesis."""
    if classification not in RISKY_LABELS:
        return NLIVerdict(False, reason="classifier label is not auto-applying")
    if not existing_facts:
        return NLIVerdict(False, reason="no existing facts to check against")

    t0 = time.time()
    per_fact = []
    for fact in existing_facts:
        a = nli(fact, new_capture)["contradiction"]
        b = nli(new_capture, fact)["contradiction"]
        per_fact.append(max(a, b))
    latency = time.time() - t0

    best = max(per_fact)
    flagged = best >= threshold
    return NLIVerdict(
        flagged,
        contradiction_score=round(best, 4),
        reason=(f"P(contradiction)={best:.2f} >= {threshold} against a stored fact "
                f"while classifier said '{classification}'" if flagged
                else f"max P(contradiction)={best:.2f} < {threshold}"),
        per_fact=[round(x, 4) for x in per_fact],
        latency_s=round(latency, 3),
    )
