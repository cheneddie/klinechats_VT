#!/usr/bin/env python3
"""Reproducible M3 causal-feature QA. Never sorts ticks; `_seq` is physical row order."""
from __future__ import annotations
import argparse,json
from pathlib import Path
import numpy as np,pandas as pd
from server.contracts import causal_front_month
from server.poc_absorption.bars import BAR_RESOLUTIONS,build_bars
from server.poc_absorption.features import FEATURE_SCHEMA_VERSION,compute_bar_features,compute_pressure_features,attach_pressure_features,compute_structural_high_zone_features
KEYS=['timeframe','session','bar_start_seq','bar_end_seq']

def bounds(day,session):
 d=pd.Timestamp(day)
 if session=='day': return d+pd.Timedelta(hours=8,minutes=45),d+pd.Timedelta(hours=13,minutes=45)
 if session=='night': return d-pd.Timedelta(days=1)+pd.Timedelta(hours=15),d+pd.Timedelta(hours=5)
 raise ValueError(session)

def read_ticks(path,dates,expiry,product='MTX',session='day'):
 import pyarrow.parquet as pq
 pf=pq.ParquetFile(path); windows=[bounds(d,session) for d in dates]; lo=min(x[0] for x in windows); hi=max(x[1] for x in windows)
 parts=[]; candidates={d:set() for d in dates}; off=0; materialized=0
 for rg in range(pf.metadata.num_row_groups):
  n=pf.metadata.row_group(rg).num_rows; st=pf.metadata.row_group(rg).column(0).statistics
  if st is not None and st.has_min_max and (pd.Timestamp(st.max)<lo or pd.Timestamp(st.min)>=hi): off+=n; continue
  f=pf.read_row_group(rg,columns=['datetime','product','expiry','price','volume','side']).to_pandas(); materialized+=len(f); dt=pd.to_datetime(f.datetime); pm=f['product'].astype(str).eq(product); ex=f['expiry'].astype(str)
  for d,(a,b) in zip(dates,windows):
   m=(dt>=a)&(dt<b)&pm
   if m.any(): candidates[d].update(ex[m].unique().tolist())
  keep=np.zeros(len(f),dtype=bool)
  for a,b in windows: keep|=((dt>=a)&(dt<b)).to_numpy()
  keep&=pm.to_numpy()&ex.eq(str(expiry)).to_numpy()
  if keep.any():
   ix=np.flatnonzero(keep); x=f.iloc[ix].copy(); x.insert(0,'_seq',off+ix); parts.append(x)
  off+=n
 if not parts: raise ValueError(f'No {product} {expiry} ticks for {dates}')
 t=pd.concat(parts,ignore_index=True); seq=t._seq.to_numpy(np.int64); dt=pd.to_datetime(t.datetime)
 if len(seq)>1 and np.any(np.diff(seq)<=0): raise AssertionError('physical _seq not strictly increasing')
 if len(dt)>1 and (dt.iloc[1:].to_numpy()<dt.iloc[:-1].to_numpy()).any(): raise AssertionError('datetime moved backward')
 checks={}
 for d in dates:
  legal=sorted(x for x in candidates[d] if len(x)==6 and x.isdigit()); strict=causal_front_month(d,legal); ok=strict==str(expiry); checks[d]={'candidate_outrights':legal,'strict_front_month':strict,'requested_expiry':str(expiry),'strict_matches_requested':ok}
  if not ok: raise AssertionError(f'{d}: strict={strict}, requested={expiry}')
 return t,{'parquet':str(path),'physical_rows':int(pf.metadata.num_rows),'row_groups':pf.metadata.num_row_groups,'row_group_rows_materialized':materialized,'selected_ticks':len(t),'first_seq':int(seq[0]),'last_seq':int(seq[-1]),'contract_checks':checks}

def joined(t,tf,session):
 bars=build_bars(t.drop(columns=['product','expiry','side'],errors='ignore'),tf,session,atr_period=14); bf=compute_bar_features(bars); p=compute_pressure_features(t,tf,session); x=attach_pressure_features(bf,p); s=compute_structural_high_zone_features(t,bf,lookback=24); return bars,bf,p,x.merge(s,on=KEYS,how='left',validate='one_to_one')

def bounded(frame):
 for c in frame.columns:
  if c.endswith('_share') or '_share_' in c:
   v=pd.to_numeric(frame[c],errors='coerce').dropna()
   if not v.between(0,1).all(): return False
 for c in ['tdp_ratio','tdp_signed_tick_ratio']+[x for x in frame if (x.startswith('high_zone_tdp_') or x.startswith('struct_high_zone_tdp_')) and not x.endswith('_z24')]:
  if c in frame:
   v=pd.to_numeric(frame[c],errors='coerce').dropna()
   if not v.between(-1,1).all(): return False
 return True

def validate_tf(t,tf,session):
 bars,bf,p,full=joined(t,tf,session); cut=min(len(bars),max(30,len(bars)//2)); pref=compute_bar_features(bars[:cut]); common=[c for c in pref if c in bf]
 prefix=bf.loc[:cut-1,common].reset_index(drop=True).equals(pref[common].reset_index(drop=True)); volume=np.allclose(full.tdp_positive_volume+full.tdp_negative_volume+full.tdp_neutral_volume,full.volume); forbidden=[c for c in full if any(k in c.lower() for k in ('aggress','cvd','footprint'))]
 ok=prefix and volume and bounded(full) and not forbidden and len(full)==len(bf)==len(p)
 return {'timeframe':tf,'ticks':len(t),'bars':len(full),'feature_columns':len(full.columns),'warm_feature_rows':int(full.ols_slope_close_24.notna().sum()),'structural_zone_rows':int(full.struct_high_zone_threshold_atr050.notna().sum()),'prefix_invariant':bool(prefix),'pressure_volume_partition':bool(volume),'bounded_shares_and_raw_tdp':bounded(full),'forbidden_semantic_columns':forbidden,'row_count_parity':len(full)==len(bf)==len(p),'all_pass':bool(ok)}

def continuity(t,tf,session):
 _,_,_,f=joined(t,tf,session); dates=pd.to_datetime(f.bar_start).dt.date.astype(str); changes=dates.ne(dates.shift(1)); gp=[];ga=[]
 for i in np.flatnonzero(changes.to_numpy())[1:]:
  gap=float(f.iloc[i].open-f.iloc[i-1].close); atr=float(f.iloc[i-1].atr_n) if pd.notna(f.iloc[i-1].atr_n) else np.nan; gp.append(gap); ga.append(gap/atr if np.isfinite(atr) and atr else np.nan)
 warm=int(f.ols_slope_close_24.notna().sum()); structural=int(f.struct_high_zone_threshold_atr050.notna().sum())
 return {'timeframe':tf,'bars':len(f),'dates':sorted(set(dates)),'warm_24_rows':warm,'structural_rows':structural,'cross_trading_day_boundaries':max(0,int(changes.sum())-1),'overnight_gap_points':gp,'overnight_gap_atr':ga,'slope_semantics':'trading_bar_sequence_not_wall_clock_normalized','all_pass':warm>0 and structural>0}

def self_test():
 rows=[];seq=0;start=pd.Timestamp('2026-08-03 08:45:00')
 for i in range(30):
  tm=start+pd.Timedelta(seconds=15*i);b=100.+i;rows += [(seq,tm,b,2.,1),(seq+1,tm+pd.Timedelta(seconds=1),b+1,3.,1),(seq+2,tm+pd.Timedelta(seconds=2),b,1.,-1)];seq+=3
 t=pd.DataFrame(rows,columns=['_seq','datetime','price','volume','side']);r=validate_tf(t,'15s','day');return {'schema_version':'POC_M3_QA_SELF_TEST_V1','feature_schema_version':FEATURE_SCHEMA_VERSION,'result':r,'all_pass':r['all_pass'] and r['warm_feature_rows']>0}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--parquet',type=Path);ap.add_argument('--cases',type=Path,default=Path('config/poc_absorption/m3_qa_cases_v1.json'));ap.add_argument('--timeframe',action='append',choices=sorted(BAR_RESOLUTIONS));ap.add_argument('--skip-continuity',action='store_true');ap.add_argument('--continuity-only',action='store_true');ap.add_argument('--self-test',action='store_true');ap.add_argument('--output',type=Path);a=ap.parse_args()
 if a.self_test:r=self_test()
 else:
  if not a.parquet: ap.error('--parquet required unless --self-test')
  if a.skip_continuity and a.continuity_only: ap.error('continuity flags conflict')
  c=json.loads(a.cases.read_text());session=c.get('session','day');product=c.get('product','MTX');pri=c['primary_case'];tfs=a.timeframe or pri['timeframes'];results=[];pm=None;cm=None;cr=None
  if not a.continuity_only:
   t,pm=read_ticks(a.parquet,[pri['date']],str(pri['expiry']),product,session);results=[validate_tf(t,tf,session) for tf in tfs]
  if not a.skip_continuity:
   cc=c['continuity_case'];t,cm=read_ticks(a.parquet,cc['dates'],str(cc['expiry']),product,session);cr=continuity(t,cc['timeframe'],session)
  gates=[x['all_pass'] for x in results]+([] if cr is None else [cr['all_pass']]);r={'schema_version':'POC_M3_REAL_QA_V1','feature_schema_version':FEATURE_SCHEMA_VERSION,'cases_file':str(a.cases),'selected_timeframes':[] if a.continuity_only else tfs,'primary_meta':pm,'timeframes':results,'continuity_meta':cm,'continuity':cr,'all_pass':bool(gates and all(gates))}
 txt=json.dumps(r,ensure_ascii=False,indent=2,default=str);print(txt)
 if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(txt+'\n')
 raise SystemExit(0 if r['all_pass'] else 2)
if __name__=='__main__':main()
