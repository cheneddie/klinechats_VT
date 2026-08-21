from __future__ import annotations

import numpy as np
import pandas as pd

from server.poc_absorption.universe import (
    EVENT_SCHEMA_VERSION,
    UNIVERSE_VERSION,
    UNIVERSE_SCHEMA_VERSION,
    HighPriceProbeConfig,
    build_high_price_probe_universe,
    first_trigger_per_episode,
)


def make_frame(n=48, drop_at=None, split_day_at=None):
    rows=[]; ticks=[]
    start=pd.Timestamp('2026-08-03 08:45:00')
    for i in range(n):
        base=100.0 + 0.5*i
        if drop_at is not None and i == drop_at:
            base -= 8.0
        if drop_at is not None and i > drop_at:
            base = 100.0 + 0.5*i
        seq=i*3
        bt=start+pd.Timedelta(minutes=i)
        o=base-0.5; h=base+1.0; l=base-1.0; c=base+0.5
        td='2026-08-03' if split_day_at is None or i < split_day_at else '2026-08-04'
        rows.append({
            'feature_schema_version':'POC_CONTINUOUS_FEATURES_V1',
            'timeframe':'1m','session':'day','bar_start':bt,'trading_date':td,
            'bar_start_seq':seq,'bar_end_seq':seq+2,
            'open':o,'high':h,'low':l,'close':c,'atr_n':2.0,
            'poc_delta_1':float((-1)**i * i),
            'tdp_ratio':float(np.sin(i)),
            'impact_per_1000_positive_volume':float(i*100),
        })
        ticks += [
            (seq,bt,o),(seq+1,bt+pd.Timedelta(seconds=20),h),(seq+2,bt+pd.Timedelta(seconds=40),c),
        ]
    return pd.DataFrame(rows),pd.DataFrame(ticks,columns=['_seq','datetime','price'])


def build(frame,ticks,cfg=None):
    return build_high_price_probe_universe(
        frame,ticks,dataset_id='SYNTH',contract='202608',partition_id='p1',
        config=cfg or HighPriceProbeConfig(lookback_bars=6,max_episode_seconds=600),
    )


def test_non_price_features_cannot_change_universe_membership_or_episode_ids():
    f,t=make_frame(36)
    a=build(f,t)
    m=f.copy(); m['poc_delta_1']=1e9; m['tdp_ratio']=-999
    m['impact_per_1000_positive_volume']=np.arange(len(m))[::-1]*-1e6
    b=build(m,t)
    assert a.triggers['event_id'].tolist()==b.triggers['event_id'].tolist()
    assert a.triggers['episode_id'].tolist()==b.triggers['episode_id'].tolist()
    assert a.triggers['trigger_seq'].tolist()==b.triggers['trigger_seq'].tolist()
    assert set(a.triggers['event_schema_version']) == {EVENT_SCHEMA_VERSION}
    assert set(a.triggers['universe_version']) == {UNIVERSE_VERSION}
    assert set(a.triggers['universe_schema_version']) == {UNIVERSE_SCHEMA_VERSION}
    assert a.triggers['universe_config_hash'].nunique() == 1
    assert a.triggers['feature_snapshot'].map(type).eq(dict).all()


def test_future_price_mutation_cannot_change_prior_triggers():
    f,t=make_frame(40)
    a=build(f,t)
    cutoff_seq=74
    fm=f.copy(); tm=t.copy()
    mask=fm['bar_end_seq']>cutoff_seq
    fm.loc[mask,['open','high','low','close']]+=5000
    tm.loc[tm['_seq']>cutoff_seq,'price']+=5000
    b=build(fm,tm)
    pa=a.triggers[a.triggers.trigger_seq<=cutoff_seq][['event_id','episode_id','trigger_seq']].reset_index(drop=True)
    pb=b.triggers[b.triggers.trigger_seq<=cutoff_seq][['event_id','episode_id','trigger_seq']].reset_index(drop=True)
    pd.testing.assert_frame_equal(pa,pb)


def test_raw_triggers_are_retained_and_first_trigger_view_does_not_delete_store():
    f,t=make_frame(36)
    r=build(f,t)
    assert len(r.triggers)>len(r.episodes)>0
    raw_count=len(r.triggers); first=first_trigger_per_episode(r.triggers)
    assert len(first)==len(r.episodes)
    assert (first.episode_trigger_number==1).all()
    assert len(r.triggers)==raw_count


def test_episode_resets_after_price_exit_and_trading_day_boundary():
    f,t=make_frame(40,drop_at=20)
    cfg=HighPriceProbeConfig(lookback_bars=6,episode_exit_atr=0.5,max_episode_seconds=3600)
    r=build(f,t,cfg)
    assert len(r.episodes)>=2
    assert 'PRICE_EXIT_ATR' in set(r.episodes.episode_end_reason)
    f2,t2=make_frame(40,split_day_at=25)
    r2=build(f2,t2,HighPriceProbeConfig(lookback_bars=6,max_episode_seconds=3600))
    assert 'TRADING_DAY_RESET' in set(r2.episodes.episode_end_reason)
    assert not (r2.episodes.episode_start_trading_date != r2.episodes.last_trigger_trading_date).any()
    d=(pd.to_datetime(r2.episodes.episode_end_time)-pd.to_datetime(r2.episodes.episode_start_time)).dt.total_seconds()
    assert (d <= 3600).all()

    # Timeout metadata must close at the frozen deadline itself, even when the
    # next completed bar arrives later. Trigger membership is unchanged.
    f3,t3=make_frame(30)
    r3=build(f3,t3,HighPriceProbeConfig(lookback_bars=6,max_episode_seconds=300,episode_exit_atr=99.0))
    timed=r3.episodes[r3.episodes.episode_end_reason.eq('MAX_EPISODE_SECONDS')]
    assert len(timed)>0
    td=(pd.to_datetime(timed.episode_end_time)-pd.to_datetime(timed.episode_start_time)).dt.total_seconds()
    assert (td == 300).all()


def test_decision_time_and_price_are_exact_physical_end_tick():
    f,t=make_frame(30)
    r=build(f,t)
    assert len(r.triggers)>0
    lookup=t.set_index('_seq')
    for row in r.triggers.itertuples(index=False):
        tick=lookup.loc[row.trigger_seq]
        assert pd.Timestamp(row.trigger_time)==pd.Timestamp(tick.datetime)
        assert row.trigger_price==tick.price==row.close
        assert row.bar_end_seq == row.trigger_seq


def test_ids_are_deterministic_and_unique():
    f,t=make_frame(36)
    a=build(f,t); b=build(f,t)
    assert a.triggers.event_id.tolist()==b.triggers.event_id.tolist()
    assert a.episodes.episode_id.tolist()==b.episodes.episode_id.tolist()
    assert a.triggers.event_id.is_unique
    assert a.episodes.episode_id.is_unique
