from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from .engine import _to_dt, _txt, OUTRIGHT_RE

TIMEFRAME_RULES={"1s":"1s","5s":"5s","15s":"15s","30s":"30s","1m":"1min","3m":"3min","5m":"5min","15m":"15min","30m":"30min"}


def _date_index(path:Path,product="MTX",contract=None):
    pf=pq.ParquetFile(path);dates=[];seen=set()
    for rg in range(pf.num_row_groups):
        d=pf.read_row_group(rg,columns=["datetime","product","expiry"]).to_pandas();d["product"]=d["product"].map(_txt);d["expiry"]=d["expiry"].map(_txt);dt=_to_dt(d["datetime"]);mask=d["product"].eq(product)&d["expiry"].str.match(OUTRIGHT_RE)
        if contract:mask&=d["expiry"].eq(str(contract))
        for x in dt.loc[mask].dt.strftime("%Y-%m-%d").drop_duplicates():
            if x not in seen:dates.append(x);seen.add(x)
    return dates


def _target_dates(path:Path,center_day:str,before=1,after=1,contract=None):
    dates=_date_index(path,contract=contract)
    if not dates:return[center_day]
    if center_day not in dates:
        vals=[pd.Timestamp(x) for x in dates];c=pd.Timestamp(center_day);i=min(range(len(vals)),key=lambda j:abs(vals[j]-c))
    else:i=dates.index(center_day)
    lo=max(0,i-max(0,int(before)));hi=min(len(dates),i+max(0,int(after))+1);return dates[lo:hi]


def _read_dates(path:Path,target_dates:list[str],contract:str,session="full"):
    pf=pq.ParquetFile(path);wanted=set(target_dates);parts=[];offset=0
    for rg in range(pf.num_row_groups):
        count=int(pf.metadata.row_group(rg).num_rows);d=pf.read_row_group(rg,columns=["datetime","product","expiry","price","volume","side"]).to_pandas();d["_seq"]=np.arange(offset,offset+count,dtype=np.int64);offset+=count;d["product"]=d["product"].map(_txt);d["expiry"]=d["expiry"].map(_txt);d["dt"]=_to_dt(d["datetime"]);d["date"]=d["dt"].dt.strftime("%Y-%m-%d");mask=d["product"].eq("MTX")&d["expiry"].eq(str(contract))&d["date"].isin(wanted)
        if session=="day":
            sec=d["dt"].dt.hour*3600+d["dt"].dt.minute*60+d["dt"].dt.second;mask&=(sec>=8*3600+45*60)&(sec<=13*3600+45*60)
        x=d.loc[mask]
        if not x.empty:parts.append(x)
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()


def aggregate_bars(d:pd.DataFrame,timeframe="1s"):
    if d.empty:return[]
    rule=TIMEFRAME_RULES.get(timeframe)
    if not rule:raise ValueError(f"unsupported timeframe: {timeframe}")
    bucket=d["dt"].dt.floor(rule);rows=[]
    for ts,b in d.groupby(bucket,sort=False):
        rows.append({"timestamp":int(pd.Timestamp(ts).value//1_000_000),"open":float(b["price"].iloc[0]),"high":float(b["price"].max()),"low":float(b["price"].min()),"close":float(b["price"].iloc[-1]),"volume":float(b["volume"].sum()),"firstSeq":int(b["_seq"].iloc[0]),"lastSeq":int(b["_seq"].iloc[-1])})
    return rows


def replay_trading_window(root:Path,event:dict,node_meta:dict|None=None,node_id:str|None=None,before=1,after=1,timeframe="1s",session="full"):
    source=event.get("source_file")
    if not source:return{"bars":[],"dates":[]}
    path=root/source
    if not path.exists():return{"bars":[],"dates":[]}
    center=event.get("trading_date") or event.get("date")
    if node_id and node_meta and node_id in node_meta:
        t=node_meta[node_id].get("decision_time") or node_meta[node_id].get("anchor_time")
        if t:center=str(t)[:10]
    dates=_target_dates(path,str(center)[:10],before,after,event.get("contract"));d=_read_dates(path,dates,str(event.get("contract")),session=session);bars=aggregate_bars(d,timeframe=timeframe)
    return{"bars":bars,"dates":dates,"timeframe":timeframe,"session":session,"source_rows":int(len(d)),"first_seq":int(d["_seq"].iloc[0]) if len(d) else None,"last_seq":int(d["_seq"].iloc[-1]) if len(d) else None}


def read_tick_path(root:Path,event:dict,start_seq:int,max_dates_after=1):
    source=event.get("source_file");path=root/source
    if not path.exists():return pd.DataFrame()
    center=event.get("trading_date") or event.get("date");dates=_target_dates(path,str(center)[:10],0,max_dates_after,event.get("contract"));d=_read_dates(path,dates,str(event.get("contract")),session="full")
    if d.empty:return d
    return d.loc[d["_seq"]>=int(start_seq)].reset_index(drop=True)
