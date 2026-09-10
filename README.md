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

Early build. Phase 0/1 per `BUILD_PLAN.md` §6: episodic capture and the index round-trip.
Consolidation, retrieval, injection, and verification are not implemented yet.

## Usage

```
recall capture "<text>"        # write an episodic capture — instant, no model calls
recall index build             # rebuild the semantic index from brain/
```

Run `recall --help` for the full (mostly stubbed) command list.
