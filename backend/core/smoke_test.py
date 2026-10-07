"""M0 smoke test. Run from the project root: python -m backend.core.smoke_test

Leaves no trace: state.json is restored byte-for-byte, the smoke table is dropped,
and engine.db is removed again if it did not exist before.
"""
import json
import re
from pathlib import Path

import pandas as pd

from backend.core import db
from backend.core.config import CHANNELS, DB_PATH, ID_PATTERNS, STATE_PATH, STOCK_COVER_RISK_DAYS
from backend.core.metrics import neuron_health, neuron_size
from backend.core.schema import Anomaly, NeuronNode, make_brain_event, to_dict


def main() -> None:
    state_path, db_path = Path(STATE_PATH), Path(DB_PATH)
    state_before = state_path.read_bytes() if state_path.exists() else None
    db_existed = db_path.exists()
    try:
        # 2. Anomaly → JSON
        a = Anomaly("AN-001", "cpc_spike", "channel", "google", "CPC spike on Google", "cpc",
                    18.0, 29.0, 0.61, 31.2, -33763, "high")
        json.dumps(to_dict(a))

        # 3. SQLite round trip
        db.write_table(pd.DataFrame({"x": [1, 2], "y": ["a", "b"]}), "smoke")
        assert len(db.read_table("smoke")) == 2
        db.drop_table("smoke")
        assert not db.table_exists("smoke")

        # 4. state round trip
        state = db.load_state()
        state["autonomy"] = "supervised"
        db.save_state(state)
        assert db.load_state()["autonomy"] == "supervised"

        # 5. brain event
        ev = make_brain_event("anomaly", entity_id="CMP-01", ref_id="AN-001", severity="high",
                              message="Creative fatigue · Meta · Summer Sneakers · broad")
        ev = db.log_brain_event(ev)
        assert re.match(ID_PATTERNS["brain_event"], ev.id), ev.id
        assert ev.region == "diagnose"
        assert ev.path == ["ingest", "diagnose"]
        assert any(e["id"] == ev.id for e in db.read_brain_events())

        # 6. neuron node
        node = NeuronNode("CMP-01", "campaign", "Summer Sneakers · broad", "meta", "meta", "SKU-A",
                          84000.0, 1.35, 21000.0, -0.12, neuron_health(1.35),
                          neuron_size(84000.0, 10000.0, 120000.0))
        json.dumps(to_dict(node))
    finally:
        # 7. restore state exactly as it was
        if state_before is None:
            state_path.unlink(missing_ok=True)
        else:
            state_path.write_bytes(state_before)
        if not db_existed:
            db_path.unlink(missing_ok=True)

    print(f"M0 OK  CHANNELS={CHANNELS}  STOCK_COVER_RISK_DAYS={STOCK_COVER_RISK_DAYS}")


if __name__ == "__main__":
    main()
