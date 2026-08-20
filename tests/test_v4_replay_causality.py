from pathlib import Path
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pyarrow as pa
import pyarrow.parquet as pq

from server.v4_replay_final import replay_trading_window, clear_index_cache


def write(path, rows):
    table = pa.table({
        'datetime': pa.array([x[0] for x in rows], type=pa.string()),
        'product': ['MTX'] * len(rows),
        'expiry': ['202501'] * len(rows),
        'price': [float(x[1]) for x in rows],
        'volume': [1] * len(rows),
        'side': [0] * len(rows),
    })
    pq.write_table(table, path, row_group_size=3)


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / 'MTX_2025.parquet'
        rows = [
            # Friday day session establishes observed trading day.
            ('2025-01-03 09:00:00', 90),
            # Friday night / Saturday early morning belong to Monday full session.
            ('2025-01-03 15:00:00', 91),
            ('2025-01-04 00:30:00', 92),
            # Monday partial minute: decision occurs at :15; :45 is forbidden future.
            ('2025-01-06 09:10:00', 100),
            ('2025-01-06 09:10:15', 101),
            ('2025-01-06 09:10:45', 999),
            ('2025-01-06 13:00:00', 102),
            # Tuesday observed day keeps Monday from being last/edge case.
            ('2025-01-07 09:00:00', 110),
        ]
        write(path, rows)
        clear_index_cache()
        event = {'source_file': path.name, 'trading_date': '2025-01-06', 'date': '2025-01-06', 'contract': '202501'}
        meta = {'MR_REJECTION': {'decision_time': '2025-01-06 09:10:15'}}

        full = replay_trading_window(root, event, meta, node_id='MR_REJECTION', before=0, after=0, timeframe='1s', session='full')
        prices = [b['close'] for b in full['bars']]
        assert 91.0 in prices and 92.0 in prices, full
        assert 90.0 not in prices, 'Friday day session must not be in Monday full trading session'
        assert full['dates'] == ['2025-01-06'], full['dates']
        assert full['trading_day_definition'].startswith('previous observed day 15:00')

        hidden = replay_trading_window(
            root, event, meta, node_id='MR_REJECTION', before=0, after=0,
            timeframe='1m', session='full', cutoff_time='2025-01-06 09:10:15'
        )
        assert hidden['cutoff_time'] is not None
        bar = next(b for b in hidden['bars'] if b['timestamp'] == 1736125800000)  # 2025-01-06 09:10 local-naive epoch encoding used by pandas
        assert bar['open'] == 100.0 and bar['close'] == 101.0, bar
        assert bar['high'] == 101.0, '09:10:45 spike leaked into pre-decision 1m bar'
        assert 999.0 not in [b['high'] for b in hidden['bars']]

    print('V4 trading-day / hide-future replay causality: PASS')


if __name__ == '__main__':
    main()
