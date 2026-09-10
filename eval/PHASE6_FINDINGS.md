# Phase 6 — verification findings

Goal: a post-classification check that catches the one classifier failure that silently corrupts
the semantic tier — a NEW capture that **retracts** an existing fact as wrong-when-made (truth =
`contradiction`, must go to review) which the classifier labelled `update` / `context_dependent_both`
/ `new` and would auto-apply. `PHASE2_V2_BASELINE.md` established this is a **general** failure
mode (recall ~2/9 on the category), not a quirk of the original costly-4.

Build: `src/verify/` — `deterministic.py` (stage 1, lexical), `nli_check.py` (stage 2, CPU MNLI),
`__init__.verify()` (orchestrator). Wired into `src/consolidate/run.py`: a flagged `SUPERSEDE`
or `DUAL_RETAIN` decision is downgraded to `REVIEW` with a `verifier_flag` in its justification.
Never auto-corrects. `recall consolidate run --verify/--no-verify` (default on).

Eval: `eval/verification_set/verification_set.yaml` (28 cases, regenerable via
`eval/verification_set/generate.py`), scored by `eval/run_verification.py`.

Verification-set composition:
- **flag (8)** — known classifier failures the verifier must catch: batch-1 costly-4 (`ex_003`,
  `ex_023`, `ex_040`, `ex_044`), batch-2 analogues (`ex_051`, `ex_052`, `ex_069`), 1 Haiku SEV1
  (`ex_037`). The batch-1 vs batch-2 split is the generalisation test.
- **pass (18)** — must NOT flag: `ex_053` (softened-not-retracted, the finer distinction) + 17
  correctly-classified high-confidence `update`/`both` cases (false-positive test).
- **detect (2)** — `ex_047`, `ex_050`: classifier already said `contradiction`, so the verifier
  never runs on them in production; kept only to probe the raw NLI signal.

---

## Shipped: deterministic stage only

Lexical first-person-retraction cues (`I was wrong`, `I should have been harder`, `presented X
as evidence of absence`, `was oversold`, `that's wrong`, `the direction is backwards`, …), with
a guard so a softened-but-retained judgment (`"'extraordinary' is probably too strong, but still
a sharp thinker"`) does not fire.

| metric | value |
|---|---|
| **catch rate (flag set)** | **5/8 = 62%** |
| — batch-1 costly-4 | 2/4 (ex_003, ex_044) |
| — batch-2 new | **3/3** (ex_051, ex_052, ex_069) |
| — Haiku SEV1 | 0/1 |
| **false-positive rate (pass set)** | **0/18 = 0%** |
| — softened case ex_053 | correctly not flagged |
| latency / call | regex, no model — sub-millisecond |

**Generalisation: catch rate on the batch-2 cases (3/3) is *higher* than on the original
costly-4 (2/4).** The verifier is not pattern-matching the four original cases — the cue set is
generic first-person retraction language and it fires on the new phrasings at least as well.

Misses (silent-corruption risk remains for these shapes):
- **ex_023** — "Company laptop is off-limits for personal projects due to IP-assignment risk."
  A flat factual constraint that happens to kill a prior plan. No retraction language.
- **ex_040** — design-doc claim vs. what a module actually does. No retraction language.
- **ex_037** — an evolutionary analogy that implicitly conflicts. No retraction language.

These have no lexical signal by construction — they need semantic reasoning the deterministic
stage cannot do. That is what the NLI stage was meant to cover.

---

## Evaluated and NOT shipped: the NLI stage

`nli_check.py` — `roberta-large-mnli` (355M, CPU), P(contradiction) between each stored fact and
the capture, both directions, max. Default `use_nli=False`.

**It does not work for this task.** The NLI contradiction score does not separate a retraction
from a normal supersession — because a normal supersession *is* a textual contradiction of the
prior fact ("the old one was true, now isn't"). The must-pass supersessions score **higher** on
P(contradiction) than the must-flag retractions:

```
must   source   P(contradiction)
flag   ex_044   0.97
flag   ex_003   0.94
flag   ex_040   0.90
flag   ex_037   0.80
flag   ex_069   0.65
flag   ex_052   0.64
flag   ex_023   0.35   <- real retraction, lowest score in the flag set
pass   ex_039   1.00   <- correct update, highest score of all
pass   ex_017   1.00
pass   ex_006   0.99
pass   ex_001   0.98
pass   ex_020   0.95
pass   ex_070   0.88
```

Threshold sweep (deterministic OR nli>=t):

| threshold | catch (flag) | FP (pass) |
|---|---|---|
| 0.55 | 7/8 | 11/18 = 61% |
| 0.80 | 6/8 | 8/18 |
| 0.90 | 5/8 | 6/18 |
| 0.99 | 5/8 | 4/18 |

No threshold is usable: at 0.55 the NLI stage adds 2 catches (ex_040, ex_037) but flags 61% of
correct updates — a worse autonomy collapse than the failed Phase 2 prompt fix. Tightening the
threshold removes the 2 extra catches before it removes the false positives.

**Why:** the retraction-vs-supersession distinction is about whether the prior fact was *ever*
true, which needs world knowledge and epistemic judgement — the exact reasoning the Tier-3
classifier itself already failed at (`PHASE2_FINDINGS.md`). It is not a textual-entailment
distinction, so an NLI model cannot draw it. AlignScore (single 0-1 alignment score) would be
strictly worse — it cannot even tell contradiction from unrelated.

NLI-stage latency (measured, for the record): first call ~150 s (model load + JIT), warm calls
~0.18–0.33 s per fact-pair, ~0.7–1.3 s per capture. Acceptable for an offline stage — accuracy,
not speed, is why it is off.

---

## Net position

- The verifier catches **62% of the known-failure set at 0% false positives**, for free, and
  generalises to the second batch of the same error type.
- It does not catch retractions that carry no first-person language (ex_023, ex_040, ex_037).
  For those, and for the residual SEV1 rate generally, the mitigation stays: the classifier's
  own `contradiction` predictions route to review, and the human review queue exists.
- NLI is a dead end for this specific check. If Phase 6 is revisited, the lever is a
  purpose-built classifier ("is the new capture retracting the prior fact as an error, or
  superseding it?") trained on the correction-data loop (`corrections/`), not an off-the-shelf
  entailment model.

Not a "Phase 6 done, silent corruption solved" claim — it is a partial, zero-false-positive
mitigation with a clearly measured ceiling.
