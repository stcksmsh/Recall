"""Deterministic verification (Phase 6, stage 1). Cheapest check, runs first, no model call.

Purpose: catch the one classifier failure that silently corrupts the semantic tier — a NEW
capture that *retracts* an existing fact as wrong-when-made (truth = "contradiction", must go to
review) but which the classifier labelled "update" / "context_dependent_both" / "new" and would
therefore auto-apply. See eval/PHASE2_V2_BASELINE.md: this is a general, ~consistent failure
mode, not a quirk of a few cases.

Signal: first-person error-admission and flat-repudiation phrasing in the capture. This is a
lexical heuristic, deliberately narrow. It fires on "I was wrong", "I should have been harder",
"presented X as evidence of absence", "that's wrong", "was oversold" — and deliberately does NOT
fire on a softened-but-retained judgment ("'extraordinary' is probably too strong, but still a
sharp thinker"), which is a real `update`. BUILD_PLAN.md 2.5: "catches the worst failures for
~free"; the NLI stage (src/verify/nli_check.py) covers what this misses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Classifier labels that auto-apply to the semantic tier (so a wrong one corrupts it silently).
# `contradiction` already routes to review, so a decision that already says contradiction needs
# no verification here.
RISKY_LABELS = frozenset({"update", "context_dependent_both", "new"})

# Ordered strongest-first. Each entry: (name, compiled regex). Case-insensitive.
_CUES: list[tuple[str, re.Pattern[str]]] = [
    ("flat-repudiation", re.compile(
        r"\b(that'?s|this is|it'?s|that was) (just |simply |flatly |plainly )?wrong\b"
        r"|\bis (just |simply |flatly )?wrong\b"
        r"|\bnot (actually |really )?true\b"
        r"|\bfalse (opposition|premise|assumption|dichotomy)\b"
        r"|\bdirectly conceded (as )?false\b"
        r"|\bthe direction is backwards\b"
        r"|\bis backwards\b"
        r"|\bcannot be (right|correct)\b", re.I)),
    ("self-admitted-error", re.compile(
        r"\bi (was|were) wrong\b"
        r"|\bi should (have|'?ve) been (harder|more careful|more rigorous|tougher)\b"
        r"|\bi should be more careful\b"
        r"|\bi can'?t actually (search|verify|know|check)\b"
        r"|\bi presented .{0,60}?as evidence of absence\b"
        r"|\bi gave it more .{0,30}?than it deserved\b"
        r"|\bi (over-?sold|over-?stated|over-?rated|inflated) (it|that|this)\b"
        r"|\bnever (my|the author'?s|actually my) (position|claim|view)\b", re.I)),
    ("retracted-as-inflated", re.compile(
        r"\bwas over-?sold\b"
        r"|\bwas over-?stated\b"
        r"|\bwas inflated\b"
        r"|\bgave it more (epistemic |credit|weight).{0,20}?than it deserved\b"
        r"|\bdressed up in (clean )?notation\b"
        r"|\bmore epistemic weight than it deserved\b", re.I)),
    ("premise-rebuttal", re.compile(
        r"\bthe (realistic|honest|actual) .{0,20}?is\b.{0,120}?\bnot\b"
        r"|\bno (strategic|real) (reason|incentive|basis)\b"
        r"|\brests on a false\b"
        r"|\bmischaracteri[sz]", re.I)),
]

# Guards against firing on a *softened but retained* judgment (a real update, not a retraction).
_SOFTENING_ONLY = re.compile(
    r"\b(probably |maybe |perhaps )?too strong\b"
    r"|\bless (rare|common|impressive) than (implied|stated|it sounded)\b"
    r"|\bmight be (less|more) \w+ than\b", re.I)


@dataclass
class DeterministicVerdict:
    flagged: bool
    reason: str = ""
    cues: list[str] = field(default_factory=list)


def check(new_capture: str, classification: str) -> DeterministicVerdict:
    """Flag if the capture reads as a retraction of a prior fact yet the classifier gave it an
    auto-applying label. Passing (`flagged=False`) means "nothing this stage can catch"."""
    if classification not in RISKY_LABELS:
        return DeterministicVerdict(False, "classifier label is not auto-applying")

    hits = [name for name, rx in _CUES if rx.search(new_capture)]

    # Softening-only phrasing with no first-person error admission: a recalibration, not a
    # retraction. Don't flag.
    if _SOFTENING_ONLY.search(new_capture) and "self-admitted-error" not in hits \
            and "flat-repudiation" not in hits:
        hits = [h for h in hits if h != "retracted-as-inflated"]

    if not hits:
        return DeterministicVerdict(False, "no retraction cue")

    return DeterministicVerdict(
        True,
        f"retraction cue(s) present while classifier said '{classification}': {', '.join(hits)}",
        hits,
    )
