from pathlib import Path
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

from server.v4_engine import ScanConfigV4, scan_day_v4, migrate_v4_schema, write_events_v4
from server.engine import connect


def frame(prices):
    base = pd.Timestamp('2025-01-02 09:00:00')
    return pd.DataFrame({
        '_seq': range(len(prices)),
        'dt': [base + pd.Timedelta(seconds=i) for i in range(len(prices))],
        'price': [float(x) for x in prices],
        'volume': [1.0] * len(prices),
        'side': [0] * len(prices),
    })


def mr_case():
    prices = [101, 103, 102, 100, 99, 97, 96, 95, 96, 98, 100, 103]
    prices += [101] * 190
    return frame(prices)


def bo_case():
    prices = [101, 103]
    prices += [103, 104, 103, 104, 103] * 5
    prices += [104] * 180
    return frame(prices)


def main():
    cfg = ScanConfigV4(auction_max_sec=30, acceptance_window_sec=20)
    prior = {'vah': 100.0, 'val': 90.0, 'poc': 95.0, 'width': 10.0}
    fake = Path('MTX_2025.parquet')

    mr = [e for e in scan_day_v4(mr_case(), prior, cfg, fake, '2025-01-02', '202501') if e['strategy'] == 'MR']
    assert mr, 'MR event not emitted'
    m = mr[0]['nodes']
    assert m['MR_REJECTION']['answer'] is True
    assert m['MR_CLEAR_RECLAIM']['answer'] is True
    assert m['MR_REJECTION']['seq'] < m['MR_CLEAR_RECLAIM']['seq'], (m['MR_REJECTION'], m['MR_CLEAR_RECLAIM'])
    assert m['AUC_EXTREME']['anchor_seq'] != m['AUC_EXTREME']['seq'], 'Extreme anchor must be distinct from causal lock when possible'
    assert m['MR_ENTRY']['seq'] is not None, 'FALSE/YES execution gate must have a causal decision location'
    assert m['NO_TRADE']['seq'] is not None

    bo = [e for e in scan_day_v4(bo_case(), prior, cfg, fake, '2025-01-02', '202501') if e['strategy'] == 'BO']
    assert bo, 'BO event not emitted'
    b = bo[0]['nodes']
    assert b['BO_DISPLACEMENT']['answer'] is True
    assert b['BO_ACCEPTANCE']['seq'] > b['BO_DISPLACEMENT']['seq'], (b['BO_DISPLACEMENT'], b['BO_ACCEPTANCE'])
    assert b['BO_ACCEPTANCE']['metrics']['outside_ratio'] >= cfg.acceptance_outside_ratio
    assert b['BO_ENTRY']['seq'] is not None, 'BO execution gate must always resolve to a time/price when branch was observed'

    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 'events.sqlite3'
        con = connect(db)
        migrate_v4_schema(con)
        write_events_v4(con, [mr[0], bo[0]], '2025-01-02T00:00:00Z')
        rows = con.execute('SELECT node_id,decision_seq,decision_price,anchor_seq,reason_code,node_schema_version FROM node_instances').fetchall()
        assert rows and all(r['node_schema_version'] == 4 for r in rows)
        assert any(r['decision_price'] is not None for r in rows)
        assert any(r['anchor_seq'] != r['decision_seq'] for r in rows if r['anchor_seq'] is not None and r['decision_seq'] is not None)
        con.close()

    print('V4 node semantics: PASS')


if __name__ == '__main__':
    main()
