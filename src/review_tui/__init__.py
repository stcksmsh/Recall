"""Interactive textual front end over the existing review-queue mechanism (Phase 8 polish,
BUILD_PLAN.md §6). Pure front end: every resolution routes through
src.consolidate.review.accept/override, the same functions `recall review accept/override`
call — no parallel correction-writing path.
"""

from src.review_tui.app import ReviewApp, SessionSummary, launch, resolve_item

__all__ = ["ReviewApp", "SessionSummary", "launch", "resolve_item"]
