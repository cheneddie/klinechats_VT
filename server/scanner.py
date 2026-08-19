from __future__ import annotations
import json, math, re, sqlite3, threading
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import defaultdict
from typing import Iterable
import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUTRIGHT_RE=re.compile(r'^\d{6}$')

@dataclass
class ScanConfig:
    product:str='MTX'
    value_area:float=.80
    session_start:str='08:45:00'
    session_end:str='13:45:00'
    excursion_pct:float=.02
    min_excursion_points:float=2.0
    reclaim_pct:float=.08
    reclaim_max_sec:int=60
    auction_max_sec:int=180
    turn_points:float=8.0
    lvn_depth:float=.55
    lvn_tolerance:float=1.0
    pullback_max_sec:int=120
    mr_stop_points:float=6.0
    mr_target_r:float=.75
    acceptance_outside_ratio:float=.70
    acceptance_displacement_pct:float=.20
    acceptance_window_sec:int=20
    bo_response_points:float=2.0
    bo_stop_points:float=8.0
    bo_target_r:float=1.0
    contract_mode:str='strict'
    roll_blackout_days:int=1

NODE_IDS=['CTX_VALUE','AUC_ATTEMPT','AUC_EXTREME','MR_REJECTION','MR_CLEAR_RECLAIM','MR_RECLAIM_LEG','MR_LVN','MR_PULLBACK','MR_ENTRY','BO_ACCEPTANCE','BO_DISPLACEMENT','BO_IMPULSE_LEG','BO_LVN','BO_PULLBACK','BO_RESPONSE','BO_ENTRY','WAIT_AMBIGUOUS','NO_TRADE']

def _txt(v):
    if isinstance(v,(bytes,bytearray)): return v.decode('utf-8','replace')
    return str(v)

def connect(db:Path):
    db.parent.mkdir(parents=True,exist_ok=True); con=sqlite3.connect(db);con.row_factory=sqlite3.Row
    con.executescript('''
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS datasets(file TEXT PRIMARY KEY,year INTEGER,rows INTEGER,start TEXT,end TEXT,products TEXT,expiries TEXT,qa TEXT,scanned_at TEXT);
    CREATE TABLE IF NOT EXISTS events(
      event_id TEXT PRIMARY KEY, source_file TEXT, year INTEGER, trading_date TEXT, contract TEXT, strategy TEXT, direction TEXT, result TEXT, difficulty INTEGER,
      attempt_start_seq INTEGER, attempt_start_time TEXT, context_start_seq INTEGER, context_end_seq INTEGER,
      extreme_seq INTEGER, extreme_time TEXT, extreme_price REAL, clear_reclaim_seq INTEGER, clear_reclaim_time TEXT, clear_reclaim_price REAL,
      turn_confirm_seq INTEGER, turn_confirm_time TEXT, lvn REAL, entry_seq INTEGER, entry_time TEXT, entry_price REAL, stop REAL, target REAL,
      vah REAL,val REAL,poc REAL,value_width REAL,features_json TEXT,nodes_json TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS node_instances(
      event_id TEXT,node_id TEXT,answer INTEGER,decision_seq INTEGER,decision_time TEXT,difficulty INTEGER,PRIMARY KEY(event_id,node_id));
    CREATE INDEX IF NOT EXISTS ix_node ON node_instances(node_id,answer);
    CREATE INDEX IF NOT EXISTS ix_event_date ON events(trading_date,strategy);
    CREATE INDEX IF NOT EXISTS ix_event_contract ON events(contract,trading_date);
    CREATE TABLE IF NOT EXISTS scan_runs(job_id TEXT PRIMARY KEY,status TEXT,started_at TEXT,finished_at TEXT,years TEXT,config_json TEXT,events INTEGER,message TEXT);
    ''');return con

def discover(root:Path):
    return sorted(root.glob('MTX_*.parquet'))

def catalog_file(path:Path):
    pf=pq.ParquetFile(path);rows=pf.metadata.num_rows;products=set();expiries=set();first=last=None;seq=0;backward=0
    for batch in pf.iter_batches(batch_size=250_000,columns=['datetime','product','expiry']):
        d=batch.to_pandas();dt=pd.to_datetime(d['datetime']);
        if len(dt):
            if first is None:first=dt.iloc[0]
            last=dt.iloc[-1]
            if not dt.is_monotonic_increasing: backward+=1
        products.update(_txt(x) for x in d['product'].dropna().unique());expiries.update(_txt(x) for x in d['expiry'].dropna().unique());seq+=len(d)
    return {'file':path.name,'year':int(re.search(r'(\d{4})',path.stem).group(1)) if re.search(r'(\d{4})',path.stem) else 0,'rows':rows,'start':first.isoformat() if first is not None else None,'end':last.isoformat() if last is not None else None,'products':sorted(products),'expiries':sorted(expiries),'qa':'PASS' if backward==0 and seq==rows else 'FAIL'}

def daily_contract_volume(path:Path,cfg:ScanConfig):
    pf=pq.ParquetFile(path);acc=defaultdict(lambda:defaultdict(float))
    for batch in pf.iter_batches(batch_size=400_000,columns=['datetime','product','expiry','volume']):
        d=batch.to_pandas();d['product']=d['product'].map(_txt);d['expiry']=d['expiry'].map(_txt);dt=pd.to_datetime(d['datetime']);d['date']=dt.dt.strftime('%Y-%m-%d');d['sec']=dt.dt.hour*3600+dt.dt.minute*60+dt.dt.second
        a=8*3600+45*60;b=13*3600+45*60;d=d[(d.product==cfg.product)&d.expiry.str.match(OUTRIGHT_RE)&(d.sec>=a)&(d.sec<=b)]
        if d.empty:continue
        g=d.groupby(['date','expiry'],sort=False)['volume'].sum()
        for (day,exp),v in g.items():acc[day][exp]+=float(v)
    return acc

def choose_contracts(volume_map,mode='strict'):
    out={};prev=None
    for day in sorted(volume_map):
        vols=volume_map[day];ranked=sorted(vols.items(),key=lambda x:(-x[1],x[0]));dominant=ranked[0][0] if ranked else None
        ym=day[:7].replace('-','');valid=sorted([e for e in vols if e>=ym])
        front=valid[0] if valid else dominant
        if mode=='front_month':pick=front
        else:pick=dominant
        changed=prev is not None and pick!=prev
        ambiguous=len(ranked)>1 and ranked[0][1] < ranked[1][1]*1.10
        out[day]={'contract':pick,'roll':changed,'ambiguous':ambiguous,'volume':vols.get(pick,0),'second':ranked[1][1] if len(ranked)>1 else 0}
        prev=pick
    return out

def profile_levels(g:pd.DataFrame,pct=.80):
    pv=g.groupby('price',sort=True)['volume'].sum();prices=pv.index.to_numpy(float);v=pv.to_numpy(float)
    if not len(v) or v.sum()<=0:return None
    poc=int(np.argmax(v));lo=hi=poc;total=float(v[poc]);target=float(v.sum()*pct)
    while total<target and (lo>0 or hi<len(v)-1):
        lv=v[lo-1] if lo>0 else -1;rv=v[hi+1] if hi<len(v)-1 else -1
        if rv>lv:hi+=1;total+=float(v[hi])
        else:lo-=1;total+=float(v[lo])
    return {'poc':float(prices[poc]),'val':float(prices[lo]),'vah':float(prices[hi]),'width':float(prices[hi]-prices[lo])}

def leg_lvn(leg:pd.DataFrame,prior,cfg):
    if len(leg)<10:return None
    pv=leg.groupby('price',sort=True)['volume'].sum();prices=pv.index.to_numpy(float);vol=pv.to_numpy(float)
    if len(prices)<5:return None
    sm=np.convolve(vol,np.ones(3)/3,mode='same');lo=prior['val']+.05*prior['width'];hi=prior['vah']-.05*prior['width'];c=[]
    for i in range(2,len(prices)-2):
        if not lo<=prices[i]<=hi:continue
        if sm[i]<=sm[i-1] and sm[i]<=sm[i+1]:
            ref=min(max(sm[i-2:i]),max(sm[i+1:i+3]));depth=1-sm[i]/ref if ref>0 else 0
            if depth>=cfg.lvn_depth:c.append((depth,float(prices[i])))
    return max(c)[1] if c else None

def _node(nodes,node,answer,seq=None,time=None):nodes[node]={'answer':bool(answer),'seq':int(seq) if seq is not None else None,'time':time.isoformat() if hasattr(time,'isoformat') else time}

def _case_base(event_id,file,day,contract,strategy,direction,prior,start_i,g):
    return {'event_id':event_id,'source_file':file.name,'year':int(day[:4]),'trading_date':day,'contract':contract,'strategy':strategy,'direction':direction,'result':'WAIT','difficulty':2,'attempt_start_seq':int(g._seq.iloc[start_i]),'attempt_start_time':g.dt.iloc[start_i].isoformat(),'context_start_seq':max(0,int(g._seq.iloc[start_i])-20000),'context_end_seq':int(g._seq.iloc[min(len(g)-1,start_i+20000)]),'vah':prior['vah'],'val':prior['val'],'poc':prior['poc'],'value_width':prior['width'],'features':{},'nodes':{}}

def scan_day(g:pd.DataFrame,prior,cfg:ScanConfig,file:Path,day:str,contract:str):
    ev=[];n=len(g);i=0;attempt=0
    if n<10 or not prior or prior['width']<=0:return ev
    excursion=max(cfg.min_excursion_points,cfg.excursion_pct*prior['width']);reclaim=max(3.0,cfg.reclaim_pct*prior['width'])
    while i<n:
        p=float(g.price.iloc[i]);up=p>prior['vah'];down=p<prior['val']
        if not(up or down):i+=1;continue
        attempt+=1;side='up' if up else 'down';boundary=prior['vah'] if up else prior['val'];start=i;extreme=p;ext_i=i;clear=None;j=i+1
        t_start=g.dt.iloc[start]
        while j<n and (g.dt.iloc[j]-t_start).total_seconds()<=cfg.auction_max_sec:
            pj=float(g.price.iloc[j])
            if up and pj>extreme:extreme=pj;ext_i=j
            if down and pj<extreme:extreme=pj;ext_i=j
            enough=(extreme-boundary>=excursion) if up else (boundary-extreme>=excursion)
            if enough and (g.dt.iloc[j]-g.dt.iloc[ext_i]).total_seconds()<=cfg.reclaim_max_sec:
                if up and pj<=boundary-reclaim:clear=j;break
                if down and pj>=boundary+reclaim:clear=j;break
            j+=1
        event_id=f'{day}-{contract}-A{attempt:03d}';trade_dir='short' if up else 'long';base=_case_base(event_id,file,day,contract,'WAIT',trade_dir,prior,start,g);nodes=base['nodes'];_node(nodes,'CTX_VALUE',True,g._seq.iloc[start],g.dt.iloc[start]);_node(nodes,'AUC_ATTEMPT',True,g._seq.iloc[start],g.dt.iloc[start]);_node(nodes,'AUC_EXTREME',True,g._seq.iloc[ext_i],g.dt.iloc[ext_i]);base.update(extreme_seq=int(g._seq.iloc[ext_i]),extreme_time=g.dt.iloc[ext_i].isoformat(),extreme_price=float(extreme))
        exc=(extreme-boundary) if up else (boundary-extreme);base['features'].update(excursion_points=float(exc),excursion_pct_value=float(exc/prior['width']))
        if clear is not None:
            base['strategy']='MR';_node(nodes,'MR_REJECTION',True,g._seq.iloc[clear],g.dt.iloc[clear]);_node(nodes,'MR_CLEAR_RECLAIM',True,g._seq.iloc[clear],g.dt.iloc[clear]);base.update(clear_reclaim_seq=int(g._seq.iloc[clear]),clear_reclaim_time=g.dt.iloc[clear].isoformat(),clear_reclaim_price=float(g.price.iloc[clear]));base['features'].update(reclaim_seconds=float((g.dt.iloc[clear]-g.dt.iloc[ext_i]).total_seconds()),reclaim_points=float(abs(g.price.iloc[clear]-boundary)))
            k=clear;leg_best=float(g.price.iloc[k]);leg_end=k;confirm=None
            while k<n and (g.dt.iloc[k]-g.dt.iloc[clear]).total_seconds()<=600:
                pk=float(g.price.iloc[k])
                if trade_dir=='short':
                    if pk<leg_best:leg_best=pk;leg_end=k
                    if pk>=leg_best+cfg.turn_points:confirm=k;break
                else:
                    if pk>leg_best:leg_best=pk;leg_end=k
                    if pk<=leg_best-cfg.turn_points:confirm=k;break
                k+=1
            _node(nodes,'MR_RECLAIM_LEG',confirm is not None,g._seq.iloc[confirm] if confirm is not None else None,g.dt.iloc[confirm] if confirm is not None else None)
            if confirm is not None:
                base.update(turn_confirm_seq=int(g._seq.iloc[confirm]),turn_confirm_time=g.dt.iloc[confirm].isoformat());leg=g.iloc[min(ext_i,leg_end):max(ext_i,leg_end)+1];lvn=leg_lvn(leg,prior,cfg);base['lvn']=lvn;_node(nodes,'MR_LVN',lvn is not None,g._seq.iloc[confirm],g.dt.iloc[confirm]);
                if lvn is not None:
                    touch=None;k=confirm+1;deadline=g.dt.iloc[confirm]+pd.Timedelta(seconds=cfg.pullback_max_sec)
                    while k<n and g.dt.iloc[k]<=deadline:
                        if abs(float(g.price.iloc[k])-lvn)<=cfg.lvn_tolerance:touch=k;break
                        k+=1
                    _node(nodes,'MR_PULLBACK',touch is not None,g._seq.iloc[touch] if touch is not None else None,g.dt.iloc[touch] if touch is not None else None)
                    if touch is not None:
                        ep=float(g.price.iloc[touch]);stop=lvn+cfg.mr_stop_points if trade_dir=='short' else lvn-cfg.mr_stop_points;risk=abs(stop-ep);target=ep-cfg.mr_target_r*risk if trade_dir=='short' else ep+cfg.mr_target_r*risk;base.update(entry_seq=int(g._seq.iloc[touch]),entry_time=g.dt.iloc[touch].isoformat(),entry_price=ep,stop=float(stop),target=float(target),result='ENTRY');_node(nodes,'MR_ENTRY',True,g._seq.iloc[touch],g.dt.iloc[touch]);base['difficulty']=3
                    else:_node(nodes,'MR_ENTRY',False)
            ev.append(base);i=max(clear+1,start+1);continue
        # No clear reclaim: classify accepted vs ambiguous using a causal 20-second window.
        end_t=t_start+pd.Timedelta(seconds=cfg.acceptance_window_sec);w=g[(g.dt>=t_start)&(g.dt<=end_t)]
        if len(w):
            outside=((w.price>prior['vah']) if up else (w.price<prior['val']));outside_ratio=float(outside.mean());disp=(float(w.price.max())-boundary) if up else (boundary-float(w.price.min()));accept=outside_ratio>=cfg.acceptance_outside_ratio and disp>=cfg.acceptance_displacement_pct*prior['width']
        else:outside_ratio=disp=0;accept=False
        _node(nodes,'MR_REJECTION',False,g._seq.iloc[min(j,n-1)] if n else None,g.dt.iloc[min(j,n-1)] if n else None);_node(nodes,'BO_ACCEPTANCE',accept,g._seq.iloc[min(j,n-1)] if n else None,g.dt.iloc[min(j,n-1)] if n else None);base['features'].update(outside_ratio=outside_ratio,acceptance_displacement=float(disp),acceptance_displacement_pct=float(disp/prior['width'] if prior['width'] else 0))
        if accept:
            base['strategy']='BO';_node(nodes,'BO_DISPLACEMENT',True,g._seq.iloc[min(j,n-1)],g.dt.iloc[min(j,n-1)]);accept_i=min(j,n-1);k=accept_i;best=float(g.price.iloc[k]);leg_end=k;confirm=None
            while k<n and (g.dt.iloc[k]-g.dt.iloc[accept_i]).total_seconds()<=600:
                pk=float(g.price.iloc[k])
                if trade_dir=='long':
                    if pk>best:best=pk;leg_end=k
                    if pk<=best-cfg.turn_points:confirm=k;break
                else:
                    if pk<best:best=pk;leg_end=k
                    if pk>=best+cfg.turn_points:confirm=k;break
                k+=1
            _node(nodes,'BO_IMPULSE_LEG',confirm is not None,g._seq.iloc[confirm] if confirm is not None else None,g.dt.iloc[confirm] if confirm is not None else None)
            if confirm is not None:
                base.update(turn_confirm_seq=int(g._seq.iloc[confirm]),turn_confirm_time=g.dt.iloc[confirm].isoformat());leg=g.iloc[min(start,leg_end):max(start,leg_end)+1];lvn=leg_lvn(leg,prior,cfg);base['lvn']=lvn;_node(nodes,'BO_LVN',lvn is not None,g._seq.iloc[confirm],g.dt.iloc[confirm])
                if lvn is not None:
                    touch=None;k=confirm+1;deadline=g.dt.iloc[confirm]+pd.Timedelta(seconds=cfg.pullback_max_sec)
                    while k<n and g.dt.iloc[k]<=deadline:
                        if abs(float(g.price.iloc[k])-lvn)<=cfg.lvn_tolerance:touch=k;break
                        k+=1
                    _node(nodes,'BO_PULLBACK',touch is not None,g._seq.iloc[touch] if touch is not None else None,g.dt.iloc[touch] if touch is not None else None)
                    response=None
                    if touch is not None:
                        k=touch;deadline=g.dt.iloc[touch]+pd.Timedelta(seconds=30);tp=float(g.price.iloc[touch])
                        while k<n and g.dt.iloc[k]<=deadline:
                            progress=(float(g.price.iloc[k])-tp) if trade_dir=='long' else (tp-float(g.price.iloc[k]))
                            if progress>=cfg.bo_response_points:response=k;break
                            k+=1
                    _node(nodes,'BO_RESPONSE',response is not None,g._seq.iloc[response] if response is not None else None,g.dt.iloc[response] if response is not None else None)
                    if response is not None:
                        ep=float(g.price.iloc[response]);stop=lvn-cfg.bo_stop_points if trade_dir=='long' else lvn+cfg.bo_stop_points;risk=abs(ep-stop);target=ep+cfg.bo_target_r*risk if trade_dir=='long' else ep-cfg.bo_target_r*risk;base.update(entry_seq=int(g._seq.iloc[response]),entry_time=g.dt.iloc[response].isoformat(),entry_price=ep,stop=float(stop),target=float(target),result='ENTRY');_node(nodes,'BO_ENTRY',True,g._seq.iloc[response],g.dt.iloc[response]);base['difficulty']=4
                    else:_node(nodes,'BO_ENTRY',False)
        else:
            base['strategy']='WAIT';_node(nodes,'WAIT_AMBIGUOUS',True,g._seq.iloc[min(j,n-1)] if n else None,g.dt.iloc[min(j,n-1)] if n else None);_node(nodes,'NO_TRADE',True);base['difficulty']=3
        ev.append(base);i=max(j+1,start+1)
    return ev

def _iter_active_days(path:Path,active,cfg:ScanConfig):
    pf=pq.ParquetFile(path);seq=0;current=None;parts=[]
    def emit(day,parts):
        if not day or not parts:return None
        g=pd.concat(parts,ignore_index=True);return day,g
    for batch in pf.iter_batches(batch_size=300_000,columns=['datetime','product','expiry','price','volume','side']):
        d=batch.to_pandas();d['_seq']=np.arange(seq,seq+len(d),dtype=np.int64);seq+=len(d);d['product']=d.product.map(_txt);d['expiry']=d.expiry.map(_txt);d['dt']=pd.to_datetime(d.datetime);d['date']=d.dt.dt.strftime('%Y-%m-%d');d['sec']=d.dt.dt.hour*3600+d.dt.dt.minute*60+d.dt.dt.second
        d=d[(d.product==cfg.product)&d.expiry.str.match(OUTRIGHT_RE)&(d.sec>=8*3600+45*60)&(d.sec<=13*3600+45*60)]
        for day,g in d.groupby('date',sort=False):
            pick=active.get(day,{}).get('contract');g=g[g.expiry==pick]
            if g.empty:continue
            if current is None:current=day
            if day!=current:
                x=emit(current,parts)
                if x:yield x
                current=day;parts=[]
            parts.append(g)
    x=emit(current,parts)
    if x:yield x

def write_events(con,events,created_at):
    for e in events:
        nodes=e.pop('nodes');features=e.pop('features');cols=['event_id','source_file','year','trading_date','contract','strategy','direction','result','difficulty','attempt_start_seq','attempt_start_time','context_start_seq','context_end_seq','extreme_seq','extreme_time','extreme_price','clear_reclaim_seq','clear_reclaim_time','clear_reclaim_price','turn_confirm_seq','turn_confirm_time','lvn','entry_seq','entry_time','entry_price','stop','target','vah','val','poc','value_width']
        vals=[e.get(c) for c in cols]+[json.dumps(features,ensure_ascii=False),json.dumps({k:v['answer'] for k,v in nodes.items()},ensure_ascii=False),created_at]
        con.execute(f"INSERT OR REPLACE INTO events({','.join(cols)},features_json,nodes_json,created_at) VALUES({','.join(['?']*(len(cols)+3))})",vals)
        con.execute('DELETE FROM node_instances WHERE event_id=?',(e['event_id'],))
        for node,x in nodes.items():con.execute('INSERT OR REPLACE INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty) VALUES(?,?,?,?,?,?)',(e['event_id'],node,1 if x['answer'] else 0,x.get('seq'),x.get('time'),e.get('difficulty',2)))

def scan_files(root:Path,db:Path,years:list[int]|None=None,config:ScanConfig|None=None,progress=None):
    cfg=config or ScanConfig();con=connect(db);files=discover(root);files=[p for p in files if not years or any(str(y) in p.stem for y in years)];total_events=0;from datetime import datetime,timezone;now=lambda:datetime.now(timezone.utc).isoformat()
    for file in files:
        cat=catalog_file(file);con.execute('INSERT OR REPLACE INTO datasets VALUES(?,?,?,?,?,?,?,?,?)',(cat['file'],cat['year'],cat['rows'],cat['start'],cat['end'],json.dumps(cat['products']),json.dumps(cat['expiries']),cat['qa'],now()));con.commit();
        if progress:progress(file.name,'catalog',0)
        volumes=daily_contract_volume(file,cfg);active=choose_contracts(volumes,cfg.contract_mode);prev_profile=None;prev_contract=None;blackout=0
        for day,g in _iter_active_days(file,active,cfg):
            contract=active[day]['contract'];roll=prev_contract is not None and contract!=prev_contract
            if roll:blackout=cfg.roll_blackout_days
            profile=profile_levels(g,cfg.value_area)
            if prev_profile and blackout<=0:
                events=scan_day(g,prev_profile,cfg,file,day,contract);write_events(con,events,now());total_events+=len(events)
            if blackout>0:blackout-=1
            prev_profile=profile;prev_contract=contract
            if progress:progress(file.name,day,total_events)
        con.commit()
    con.close();return total_events

def read_replay_window(root:Path,event:dict,margin=20000):
    path=root/event['source_file'];pf=pq.ParquetFile(path);lo=max(0,int(event['context_start_seq'] or event['attempt_start_seq'])-margin);hi=int(event['context_end_seq'] or event['attempt_start_seq'])+margin;offset=0;parts=[]
    for rg in range(pf.num_row_groups):
        n=pf.metadata.row_group(rg).num_rows;rg_lo,rg_hi=offset,offset+n-1
        if rg_hi<lo:offset+=n;continue
        if rg_lo>hi:break
        t=pf.read_row_group(rg,columns=['datetime','product','expiry','price','volume','side']).to_pandas();t['_seq']=np.arange(offset,offset+n,dtype=np.int64);t=t[(t._seq>=lo)&(t._seq<=hi)];parts.append(t);offset+=n
    if not parts:return[]
    d=pd.concat(parts,ignore_index=True);d['product']=d.product.map(_txt);d['expiry']=d.expiry.map(_txt);d=d[(d.product=='MTX')&(d.expiry==event['contract'])];d['dt']=pd.to_datetime(d.datetime);rows=[]
    for ts,b in d.groupby(d.dt.dt.floor('1s'),sort=False):rows.append({'timestamp':int(ts.value//1_000_000),'open':float(b.price.iloc[0]),'high':float(b.price.max()),'low':float(b.price.min()),'close':float(b.price.iloc[-1]),'volume':float(b.volume.sum()),'firstSeq':int(b._seq.iloc[0]),'lastSeq':int(b._seq.iloc[-1])})
    return rows
