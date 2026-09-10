# Recall

A self-maintaining AI memory system: plaintext-first, recoverable by construction, honest about
what it doesn't know.

The product is not "AI second brain." The product is **the memory layer that doesn't lie to you.**

Two claims:

1. **Cost-discipline and anti-rot are the same system.** Expensive reasoning happens once, at
   write time (consolidation), amortized over many cheap reads. A clean store is what makes cheap
   retrieval sufficient most of the time.
2. **We don't claim to never be wrong. We claim to never be wrong silently, and to never lose
   ground truth.** Every write is derived from an immutable, recoverable source. Autonomy is
   earned via measured confidence, not assumed.

We don't claim to solve memory rot. We claim to never be wrong without telling you, and to get
measurably better at not being wrong over time — because every correction is data, and every
mistake is recoverable by construction.

See `ARCHITECTURE.md` for the full design (three-tier memory model, write-time conflict
classification, blast-radius containment) and `BUILD_PLAN.md` for repo structure, model/library
choices, and phased build scope.

## Status

Phases 0–7 of `BUILD_PLAN.md` §6 are implemented, plus the Phase 2 follow-up. Phase 6 is partial.

- **Phase 0–1 — episodic + index round-trip.** `recall capture` and `recall index build` work; the
  rebuild guarantee (`rm -rf brain/.brainindex && recall index build` → equivalent index) is
  verified by the test suite.
- **Phase 2 (+ follow-up) — classifier eval loop.** Run in isolation against a hand-labelled
  76-case real corpus. Measured accuracy 60.5%, below the 65.3% general ceiling; a prompt fix and a
  cheaper model were both tried and neither beat baseline (`eval/PHASE2_*_FINDINGS.md`). This is why
  the default auto-apply confidence threshold is a conservative 0.9.
- **Phase 3 — consolidation loop.** The classifier proposes; a deterministic executor is the only
  thing that writes the semantic tier. Sub-threshold decisions go to a review queue.
- **Phase 4 — retrieval.** Entity/scope-anchored retrieval, hybrid BM25 + vector fusion, 1–2 hop
  graph expansion, and a sufficiency gate. No model calls on this path.
- **Phase 5 — injection + provenance.** Retrieval output formatted into XML-tagged, authority-framed
  fact blocks, each stamped with the commit hash it was derived from.
- **Phase 6 — verification (partial).** The deterministic lexical retraction check is shipped and
  wired into `consolidate run`: a flagged decision is downgraded to review, never auto-corrected.
  The NLI stage was built and evaluated but **not shipped** — see `eval/PHASE6_FINDINGS.md`. Its
  blind spot (a confident retraction with no first-person lexical cue) is documented in
  `LIMITATIONS.md`; combined gate+verifier exposure is 0/76 on the real corpus
  (`eval/COMBINED_CORRUPTION.md`), not 0 by construction.
- **Phase 7 — correction data loop.** Every review accept/override is logged as a labelled example
  (`facts_in`, `classification_given`, `confidence_given`, `correct_classification`).
- **Phase 8 (partial) — CLI polish.** `recall status` prints a read-only store snapshot; the
  review-queue commands show the conflicting fact and resolution hints. Broader UX polish is
  ongoing.

## Usage

```
recall capture "<text>"              # write an episodic capture — instant, no model/network calls
recall capture --file NOTES.md       # ...or capture from a file (omit the arg entirely to read stdin)
recall index build                   # rebuild the SQLite index from brain/episodic/ + brain/semantic/
recall consolidate run               # classify not-yet-consolidated captures; auto-apply above
                                     #   --confidence-threshold (default 0.9), else queue for review.
                                     #   one classifier API call per capture; --verify (default on)
                                     #   runs the lexical retraction check.
recall review list                   # list pending review-queue items
recall review accept <id>            # confirm the classifier's call and apply its action
recall review override <id> <class>  # apply the correct classification instead
                                     #   (new|update|contradiction|context_dependent_both)
recall retrieve "<query>"            # read path: format stored facts for a query, no model calls
                                     #   --entity / --scope to filter
recall status                        # read-only store snapshot: capture/fact/review/correction counts
```

Run `recall --help` for the command list.
