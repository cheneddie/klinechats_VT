from __future__ import annotations

import numpy as np
import pandas as pd

from server.poc_absorption.bars import build_bars
from server.poc_absorption.features import (
    compute_bar_features,
    compute_pressure_features,
    attach_pressure_features,
)


def ticks(rows):
    return pd.DataFrame(rows, columns=["_seq", "datetime", "price", "volume", "side"])


def make_bars(n=30):
    rows=[]
    seq=1
    for i in range(n):
        t=pd.Timestamp('2026-08-03 08:45:00')+pd.Timedelta(seconds=15*i)
        base=100+i
        rows += [(seq,t,base,2,1),(seq+1,t+pd.Timedelta(seconds=1),base+1,2,1),(seq+2,t+pd.Timedelta(seconds=2),base,2,-1)]
        seq += 3
    df=ticks(rows)
    return df, build_bars(df.drop(columns='side'), '15s','day',atr_period=3)


def test_completed_feature_prefix_is_future_invariant():
    _, bars=make_bars(30)
    full=compute_bar_features(bars)
    prefix=compute_bar_features(bars[:20])
    common=[c for c in prefix.columns if c in full.columns]
    pd.testing.assert_frame_equal(full.loc[:19,common].reset_index(drop=True),prefix[common].reset_index(drop=True),check_dtype=False)


def test_rising_bars_produce_positive_trend_and_poc_velocity():
    _, bars=make_bars(30)
    f=compute_bar_features(bars)
    row=f.iloc[-1]
    assert row['ols_slope_close_6'] > 0
    assert row['higher_high_ratio_6'] == 1.0
    assert row['poc_velocity_2'] > 0
    assert row['channel_width_6'] > 0


def test_pressure_feature_math_and_names_are_tdp_proxy_only():
    df=ticks([
        (1,'2026-08-03 08:45:00',100,10,1),
        (2,'2026-08-03 08:45:01',101,20,1),
        (3,'2026-08-03 08:45:02',102,5,-1),
        (4,'2026-08-03 08:45:03',102,5,0),
    ])
    p=compute_pressure_features(df,'15s','day').iloc[0]
    assert p['tdp_total_volume'] == 40
    assert p['tdp_signed_volume'] == 25
    assert p['tdp_positive_volume'] == 30
    assert np.isclose(p['tdp_ratio'],25/40)
    assert p['high_zone_positive_volume_q80'] == 0
    assert p['high_zone_negative_volume_q80'] == 5
    assert not any('aggress' in c.lower() or 'cvd' in c.lower() for c in p.index)


def test_pressure_prefix_bars_do_not_change_when_later_bar_is_mutated():
    df=ticks([
        (1,'2026-08-03 08:45:00',100,10,1),
        (2,'2026-08-03 08:45:10',101,10,-1),
        (3,'2026-08-03 08:45:15',102,10,1),
        (4,'2026-08-03 08:45:20',103,10,1),
    ])
    p1=compute_pressure_features(df,'15s','day')
    mutated=df.copy();mutated.loc[2:,'price'] += 10000;mutated.loc[2:,'volume'] *= 1000
    p2=compute_pressure_features(mutated,'15s','day')
    pd.testing.assert_series_equal(p1.iloc[0],p2.iloc[0],check_names=False)


def test_pressure_join_uses_exact_seq_boundaries():
    df,bars=make_bars(30)
    bf=compute_bar_features(bars)
    pf=compute_pressure_features(df,'15s','day')
    joined=attach_pressure_features(bf,pf)
    assert len(joined)==len(bf)==len(pf)
    assert joined['tdp_total_volume'].notna().all()
    assert np.allclose(joined['tdp_total_volume'],joined['volume'])


def test_structural_high_zone_uses_completed_rolling_high_and_atr():
    from server.poc_absorption.features import compute_structural_high_zone_features
    df,bars=make_bars(30)
    bf=compute_bar_features(bars)
    sf=compute_structural_high_zone_features(df,bf,lookback=24,atr_multipliers=(0.5,))
    assert len(sf)==len(bf)
    assert sf['struct_high_zone_threshold_atr050'].iloc[:23].isna().all()
    assert sf['struct_high_zone_volume_atr050'].iloc[23:].notna().all()
    assert (sf['struct_high_zone_volume_share_atr050'].dropna().between(0,1)).all()
