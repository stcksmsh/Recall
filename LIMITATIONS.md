# Known limitations

Recall's product claim is "never wrong *silently*." This file is where the known ways it can still
be wrong are written down, so the claim stays honest.

## The retraction blind spot (Phase 6 verifier)

**What can get through:** a new capture that retracts an existing fact as *wrong when it was
made* — which should go to a human review queue — can instead be auto-applied as a normal
`update` (silently invalidating the old fact) if **both** of these hold:

1. the classifier mislabels it `update` / `context_dependent_both` **with confidence ≥ 0.90**, and
2. the capture is phrased **without a first-person lexical retraction cue** — no "I was wrong",
   "I overstated", "I should have been harder on that", "presented X as Y", etc.

The shipped deterministic verifier (`src/verify/deterministic.py`) is a lexical cue matcher. It
catches retractions phrased as self-correction. It does **not** catch a retraction phrased as a
flat factual statement ("Actually the number is 5%", "That hardware isn't available") when the
classifier is also confident it's a routine update. The NLI stage that was meant to cover this
was built, evaluated, and **not shipped** — see `eval/PHASE6_FINDINGS.md`.

**Measured exposure today:** on the 76-case real corpus, this exact combination occurs **zero**
times — every one of the 7 SEV1 cases is stopped, 6 by the confidence gate and 1 by the verifier
(`eval/COMBINED_CORRUPTION.md`). But:

- the 6 gate catches are not structural — nothing forces a misclassified retraction to score
  below 0.90, and the classifier already scored `ex_044` at 0.92 on a mistake;
- the 1 verifier catch (`ex_044`) is against a cue authored with that case in view, so it is weak
  evidence the check generalises.

So the true rate is "0/76 on this corpus, not 0 by construction."

**Related gap:** a truth-`contradiction` capture that the classifier labels `new` is written as a
fresh fact with no gate and no verifier (`WRITE_NEW` is additive). It does not corrupt the old
fact, but it does leave the wrong-when-made fact in the store uncorrected. The 76-case confusion
matrix shows 1 such case.

## Path to closing it

Not a prompt tweak — three variants of a targeted classifier prompt fix were already falsified on
real data (`eval/PHASE2_FOLLOWUP_FINDINGS.md`). The plan is to accumulate real retraction
corrections from actual usage (`wire-phase7-correction-log`) and then revisit a purpose-built
retraction check trained on that data (`retraction-classifier-revisit`) — not before, because
there is no non-synthetic training signal yet.

## Retrieval: lexical collision and entity anchoring (retrieval-precision-at-scale)

**What can get through:** `search()` (`src/retrieve/hybrid.py`) is pure lexical matching (BM25 +
TF-IDF cosine, no semantic embeddings — a deliberate v1 simplification, see the module docstring).
When two facts in the real corpus are topically unrelated but happen to share one rare content
word (e.g. "threshold" used once in a Recall-architecture note and once in an unrelated
philosophy-of-mind note, 2 of 121 real facts total), BM25's IDF weighting can rank the wrong fact
#1 — a single rare-term match can outweigh a genuinely relevant fact matching several more common
terms. Confirmed on the real corpus; see `eval/RETRIEVAL_PRECISION_AT_SCALE.md` Part 2.

This is different from (and found while investigating) the dilution/padding bug the task was filed
to fix — that one is fixed: `search()` no longer pads its result set with near-random facts from
unrelated topics for the general case. This lexical-collision case is a real, narrower miss that
survives the fix, and needs real (semantic) embeddings to close — no purely lexical scoring change
can distinguish two unrelated uses of the same word.

**Entity/scope anchoring has never engaged in production.** BUILD_PLAN.md's intended *primary*
retrieval path (`src/retrieve/entity_scope.py`) is confirmed still a pass-through: 100% of real
facts have `entity="unsorted"`, `scope=null`, and nothing in the write path or CLI ever populates
or supplies a real value automatically — hybrid similarity search has carried 100% of real
retrieval load alone. Not the cause of the padding/dilution bug (that reported query contained no
named entity to anchor on either way), but a real structural gap worth closing eventually — a
cheap heuristic (proper-noun/capitalized-term extraction, or `scope` as a controlled vocabulary)
was considered and not built here, since `scope` currently has zero real values to match against
and it would not have fixed the case that prompted this investigation.

## Classifier accuracy generally

The write-time classifier runs at ~60% on the 76-case real set (`eval/PHASE2_V2_BASELINE.md`),
roughly the general ceiling for this task. The 0.90 confidence gate and the review queue exist
because the classifier is *expected* to be wrong often; autonomy is earned per-decision by
measured confidence, not assumed.
