from __future__ import annotations
import json
from pathlib import Path
from .storage import connect,migrate_event_db,tx,utcnow

def _latest_sanity_pass(con,run_id):
    r=con.execute("SELECT status FROM event_sanity_runs WHERE research_run_id=? ORDER BY created_at DESC LIMIT 1",(run_id,)).fetchone()
    return bool(r and r['status']=='PASS')

def _terminal(e):
    f=json.loads(e.get('features_json') or '{}'); seq=f.get('terminal_entry_seq'); price=f.get('terminal_entry_price'); stop=f.get('terminal_stop')
    if seq is None: seq=e.get('entry_seq')
    if price is None: price=e.get('entry_price')
    if stop is None: stop=e.get('stop')
    if seq is None or price is None or stop is None:return None
    return int(seq),float(price),float(stop),f.get('terminal_entry_time') or e.get('entry_time')

def _strict(e):
    if e.get('entry_seq') is None or e.get('entry_price') is None or e.get('stop') is None:return None
    return int(e['entry_seq']),float(e['entry_price']),float(e['stop']),e.get('entry_time')

def _read_path(root,e,seq,max_after_days):
    try:
        from server.v4_replay_final import read_tick_path
        path=read_tick_path(Path(root),e,int(seq),max_after_days)
        # Outcome truth starts at entry_seq + 1. The entry row itself is the fill,
        # not a future observation and must not participate in first-hit ordering.
        if path is not None and not getattr(path,'empty',True) and '_seq' in path.columns:
            path=path.loc[path['_seq']>int(seq)].reset_index(drop=True)
        return path
    except Exception:
        return None

def simulate(path,entry,risk,direction,target_r):
    if path is None or getattr(path,'empty',True) or risk<=0:return {}
    mfe=mae=0.0; hit={1:None,2:None,3:None,5:None}; stop_seq=None; target_seq=None
    for _,row in path.iterrows():
        p=float(row['price']); seq=int(row['_seq']); fav=p-entry if direction=='long' else entry-p; adv=entry-p if direction=='long' else p-entry
        mfe=max(mfe,fav); mae=max(mae,adv)
        if stop_seq is None and adv>=risk:stop_seq=seq
        for rr in hit:
            if hit[rr] is None and fav>=rr*risk:hit[rr]=seq
        if target_seq is None and fav>=target_r*risk:target_seq=seq
    if stop_seq is not None and (target_seq is None or stop_seq<target_seq):realized=-1.0
    elif target_seq is not None:realized=float(target_r)
    else:
        last=float(path['price'].iloc[-1]); realized=(last-entry if direction=='long' else entry-last)/risk
    return {'mfe_points':mfe,'mae_points':mae,'mfe_r':mfe/risk,'mae_r':mae/risk,
            'hit_1r':int(hit[1] is not None and (stop_seq is None or hit[1]<stop_seq)),
            'hit_2r':int(hit[2] is not None and (stop_seq is None or hit[2]<stop_seq)),
            'hit_3r':int(hit[3] is not None and (stop_seq is None or hit[3]<stop_seq)),
            'hit_5r':int(hit[5] is not None and (stop_seq is None or hit[5]<stop_seq)),
            'stop_first':int(stop_seq is not None and (target_seq is None or stop_seq<target_seq)),
            'target_first':int(target_seq is not None and (stop_seq is None or target_seq<stop_seq)),
            'realized_r':realized,'capture_ratio':(realized/(mfe/risk) if mfe>0 and realized>0 else 0.0)}

def compute_outcomes(event_db:str|Path,data_root:str|Path,research_run_id:str,*,max_after_days:int=1,require_sanity=True):
    migrate_event_db(event_db); con=connect(event_db)
    try:
        if require_sanity and not _latest_sanity_pass(con,research_run_id): raise RuntimeError('EVENT_SANITY_GATE has not passed')
        events=[dict(r) for r in con.execute('SELECT * FROM events WHERE research_run_id=? ORDER BY source_file,trading_date,attempt_start_seq',(research_run_id,)).fetchall()]
    finally:con.close()
    done=0; rows=[]
    for e in events:
        for basis,spec in [('terminal',_terminal(e)),('strict',_strict(e))]:
            if spec is None:continue
            seq,entry,stop,etime=spec; risk=abs(entry-stop)
            if risk<=0:continue
            target_r=(1.0 if e.get('strategy')=='MR' else 2.0) if basis=='strict' else 1.0
            path=_read_path(data_root,e,seq,max_after_days); hits=simulate(path,entry,risk,e.get('direction'),target_r)
            if not hits:continue
            management={}
            try:
                from server.v4_audit import management_suite
                management=management_suite(path,entry,risk,e.get('direction'))
            except Exception:pass
            rows.append((research_run_id,e['event_id'],basis,seq,etime,entry,stop,target_r,risk,hits['mfe_points'],hits['mae_points'],hits['mfe_r'],hits['mae_r'],hits['hit_1r'],hits['hit_2r'],hits['hit_3r'],hits['hit_5r'],hits['stop_first'],hits['target_first'],hits['realized_r'],hits['capture_ratio'],json.dumps(management,ensure_ascii=False),utcnow()));done+=1
    with tx(event_db) as c:
        c.executemany('''INSERT OR REPLACE INTO opportunity_outcomes(research_run_id,event_id,basis,entry_seq,entry_time,entry_price,stop,target_r,risk_points,mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_5r,stop_first,target_first,realized_r,capture_ratio,management_json,computed_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',rows)
    return {'research_run_id':research_run_id,'computed':done,'terminal':sum(1 for r in rows if r[2]=='terminal'),'strict':sum(1 for r in rows if r[2]=='strict')}
