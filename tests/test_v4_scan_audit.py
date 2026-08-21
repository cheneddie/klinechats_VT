from pathlib import Path
import json
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from server.contracts import choose_contracts
from server.engine import connect
from server.progress_scanner import _catalog_file, _ensure_audit_tables, _persist_contract_audit
from server.v4_multiyear import migrate_multiyear_schema
from server.v4_release_engine import ScanConfigV4Final
from tools.run_v4_diagnostic import clean_rebuildable_years, db_summary


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        parquet = root / "MTX_2025.parquet"
        db = root / "fabio.sqlite3"
        d = pd.DataFrame({
            "datetime": pd.to_datetime([
                "2025-01-02 08:45:00",
                "2025-01-02 08:45:01",
                "2025-01-02 08:45:02",
                "2025-01-02 08:45:03",
                "2025-01-02 08:45:04",
                "2025-01-02 08:45:05",
            ]),
            "product": ["MTX", "MTX", "MTX", "MTX", "MTX", "TX"],
            "expiry": ["202501", "202501", "202501", "202501/202502", "SPREAD", "202501"],
            "price": [23000, 23001, 23002, 23003, 23004, 23005],
            "volume": [2, 4, 6, 8, 10, 12],
            "side": [1, 1, -1, 1, -1, 1],
        })
        d.to_parquet(parquet, index=False)

        cfg = ScanConfigV4Final(contract_mode="strict")
        cat = _catalog_file(parquet, cfg)
        assert cat["source_rows"] == 6, cat
        assert cat["mtx_rows"] == 5, cat
        assert cat["outright_rows"] == 3, cat
        assert cat["spread_removed_rows"] == 2, cat
        assert cat["outright_contracts"] == ["202501"], cat
        assert cat["qa"] == "PASS", cat

        con = connect(db)
        migrate_multiyear_schema(con)
        _ensure_audit_tables(con)
        con.execute(
            "INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)",
            (parquet.name, 2025, 6, "2025-01-02T08:45:00", "2025-01-02T08:45:05", '["MTX","TX"]', '["202501","SPREAD"]', "PASS", "now"),
        )
        con.execute(
            """INSERT OR REPLACE INTO dataset_integrity(
            file,year,source_rows,mtx_rows,outright_rows,spread_removed_rows,
            outright_contracts_json,source_order_qa,scanned_at)
            VALUES(?,?,?,?,?,?,?,?,?)""",
            (parquet.name, 2025, 6, 5, 3, 2, '["202501"]', "PASS", "now"),
        )
        volume_map = {"2025-01-02": {"202501": 12.0}}
        active = choose_contracts(volume_map, "strict")
        _persist_contract_audit(con, parquet, volume_map, active)

        eid = "2025-01-02-202501-A001-MR"
        con.execute(
            """INSERT INTO events(event_id,source_file,year,trading_date,contract,strategy,direction,result,features_json,nodes_json,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, parquet.name, 2025, "2025-01-02", "202501", "MR", "long", "ENTRY", json.dumps({"terminal_signal": True}), "{}", "now"),
        )
        con.execute(
            "INSERT INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty) VALUES(?,?,?,?,?,?)",
            (eid, "AUC_ATTEMPT", 1, 0, "2025-01-02T08:45:00", 2),
        )
        con.execute(
            """INSERT INTO opportunity_outcomes(event_id,strategy,direction,entry_seq,entry_price,risk_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_stop,management_json,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, "MR", "long", 0, 23000.0, 5.0, 2.0, .5, 1, 1, 0, 0, '{"fixed_0.75R":{"r":0.75}}', "now"),
        )
        con.execute(
            """INSERT INTO strict_trade_outcomes(event_id,year,trading_date,contract,strategy,direction,entry_seq,entry_time,entry_price,stop,risk_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_5r,hit_stop,management_json,computed_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (eid, 2025, "2025-01-02", "202501", "MR", "long", 0, "2025-01-02T08:45:00", 23000.0, 22995.0, 5.0, 2.0, .5, 1, 1, 0, 0, 0, '{"fixed_1R":{"r":1.0}}', "now"),
        )
        con.execute(
            """INSERT INTO training_attempts(attempt_id,event_id,node_id,human_answer,correct,confidence,reaction_ms,mode,difficulty,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?)""",
            ("human-1", eid, "AUC_ATTEMPT", 1, 1, 4, 900, "practice", 2, "now"),
        )
        con.commit()
        con.close()

        summary = db_summary(db, [2025])
        f = summary["funnel"]
        assert f["source_rows"] == 6, summary
        assert f["mtx_rows"] == 5, summary
        assert f["outright_rows"] == 3, summary
        assert f["spread_removed_rows"] == 2, summary
        assert f["contracts_found"] == ["202501"], summary
        assert f["active_contracts"] == ["202501"], summary
        assert f["trading_days"] == 1, summary
        assert summary["contract_policy_causal"] is True, summary
        selection = summary["contract_selection"][0]
        assert selection["candidate_contracts"] == ["202501"], selection
        assert selection["selected_volume_raw"] == 12.0, selection
        assert selection["selected_volume_normalized"] == 6.0, selection

        cleaned = clean_rebuildable_years(db, [2025])
        assert cleaned["removed_event_ids"] == 1, cleaned
        con = connect(db)
        assert con.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM node_instances").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM opportunity_outcomes").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM strict_trade_outcomes").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM dataset_integrity").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM contract_selection_audit").fetchone()[0] == 0
        # Human practice history is intentionally not rebuildable from market data.
        assert con.execute("SELECT COUNT(*) FROM training_attempts").fetchone()[0] == 1
        con.close()

    print("V4 source funnel / contract audit / clean rebuild: PASS")


if __name__ == "__main__":
    main()
