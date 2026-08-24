from __future__ import annotations
from pathlib import Path
from fastapi import HTTPException
from .storage import connect


def install_replay(app, *, event_db: Path, data_root: Path):
    from server.v4_replay_final import TIMEFRAME_RULES, replay_trading_window

    def load_event(run_id: str, event_id: str):
        con=connect(event_db)
        try:
            e=con.execute('SELECT * FROM events WHERE research_run_id=? AND event_id=?',(run_id,event_id)).fetchone()
            if not e:raise HTTPException(404,'V5 event not found')
            ns=[dict(r) for r in con.execute('SELECT * FROM event_nodes WHERE research_run_id=? AND event_id=?',(run_id,event_id)).fetchall()]
            event=dict(e); meta={n['node_id']:n for n in ns};event['id']=event_id;event['date']=event.get('trading_date');event['nodeMeta']=meta
            return event,meta
        finally:con.close()

    @app.get('/api/v5/replay/{event_id}')
    def replay(event_id:str,research_run_id:str,node_id:str|None=None,days_before:int=1,days_after:int=1,timeframe:str='1m',session:str='full'):
        if timeframe not in TIMEFRAME_RULES:raise HTTPException(400,f'unsupported timeframe: {timeframe}')
        event,meta=load_event(research_run_id,event_id)
        payload=replay_trading_window(data_root,event,meta,node_id=node_id,before=max(0,min(5,days_before)),after=max(0,min(5,days_after)),timeframe=timeframe,session=session)
        return {'case':event,**payload,'visual_schema':5,'decision_price_source':'persisted_physical_seq'}

    @app.get('/api/v5/training/replay/{event_id}')
    def training_replay(event_id:str,research_run_id:str,node_id:str,days_before:int=1,timeframe:str='1m',session:str='full'):
        if timeframe not in TIMEFRAME_RULES:raise HTTPException(400,f'unsupported timeframe: {timeframe}')
        event,meta=load_event(research_run_id,event_id);node=meta.get(node_id)
        if not node:raise HTTPException(404,f'node not found: {node_id}')
        cutoff=node.get('decision_time') or node.get('anchor_time')
        if not cutoff:raise HTTPException(409,f'node has no causal decision time: {node_id}')
        payload=replay_trading_window(data_root,event,meta,node_id=node_id,before=max(0,min(5,days_before)),after=0,timeframe=timeframe,session=session,cutoff_time=cutoff)
        return {'case':event,**payload,'center_node':node_id,'visual_schema':5,'decision_price_source':'persisted_physical_seq','hide_future':True,'cutoff_basis':'physical ticks before timeframe aggregation'}
    return app
