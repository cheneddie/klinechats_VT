from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pandas as pd

# Import release adapter first: it patches strict BO execution to response time.
from server import v4_release_engine as release
from server import v4_final_engine as core


def frame(prices, volumes=None):
    base = pd.Timestamp('2025-01-02 09:00:00')
    if volumes is None:
        volumes = [1.0] * len(prices)
    return pd.DataFrame({
        '_seq': range(len(prices)),
        'dt': [base + pd.Timedelta(seconds=i) for i in range(len(prices))],
        'price': [float(x) for x in prices],
        'volume': [float(x) for x in volumes],
        'side': [0] * len(prices),
    })


def main():
    prior = {'vah': 100.0, 'val': 0.0, 'poc': 50.0, 'width': 100.0}
    fake = Path('MTX_2025.parquet')
    cfg = release.ScanConfigV4Final(auction_max_sec=30, turn_points=2, acceptance_window_sec=10)

    # Qualified Auction (>=2pt) but nowhere near 20pt displacement.
    weak = frame([101, 102, 103] + [103] * 35)
    events = release.scan_day_v4_final(weak, prior, cfg, fake, '2025-01-02', '202501')
    bo = [e for e in events if e['strategy'] == 'BO']
    assert bo, 'Every qualified auction must emit a BO research candidate'
    assert bo[0]['nodes']['AUC_ATTEMPT']['answer'] is True
    assert bo[0]['nodes']['BO_DISPLACEMENT']['answer'] is False, bo[0]['nodes']['BO_DISPLACEMENT']

    # Patch only LVN discovery so this unit test isolates universe/gate semantics.
    old_leg_valley = core._best_valley_leg
    old_mr_valley = core._best_valley
    try:
        core._best_valley_leg = lambda leg: (106.0, 0.80)
        core._best_valley = lambda leg, prior: (95.0, 0.80)

        # BO: broad Pullback terminal exists, but no 2pt response in 30s.
        prices = [101, 103, 105, 107, 109, 110, 109, 108, 107, 106]
        prices += [106, 107, 106, 107] * 12
        g = frame(prices)
        e = core._build_bo(
            g, prior, cfg, fake, '2025-01-02', '202501', 1,
            0, 1, 5, 110.0, 100.0, True, None, None, None, 20,
        )
        assert e['features']['terminal_signal'] is True, e['features']
        assert e['nodes']['BO_DISPLACEMENT']['answer'] is False
        assert e['nodes']['BO_RESPONSE']['answer'] is False
        assert e['result'] != 'ENTRY', 'Response=NO must not become strict BO entry'

        # MR: strict Rejection misses the <=60s rule, but a relaxed late re-entry
        # may still form an audit terminal opportunity.  This is exactly what lets
        # the reverse audit measure whether the time gate kills winners/losers.
        prices = [110.0] * 70
        prices += [100, 98, 96, 94, 92, 90, 92, 94, 95]
        prices += [95] * 20
        g2 = frame(prices)
        e2 = core._build_mr(
            g2, prior, cfg, fake, '2025-01-02', '202501', 2,
            0, 1, 1, 110.0, 100.0, True,
            None, 70, None, 30,
        )
        assert e2['nodes']['MR_REJECTION']['answer'] is False
        assert e2['features']['terminal_signal'] is True, e2['features']
        assert e2['result'] != 'ENTRY'

        # Strict BO: terminal audit anchor is Pullback touch, while true strategy
        # entry waits for Response.  They must be different physical rows.
        prices = [101, 103, 105, 107, 109, 110, 109, 108, 107, 106, 107, 108]
        prices += [108] * 20
        g3 = frame(prices)
        e3 = core._build_bo(
            g3, prior, cfg, fake, '2025-01-02', '202501', 3,
            0, 1, 5, 110.0, 100.0, True, None, None, 2, 20,
        )
        # Direct helper sets acceptance from observed prices; if strict chain passes
        # the release adapter must place actual entry at/after response.
        if e3['result'] == 'ENTRY':
            assert e3['features']['terminal_entry_seq'] < e3['entry_seq'], (e3['features'], e3['entry_seq'])
            assert e3['entry_seq'] == e3['nodes']['BO_RESPONSE']['seq']
            assert e3['nodes']['BO_ENTRY']['seq'] == e3['nodes']['BO_RESPONSE']['seq']
    finally:
        core._best_valley_leg = old_leg_valley
        core._best_valley = old_mr_valley

    print('V4 unbiased terminal universe: PASS')


if __name__ == '__main__':
    main()
