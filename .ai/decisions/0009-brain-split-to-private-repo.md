# 0009 — `brain/` split into its own private repository

## Decision
`brain/` (Tier 1 episodic + Tier 2 semantic — the actual memory store) is no longer part of this
repository's git history. It now lives as its own independent git repository,
**`github.com/stcksmsh/recall-brain`, private**, checked out locally at `./brain/` inside this
working directory. This repo (`Recall`) ignores `brain/` entirely (`.gitignore`).

Decision 0001's "dual representation, plaintext + git-versioned, recoverable by construction"
design is preserved exactly — `brain/` is still its own git repo with full history, still the
thing `provenance.py` stamps a commit hash against. Only the *host* changed: private repo
instead of a subdirectory of the public code repo.

## Rationale
This repo (`stcksmsh/Recall`) is **public**. `brain/` is meant to hold the owner's real personal
usage data once daily use starts (`start-daily-usage`) — that is the entire point of the product.
Personal data and public, permanently-archived git history are fundamentally incompatible. This
should have been caught before `brain/` was first committed here; it wasn't, because everything
written to it so far happened to be engineering-only (dogfooding this build's own decisions).
That was luck, not design — the first real backfill-import batch attempted (real personal/
financial-adjacent conversation history) is what surfaced the gap.

## What was done
- `git filter-repo --subdirectory-filter brain` on a fresh clone → pushed as the initial history
  of the new private repo, preserving all prior `brain/` commits (episodic + semantic file
  history, including provenance).
- `git filter-repo --path brain --invert-paths` on a fresh clone of this repo → force-pushed to
  `origin/master` here, removing `brain/` from every historical commit. (Safe to force-push:
  0 stars / 0 forks at the time — realistically nobody had a copy of the prior history.)
- `brain/` re-populated locally from the extracted copy (same content, own `.git`, remote set to
  `recall-brain`), added to this repo's `.gitignore`.
- **Fixed a real bug this split exposed**: `src/inject/provenance.py`'s callers
  (`src/retrieve/pipeline.py`, `src/inject/session_start.py`, `src/inject/format.py`) defaulted
  `repo_root` to `Path(".")` / cwd — correct when `brain/` was a subdirectory of the same repo,
  silently wrong now (would stamp facts with `Recall`'s commit hash instead of `brain/`'s own).
  All three now default to `brain_root`. Verified against the real store: `recall inject
  --for-session` now stamps `brain/`'s own HEAD, confirmed different from `Recall`'s HEAD.

## Status in codebase — MATCHES (as of this decision)
- `brain/` git-tracked, private, pushed. This repo's `.gitignore` excludes it entirely.
- Full test suite (70) green; a live CLI check confirms correct provenance stamping post-split.
- A local safety bundle of this repo's pre-split history was made before any rewrite
  (`Recall-backup-before-brain-split.bundle`, not committed anywhere — local only).

## Conflicts / gaps
- `BUILD_PLAN.md`'s repo-structure diagram still shows `brain/` as a subdirectory "committed" as
  part of one tree — still directionally true (it is git-committed) but no longer part of *this*
  repo's history. Worth a one-line clarification there; not corrected as part of this decision
  doc itself.
- Anyone who had already cloned `stcksmsh/Recall` before this split keeps the old history
  (including `brain/`) in their local copy — force-pushing doesn't reach existing clones. Given
  0 stars/0 forks at split time, this is believed to be a non-issue, but it is not something git
  can guarantee after the fact.
- The two pending backfill-import batches (`recall_backfill_captures.yaml`,
  `recall_backfill_captures_v2.yaml`, untracked in this repo, not yet processed) are unaffected
  by this decision except that they now correctly land in the private `brain/` repo once
  imported, not this one.
