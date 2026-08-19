from __future__ import annotations

import tempfile
from pathlib import Path

import pandas as pd

from server.causal_engine import connect, read_replay_window, write_events


def build_fixture(root: Path) -> Path:
    path = root / 'MTX_2025.parquet'
    df = pd.DataFrame({
        'datetime': pd.to_datetime([
            '2025-03-18 09:00:00','2025-03-18 09:00:00','2025-03-18 09:00:00',
            '2025-03-18 09:00:01','2025-03-18 09:00:01','2025-03-18 09:00:01',
        ]),
        'product': ['MTX'] * 6,
        'expiry': ['202503'] * 6,
        'price': [100.0, 102.0, 101.0, 103.0, 99.0, 104.0],
        'volume': [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],
        'side': [0.0, 1.0, -1.0, 1.0, -1.0, 1.0],
    })
    df.to_parquet(path, index=False, row_group_size=4)
    return path


def test_replay_preserves_physical_same_second_order():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = build_fixture(root)
        event = {
            'source_file': path.name,
            'contract': '202503',
            'context_start_seq': 0,
            'context_end_seq': 5,
            'attempt_start_seq': 0,
        }
        bars = read_replay_window(root, event, margin=0)
        assert len(bars) == 2
        first, second = bars
        assert first['open'] == 100.0
        assert first['close'] == 101.0
        assert first['high'] == 102.0
        assert first['low'] == 100.0
        assert first['volume'] == 12.0
        assert first['firstSeq'] == 0
        assert first['lastSeq'] == 2
        assert second['open'] == 103.0
        assert second['close'] == 104.0
        assert second['high'] == 104.0
        assert second['low'] == 99.0
        assert second['firstSeq'] == 3
        assert second['lastSeq'] == 5


def test_event_store_indexes_each_binary_node():
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / 'events.sqlite3'
        con = connect(db)
        event = {
            'event_id': '2025-03-18-202503-A001',
            'source_file': 'MTX_2025.parquet',
            'year': 2025,
            'trading_date': '2025-03-18',
            'contract': '202503',
            'strategy': 'MR',
            'direction': 'short',
            'result': 'WAIT',
            'difficulty': 2,
            'attempt_start_seq': 10,
            'attempt_start_time': '2025-03-18T09:00:00',
            'context_start_seq': 0,
            'context_end_seq': 100,
            'vah': 100.0,
            'val': 90.0,
            'poc': 95.0,
            'value_width': 10.0,
            'features': {'excursion_pct_value': 0.05},
            'nodes': {
                'AUC_ATTEMPT': {'answer': True, 'seq': 10, 'time': '2025-03-18T09:00:00'},
                'MR_REJECTION': {'answer': False, 'seq': 20, 'time': '2025-03-18T09:00:05'},
            },
        }
        write_events(con, [event], '2026-08-19T00:00:00+00:00')
        con.commit()
        rows = con.execute(
            'SELECT node_id,answer,decision_seq FROM node_instances WHERE event_id=? ORDER BY node_id',
            (event['event_id'],),
        ).fetchall()
        con.close()
        got = [(r['node_id'], r['answer'], r['decision_seq']) for r in rows]
        assert got == [('AUC_ATTEMPT', 1, 10), ('MR_REJECTION', 0, 20)]


if __name__ == '__main__':
    test_replay_preserves_physical_same_second_order()
    test_event_store_indexes_each_binary_node()
    print('scanner e2e tests: PASS')
