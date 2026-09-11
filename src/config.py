"""Single source of truth for where brain/ lives.

brain/ is a separate, private git repo (github.com/stcksmsh/recall-brain, .ai/decisions/0009),
checked out locally as a subdirectory of this checkout and gitignored by this (public) repo. Every
module that needs the default location imports BRAIN_ROOT from here instead of hardcoding
`Path("brain")` -- keeps the one filesystem assumption in one place. Callers that need a different
location (tests, an alternate checkout) still pass `brain_root=...` explicitly; this is only the
default.
"""

from __future__ import annotations

from pathlib import Path

BRAIN_ROOT = Path("brain")
