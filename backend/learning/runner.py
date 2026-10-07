"""M7 entry point: seed the history if needed, measure any new outcomes, and print what the engine has learned.

Run from the project root:  python -m backend.learning.runner [--no-brain-events]
"""
from __future__ import annotations

from backend.core import metrics as m
from backend.core.config import ROLLING_WINDOW
from backend.learning.loop import learning_report, record_outcomes


def first_last_rolling(curve: list[dict]) -> tuple[float | None, float | None]:
    """First and last rolling MAPE, using the first FULL window (a partial start window is noisy)."""
    if not curve:
        return None, None
    full = curve[ROLLING_WINDOW - 1:] or curve
    return full[0]["rolling_mape"], full[-1]["rolling_mape"]


def print_report(report: dict, new: list[dict]) -> None:
    k, cal = report["kpis"], report["calibration"]
    print("KPIs")
    print(f"  forecast error (MAPE, last {cal['n']}): {k['forecast_error']:.1%}")
    print(f"  calibration factor: {k['calibration_factor']:.3f}")
    print(f"  win-rate: {k['win_rate']:.0%}")
    print(f"  measured outcomes: {k['measured_count']} · total measured profit {m.format_inr(k['total_measured_profit'])}/day (simulated)")
    first, last = first_last_rolling(report["accuracy_curve"])
    print(f"\nACCURACY CURVE (rolling MAPE over {ROLLING_WINDOW} outcomes): {first:.1%} → {last:.1%}")
    print("  " + "  ".join(f"{p['rolling_mape']:.0%}" for p in report["accuracy_curve"]))
    cum = report["cumulative_profit"]
    print(f"\nCUMULATIVE MEASURED PROFIT: {m.format_inr(cum[-1]['cumulative'])}/day by {cum[-1]['date']}")
    print(f"\n{'decision':<34}{'predicted':>11}{'actual':>10}{'error':>8}  simulated")
    for o in report["outcomes"][:5]:
        err = f"{o['error_pct']:+.0%}" if o["error_pct"] is not None else "—"
        print(f"{o['title'][:33]:<34}{m.format_inr(o['predicted']):>11}{m.format_inr(o['actual']):>10}{err:>8}  {o['simulated']}")
    strongest = sorted(report["synapse_strength"].items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    print("\nSTRONGEST SYNAPSES: " + ", ".join(f"{key} {v:.2f}" for key, v in strongest))
    print(f"\n{report['simulated_note']}")
    print(f"\nM7 OK · {k['measured_count']} outcomes · MAPE {k['forecast_error']:.0%} · calibration {k['calibration_factor']:.2f} · "
          f"win-rate {k['win_rate']:.0%} · simulated" + (f" · {len(new)} new outcome(s)" if new else ""))


def main(argv: list[str] | None = None) -> None:
    import argparse

    p = argparse.ArgumentParser(description="M7 closed-loop learning")
    p.add_argument("--no-brain-events", action="store_true", help="do not log outcome brain events")
    args = p.parse_args(argv)
    new = record_outcomes(emit_brain_events=not args.no_brain_events)  # seeds the history on first use
    print_report(learning_report(), new)


if __name__ == "__main__":
    main()
