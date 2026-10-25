"""The System voice: player-facing refusal and status lines the API returns."""

from __future__ import annotations

SHARED_WORLD_SEALED = (
    "<<This volume is sealed. The shared page took its last action; "
    "claim your own with an invite code.>>"
)


MOMENT_PASSED = "<<The moment has passed. Declare the action again.>>"


TURN_IN_FLIGHT = "<<The Quill is still writing your last action. A moment.>>"


TURN_TOO_FAST = "<<The Quill outpaces you. A breath, then declare again.>>"


TURN_DAILY_DONE = (
    "<<The Quill has written enough of you for one day. Return tomorrow.>>"
)


INK_SPENT = "<<The ink is spent for today. The Quill resumes tomorrow.>>"


CLAIM_THROTTLED = "<<The Quill will not be rushed. Try again shortly.>>"


#: Degrade-not-block: the deterministic turn STILL resolves when the
#: paid-narration budget is spent — the deed is canon, only the prose rests.
NARRATION_RESTING = (
    "<<The Quill sets down its pen for now: your deed is written to the record, "
    "but its telling must wait. Return tomorrow for the Quill's own voice.>>"
)


#: Free text needs the paid parser; when the budget is spent the engine stays
#: open to STRUCTURED (tapped) actions — the conversation is never fully closed.
INK_TYPED_REQUIRES_TAP = (
    "<<The Quill's ink runs thin for free hand today. Tap a suggested action "
    "and the deed still resolves.>>"
)

#: Machine code sent beside each 429 line, so the client can tell a breath
#: (in flight, too fast) from a spent day without reading the prose.
CODE_FOR_429_LINE = {
    TURN_IN_FLIGHT: "TURN_IN_FLIGHT",
    TURN_TOO_FAST: "TURN_TOO_FAST",
    TURN_DAILY_DONE: "TURN_DAILY_DONE",
    INK_SPENT: "INK_SPENT",
    INK_TYPED_REQUIRES_TAP: "INK_TYPED_REQUIRES_TAP",
    CLAIM_THROTTLED: "CLAIM_THROTTLED",
}
