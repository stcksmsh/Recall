"""Phase 6 verification. Post-classification, pre-flush second opinion.

Catches the silent-corruption failure mode from eval/PHASE2_FINDINGS.md /
eval/PHASE2_V2_BASELINE.md: the classifier labels a *retraction* of an existing fact as
`update` / `context_dependent_both` / `new` (all auto-applying) when the truth is
`contradiction` (review only). On a flag, the caller downgrades the decision to REVIEW rather
than auto-applying it. Never auto-corrects — that would reintroduce the "silent" failure.

Two stages, cheapest first:
1. deterministic.py — lexical retraction cues, ~free. **Shipped, on by default.**
2. nli_check.py    — CPU MNLI model, P(contradiction) between each stored fact and the capture.
   **Evaluated and NOT shipped by default (`use_nli=False`).** eval/PHASE6_FINDINGS.md: NLI
   contradiction score cannot separate a retraction from a normal supersession — both negate the
   prior text — so at any threshold it either misses real retractions or flags ~60% of correct
   updates. Kept as opt-in and for the eval; the distinction is not textual-entailment-shaped.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.verify import deterministic
from src.verify.deterministic import RISKY_LABELS


@dataclass
class VerificationResult:
    flagged: bool
    stage: str | None          # "deterministic" | "nli" | None
    reason: str
    signals: dict


def verify(
    existing_facts: list[str],
    new_capture: str,
    classification: str,
    *,
    use_nli: bool = False,
    nli_threshold: float = 0.55,
) -> VerificationResult:
    """Return a flag if this classification looks like a mislabelled retraction.

    `flagged=False` means "verification found nothing" — not "verified correct".
    """
    if classification not in RISKY_LABELS:
        return VerificationResult(False, None, "classifier label already routes to review", {})

    det = deterministic.check(new_capture, classification)
    if det.flagged:
        return VerificationResult(True, "deterministic", det.reason, {"cues": det.cues})

    if not use_nli:
        return VerificationResult(False, None, "deterministic pass; NLI disabled", {})

    try:
        from src.verify import nli_check
        res = nli_check.check(existing_facts, new_capture, classification, threshold=nli_threshold)
    except Exception as e:  # noqa: BLE001
        # Fail safe: an unavailable NLI model must not let an unverified auto-apply through.
        return VerificationResult(
            True, "nli-error", f"NLI stage unavailable ({e!r}); routing to review to be safe", {})
    if res.flagged:
        return VerificationResult(
            True, "nli", res.reason,
            {"contradiction_score": res.contradiction_score, "per_fact": res.per_fact,
             "latency_s": res.latency_s})
    return VerificationResult(
        False, None, res.reason,
        {"contradiction_score": res.contradiction_score, "latency_s": res.latency_s})
