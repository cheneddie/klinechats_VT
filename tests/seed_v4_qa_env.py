from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pyarrow as pa
import pyarrow.parquet as pq

from server.engine import connect
from server.v4_final_engine import migrate_v4_schema, write_events_v4


def node(answer, seq, time, price, reason, *, anchor_seq=None, anchor_time=None, anchor_price=None, metrics=None):
    return {
        'answer': bool(answer), 'seq': seq, 'time': time, 'decision_price': float(price),
        'anchor_seq': seq if anchor_seq is None else anchor_seq,
        'anchor_time': time if anchor_time is None else anchor_time,
        'anchor_price': float(price if anchor_price is None else anchor_price),
        'reason_code': reason, 'metrics': metrics or {}, 'schema_version': 4,
    }


def event(event_id, day, strategy, direction, seq0, entry_seq, entry_time, entry_price, stop, target, nodes, *, result='ENTRY'):
    return {
        'event_id': event_id, 'source_file': 'MTX_2025.parquet', 'year': 2025,
        'trading_date': day, 'contract': '202501', 'strategy': strategy, 'direction': direction,
        'result': result, 'difficulty': 2, 'attempt_start_seq': seq0,
        'attempt_start_time': nodes['AUC_ATTEMPT']['time'],
        'context_start_seq': max(0, seq0 - 10), 'context_end_seq': entry_seq + 20,
        'extreme_seq': nodes['AUC_EXTREME']['anchor_seq'], 'extreme_time': nodes['AUC_EXTREME']['anchor_time'],
        'extreme_price': nodes['AUC_EXTREME']['anchor_price'],
        'clear_reclaim_seq': nodes.get('MR_CLEAR_RECLAIM', {}).get('seq'),
        'clear_reclaim_time': nodes.get('MR_CLEAR_RECLAIM', {}).get('time'),
        'clear_reclaim_price': nodes.get('MR_CLEAR_RECLAIM', {}).get('decision_price'),
        'turn_confirm_seq': nodes.get('MR_RECLAIM_LEG', nodes.get('BO_IMPULSE_LEG', {})).get('seq'),
        'turn_confirm_time': nodes.get('MR_RECLAIM_LEG', nodes.get('BO_IMPULSE_LEG', {})).get('time'),
        'lvn': 100.0 if strategy == 'MR' else 110.0,
        'entry_seq': entry_seq, 'entry_time': entry_time, 'entry_price': float(entry_price),
        'stop': float(stop), 'target': float(target),
        'vah': 105.0, 'val': 95.0, 'poc': 100.0, 'value_width': 10.0,
        'features': {
            'node_schema_version': 4, 'scanner_version': 'V4.1-QA',
            'audit_universe_version': 'V4.1_RELAXED_TERMINAL', 'terminal_signal': True,
            'terminal_entry_seq': entry_seq, 'terminal_entry_price': float(entry_price),
            'terminal_stop': float(stop), 'strict_chain_complete': result == 'ENTRY',
        },
        'nodes': nodes,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', required=True)
    ap.add_argument('--db', required=True)
    ap.add_argument('--manifest', default='qa-artifacts/seed.json')
    args = ap.parse_args()
    root = Path(args.root); root.mkdir(parents=True, exist_ok=True)
    db = Path(args.db); db.parent.mkdir(parents=True, exist_ok=True)

    rows = [
        # Previous observed trading day + night session.
        ('2025-01-03 09:00:00', 100), ('2025-01-03 15:00:00', 101), ('2025-01-04 00:30:00', 102),
        # Monday MR YES opportunity.
        ('2025-01-06 08:45:00', 105), ('2025-01-06 09:00:00', 108), ('2025-01-06 09:00:05', 110),
        ('2025-01-06 09:00:10', 105), ('2025-01-06 09:00:15', 102), ('2025-01-06 09:00:20', 100),
        ('2025-01-06 09:00:25', 99), ('2025-01-06 09:00:30', 102), ('2025-01-06 09:00:35', 100),
        ('2025-01-06 09:00:40', 98), ('2025-01-06 09:01:00', 96), ('2025-01-06 09:02:00', 94),
        # Monday later MR NO/late-reentry opportunity.
        ('2025-01-06 10:00:00', 106), ('2025-01-06 10:00:10', 109), ('2025-01-06 10:01:20', 105),
        ('2025-01-06 10:01:30', 102), ('2025-01-06 10:02:00', 100), ('2025-01-06 10:03:00', 97),
        ('2025-01-06 13:45:00', 101), ('2025-01-06 15:00:00', 103), ('2025-01-06 23:00:00', 104),
        # Tuesday BO YES opportunity.
        ('2025-01-07 08:45:00', 104), ('2025-01-07 09:05:00', 106), ('2025-01-07 09:05:05', 110),
        ('2025-01-07 09:05:10', 113), ('2025-01-07 09:05:20', 114), ('2025-01-07 09:05:30', 113),
        ('2025-01-07 09:05:40', 112), ('2025-01-07 09:05:45', 114), ('2025-01-07 09:06:00', 116),
        ('2025-01-07 09:07:00', 119), ('2025-01-07 13:45:00', 118), ('2025-01-07 15:00:00', 117),
        # Wednesday anchors for +1 trading day replay.
        ('2025-01-08 08:45:00', 116), ('2025-01-08 09:00:00', 115), ('2025-01-08 13:45:00', 114),
    ]
    table = pa.table({
        'datetime': pa.array([x[0] for x in rows], type=pa.string()),
        'product': ['MTX'] * len(rows), 'expiry': ['202501'] * len(rows),
        'price': [float(x[1]) for x in rows], 'volume': [1] * len(rows), 'side': [0] * len(rows),
    })
    pq.write_table(table, root / 'MTX_2025.parquet', row_group_size=7)

    def n_common(start_seq, start_time, start_price, extreme_seq, extreme_time, extreme_price):
        return {
            'CTX_VALUE': node(True, start_seq, start_time, start_price, 'PROFILE_READY'),
            'AUC_ATTEMPT': node(True, start_seq, start_time, start_price, 'EXCURSION_PASS'),
            'AUC_EXTREME': node(True, extreme_seq + 1, extreme_time, extreme_price, 'EXTREME_LOCKED', anchor_seq=extreme_seq, anchor_time=extreme_time, anchor_price=extreme_price),
        }

    mr_yes = n_common(4, rows[4][0], rows[4][1], 5, rows[5][0], rows[5][1])
    mr_yes.update({
        'MR_REJECTION': node(True, 6, rows[6][0], rows[6][1], 'REENTERED_VALUE'),
        'MR_CLEAR_RECLAIM': node(True, 7, rows[7][0], rows[7][1], 'CLEAR_RECLAIM_PASS'),
        'MR_RECLAIM_LEG': node(True, 10, rows[10][0], rows[10][1], 'TURN_CONFIRMED'),
        'MR_LVN': node(True, 10, rows[10][0], 100, 'LVN_DEPTH_PASS'),
        'MR_PULLBACK': node(True, 11, rows[11][0], rows[11][1], 'FIRST_PULLBACK_PASS'),
        'MR_ENTRY': node(True, 11, rows[11][0], rows[11][1], 'ENTRY_QUALITY_PASS'),
        'WAIT_AMBIGUOUS': node(False, 7, rows[7][0], rows[7][1], 'BRANCH_RESOLVED'),
        'NO_TRADE': node(False, 11, rows[11][0], rows[11][1], 'EXECUTE_MR'),
    })
    e1 = event('QA-20250106-MR-YES', '2025-01-06', 'MR', 'short', 4, 11, rows[11][0], rows[11][1], 106, 95.5, mr_yes)

    mr_no = n_common(16, rows[16][0], rows[16][1], 17, rows[17][0], rows[17][1])
    mr_no.update({
        'MR_REJECTION': node(False, 18, rows[18][0], rows[18][1], 'REENTRY_TOO_LATE'),
        'MR_CLEAR_RECLAIM': node(False, 19, rows[19][0], rows[19][1], 'RECLAIM_TOO_LATE'),
        'MR_RECLAIM_LEG': node(True, 20, rows[20][0], rows[20][1], 'SHADOW_TURN_CONFIRMED'),
        'MR_LVN': node(True, 20, rows[20][0], 100, 'LVN_DEPTH_PASS'),
        'MR_PULLBACK': node(True, 20, rows[20][0], rows[20][1], 'FIRST_PULLBACK_PASS'),
        'MR_ENTRY': node(False, 20, rows[20][0], rows[20][1], 'UPSTREAM_GATE_FAIL'),
        'WAIT_AMBIGUOUS': node(False, 20, rows[20][0], rows[20][1], 'BRANCH_OBSERVED'),
        'NO_TRADE': node(True, 20, rows[20][0], rows[20][1], 'STRICT_REJECTION_FAIL'),
    })
    e2 = event('QA-20250106-MR-NO', '2025-01-06', 'MR', 'short', 16, 20, rows[20][0], rows[20][1], 106, 95.5, mr_no, result='OPPORTUNITY')

    bo = n_common(26, rows[26][0], rows[26][1], 28, rows[28][0], rows[28][1])
    bo.update({
        'MR_REJECTION': node(False, 29, rows[29][0], rows[29][1], 'NO_VALUE_REENTRY'),
        'BO_DISPLACEMENT': node(True, 28, rows[28][0], rows[28][1], 'DISPLACEMENT_PASS'),
        'BO_ACCEPTANCE': node(True, 30, rows[30][0], rows[30][1], 'ACCEPTANCE_PASS'),
        'BO_IMPULSE_LEG': node(True, 31, rows[31][0], rows[31][1], 'TURN_CONFIRMED'),
        'BO_LVN': node(True, 31, rows[31][0], 112, 'LVN_DEPTH_PASS'),
        'BO_PULLBACK': node(True, 32, rows[32][0], rows[32][1], 'FIRST_PULLBACK_PASS'),
        'BO_RESPONSE': node(True, 33, rows[33][0], rows[33][1], 'RESPONSE_PASS'),
        'BO_ENTRY': node(True, 33, rows[33][0], rows[33][1], 'ENTRY_QUALITY_PASS'),
        'WAIT_AMBIGUOUS': node(False, 30, rows[30][0], rows[30][1], 'BRANCH_RESOLVED'),
        'NO_TRADE': node(False, 33, rows[33][0], rows[33][1], 'EXECUTE_BO'),
    })
    e3 = event('QA-20250107-BO-YES', '2025-01-07', 'BO', 'long', 26, 33, rows[33][0], rows[33][1], 108, 120, bo)

    con = connect(db)
    try:
        migrate_v4_schema(con)
        write_events_v4(con, [e1, e2, e3], '2026-08-20T00:00:00+00:00')
        con.execute("INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)", (
            'MTX_2025.parquet', 2025, len(rows), rows[0][0], rows[-1][0], json.dumps(['MTX']), json.dumps(['202501']), 'PASS', '2026-08-20T00:00:00+00:00'
        ))
        con.commit()
    finally:
        con.close()

    manifest = Path(args.manifest); manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps({
        'data_root': str(root), 'db': str(db),
        'mr_yes': e1['event_id'], 'mr_no': e2['event_id'], 'bo_yes': e3['event_id']
    }, indent=2), encoding='utf-8')
    print(f'V4 QA seed: PASS ({len(rows)} rows, 3 events)')


if __name__ == '__main__':
    main()
