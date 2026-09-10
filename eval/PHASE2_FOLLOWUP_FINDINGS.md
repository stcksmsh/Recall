# Phase 2 follow-up — prompt fix attempt + cheaper-model comparison

Companion to `PHASE2_FINDINGS.md`. Same harness (`eval/run_eval.py`), same 46-case real set
(`eval/classifier_set/real_examples.yaml`), same 22 `[HARD CASE]` markers. All runs are one real
inference call per example — no mock.

Two things were tried here:

1. Revise the classifier prompt to fix the dominant Phase 2 error (update ↔ contradiction).
2. Run the eval against cheaper models (Claude Haiku 4.5, a local CPU 7B).

**Bottom line up front:**
- The prompt fix, in three variants, is a **net regression** on this set. It is **not shipped**;
  `classifier.py` keeps the Phase 2 baseline prompt. Only the `parse_response` refactor is kept.
- Haiku 4.5 and the local 7B are **both materially worse** than Sonnet 5, with a **higher, more
  confident silent-corruption rate**. No model switch is recommended.

---

## Baseline (this session's re-run, for apples-to-apples)

Sonnet 5, Phase 2 prompt. Re-run because model output is non-deterministic and the Phase 2
`results_*.json` was not retained.

| | overall | hard (22) |
|---|---|---|
| this re-run | 27/46 = **58.7%** | 11/22 = **50.0%** |
| Phase 2 doc | 28/46 = 60.9% | 12/22 = 54.5% |

Run-to-run variance is ~2 points. Baseline confusion (rows expected, cols predicted):

```
                          new  update  contra  both  tot
new                        7      1       0      0    8
update                     0     10       5      1   16
contradiction              1      3       3      1    8
context_dependent_both     1      4       2      7   14
```

Four costly cases (Phase 2 SEV1 — wrong `update`/`both` at high confidence, truth
`contradiction`): **ex_003, ex_023, ex_040, ex_044 — all four wrong in the baseline re-run too.**

---

## 1. Prompt fix — three variants, all net-negative

The idea (from `PHASE2_FINDINGS.md`): make the model answer, per the JSON contract, whether the
prior fact was *valid when recorded and later superseded* (`update`) or *wrong from the start*
(`contradiction`), via a required `prior_fact_was_valid_when_recorded: true|false` field, and wire
`false` toward `contradiction`.

| variant | what changed | overall | hard | fixed vs baseline | regressions | SEV1 |
|---|---|---|---|---|---|---|
| **A** | full STEP 1 / STEP 2 rewrite, strong "false ⇒ contradiction" | 18/46 = 39.1%¹ | 12/22 = 54.5% | 3 | 12 | 0 |
| **B** | narrow `false` definition, rewritten class defs, `max_tokens` 1024 | 23/46 = 50.0% | 10/22 = 45.5% | 5 | 9 | 2 |
| **C** | baseline prompt + STEP 1 field only + deterministic guard (`false` + `update`/`both` → `contradiction`) | 23/46 = 50.0% | 14/22 = 63.6% | 7 | 11 | 3 |

¹ variant A also produced 3 hard JSON-truncation errors (the added reasoning blew past
`max_tokens=512`); even scoring those as "not wrong", it is 18/43 = 41.9%.

### Why it fails

Making the model reason explicitly about "was the prior fact valid" **reweights its entire
classification distribution**, not just the target boundary:

- Variant A/B: real `update` cases collapse into `contradiction` (A: 11 of 16 `update` →
  `contradiction`). The model rationalises nearly every conceptual refinement ("B is not a
  prediction box, it's a workspace") as "the original framing was an overstatement / wrong from
  the start."
- Variant C: adding the STEP 1 question destroys `new` detection — **all 8 `new` cases →
  `context_dependent_both`**. Prompted to find "the single most-related existing fact" and judge
  its validity, the model stops concluding "no meaningful overlap."
- The deterministic guard (variant C) fired on 3 cases: it corrected ex_003 and ex_044, and
  **broke ex_006** (a real `update` the model had right). Net +1 on 46 cases — noise.

The four costly cases: variant C fixed ex_003 and ex_044 (both via the guard) but ex_023 and
ex_040 stayed wrong (the model rated their prior fact *valid*, so the guard never engaged), and
SEV1 was still 3 (ex_023, ex_037, ex_040).

### Decision

**Reverted.** `classifier.py` keeps the Phase 2 baseline prompt verbatim. The 46-case set does
not support any prompt-level fix, and every variant traded the target error for collateral
damage across the other three classes. The real backstop remains Phase 6 verification (as
`PHASE2_FINDINGS.md` already concluded); the confidence gate stays at 0.90.

Kept from this pass: `classifier.parse_response()` split out of `classify()` so the model
comparison below can feed local-model output through the identical parser.

---

## 2. Cheaper / local models — same baseline prompt, same 46 cases

### Claude Haiku 4.5 (`claude-haiku-4-5-20251001`), via API

Overall **20/46 = 43.5%**, hard 15/22 = 68.2%, easy 5/24 = 20.8%. Per-call latency ~3.4s.

```
                          new  update  contra  both  tot
new                        0      0       0      8    8
update                     0      5       8      3   16
contradiction              0      2       4      2    8
context_dependent_both     0      1       2     11   14
```

- **`new` is completely broken** — 0/8, all 8 → `context_dependent_both`. Haiku always finds a way
  two facts "operate at different levels of analysis."
- **SEV1 = 4**, all at **0.92–0.95 confidence** (ex_044 @ 0.95, ex_003 @ 0.92, ex_040 @ 0.92,
  +1). Higher and more confident than Sonnet's silent-corruption rate.
- Not the Graphiti "fails to attempt reasoning" collapse — Haiku reasons *verbosely* (200-word
  justifications). The failure is that it pattern-matches toward "both can be true" / "this is an
  update" instead of engaging with whether the store's owner would call it a genuine conflict.
- Only ex_023 of the four costly cases is fixed.

### Local — Qwen2.5-7B-Instruct, Q4_K_M GGUF, llama.cpp CPU

Hardware: 20-thread Intel, no GPU, 30 GB RAM (the target laptop). Model file 4.68 GB.
`n_ctx=4096`, `temperature=0`, `response_format=json_object`. Chosen as the pragmatic 7-8B
CPU option: single-file GGUF, strong instruction-following / JSON adherence, well-supported by
llama-cpp-python. `pip install llama-cpp-python` (CPU wheel) + `hf download`.

Overall **13/46 = 28.3%**, hard 4/22 = 18.2%, easy 9/24 = 37.5%.
**Per-call latency: min 11.2s / median 15.0s / max 18.6s** (689s wall for 46). ~40× slower per
call than the APIs, on top of being the least accurate.

```
                          new  update  contra  both  tot
new                        1      1       1      5    8
update                     0     10       6      0   16
contradiction              0      7       0      1    8
context_dependent_both     0      9       3      2   14
```

- **Valid JSON on all 46** — no parse failures. It follows the output contract.
- **It does attempt reasoning** — every response has a 1-2 sentence justification. This is *not*
  the "doesn't try" collapse. It is the *other* Graphiti failure mode: shallow, pattern-matched
  reasoning. Several justifications contradict their own label — ex_040: _"directly contradicts
  the existing fact … suggests the existing fact is no longer accurate"_ → predicts **update**.
- **`contradiction` recall is 0/8.** Every real contradiction was called `update` (7) or `both`
  (1). Contradiction detection is the one thing protecting the semantic tier, and this model
  cannot do it at all.
- **No confidence signal**: 40 of 46 predictions are exactly 0.90, one is 1.00, the rest 0.80.
  The gate cannot function — at 0.90 all 8 SEV1 errors still auto-apply.
- **SEV1 = 8** (worst of the three models by far).
- Costly cases: **0/4** fixed.

---

## Comparison table

| model | ~cost / call² | latency / call | full-set acc | hard-subset acc | costly-4³ | SEV1 |
|---|---|---|---|---|---|---|
| **Sonnet 5** (baseline) | ~$0.004 | ~2.9 s | **58.7%** | 50.0% | 0/4 | 3–4 |
| Haiku 4.5 | ~$0.0009 | ~3.4 s | 43.5% | 68.2%⁴ | 1/4 | 4 |
| Qwen2.5-7B Q4 (local, CPU) | $0 + ~15 s CPU | ~15 s | 28.3% | 18.2% | 0/4 | 8 |

² rough: ~700 in + ~150 out tokens. Sonnet 5 $3/$15 per Mtok → ~$0.004. Haiku 4.5 $1/$5 →
~$0.0009. Batch API would halve both; not applied here. At a realistic few-hundred
consolidations/month this is the difference between ~$1 and ~$0.25 a month — not decision-relevant.

³ how many of ex_003 / ex_023 / ex_040 / ex_044 (the Phase 2 silent-corruption cases) were
classified correctly.

⁴ Haiku's and Qwen's hard-subset numbers are a distribution artefact, not a capability: the hard
subset is 14/22 `context_dependent_both`, and both cheaper models are heavily biased toward a
non-`update`, non-`new` label. Haiku happens to land on `both`; on the easy subset (more `new`
and `update`) it scores 20.8%.

### Recommendation

**Stay on Sonnet 5. No model switch.**

- **Haiku 4.5**: ~4× cheaper, but −15 points full-set accuracy, **cannot classify `new` at all**
  (0/8), and produces *more* silent-corruption errors *at higher confidence* (0.92–0.95). That is
  precisely the trade `PHASE2_FINDINGS.md` said not to make, because the confidence gate is not a
  reliable backstop. The ~$0.75/month saved is not worth it.
- **Qwen2.5-7B local**: free in dollars, but 28% accuracy, 0/8 contradiction recall, no usable
  confidence signal, and 15 s/call on the target hardware. This is the research-predicted
  collapse for a weak model on write-time conflict classification. Confirms `BUILD_PLAN.md` §3's
  "no local classifier" call with local data. Keep it as a documented negative result, not a
  fallback.

Sonnet 5 at 58.7% / SEV1 3–4 is itself not good — but it is the best available, and the fix for
its residual silent-corruption risk is Phase 6 verification, not a cheaper model and not a prompt
tweak.
