# 0002 — Cost-discipline and anti-rot are the same problem

## Decision
Expensive reasoning belongs at **write-time** (consolidation), not read-time (every query).
A clean, consolidated store is what makes cheap retrieval sufficient most of the time; it is
also what prevents memory rot. These are not two goals — they are one.

Corollary constraint: no LLM call, and no consolidation work, in the read/query path or in a
live session-start path. See [0006-aiw-boundary](0006-aiw-boundary.md).

## Rationale
Amortise one expensive reconciliation over many cheap reads. Systems that reason at read-time
pay per query and still rot, because nothing ever cleans the store.

## Status in codebase — MATCHES
- `src/capture/capture.py`: "No model call on write" — episodic capture is instant.
- The only LLM call in the write path is `src/consolidate/classifier.py`, invoked by
  `recall consolidate run` (manual/offline).
- `src/retrieve/`, `src/inject/` make no model calls.
- `README.md` states this as claim 1.

## Conflicts / gaps
None.
