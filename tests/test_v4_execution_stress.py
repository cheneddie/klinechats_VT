from pathlib import Path
import json
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from server.engine import connect
from server.v4_execution_stress import execution_stress_summary
from server.v4_multiyear import migrate_multiyear_schema


def main():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "fabio.sqlite3"
        con = connect(db)
        migrate_multiyear_schema(con)
        for year in (2024, 2025):
            for i in range(20):
                strategy = "MR" if i < 10 else "BO"
                risk = 5.0 if strategy == "MR" else 10.0
                gross = 1.0 if i % 4 != 0 else -1.0
                mgmt = {
                    "fixed_1R": {"r": gross},
                    "fixed_2R": {"r": 2.0 if gross > 0 else -1.0},
                }
                con.execute(
                    """INSERT INTO strict_trade_outcomes(
                    event_id,year,trading_date,contract,strategy,direction,entry_seq,entry_time,
                    entry_price,stop,risk_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_5r,hit_stop,
                    management_json,computed_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        f"{year}-{strategy}-{i}", year, f"{year}-{1 + (i % 2):02d}-{1 + i:02d}", f"{year}01",
                        strategy, "long", i, "09:00:00", 100.0, 100.0-risk, risk,
                        3.0 if gross > 0 else .4, .4 if gross > 0 else 1.0,
                        int(gross > 0), int(gross > 0), 0, 0, int(gross < 0),
                        json.dumps(mgmt), "now",
                    ),
                )
        con.commit()

        out = execution_stress_summary(con, [2024, 2025])
        mr = out["strategies"]["MR"]
        bo = out["strategies"]["BO"]
        assert mr["n"] == 20, mr
        assert bo["n"] == 20, bo
        mr_cost = {x["cost_points_round_trip"]: x for x in mr["cost_stress"]}
        assert mr_cost[0.0]["avg_net_r"] > mr_cost[3.0]["avg_net_r"], mr_cost
        assert mr["monthly_concentration"]["periods"], mr
        assert mr["yearly_concentration"]["periods"], mr
        assert out["latency"]["status"] == "PENDING_FROZEN_SPEC", out["latency"]
        assert mr["policy"]["cost_pass_fail"].startswith("PENDING"), mr["policy"]
        con.close()
    print("V4 strict execution stress: PASS")


if __name__ == "__main__":
    main()
