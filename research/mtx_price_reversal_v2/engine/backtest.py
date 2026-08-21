from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import math, re
import numpy as np
import pandas as pd
from .signal import full_session, price_signal, crossings

OUTRIGHT_RE=re.compile(r"^\d{6}$")

@dataclass(frozen=True)
class BacktestSpec:
    lookback_sec:int=30
    quantile:float=0.0005
    previous_contracts:int=3
    latency_after_confirmation_sec:int=1
    holding_sec:int=300
    friction_points:float=2.0

def _dist(path:Path,lookback:int)->np.ndarray:
    x=pd.read_csv(path); vals=[]
    for _,z in x.groupby("session_key",sort=False):
        s=full_session(z); a=price_signal(s,lookback).dropna().to_numpy(float)
        if len(a): vals.append(a)
    return np.concatenate(vals) if vals else np.array([],dtype=float)

def run_baseline(cache_dir:Path,spec:BacktestSpec=BacktestSpec())->pd.DataFrame:
    files={p.stem:p for p in cache_dir.glob("*.csv") if OUTRIGHT_RE.fullmatch(p.stem)}
    contracts=sorted(files); dcache={}; trades=[]; position_until=-math.inf
    for i,exp in enumerate(contracts):
        if i<spec.previous_contracts: continue
        prev=contracts[i-spec.previous_contracts:i]; train=[]
        for pexp in prev:
            dcache.setdefault(pexp,_dist(files[pexp],spec.lookback_sec))
            if len(dcache[pexp]): train.append(dcache[pexp])
        if not train: continue
        threshold=float(np.quantile(np.concatenate(train),spec.quantile))
        x=pd.read_csv(files[exp])
        for sk,z in x.groupby("session_key",sort=False):
            s=full_session(z); sig=price_signal(s,spec.lookback_sec)
            obs=s.index[s.observed].to_numpy(np.int64)
            for signal_ts in crossings(sig,threshold):
                earliest=int(signal_ts+1+spec.latency_after_confirmation_sec)
                j=int(np.searchsorted(obs,earliest,"left"))
                if j>=len(obs): continue
                entry_ts=int(obs[j])
                if entry_ts<=position_until: continue
                k=int(np.searchsorted(obs,entry_ts+spec.holding_sec,"left"))
                if k>=len(obs): continue
                exit_ts=int(obs[k]); er=s.loc[entry_ts]; xr=s.loc[exit_ts]
                gross=float(xr.open-er.open)
                path=s.loc[(s.index>=entry_ts)&(s.index<=exit_ts)&s.observed]
                trades.append({"contract":exp,"session_key":sk,"session_kind":str(z.session_kind.iloc[0]),"signal_ts":int(signal_ts),"signal_dt":pd.to_datetime(signal_ts,unit="s"),"threshold":threshold,"signal_value":float(sig.loc[signal_ts]),"entry_ts":entry_ts,"entry_dt":pd.to_datetime(entry_ts,unit="s"),"entry_seq":int(er.first_seq),"entry_price":float(er.open),"exit_ts":exit_ts,"exit_dt":pd.to_datetime(exit_ts,unit="s"),"exit_seq":int(xr.first_seq),"exit_price":float(xr.open),"gross":gross,"net":gross-spec.friction_points,"mfe":float(path.high.max()-er.open),"mae":float(path.low.min()-er.open)})
                position_until=exit_ts
    return pd.DataFrame(trades)
