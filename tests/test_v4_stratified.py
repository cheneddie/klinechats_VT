from pathlib import Path
import json
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server.engine import connect
from server.v4_multiyear import migrate_multiyear_schema
from server.v4_stratified import stratified_edge_report


def main():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "fabio.sqlite3"
        con = connect(db)
        migrate_multiyear_schema(con)
        for i in range(40):
            month = 1 if i < 20 else 2
            day = (i % 20) + 1
            direction = "long" if i % 2 == 0 else "short"
            hour = 8 if i % 4 == 0 else 9
            minute = 50 if hour == 8 else (10 if i % 3 else 40)
            eid = f"2025-MR-{i:03d}"
            passed = i % 2 == 0
            features = {
                "terminal_signal": True,
                "auction_side": "down" if direction == "long" else "up",
                "excursion_pct_value": 0.02 + i * 0.001,
                "audit_lvn_depth": 0.10 + i * 0.01,
            }
            con.execute(
                """INSERT INTO events(
                event_id,source_file,year,trading_date,contract,strategy,direction,result,
                entry_seq,entry_time,entry_price,stop,value_width,features_json,nodes_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, "MTX_2025.parquet", 2025, f"2025-{month:02d}-{day:02d}", "202501",
                    "MR", direction, "ENTRY", i, f"2025-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00",
                    100.0, 95.0 if direction == "long" else 105.0, 40.0 + i,
                    json.dumps(features), "{}", "now",
                ),
            )
            con.execute(
                """INSERT INTO strict_trade_outcomes(
                event_id,year,trading_date,contract,strategy,direction,entry_seq,entry_time,
                entry_price,stop,risk_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_5r,hit_stop,
                management_json,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, 2025, f"2025-{month:02d}-{day:02d}", "202501", "MR", direction, i,
                    f"2025-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:00", 100.0,
                    95.0 if direction == "long" else 105.0, 5.0,
                    2.0 if passed else .4, .4 if passed else 1.1,
                    int(passed), int(passed), 0, 0, int(not passed),
                    json.dumps({"fixed_1R": {"r": 1.0 if passed else -1.0}}), "now",
                ),
            )
            con.execute(
                """INSERT INTO opportunity_outcomes(
                event_id,strategy,direction,entry_seq,entry_price,risk_points,mfe_r,mae_r,
                hit_1r,hit_2r,hit_3r,hit_stop,management_json,computed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    eid, "MR", direction, i, 100.0, 5.0,
                    2.5 if passed else .3, .4 if passed else 1.2,
                    int(passed), int(passed), 0, int(not passed),
                    json.dumps({"fixed_0.75R": {"r": .75 if passed else -1.0}}), "now",
                ),
            )
            con.execute(
                "INSERT INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty) VALUES(?,?,?,?,?,?)",
                (eid, "AUC_ATTEMPT", int(passed), i, f"2025-{month:02d}-{day:02d}T09:00:00", 2),
            )
        con.commit()

        report = stratified_edge_report(con, [2025])
        strict = report["strict_strategy"]["strategies"]["MR"]
        assert set(strict["by_month"]) == {"2025-01", "2025-02"}, strict["by_month"]
        assert set(strict["by_direction"]) == {"long", "short"}, strict["by_direction"]
        assert "08:45-09:00" in strict["by_intraday_time"], strict["by_intraday_time"]
        assert "09:00-09:30" in strict["by_intraday_time"], strict["by_intraday_time"]
        assert "09:30-10:30" in strict["by_intraday_time"], strict["by_intraday_time"]
        assert set(strict["by_value_width_quartile"]) == {"Q1", "Q2", "Q3", "Q4"}, strict["by_value_width_quartile"]
        assert report["strict_strategy"]["unavailable_regimes"]["trend_regime"].startswith("NOT_PERSISTED")

        node = next(x for x in report["node_month_consistency"]["nodes"] if x["strategy"] == "MR" and x["node_id"] == "AUC_ATTEMPT")
        assert node["sufficient_months"] == 2, node
        assert len(node["months"]) == 2, node
        con.close()
    print("V4 stratified edge report: PASS")


if __name__ == "__main__":
    main()
