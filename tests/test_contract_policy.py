from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.contracts import causal_front_month, choose_contracts, third_wednesday


def test_third_wednesday_2025_03():
    assert third_wednesday(2025, 3).isoformat() == '2025-03-19'


def test_expiry_day_stays_expiring_month():
    assert causal_front_month('2025-03-19', ['202503', '202504']) == '202503'


def test_day_after_expiry_rolls_next_month():
    assert causal_front_month('2025-03-20', ['202503', '202504']) == '202504'


def test_strict_ignores_completed_day_volume_rank():
    volume_map = {
        '2025-03-18': {'202503': 100.0, '202504': 100000.0},
        '2025-03-19': {'202503': 50.0, '202504': 200000.0},
        '2025-03-20': {'202503': 300000.0, '202504': 10.0},
    }
    out = choose_contracts(volume_map, 'strict')
    assert out['2025-03-18']['contract'] == '202503'
    assert out['2025-03-19']['contract'] == '202503'
    assert out['2025-03-20']['contract'] == '202504'
    assert all(x['causal'] for x in out.values())


def test_no_stale_expired_fallback():
    assert causal_front_month('2025-03-20', ['202503']) is None


if __name__ == '__main__':
    test_third_wednesday_2025_03()
    test_expiry_day_stays_expiring_month()
    test_day_after_expiry_rolls_next_month()
    test_strict_ignores_completed_day_volume_rank()
    test_no_stale_expired_fallback()
    print('contract policy tests: PASS')
