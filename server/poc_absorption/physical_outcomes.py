from __future__ import annotations
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Iterable
import numpy as np
import pandas as pd
from .outcomes import FROZEN_HORIZONS, make_probe_outcome_skeleton, validate_probe_events, validate_probe_outcomes

PHYSICAL_PATH_SCHEMA_VERSION='POC_M5_PHYSICAL_PATH_V1'
HORIZON_SECONDS={'30s':30,'1m':60,'3m':180,'5m':300,'15m':900,'30m':1800,'60m':3600}

@dataclass(frozen=True)
class PhysicalOutcomeDiagnostics:
    sessions_indexed:int=0; physical_ticks_indexed:int=0; range_queries:int=0
    extrema_index_build_seconds:float=0.0; range_query_seconds:float=0.0; output_finalize_seconds:float=0.0
    def as_dict(self): return asdict(self)

def _session_end_exclusive(trigger_time,session):
    ts=pd.Timestamp(trigger_time); d=ts.normalize()
    if session=='day':
        end=d+pd.Timedelta(hours=13,minutes=45)
        if not (d+pd.Timedelta(hours=8,minutes=45)<=ts<end): raise ValueError(f'day event trigger_time outside session: {ts}')
        return end
    if session=='night':
        if ts.time()>=pd.Timestamp('15:00:00').time(): return d+pd.Timedelta(days=1,hours=5)
        if ts.time()<pd.Timestamp('05:00:00').time(): return d+pd.Timedelta(hours=5)
        raise ValueError(f'night event trigger_time outside session: {ts}')
    raise ValueError(f'unsupported session: {session!r}')

def _session_key_ns(dt:pd.Series,session:str)->np.ndarray:
    x=pd.to_datetime(dt,errors='raise',format='mixed')
    base=x.dt.normalize()
    if session=='night': base=base-pd.to_timedelta((x.dt.hour<5).astype(np.int64),unit='D')
    return base.to_numpy(dtype='datetime64[ns]').astype(np.int64)

def _validate_ticks(ticks,contract,session):
    req={'_seq','datetime','price'}; miss=req-set(ticks.columns)
    if miss: raise ValueError(f'physical ticks missing columns: {sorted(miss)}')
    if ticks.empty: raise ValueError('physical tick partition must not be empty')
    seq=pd.to_numeric(ticks._seq,errors='raise').to_numpy(np.int64)
    if len(seq)>1 and np.any(np.diff(seq)<=0): raise ValueError('physical ticks _seq must be strictly increasing; outcome engine never sorts')
    dt=pd.to_datetime(ticks.datetime,errors='raise',format='mixed'); ns=dt.to_numpy(dtype='datetime64[ns]').astype(np.int64)
    if len(ns)>1 and np.any(np.diff(ns)<0): raise ValueError('physical tick datetime moved backward; outcome engine never sorts')
    pr=pd.to_numeric(ticks.price,errors='coerce').to_numpy(float)
    if not np.isfinite(pr).all(): raise ValueError('physical ticks contain invalid price')
    if 'expiry' in ticks:
        obs=set(ticks.expiry.astype(str).unique())
        if obs!={str(contract)}: raise ValueError(f'physical tick partition expiry drift: expected {contract!r}, observed {sorted(obs)!r}')
    sec=dt.dt.hour*3600+dt.dt.minute*60+dt.dt.second
    ok=((sec>=8*3600+45*60)&(sec<13*3600+45*60)) if session=='day' else ((sec>=15*3600)|(sec<5*3600))
    if not bool(ok.all()): raise ValueError('physical tick partition contains ticks outside requested session')
    return seq,dt,ns,pr

def _build_boundaries(keys):
    if not len(keys): return {}
    starts=np.r_[0,1+np.flatnonzero(keys[1:]!=keys[:-1])]; ends=np.r_[starts[1:],len(keys)]
    return {int(keys[s]):(int(s),int(e)) for s,e in zip(starts,ends)}

def _build_tree(price,mode):
    n=len(price); size=1<<(max(1,n)-1).bit_length(); tree=np.full(2*size,-1,dtype=np.int32); tree[size:size+n]=np.arange(n,dtype=np.int32)
    start=size//2
    while start:
        par=np.arange(start,2*start,dtype=np.int64); l=tree[2*par]; r=tree[2*par+1]; out=l.copy(); lv=l>=0; rv=r>=0; onlyr=(~lv)&rv; out[onlyr]=r[onlyr]; both=lv&rv
        if both.any():
            li=l[both]; ri=r[both]; lp=price[li]; rp=price[ri]
            choose=(rp>lp)|((rp==lp)&(ri<li)) if mode=='max' else (rp<lp)|((rp==lp)&(ri<li))
            tmp=out[both]; tmp[choose]=ri[choose]; out[both]=tmp
        tree[par]=out; start//=2
    return size,tree

def _merge(best,q,cand,price,mode):
    if len(q)==0:return
    b=best[q]; valid=cand>=0; empty=b<0; take=valid&empty; both=valid&(~empty)
    if both.any():
        bb=b[both]; cc=cand[both]; bp=price[bb]; cp=price[cc]
        better=(cp>bp)|((cp==bp)&(cc<bb)) if mode=='max' else (cp<bp)|((cp==bp)&(cc<bb))
        ii=np.flatnonzero(both); take[ii[better]]=True
    b[take]=cand[take]; best[q]=b

def _batch_query(size,tree,price,L,R,mode):
    l=L.astype(np.int64)+size; r=R.astype(np.int64)+size; best=np.full(len(L),-1,dtype=np.int32); active=l<r
    while active.any():
        q=np.flatnonzero(active&((l&1)==1)); _merge(best,q,tree[l[q]],price,mode); l[q]+=1
        q=np.flatnonzero(active&((r&1)==1)); r[q]-=1; _merge(best,q,tree[r[q]],price,mode)
        q=np.flatnonzero(active); l[q]//=2; r[q]//=2; active[q]=l[q]<r[q]
    return best

def _alloc(n,hs):
    b={'physical_path_schema_version':np.full(n,PHYSICAL_PATH_SCHEMA_VERSION,dtype=object)}
    nat_ns=np.datetime64('NaT','ns')
    for h in hs:
        p='h_'+h; b[p+'_requested_horizon_seconds']=np.full(n,np.nan if h=='session_end' else HORIZON_SECONDS[h],float); b[p+'_effective_horizon_seconds']=np.full(n,np.nan); b[p+'_deadline_time']=np.full(n,nat_ns,dtype='datetime64[ns]'); b[p+'_truncated_by_session_end']=np.zeros(n,bool); b[p+'_future_tick_count']=np.zeros(n,np.int64)
        for k in ['window_start_seq','window_end_seq','forward_high_seq','forward_low_seq','mfe_seq','mae_seq']: b[p+'_'+k]=np.full(n,-1,np.int64)
        for k in ['forward_high','forward_low','short_mfe','short_mae','mfe_atr','mae_atr','time_to_mfe_seconds','time_to_mae_seconds']: b[p+'_'+k]=np.full(n,np.nan)
        for k in ['forward_high_time','forward_low_time','mfe_time','mae_time']: b[p+'_'+k]=np.full(n,nat_ns,dtype='datetime64[ns]')
    return b

def _compute(events,ticks,contract,session,hs):
    validate_probe_events(events)
    hs=tuple(hs)
    if len(set(hs))!=len(hs) or any(h not in FROZEN_HORIZONS for h in hs): raise ValueError('invalid/duplicate horizons')
    if set(events.contract.astype(str).unique())!={str(contract)} or set(events.session.astype(str).unique())!={session}: raise ValueError('events must contain exactly requested contract/session')
    seq,dt,tns,price=_validate_ticks(ticks,contract,session); tkeys=_session_key_ns(dt,session); bounds=_build_boundaries(tkeys); ekeys=_session_key_ns(events.trigger_time,session)
    pos=np.searchsorted(seq,pd.to_numeric(events.trigger_seq).to_numpy(np.int64)); ok=(pos<len(seq))&(seq[np.minimum(pos,len(seq)-1)]==pd.to_numeric(events.trigger_seq).to_numpy(np.int64))
    if not ok.all(): raise ValueError('trigger_seq missing from physical tick partition')
    if not np.array_equal(tns[pos],pd.to_datetime(events.trigger_time,format='mixed').to_numpy(dtype='datetime64[ns]').astype(np.int64)): raise ValueError('trigger_time mismatch')
    if not np.allclose(price[pos],pd.to_numeric(events.trigger_price).to_numpy(float),rtol=0,atol=1e-12): raise ValueError('trigger_price mismatch')
    n=len(events); block=_alloc(n,hs); idx_build=query=0.0; queries=0; indexed=0; sessions=0
    ev_seq=pd.to_numeric(events.trigger_seq).to_numpy(np.int64); ev_time=pd.to_datetime(events.trigger_time,format='mixed'); ev_tns=ev_time.to_numpy(dtype='datetime64[ns]').astype(np.int64); ev_px=pd.to_numeric(events.trigger_price).to_numpy(float); ev_atr=pd.to_numeric(events.atr).to_numpy(float)
    for key in pd.unique(ekeys):
        if int(key) not in bounds: raise ValueError('event session has no physical ticks')
        a,b=bounds[int(key)]; loc=np.flatnonzero(ekeys==key); ss=seq[a:b]; ts=tns[a:b]; ps=price[a:b]; indexed+=len(ps); sessions+=1
        starts=np.searchsorted(ss,ev_seq[loc],side='right').astype(np.int32)
        t0=perf_counter(); size,maxt=_build_tree(ps,'max'); _,mint=_build_tree(ps,'min'); idx_build+=perf_counter()-t0
        se=np.array([np.datetime64(_session_end_exclusive(ev_time.iloc[i],session),'ns').astype(np.int64) for i in loc],dtype=np.int64)
        for h in hs:
            p='h_'+h
            if h=='session_end': dead=se.copy(); trunc=np.zeros(len(loc),bool)
            else:
                raw=ev_tns[loc]+np.int64(HORIZON_SECONDS[h])*1_000_000_000; trunc=raw>=se; dead=np.minimum(raw,se)
            stop=np.searchsorted(ts,dead,side='right').astype(np.int32); at_end=dead==se
            if at_end.any(): stop[at_end]=len(ts)
            stop=np.maximum(starts,np.minimum(stop,len(ts))).astype(np.int32); cnt=(stop-starts).astype(np.int64); queries+=len(loc)
            t0=perf_counter(); hi=_batch_query(size,maxt,ps,starts,stop,'max'); lo=_batch_query(size,mint,ps,starts,stop,'min'); query+=perf_counter()-t0
            block[p+'_deadline_time'][loc]=dead.astype('datetime64[ns]'); block[p+'_effective_horizon_seconds'][loc]=(dead-ev_tns[loc])/1e9; block[p+'_truncated_by_session_end'][loc]=trunc; block[p+'_future_tick_count'][loc]=cnt
            has=cnt>0; gl=loc[has]; lh=hi[has]; ll=lo[has]; st=starts[has]; sp=stop[has]
            if len(gl):
                block[p+'_window_start_seq'][gl]=ss[st]; block[p+'_window_end_seq'][gl]=ss[sp-1]; block[p+'_forward_high'][gl]=ps[lh]; block[p+'_forward_high_seq'][gl]=ss[lh]; block[p+'_forward_high_time'][gl]=ts[lh].astype('datetime64[ns]'); block[p+'_forward_low'][gl]=ps[ll]; block[p+'_forward_low_seq'][gl]=ss[ll]; block[p+'_forward_low_time'][gl]=ts[ll].astype('datetime64[ns]')
                mfe=np.maximum(ev_px[gl]-ps[ll],0.0); mae=np.maximum(ps[lh]-ev_px[gl],0.0); block[p+'_short_mfe'][gl]=mfe; block[p+'_short_mae'][gl]=mae; block[p+'_mfe_atr'][gl]=mfe/ev_atr[gl]; block[p+'_mae_atr'][gl]=mae/ev_atr[gl]
                fav=mfe>0; adv=mae>0; gf=gl[fav]; ga=gl[adv]; lf=ll[fav]; la=lh[adv]
                if len(gf): block[p+'_mfe_seq'][gf]=ss[lf]; block[p+'_mfe_time'][gf]=ts[lf].astype('datetime64[ns]'); block[p+'_time_to_mfe_seconds'][gf]=(ts[lf]-ev_tns[gf])/1e9
                if len(ga): block[p+'_mae_seq'][ga]=ss[la]; block[p+'_mae_time'][ga]=ts[la].astype('datetime64[ns]'); block[p+'_time_to_mae_seconds'][ga]=(ts[la]-ev_tns[ga])/1e9
    t0=perf_counter(); out=pd.concat([make_probe_outcome_skeleton(events).reset_index(drop=True),pd.DataFrame(block)],axis=1)
    for h in hs:
        p='h_'+h
        for k in ['window_start_seq','window_end_seq','forward_high_seq','forward_low_seq','mfe_seq','mae_seq']:
            arr=out[p+'_'+k].to_numpy(np.int64); out[p+'_'+k]=pd.array(np.where(arr<0,None,arr),dtype='Int64')
    finalize=perf_counter()-t0
    rep=validate_probe_outcomes(events,out)
    if not rep.all_pass: raise AssertionError('contract violation')
    return out,PhysicalOutcomeDiagnostics(sessions,indexed,queries,idx_build,query,finalize)

def compute_physical_tick_outcomes(events,ticks,*,contract,session,horizons=FROZEN_HORIZONS): return _compute(events,ticks,contract,session,horizons)[0]
def compute_physical_tick_outcomes_with_diagnostics(events,ticks,*,contract,session,horizons=FROZEN_HORIZONS): return _compute(events,ticks,contract,session,horizons)
