# Build Plan — Recall

Companion to `ARCHITECTURE.md` (design decisions) and the two research reports (classification
ceiling; context-faithfulness/retrieval-completeness/provenance/verification). This doc is the
concrete "how do I actually build this" reference: repo layout, component-by-component design,
tool/library choices, cost model, and phased scope. No timelines — phases are ordered by
dependency and risk, not calendar time.

Constraints locked in: solo dogfood build, personal laptop only (32GB RAM, 20-thread Intel, no
GPU), CLI-first interface, API-based classification (no local classifier), CPU-local verification
model. Company laptop is out of scope entirely — not used for anything in this project.

---

## 1. Repo Structure

```
[project]/
├── brain/                        # the actual data store (this is what gets git-committed as the "memory")
│   ├── episodic/                 # Tier 1 — immutable, append-only captures
│   │   └── 2026/
│   │       └── 08/
│   │           └── 2026-08-26T14-30-00_capture.md
│   ├── semantic/                 # Tier 2 — consolidated facts, source of truth
│   │   └── facts/
│   │       └── <entity-or-topic>/
│   │           └── <fact-id>.md  # frontmatter + body
│   └── .brainindex/              # derived SQLite index — GITIGNORED, fully rebuildable
│       └── index.db
├── src/
│   ├── capture/                  # CLI commands for writing to episodic tier
│   ├── consolidate/              # the batch consolidation loop (Tier 3)
│   │   ├── classifier.py         # LLM call: contradiction/update/context-dependent-both
│   │   ├── executor.py           # deterministic: applies classification result
│   │   └── blast_radius.py       # candidate-neighborhood bounding (top-K + scope filter)
│   ├── retrieve/                 # read path
│   │   ├── entity_scope.py       # entity/scope-anchored retrieval
│   │   ├── graph_expand.py       # 1-2 hop link expansion
│   │   ├── hybrid.py             # BM25 + vector + RRF fusion
│   │   └── sufficiency.py        # "is this retrieval complete enough" gate
│   ├── inject/                   # context construction for the active session
│   │   ├── format.py             # XML-tagged fact injection, authority framing
│   │   └── provenance.py         # commit-hash tagging per injected fact
│   ├── verify/                   # cheap post-hoc check
│   │   ├── deterministic.py      # structured value-match check
│   │   └── nli_check.py          # MiniCheck/AlignScore wrapper, CPU-local
│   ├── index/                    # the MD <-> SQLite round-trip
│   │   ├── build.py              # markdown -> index (full rebuild)
│   │   └── flush.py              # index transaction -> markdown writes
│   └── cli.py                    # entry point, command dispatch
├── eval/
│   ├── classifier_set/           # hand-labeled contradiction/update/both examples (YOUR data)
│   ├── faithfulness_set/         # ClashEval-style injected-contradiction test cases
│   └── run_eval.py
├── pyproject.toml
└── README.md
```

Rationale for the shape: `brain/` is the actual product from the user's perspective — it should be
independently comprehensible if someone opens it with no code running (that's the whole "cat it if
we vanish" claim, made literal). Everything under `src/` is disposable tooling that operates on
`brain/`. `.brainindex/` is gitignored on purpose — proving it's genuinely rebuildable is a build
milestone, not an assumption (see §6, Phase 1).

---

## 2. Component-by-Component Design

### 2.1 Episodic capture (`src/capture/`)
- CLI command: `recall capture "<text>"` or `recall capture --file <path>` or piped stdin.
- Writes a new timestamped MD file under `brain/episodic/YYYY/MM/`. Filename includes ISO
  timestamp — sortable, unique, human-readable without opening the file.
- Frontmatter: `id`, `captured_at`, `source` (cli/import/etc). Body: raw text, untouched.
- **No model call on write.** This must be instant. Embedding for retrieval purposes happens
  lazily/async (a cheap local embedding model — see §3) or as part of the next consolidation pass,
  not synchronously in the capture path.
- Never edited after write. If a correction is needed, that's a *new* capture referencing the old
  one, not a mutation — this is the whole point of the tier.

### 2.2 Consolidation loop (`src/consolidate/`)
- Trigger: manual (`recall consolidate`) to start, cron/scheduled task once trustworthy. Also
  supports `recall consolidate --since <commit>` for incremental runs.
- **classifier.py**: for each new episodic capture, retrieve the top-K candidate existing facts
  (bounded neighborhood, see `blast_radius.py`), send one API call per capture (or batched — see
  §5 cost model) asking for `{classification: contradiction|update|context_dependent_both|new,
  confidence: 0-1, reasoning: str}`. This is the ONLY place model judgment happens in the whole
  write path.
- **executor.py**: pure function, no model call. Given a classification + confidence:
  - `new` + any confidence → write new semantic fact.
  - `update` + confidence ≥ threshold → bitemporal invalidate old fact (`invalid_at` = now),
    write new fact.
  - `contradiction` + confidence ≥ threshold → flag both facts, do NOT auto-resolve, write to
    review queue.
  - `context_dependent_both` + confidence ≥ threshold → write new fact with distinct `scope` tag,
    retain both.
  - Any classification below threshold → review queue regardless of type.
  - Every executor decision writes a `justification` field to the resulting MD frontmatter:
    what was decided, why, confidence, which episodic capture triggered it. This is your TMS-style
    audit trail from `ARCHITECTURE.md` §3.
- **blast_radius.py**: candidate retrieval for the classifier is entity/scope-anchored first
  (§2.3), hard-capped at top-K (start K=10, tune later), never a full-graph scan. This directly
  implements the O(n²) mitigation from the first research pass.

### 2.3 Retrieval (`src/retrieve/`)
- **entity_scope.py**: given a query/task, resolve named entities/scope tags, query the SQLite
  index for all facts joined on those entities/scopes. This is the primary retrieval path, not a
  fallback — similarity search supplements it, doesn't replace it (per the second research pass's
  Area 2 finding that pure similarity retrieval omits answer-critical facts).
- **graph_expand.py**: from the entity/scope match, expand 1 hop over the `links` field in
  frontmatter (bound at 1, extend to 2 only if eval shows it's needed — unbounded hops amplify
  noise per the research).
- **hybrid.py**: BM25 (for exact tokens — IDs, names, numbers) + vector similarity (for semantic
  match), fused via Reciprocal Rank Fusion. Supplements the entity/scope path for cases with no
  clean entity match.
- **sufficiency.py**: a cheap check (start with a simple heuristic — e.g. "did entity resolution
  find zero facts but similarity found some low-confidence ones" → flag; graduate to a small
  classifier only if the heuristic proves insufficient in your own eval).

### 2.4 Injection (`src/inject/`)
- **format.py**: wraps each retrieved fact in an XML tag with metadata:
  `<fact id="..." valid_at="..." scope="..." source_commit="...">value</fact>`. System/user prompt
  includes the authority-framing instruction from the research (verified stored facts, treat as
  ground truth, say so if insufficient). Requires quote-before-answer in the response format.
- **provenance.py**: stamps the current Git commit hash of `brain/` at the moment of injection.
  This is what makes a session replayable — `git checkout <hash>` reconstructs exactly what the
  model saw.

### 2.5 Verification (`src/verify/`)
- **deterministic.py**: runs first, cheapest. If a specific fact with a specific value was
  injected, extract the corresponding claim from the model's response and check it against the
  value directly (string/numeric match). Catches the worst failures for ~free.
- **nli_check.py**: CPU-local MiniCheck or AlignScore (see §3 for which). Runs on anything the
  deterministic check doesn't cover — each injected fact as premise, each extracted response claim
  as hypothesis. Flags unsupported/contradicted claims.
- Verification runs **after** generation, before the response is shown to you. On a flag, either
  regenerate once or surface the flag inline ("this may contradict your stored fact X — check
  manually"). Don't silently auto-correct — that reintroduces the "silent" failure mode you're
  trying to eliminate.

### 2.6 Index round-trip (`src/index/`)
- **build.py**: walks `brain/semantic/`, parses frontmatter + body, writes rows into SQLite. Must
  be idempotent and must be the *only* way the SQLite file is created.
- **flush.py**: takes a consolidation transaction's in-memory changes and writes them out as MD
  file changes (new files, frontmatter edits for invalidation stamps) — this is what actually
  lands in Git. The SQLite transaction wraps the *decision-making*, but the MD write is the
  durable commit.
- **Milestone test (do this early, it's cheap and it's the whole trust claim):** `rm -rf
  .brainindex/ && recall index build` must reconstruct an index that's byte-for-byte equivalent
  (or at least query-equivalent) to the one it replaced.

---

## 3. Model & Tooling Choices

| Component | Choice | Why |
|---|---|---|
| Classification (Tier 3) | Claude API (Sonnet-class) or GPT-4o-class, via batch API where possible | Research ceiling (65.3%) was measured on frontier models; small/local models collapsed (1/9 correct case). Not optional to use a strong model here. |
| Embeddings (retrieval) | A small open embedding model, local, CPU-fine (e.g. a sentence-transformers class model) | Cheap, no reasoning required, doesn't need GPU or API spend for every capture. |
| Verification (NLI) | MiniCheck-FT5 (770M) or AlignScore (355M), local, CPU | Research: MiniCheck matches Claude-3 Opus faithfulness detection at ~400x lower cost; both are small enough for CPU inference on your hardware. Start with AlignScore (smaller, faster) if CPU latency on MiniCheck is uncomfortable; upgrade if accuracy is insufficient. |
| BM25 | `rank_bm25` (Python) or SQLite FTS5 | FTS5 is likely the better call since it lives in the same SQLite file as everything else — one less dependency. |
| Vector search | `sqlite-vec` or a simple flat numpy index | At personal-scale data volume (thousands, not millions of facts), a brute-force numpy cosine search is genuinely fine — don't reach for a vector DB you don't need yet. |
| Git operations | `GitPython` or shelling out to `git` directly | Direct shell-out is simpler and avoids a dependency that lags behind Git itself. |
| CLI framework | `click` or `typer` | Typer if you want type-hint-driven CLI definitions (fast to write, good error messages, good --help output) — fits the "not clunky" bar cheaply. |
| Frontmatter parsing | `python-frontmatter` | Standard, does exactly this, no reason to hand-roll. |

**Explicitly not needed for v1:** a graph database (Kùzu etc.) — your frontmatter `links` field plus
SQLite joins covers 1-2 hop expansion at this scale; a vector database service (Pinecone/Weaviate)
— unnecessary until data volume is much larger than one person's notes; any local classifier model
— the research is clear this needs a strong model, and API cost at solo-dogfood volume is small
(see §5).

---

## 4. Prompt Design Sketches (concrete, not placeholder)

### Classifier prompt (Tier 3, `classifier.py`)
```
You are comparing a NEW captured fact against EXISTING stored facts about the same
entity/scope. Classify the relationship as exactly one of:
- "new": no meaningful overlap with existing facts
- "update": the new fact supersedes an existing fact (the old one was true, now isn't)
- "contradiction": the new and existing facts cannot both be true, and it's not simply
  that one is newer (genuine conflict, not evolution)
- "context_dependent_both": both facts can be true simultaneously in different contexts/scopes

Existing facts:
<fact id="{id}" valid_at="{date}">{content}</fact>
...

New captured fact:
<capture id="{id}" captured_at="{date}">{content}</capture>

Respond with JSON: {"classification": "...", "confidence": 0.0-1.0, "reasoning": "...",
"conflicting_fact_id": "..." or null}
```
Keep this simple at first — do not over-engineer prompt complexity before the eval set tells you
where it's actually failing. Iterate against `eval/classifier_set/`, not against intuition.

### Injection prompt (context construction, `format.py`)
```
The following are verified facts from the user's own memory store. Treat them as ground
truth. If your prior knowledge conflicts with them, the stored facts are correct. If they
do not fully cover the question, say so explicitly rather than filling gaps from assumption.

<fact id="f_001" valid_at="2026-08-01" scope="work" source_commit="a3f9c2e">
User's primary language at work is Kotlin.
</fact>
<fact id="f_002" valid_at="2026-06-15" scope="personal" source_commit="9b1e0d4">
User is learning Python for AI/ML side projects.
</fact>

Before answering, restate the specific stored fact(s) you are relying on, with their IDs.
Then answer the user's question.
```

---

## 5. Cost Model

Only real recurring cost is Tier 3 classification API calls (everything else is local/free given
hardware you already own).

**Formula:** `monthly_cost ≈ (captures_per_month) × (cost_per_classification_call)`

- Cost per call depends on token count (existing facts retrieved as candidates + new capture +
  response) and model choice. A realistic estimate for a Sonnet-class model with a modest prompt
  (a few hundred to low-thousand tokens in, a small JSON out): **fractions of a cent to a few
  cents per call**, before any batch/caching discount.
- Batch API (~50% off) applies cleanly here since consolidation is explicitly offline/batched by
  design — queue captures, run consolidation on a schedule, submit as a batch job.
- Prompt caching (~90% off repeated input) helps if the "existing facts" candidate set is stable
  across nearby calls in the same batch — worth structuring the batch so similar-scope captures
  are processed together to maximize cache hits.

**Realistic personal-use volume:** even an unusually prolific note-taker doing tens of captures a
day is on the order of a few hundred to ~1000 consolidation events a month. At worst-case
per-call cost (a few cents, no discounts applied), that's **single-digit dollars a month**. With
batching and caching, meaningfully less. This is not a budget-relevant cost at solo scale — don't
over-plan around it. Revisit only if this ever moves beyond personal use to many users, at which
point the same batch/cache economics change scale but not shape.

**Verification (NLI) and embeddings: $0 recurring** — local, CPU, your hardware, one-time model
download.

**No hardware spend required.** Nothing in this plan needs new hardware beyond the laptop you have.

---

## 6. Phased Scope (dependency order, not calendar)

**Phase 0 — Scaffolding**
Repo structure, `brain/` directory shape, frontmatter schema finalized, CLI skeleton with `--help`
working end to end even if commands are stubs.

**Phase 1 — Episodic + index round-trip**
`recall capture` works. `recall index build` works. **Prove the rebuild guarantee**
(`rm -rf .brainindex && rebuild` → equivalent index) before writing anything else — this is the
foundational trust claim and it's cheap to verify now, expensive to discover broken later.

**Phase 2 — Classifier eval loop (in isolation, before wiring into the pipeline)**
Hand-label 30-50 real examples from your own notes into `eval/classifier_set/`. Run the prompt
from §4 against them. Measure accuracy. This is the step with genuine uncertainty — if your
domain-scoped accuracy is meaningfully better than the general 65.3% ceiling, great; if not, that's
the information that should shape the confidence threshold in Phase 3, not a surprise discovered
after the whole pipeline is built.

**Phase 3 — Consolidation loop (classifier + executor + review queue)**
Wire the eval'd classifier into `consolidate/`. Build the executor's deterministic lookup logic.
Build the review queue (even a simple CLI list of flagged items with an accept/override command is
enough for v1 — no need for anything fancier while it's just you).

**Phase 4 — Retrieval**
Entity/scope-anchored retrieval, then hybrid BM25+vector, then graph expansion, then the
sufficiency gate — roughly in that order of value delivered per effort.

**Phase 5 — Injection + provenance**
Wire retrieval output into the format.py XML-tagged, authority-framed injection. Add commit-hash
stamping. Build the session replay manifest (log `{session_id, prompt_hash, retrieved_fact_ids,
commit_hash}` per session).

**Phase 6 — Verification**
Deterministic check first (cheap, catches the worst cases). Add NLI check (AlignScore first,
upgrade to MiniCheck if needed). Wire the flag-on-mismatch behavior into the CLI output.

**Phase 7 — Correction data loop**
Every review-queue override or accept gets logged as a labeled example
(`facts_in, classification_given, confidence_given, correct_classification`). This is the
compounding asset from `ARCHITECTURE.md` §7 — must exist before real usage accumulates, which is
why it's explicitly its own phase rather than an afterthought bolted onto Phase 3.

**Phase 8 — Polish pass on CLI UX**
Once the loop works end to end, invest in it not feeling clunky: consistent output formatting,
good error messages, a `recall status` command showing pending review items / recent consolidation
activity, maybe a lightweight TUI (e.g. `textual`) for the review queue specifically, since
reviewing flagged items is the one interaction that'll happen often enough to be worth the UX
investment.

---

## 7. Explicitly Out of Scope for v1 (revisit later, not now)

- Any GUI beyond CLI/TUI.
- Local classifier model (API-only, per research and hardware constraints).
- Multi-user / hosted service / correction-data-sharing infrastructure — irrelevant until there's
  any indication beyond-personal use is worth pursuing.
- CAD/contrastive decoding or any technique requiring logit access / self-hosted frontier model.
- Graph database — SQLite + frontmatter links is sufficient at this scale.
- Scheduled/automatic consolidation triggers — manual invocation is fine until the manual version
  is trusted.
