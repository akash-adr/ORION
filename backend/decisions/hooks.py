"""M6 → M7 learning hooks. M7 (learning) is not built yet: these are deliberate no-ops.

M7 will implement them to record the predicted impact at execution time and measure the actual outcome later.
The executor wraps every call in try/except, so a hook failure can never break an execution or a rollback.
"""
from __future__ import annotations


def on_executed(decision: dict, audit_entry: dict) -> None:
    """Called after a decision has been executed. M7 will snapshot the prediction here."""


def on_rolled_back(decision: dict, audit_entry: dict) -> None:
    """Called after a decision has been rolled back. M7 will discard the pending outcome here."""
