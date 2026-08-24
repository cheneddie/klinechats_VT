from pathlib import Path
import json
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server.engine import connect
from server.v4_multiyear import (
    migrate_multiyear_schema,
    multi_year_edge_map,
    production_gate,
    right_tail_summary,
    strict_trade_summary,
)


def main():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "fabio.sqlite3"
        con = connect(db)
        migrate_multiyear_schema(con)

        # Two sufficiently large years for a deliberately clean MR node example.
        for year in (2024, 2025):
            for i in range(60):
                eid = f"{year}-MR-{i:03d}"
                passed = (i % 2 == 0)
                control_r = 0.50 if passed else -0.50
                con.execute(
                    """INSERT INTO events(
                    event_id,source_file,year,trading_date,contract,strategy,direction,result,
                    features_json,nodes_json,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        eid, f"MTX_{year}.parquet", year, f"{year}-01-{(i % 20) + 1:02d}", f"{year}01",
                        "MR", "long", "OPPORTUNITY", json.dumps({"terminal_signal": True}), "{}", "now",
                    ),
                )
                con.execute(
                    """INSERT INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty)
                       VALUES(?,?,?,?,?,?)""",
                    (eid, "AUC_ATTEMPT", int(passed), i, f"{year}-01-01T09:00:{i % 60:02d}", 2),
                )
                management = {"fixed_0.75R": {"r": control_r}}
                con.execute(
                    """INSERT INTO opportunity_outcomes(
                    event_id,strategy,direction,entry_seq,entry_price,risk_points,mfe_r,mae_r,
                    hit_1r,hit_2r,hit_3r,hit_stop,management_json,computed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        eid, "MR", "long", i, 100.0, 5.0,
                        3.0 if passed else 0.3, 0.4 if passed else 1.2,
                        int(passed), int(passed), int(passed), int(not passed),
                        json.dumps(management), "now",
                    ),
                )

        # Strict strategy rows are distinct from relaxed opportunity outcomes.
        for year in (2024, 2025):
            for i in range(30):
                win = i < 18
                rr = 1.0 if win else -1.0
                mfe = 2.5 if win else 0.4
                con.execute(
                    """INSERT INTO strict_trade_outcomes(
                    event_id,year,trading_date,contract,strategy,direction,entry_seq,entry_time,
                    entry_price,stop,risk_points,mfe_points,mae_points,mfe_r,mae_r,
                    hit_1r,hit_2r,hit_3r,hit_5r,hit_stop,management_json,computed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"STRICT-{year}-{i:03d}", year, f"{year}-02-{(i % 20) + 1:02d}", f"{year}02",
                        "MR", "long", i, "09:00:00", 100.0, 95.0, 5.0,
                        mfe * 5.0, 5.0 if not win else 2.0, mfe, 1.0 if not win else .4,
                        int(win), int(win), 0, 0, int(not win),
                        json.dumps({"fixed_1R": {"r": rr}, "fixed_2R": {"r": rr}}), "now",
                    ),
                )
        con.commit()

        edge = multi_year_edge_map(con, [2024, 2025])
        auc = next(x for x in edge["nodes"] if x["strategy"] == "MR" and x["node_id"] == "AUC_ATTEMPT")
        assert auc["classification"] == "CORE", auc
        assert auc["sufficient_years"] == 2
        assert auc["weighted_delta_control_avg_r"] > 0

        strict = strict_trade_summary(con, [2024, 2025])
        assert strict["combined"]["MR"]["n"] == 60
        assert strict["combined"]["MR"]["avg_r"] > 0
        assert strict["combined"]["MR"]["p95_mfe_r"] >= 2.0

        tail = right_tail_summary(con, [2024, 2025])
        assert tail["strict_entries"]["MR"]["n"] == 60
        assert tail["relaxed_terminal_opportunities"]["MR"]["n"] == 120

        gate = production_gate(con, [2024, 2025])
        mr = gate["strategies"]["MR"]
        assert mr["gates"]["positive_expectancy_at_practical_target"] == "PASS"
        assert mr["gates"]["cross_year_positive_consistency"] == "PASS"
        assert mr["gates"]["avg_winner_points_ge_10pct_atr"] == "PENDING_ATR_REFERENCE"
        assert mr["live_approved"] is False
        assert mr["status"] == "NOT_LIVE_APPROVED"

        con.close()
    print("V4 multi-year / strict production diagnostics: PASS")


if __name__ == "__main__":
    main()
