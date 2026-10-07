"""M6 → M7 learning hooks: where the loop closes.

M6's executor calls these after a decision is executed or rolled back. M7 implements them:
  on_executed    → measure the outcome of every newly executed decision (backend.learning.loop.record_outcomes)
  on_rolled_back → forget that outcome and reverse its synapse changes (remove_outcome)

M6 wraps every call in try/except, so a hook failure can never break an execution or a rollback. The executor also
sets `emitting(flag)` around the call, so `emit_brain_events=False` silences the Learn-lobe pulses too.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

_EMIT = ContextVar("emit_brain_events", default=True)


@contextmanager
def emitting(flag: bool):
    """Tell the hooks whether brain events are enabled for the call that is running them."""
    token = _EMIT.set(flag)
    try:
        yield
    finally:
        _EMIT.reset(token)


def on_executed(decision: dict, audit_entry: dict) -> None:
    """A decision was executed: M7 measures its outcome, updates the calibration and the synapses."""
    from backend.learning.loop import record_outcomes  # local: M6 must import without M7 data

    record_outcomes(emit_brain_events=_EMIT.get())


def on_rolled_back(decision: dict, audit_entry: dict) -> None:
    """A decision was rolled back: M7 removes its outcome and reverses its synapse changes exactly."""
    from backend.learning.loop import remove_outcome

    remove_outcome(decision["id"])
