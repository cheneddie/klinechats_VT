from pathlib import Path
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pyarrow as pa
import pyarrow.parquet as pq
import server.fabio_api as api


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / 'MTX_2025.parquet'
        table = pa.table({
            'price': [100.0, 102.0, 101.0, 105.0, 103.0, 107.0],
            'datetime': [1, 1, 1, 2, 2, 2],
            'product': ['MTX'] * 6,
            'expiry': ['202501'] * 6,
            'volume': [1] * 6,
            'side': [0] * 6,
        })
        pq.write_table(table, path, row_group_size=3)
        old_root = api.ROOT
        api.ROOT = root
        try:
            event = {'source_file': path.name}
            meta = {
                'AUC_ATTEMPT': {'decision_seq': 1, 'decision_time': '2025-01-01T09:00:00'},
                'AUC_EXTREME': {'decision_seq': 2, 'decision_time': '2025-01-01T09:00:00'},
                'MR_CLEAR_RECLAIM': {'decision_seq': 4, 'decision_time': '2025-01-01T09:00:01'},
                'NO_TRADE': {'decision_seq': None, 'decision_time': None},
            }
            out = api.enrich_exact_decision_prices(event, meta)
            assert out['AUC_ATTEMPT']['decision_price'] == 102.0
            assert out['AUC_EXTREME']['decision_price'] == 101.0
            assert out['MR_CLEAR_RECLAIM']['decision_price'] == 103.0
            assert out['AUC_ATTEMPT']['price_source'] == 'physical_seq'
            assert 'decision_price' not in out['NO_TRADE']
        finally:
            api.ROOT = old_root
    print('exact decision price tests: PASS')


if __name__ == '__main__':
    main()
