# Recall — Architecture & Design Decisions

A self-maintaining AI memory system: plaintext-first, recoverable by construction, honest about
what it doesn't know. This doc is the single reference for all standing architecture and CS
decisions — not a timeline, not a task list. Update it when a decision changes; don't let it drift
from what's actually built.

---

## 0. Core Thesis

Two claims, stated precisely so we don't overclaim later:

1. **Cost-discipline and anti-rot are the same system.** Expensive reasoning happens once, at
   write time (consolidation), amortized over many cheap reads. A clean store is what makes cheap
   retrieval sufficient most of the time.
2. **We don't claim to never be wrong. We claim to never be wrong silently, and to never lose
   ground truth.** Every write is derived from an immutable, recoverable source. Autonomy is
   earned via measured confidence, not assumed.

The product is not "AI second brain." The product is **the memory layer that doesn't lie to you.**

---

## 1. Three-Tier Memory Model

Directly modeled on memory consolidation (hippocampus → sleep consolidation → neocortex), used as
a systems analogy, not a claim that we've reproduced neural representation.

### Tier 1 — Episodic (capture)
- Raw plaintext Markdown. **Append-only. Never edited, never deleted.**
- Timestamped, cheaply embedded on write (cheap model / local embedding model — no reasoning
  needed here).
- This is ground truth. Every other tier is derived from this and must be re-derivable from it.
- Directory-of-files, one capture per file or append-log style — TBD, doesn't affect anything
  downstream as long as it stays immutable and timestamped.

### Tier 2 — Semantic (consolidated)
- Deduplicated, linked, temporally-stamped facts.
- **Dual representation, not a choice between them:**
  - **Source of truth: plaintext Markdown + YAML frontmatter**, Git-versioned. Human-legible,
    diffable, "cat it if we vanish" stays literally true.
  - **Derived index: SQLite (or DuckDB/Kùzu if graph queries dominate)**, rebuilt deterministically
    from the MD. Never holds information the MD doesn't have. Exists purely for: transactional
    multi-fact writes during consolidation, fast conflict-candidate lookups, referential integrity.
  - Round-trip contract: `index = build(markdown)` and `markdown ← flush(index_transaction)`. The
    DB is disposable; `rm index.db && rebuild` must always work and must be a tested operation, not
    an assumption.
- This is what the read path actually hits.

### Tier 3 — Consolidation loop
- Offline/batched process. Strong model. The only place expensive reasoning happens.
- Reads recent episodic captures, integrates into semantic tier.
- Triggers (hybrid, not purely scheduled — see §4):
  - Scheduled batch pass (new episodic captures since last run).
  - **Recall-triggered re-integration**: a read that surfaces a mismatch/competing fact enqueues
    that node-pair for the next batch pass (reconsolidation-inspired). Gated by a cheap novelty/
    mismatch check so this doesn't fire on every read.
- Must be **incremental and blast-radius-bounded** — see §5. Never a full-graph rescan.

---

## 2. The Crux: Write-Time Conflict Classification

This is the actual hard problem. Everything else in this doc is standard engineering; this is not.

### The decision
When a new fact is integrated, classify its relationship to existing semantic facts as one of:
- **Contradiction** — mutually exclusive, one is wrong or outdated with no valid shared context.
- **Update / supersession** — new fact replaces old; old becomes historically-valid-until-X, not
  false.
- **Context-dependent-both** — both hold, scoped to different contexts (e.g. "prefers Python" /
  "uses TypeScript at work" — not a conflict, a scope problem).

### Known ceiling (as of research, cite before assuming this has moved)
- Best published model (Gemini 2.5 Flash) on explicit three-way classification: **65.3%**
  (CONFLICTS benchmark).
- Implicit conflicts requiring inference: as low as **17.6%** even when models are explicitly told
  to look for contradictions.
- Weak/non-reasoning models on this task can collapse hard (observed: 1/9 correct on a small
  eval) — **reasoning-capable model is not optional for this step.**

### Architectural response — split classification from execution
- **Classifier (probabilistic):** LLM call, strong/reasoning model, emits `{classification,
  confidence, reasoning}`. This is the only place we let the model "decide" anything.
- **Executor (deterministic):** given a classification + confidence, applies the mechanical
  consequence — bitemporal invalidation for supersession, dual-retention with scope tags for
  context-dependent-both, flag for contradiction. No judgment happens here; it's a lookup table.
- **This split is the actual IP**, to the extent there is any. Not the fact that we use an LLM —
  everyone does. The fact that we don't let the LLM both judge and act unsupervised.

### Confidence-gated autonomy (not binary human-in-loop vs. not)
- High confidence → auto-apply, logged with justification.
- Low/mid confidence → review queue (human, or a second stronger-model pass, or both).
- **The threshold is tunable, not fixed** — see §6 (review breadth as a product knob).
- Threshold should move over time based on **measured revert rate**, not a one-time guess. This
  requires the eval/correction loop (§7) to exist from day one — retrofitting it loses all early
  signal.

### Why aggressive autonomy is safe here specifically
Because Tier 1 is immutable, a wrong auto-applied classification is a `git revert` + re-derive from
episodic, not permanent data loss. This is the thing no reviewed competitor (Mem0, Zep, Cognee)
structurally has — they either don't have a clean immutable backstop, or they retreated to
append-only specifically because overwriting was unsafe without one. **Exploit this explicitly**:
it's the reason we can set the autonomy threshold higher than they safely can, and it should be
stated in the pitch, not buried in the architecture.

---

## 3. Formal Machinery to Reuse (don't reinvent)

These are solved subfields; use them as backend plumbing, not as the classifier.

- **Bitemporal validity** (SQL:2011 pattern — `valid_at`/`invalid_at` for real-world truth,
  `created_at`/`expired_at` for system knowledge). Fully solved, decidable. Every fact in Tier 2
  carries both. This is the executor's primary tool for supersession.
- **Truth Maintenance Systems (JTMS/ATMS)** — justification tracking for *why* a belief holds, and
  dependency-directed retraction when a justification is invalidated. Use the *pattern*
  (every write logs its justification chain) even if we don't import a full TMS implementation.
  ATMS's multi-context model is the direct formal analog for context-dependent-both — both facts
  live in different assumption contexts rather than competing for one slot.
- **AGM belief revision** (expansion / revision / contraction, Levi identity) — informs *what a
  rational retraction looks like* (minimal change, preserve consistency). Doesn't replace the
  classifier; the classifier decides *that* revision is needed, AGM-style postulates inform *how*
  the executor does it cleanly.
- **Explicitly not reusable as-is:** these formal systems assume clean logical negation (`p` vs.
  `¬p`). LLM-extracted natural language facts aren't formally negated statements. The
  classifier's job is precisely to bridge this gap — translate messy language into a decision the
  deterministic backend can execute on. (Neurosymbolic pattern, à la Logic-LM: LLM → symbolic form
  → deterministic solver.)

---

## 4. Trigger & Scheduling Design

- **Cheap capture, no gating.** Anything can always be written to episodic instantly. Never block
  on classification.
- **Batch consolidation**, scheduled (e.g. nightly, or on N-new-captures threshold) — this is where
  the strong model runs, and it's the natural fit for batch API pricing (~50% off).
- **Recall-triggered re-integration** — reading a node that surfaces a mismatch enqueues it for the
  *next* batch pass rather than triggering an immediate synchronous model call. Keeps reads cheap
  and non-blocking; keeps the reconsolidation-inspired benefit without the cost.
- **Novelty/mismatch gate before enqueueing** — cheap heuristic (embedding distance threshold,
  or simple keyword/entity overlap check) decides whether something is even a candidate conflict
  before it costs a model call. Most reads should not trigger anything.

---

## 5. Blast-Radius Containment (consolidation cost control)

The failure mode to design against from day one: consolidation cost growing faster than linear as
the graph grows (naive "compare new fact against everything" is O(n²) and will eventually make the
whole cost thesis collapse).

- **Hard-capped candidate neighborhood per write** — top-K nearest by embedding + entity/scope
  filter, never a global scan. K is a tunable constant, not "as many as seem relevant."
  is the container.
- **Incremental entity resolution with periodic repair**, not full rebuilds — cluster
  incrementally as facts arrive, run a cheap periodic consistency pass rather than reprocessing
  everything each time.
- **Interference awareness**: LLMs measurably degrade at correctly integrating a new fact when
  the surrounding context contains many similar prior facts (proactive-interference-style
  failure). This is a second, independent argument for keeping the classifier's context window
  narrow and deduplicated — not just a cost optimization, a correctness one.

---

## 6. Product-Facing Knobs (design these as first-class, not afterthoughts)

- **Confidence threshold** — how aggressively auto-apply vs. queue for review. Directly trades
  safety/data-quality against autonomy and API spend.
- **Review breadth by scope** — user can declare some domains high-stakes (review everything) and
  others low-stakes (auto-apply liberally). This turns the unsolved "scope modeling" research gap
  into a feature: the human declares scope boundaries instead of the system inferring them
  perfectly.
- **Classifier backend selection** — hosted API (default, higher reliability, matches the research
  ceiling) vs. local model (user-supplied endpoint, lower confidence expected, review threshold
  should auto-widen to compensate). Never silently degrade quality without surfacing it.
- **Spend visibility** — review breadth and backend choice should show projected/actual cost, not
  be an abstract dial.

---

## 7. Correction Data Loop (build this from day one, not later)

Every human override, edit, or revert of a consolidation decision is a labeled training example:
`(facts_in, classification_given, confidence_given, correct_classification)`. This is the
compounding asset — the thing that could make the classifier measurably improve with usage, which
nothing else in the space currently captures cleanly.

- Must be structural in the data model from v0, not bolted on — retrofitting loses all early
  signal.
- **Local-first, opt-in aggregate contribution.** Corrections stay local by default; contributing
  them to improve a shared/hosted classifier is an explicit opt-in, not a default-on telemetry
  pattern. This is a trust product — an extractive-feeling data mechanism undermines the entire
  pitch.

---

## 8. Open/Closed Boundary (if this becomes more than OSS-for-its-own-sake)

Decided direction, revisit only if goals change:

- **Architecture: fully open (OSS).** Storage model, consolidation loop, executor logic, v0
  classifier and prompts — all public, forkable, MIT/Apache-style. This is the reputational/
  portfolio asset regardless of what else happens.
- **Post-launch compounding asset: closed by default.** The correction dataset and any
  fine-tuned/improved classifier that results from aggregate usage stay private (hosted service).
  This is reversible in one direction only — closed-then-open is trivial (just publish later),
  open-then-closed is nearly impossible once a community expects it. **Default closed on this now.**
- This does not conflict with the OSS release being genuinely complete and useful — v0 ships with
  a working, honestly-mediocre-per-the-research-ceiling classifier. Nothing is crippled or held
  back to force upgrade.

---

## 9. What's Actually Novel Here (keep this honest, revisit as competitors move)

- **Not novel:** LLM + markdown/vector store + agents. This is Khoj's whole pitch and they're
  ahead, funded, and further along. Don't compete here.
- **Not novel:** hybrid vector+graph retrieval, temporal knowledge graphs. Zep/Graphiti already
  does bitemporal edges well.
- **Actually novel (as of this research pass):** the explicit split of classification (model,
  probabilistic, confidence-scored) from execution (deterministic, bitemporal, logged), combined
  with a genuinely immutable, re-derivable ground truth tier. No reviewed competitor does both;
  most either let one model call both judge and silently act (Mem0's original design, Zep,
  Cognee), or retreated to append-only specifically because they lacked a safe recovery story
  (Mem0's actual pivot).
- **The pitch, precisely:** "We don't claim to solve memory rot. We claim to never be wrong
  without telling you, and to get measurably better at not being wrong over time — because every
  correction is data, and every mistake is recoverable by construction."

---

## 10. Explicitly Deferred / Not Yet Decided

- Exact DB choice for the index tier (SQLite vs. DuckDB vs. Kùzu) — depends on how graph-heavy
  queries end up being in practice; don't over-decide before building.
- Whether episodic capture is one-file-per-entry or an append-log — doesn't block anything else.
- Exact eval set methodology for the classifier (size, sourcing, labeling process) — needs its own
  short design pass before the classifier work starts, not decided here.
- Local model classifier support — planned as an option (§6) but not scoped in detail yet.

---

## 11. Build Order (sequencing logic, not a timeline)

1. **Episodic tier** — append-only MD capture. Trivial, do first, unblocks everything.
2. **Semantic tier schema** — bitemporal MD frontmatter + the index round-trip contract
   (`build`/`flush`). This is "boring but load-bearing" — get the round-trip correct before
   anything depends on it.
3. **Classifier eval loop** — hand-labeled contradiction/update/context-dependent-both set from
   real notes (30-50 examples is enough for initial signal), test classification accuracy in
   isolation, *before* wiring it into the rest of the system. This is the one piece with genuine
   uncertainty — treat it as its own mini-project with its own iteration loop, not "one more
   function" in the main build.
4. **Executor** — deterministic lookup-table logic consuming classifier output. Standard once §2/§3
   above are settled.
5. **Consolidation loop wiring** — batch trigger + recall-triggered enqueue (§4), blast-radius
   containment (§5).
6. **Correction capture** — wire logging of overrides/reverts into the data model (§7) — do this
   alongside step 5, not after, since it needs to exist before real usage generates signal worth
   keeping.
7. **Product knobs** (§6) — confidence threshold, scope-based review breadth, backend selection —
   once the core loop works end-to-end.
