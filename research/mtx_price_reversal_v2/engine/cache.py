from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
from .data import iter_parquet_ticks, clean_mtx_ticks

FLOW_COLUMNS = ("trsv","dir_count","volume","trades")

def build_second_cache(parquet_path: Path, out_dir: Path) -> dict:
    """Deterministic seconds while preserving raw `_seq` for physical fills."""
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = out_dir / "_parts"; parts.mkdir(exist_ok=True)
    part_paths=[]; audit={"rows":0,"outright_mtx_rows":0,"outside_session_rows":0}
    for rg,batch in enumerate(iter_parquet_ticks(parquet_path)):
        audit["rows"] += len(batch.frame)
        x = clean_mtx_ticks(batch.frame)
        audit["outright_mtx_rows"] += len(x)
        if x.empty: continue
        x["trsv_trade"] = x["side"].astype(float) * x["volume_one_sided"].astype(float)
        x["ts"] = pd.to_datetime(x["datetime"]).astype("int64") // 1_000_000_000
        g=x.groupby(["expiry","session_key","session_kind","ts"], sort=False, observed=True)
        sec=g.agg(first_seq=("_seq","min"),last_seq=("_seq","max"),open=("price","first"),high=("price","max"),low=("price","min"),close=("price","last"),volume=("volume_one_sided","sum"),trsv=("trsv_trade","sum"),dir_count=("side","sum"),trades=("_seq","size")).reset_index()
        p=parts/f"rg_{rg:03d}.csv"; sec.to_csv(p,index=False); part_paths.append(p)
    expiries=set()
    for p in part_paths:
        expiries.update(pd.read_csv(p,usecols=["expiry"])["expiry"].astype(str).unique())
    for exp in sorted(expiries):
        chunks=[]
        for p in part_paths:
            z=pd.read_csv(p); z["expiry"]=z["expiry"].astype(str); z=z[z.expiry==exp]
            if not z.empty: chunks.append(z)
        if not chunks: continue
        x=pd.concat(chunks,ignore_index=True)
        rows=[]
        for _,z in x.groupby(["expiry","session_key","session_kind","ts"],sort=False,observed=True):
            z=z.sort_values("first_seq",kind="stable")
            rows.append({"expiry":exp,"session_key":z.session_key.iloc[0],"session_kind":z.session_kind.iloc[0],"ts":int(z.ts.iloc[0]),"first_seq":int(z.first_seq.min()),"last_seq":int(z.last_seq.max()),"open":float(z.loc[z.first_seq.idxmin(),"open"]),"high":float(z.high.max()),"low":float(z.low.min()),"close":float(z.loc[z.last_seq.idxmax(),"close"]),"volume":float(z.volume.sum()),"trsv":float(z.trsv.sum()),"dir_count":float(z.dir_count.sum()),"trades":int(z.trades.sum())})
        pd.DataFrame(rows).sort_values(["ts","first_seq"],kind="stable").to_csv(out_dir/f"{exp}.csv",index=False)
    (out_dir/"audit.json").write_text(json.dumps(audit,indent=2),encoding="utf-8")
    return audit
