#!/usr/bin/env python3
"""Build Fabio Replay Trainer fixtures from MTX Tick Parquet.

Hard data-integrity rules:
1. Add `_seq` immediately after read and NEVER sort the Tick rows.
2. Filter product / outright contract / spread exclusion with boolean masks only.
3. Same-second trades retain their physical file order.
4. `side` is not treated as Bid/Ask aggressor information.

This extractor is for replay/training-case generation. It is not the research
optimizer used to discover or validate the frozen V3/V4 strategy parameters.
"""
from __future__ import annotations
import argparse, json, re
from pathlib import Path
import numpy as np
import pandas as pd


def text(v):
    if isinstance(v,(bytes,bytearray)): return v.decode('utf-8','replace')
    return str(v)


def profile_levels(g: pd.DataFrame, va_pct: float=0.80):
    vol=g.groupby('price',sort=True)['volume'].sum()
    prices=vol.index.to_numpy(float); vv=vol.to_numpy(float)
    poc_i=int(np.argmax(vv)); lo=hi=poc_i; total=float(vv[poc_i]); target=float(vv.sum()*va_pct)
    while total<target and (lo>0 or hi<len(vv)-1):
        lv=vv[lo-1] if lo>0 else -1; rv=vv[hi+1] if hi<len(vv)-1 else -1
        if rv>lv: hi+=1; total+=float(vv[hi])
        else: lo-=1; total+=float(vv[lo])
    return {'poc':float(prices[poc_i]),'val':float(prices[lo]),'vah':float(prices[hi]),'width':float(prices[hi]-prices[lo])}


def bars(g: pd.DataFrame, rule: str):
    result=[]
    # sort=False is intentional. Tick rows inside each bucket stay in physical order.
    for ts,b in g.groupby(g['dt'].dt.floor(rule),sort=False):
        if b.empty: continue
        result.append({'timestamp':int(ts.value//1_000_000),'open':float(b.price.iloc[0]),'high':float(b.price.max()),'low':float(b.price.min()),'close':float(b.price.iloc[-1]),'volume':float(b.volume.sum()),'firstSeq':int(b._seq.iloc[0]),'lastSeq':int(b._seq.iloc[-1])})
    return result


def leg_lvn(leg: pd.DataFrame, prior: dict):
    if len(leg)<10: return None
    pv=leg.groupby('price',sort=True)['volume'].sum(); prices=pv.index.to_numpy(float); vols=pv.to_numpy(float)
    if len(prices)<5:return None
    sm=np.convolve(vols,np.ones(3)/3,mode='same'); lo=prior['val']+.05*prior['width']; hi=prior['vah']-.05*prior['width']
    c=[]
    for i in range(2,len(prices)-2):
        if not(lo<=prices[i]<=hi):continue
        if sm[i]<=sm[i-1] and sm[i]<=sm[i+1]:
            ref=min(max(sm[i-2:i]),max(sm[i+1:i+3]))
            if ref>0 and 1-sm[i]/ref>=.55:c.append((1-sm[i]/ref,float(prices[i])))
    if c:return max(c)[1]
    valid=[i for i in range(1,len(prices)-1) if lo<=prices[i]<=hi]
    if not valid:return None
    q=np.quantile(sm[valid],.30); low=[i for i in valid if sm[i]<=q]
    return float(prices[min(low,key=lambda i:sm[i])]) if low else None


def find_cases(g: pd.DataFrame,date: str,prior_date: str,prior: dict):
    cases=[]; early=g[(g.secs>=8*3600+45*60)&(g.secs<=9*3600+30*60)].copy()
    if early.empty or prior['width']<=0:return cases
    exc=max(2.0,.02*prior['width']); reclaim=max(3.0,.08*prior['width'])
    start_i=int(early.index.min()); last_i=int(early.index.max()); i=start_i; attempt=0
    while i<=last_i:
        p=float(g.price.iloc[i]); outside=p>prior['vah'] or p<prior['val']
        if not outside:i+=1;continue
        direction='up' if p>prior['vah'] else 'down'; boundary=prior['vah'] if direction=='up' else prior['val']; attempt+=1
        start=i; extreme=p; extreme_i=i; j=i+1; clear_i=None; t0=g.dt.iloc[start]
        while j<=last_i and (g.dt.iloc[j]-t0).total_seconds()<=180:
            pj=float(g.price.iloc[j])
            if direction=='up' and pj>extreme:extreme=pj;extreme_i=j
            if direction=='down' and pj<extreme:extreme=pj;extreme_i=j
            enough=(extreme-boundary>=exc) if direction=='up' else (boundary-extreme>=exc)
            sec=(g.dt.iloc[j]-g.dt.iloc[extreme_i]).total_seconds()
            if enough and sec<=60:
                if direction=='up' and pj<=boundary-reclaim:clear_i=j;break
                if direction=='down' and pj>=boundary+reclaim:clear_i=j;break
            j+=1
        if clear_i is None:
            h=g.iloc[start:min(last_i+1,start+5000)];h=h[h.dt<=t0+pd.Timedelta(seconds=60)]
            if len(h)>20:
                out=float((h.price>prior['vah']).mean()) if direction=='up' else float((h.price<prior['val']).mean())
                disp=float(h.price.max()-prior['vah']) if direction=='up' else float(prior['val']-h.price.min())
                if out>=.75 and disp>=max(exc,.05*prior['width']):
                    cases.append({'id':f'{date}-BO-{attempt}','date':date,'strategy':'BO','label':'突破回測｜搬家','direction':'long' if direction=='up' else 'short','priorDate':prior_date,'priorProfile':prior,'attemptStartSeq':int(g._seq.iloc[start]),'attemptStartTime':g.dt.iloc[start].isoformat(),'extremeTime':h.dt.iloc[-1].isoformat(),'extremePrice':float(h.price.iloc[-1]),'outsideRatio60s':out,'displacement60s':disp,'answerPath':['AUCTION_YES','REJECTION_NO','ACCEPTANCE_YES','DISPLACEMENT_YES','IMPULSE_LEG_WAIT']})
            i=max(j+1,i+1);continue
        trade_dir='short' if direction=='up' else 'long'; k=clear_i; leg_ext=float(g.price.iloc[k]); leg_end=k; confirm=None
        while k<len(g) and (g.dt.iloc[k]-g.dt.iloc[clear_i]).total_seconds()<=600:
            pk=float(g.price.iloc[k])
            if trade_dir=='short':
                if pk<leg_ext:leg_ext=pk;leg_end=k
                if pk>=leg_ext+8:confirm=k;break
            else:
                if pk>leg_ext:leg_ext=pk;leg_end=k
                if pk<=leg_ext-8:confirm=k;break
            k+=1
        lvn=entry_i=None
        if confirm is not None:
            leg=g.iloc[min(extreme_i,leg_end):max(extreme_i,leg_end)+1];lvn=leg_lvn(leg,prior)
            if lvn is not None:
                k=confirm+1;limit=g.dt.iloc[confirm]+pd.Timedelta(minutes=20)
                while k<len(g) and g.dt.iloc[k]<=limit:
                    if abs(float(g.price.iloc[k])-lvn)<=1:entry_i=k;break
                    k+=1
        case={'id':f'{date}-MR-{attempt}','date':date,'strategy':'MR','label':'均值回歸｜回家','direction':trade_dir,'priorDate':prior_date,'priorProfile':prior,'attemptStartSeq':int(g._seq.iloc[start]),'attemptStartTime':g.dt.iloc[start].isoformat(),'extremeSeq':int(g._seq.iloc[extreme_i]),'extremeTime':g.dt.iloc[extreme_i].isoformat(),'extremePrice':float(extreme),'clearReclaimSeq':int(g._seq.iloc[clear_i]),'clearReclaimTime':g.dt.iloc[clear_i].isoformat(),'clearReclaimPrice':float(g.price.iloc[clear_i]),'turnConfirmSeq':int(g._seq.iloc[confirm]) if confirm is not None else None,'turnConfirmTime':g.dt.iloc[confirm].isoformat() if confirm is not None else None,'lvn':lvn,'entrySeq':int(g._seq.iloc[entry_i]) if entry_i is not None else None,'entryTime':g.dt.iloc[entry_i].isoformat() if entry_i is not None else None,'entryPrice':float(g.price.iloc[entry_i]) if entry_i is not None else None,'answerPath':['AUCTION_YES','REJECTION_YES','CLEAR_RECLAIM_YES','LEG_YES','LVN_YES']+(['PULLBACK_YES','EXECUTE_MR'] if entry_i is not None else ['PULLBACK_NO','WAIT'])}
        if entry_i is not None:
            ep=float(g.price.iloc[entry_i]);case['stop']=lvn+6 if trade_dir=='short' else lvn-6;case['target']=ep-.75*(case['stop']-ep) if trade_dir=='short' else ep+.75*(ep-case['stop'])
        cases.append(case);i=clear_i+1
    return cases


def main():
    ap=argparse.ArgumentParser();ap.add_argument('parquet',type=Path);ap.add_argument('-o','--output',type=Path,default=Path('public/data/mtx_replay.json'));ap.add_argument('--product',default='MTX');ap.add_argument('--expiry-pattern',default=r'^\d{6}$');args=ap.parse_args()
    cols=['datetime','product','expiry','price','volume','side'];df=pd.read_parquet(args.parquet,columns=cols);df['_seq']=np.arange(len(df),dtype=np.int64)
    df['product']=df.product.map(text);df['expiry']=df.expiry.map(text)
    mask=(df.product==args.product)&df.expiry.str.match(args.expiry_pattern)&~df.expiry.str.contains('/',regex=False)
    df=df.loc[mask].copy()  # Boolean filtering preserves original row order. DO NOT sort.
    if not df['_seq'].is_monotonic_increasing:raise RuntimeError('physical source order was changed')
    df['dt']=pd.to_datetime(df.datetime) if pd.api.types.is_datetime64_any_dtype(df.datetime) else pd.to_datetime(df.datetime,unit='us')
    if not df.dt.is_monotonic_increasing:raise RuntimeError('timestamp reverses in physical source order')
    df['secs']=df.dt.dt.hour*3600+df.dt.dt.minute*60+df.dt.dt.second;df['date']=df.dt.dt.strftime('%Y-%m-%d')
    day=df[(df.secs>=8*3600+45*60)&(df.secs<=13*3600+45*60)].copy();dates=list(day.date.drop_duplicates());profiles={d:profile_levels(day[day.date==d]) for d in dates};sessions={};cases=[]
    for i,d in enumerate(dates):
        g=day[day.date==d].reset_index(drop=True);sessions[d]={'date':d,'bars':bars(g,'1min'),'profile':profiles[d]}
        if i:
            pdte=dates[i-1];sessions[d]['priorDate']=pdte;sessions[d]['priorProfile']=profiles[pdte];cases.extend(find_cases(g,d,pdte,profiles[pdte]))
    meta={'sourceFile':args.parquet.name,'rows':int(len(df)),'dayRows':int(len(day)),'datetimeStart':df.dt.iloc[0].isoformat(),'datetimeEnd':df.dt.iloc[-1].isoformat(),'product':args.product,'expiries':sorted(df.expiry.unique().tolist()),'sourceOrderPreserved':True,'timestampResolution':'1 second; same-second physical row order preserved','sideMeaning':'tick-direction proxy only; NOT Bid/Ask aggressor','caseCount':len(cases)}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps({'meta':meta,'sessions':sessions,'cases':cases},ensure_ascii=False,separators=(',',':')));print(json.dumps(meta,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
