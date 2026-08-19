from __future__ import annotations
import json, os, threading, uuid
from pathlib import Path
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from .causal_engine import ScanConfig, connect, discover, scan_files, read_replay_window

ROOT=Path(os.environ.get('FABIO_DATA_ROOT',r'D:\tools\traderChatV1\data\parquet\Future'))
DB=Path(os.environ.get('FABIO_EVENT_DB',str(Path.home()/'.fabio-decision-gym'/'events.sqlite3')))
app=FastAPI(title='Fabio Decision Gym Local API',version='2.0.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_methods=['*'],allow_headers=['*'])
jobs={}

class ScanRequest(BaseModel):
    years:list[int]|None=None
    contract_mode:str='strict'

@app.get('/api/health')
def health():
    return {'ok':True,'version':'2.0.0','data_root':str(ROOT),'db':str(DB),'files':len(discover(ROOT)) if ROOT.exists() else 0}

@app.get('/api/datasets')
def datasets():
    con=connect(DB);rows=[dict(r) for r in con.execute('SELECT * FROM datasets ORDER BY year,file').fetchall()];con.close()
    if not rows and ROOT.exists():
        for p in discover(ROOT):
            try:
                y=int(p.stem.split('_')[-1]);rows.append({'file':p.name,'year':y,'rows':0,'qa':'DISCOVERED'})
            except:pass
    return {'items':rows,'root':str(ROOT)}

def event_row(r):
    d=dict(r);d['nodes']=json.loads(d.pop('nodes_json') or '{}');d['features']=json.loads(d.pop('features_json') or '{}')
    d['id']=d['event_id'];d['date']=d['trading_date'];d['attemptStartTime']=d.get('attempt_start_time');d['extremeTime']=d.get('extreme_time');d['extremePrice']=d.get('extreme_price');d['clearReclaimTime']=d.get('clear_reclaim_time');d['clearReclaimPrice']=d.get('clear_reclaim_price');d['turnConfirmTime']=d.get('turn_confirm_time');d['entryTime']=d.get('entry_time');d['entryPrice']=d.get('entry_price');d['priorProfile']={'vah':d.get('vah'),'val':d.get('val'),'poc':d.get('poc'),'width':d.get('value_width')};return d

@app.get('/api/cases')
def cases(limit:int=1000,offset:int=0,node_id:str|None=None,answer:bool|None=None,strategy:str|None=None,year:int|None=None,direction:str|None=None,difficulty:int|None=None):
    con=connect(DB);where=[];args=[];join=''
    if node_id:
        join=' JOIN node_instances n ON n.event_id=e.event_id ';where.append('n.node_id=?');args.append(node_id)
        if answer is not None:where.append('n.answer=?');args.append(1 if answer else 0)
    if strategy:where.append('e.strategy=?');args.append(strategy)
    if year:where.append('e.year=?');args.append(year)
    if direction:where.append('e.direction=?');args.append(direction)
    if difficulty:where.append('e.difficulty=?');args.append(difficulty)
    sql='SELECT e.* FROM events e '+join+(' WHERE '+' AND '.join(where) if where else '')+' ORDER BY e.trading_date,e.attempt_start_seq LIMIT ? OFFSET ?';args.extend([min(limit,10000),offset]);rows=[event_row(r) for r in con.execute(sql,args).fetchall()];con.close();return {'items':rows,'limit':limit,'offset':offset}

@app.get('/api/cases/{event_id}')
def case(event_id:str):
    con=connect(DB);r=con.execute('SELECT * FROM events WHERE event_id=?',(event_id,)).fetchone();con.close()
    if not r:raise HTTPException(404,'case not found')
    return event_row(r)

@app.get('/api/nodes/stats')
def node_stats():
    con=connect(DB);rows=[dict(r) for r in con.execute('SELECT node_id,COUNT(*) total,SUM(answer) yes_count,COUNT(*)-SUM(answer) no_count FROM node_instances GROUP BY node_id ORDER BY node_id').fetchall()];con.close();return {'items':rows}

@app.get('/api/replay/{event_id}')
def replay(event_id:str,margin:int=20000):
    con=connect(DB);r=con.execute('SELECT * FROM events WHERE event_id=?',(event_id,)).fetchone();con.close()
    if not r:raise HTTPException(404,'case not found')
    event=event_row(r);bars=read_replay_window(ROOT,event,margin=max(1000,min(margin,100000)));return {'case':event,'bars':bars,'period':'1s'}

@app.get('/api/research/summary')
def research_summary():
    con=connect(DB);summary=dict(con.execute("SELECT COUNT(*) events,SUM(strategy='MR') mr,SUM(strategy='BO') bo,SUM(strategy='WAIT') wait,SUM(result='ENTRY') entries FROM events").fetchone());by_year=[dict(r) for r in con.execute('SELECT year,COUNT(*) events,SUM(result=\'ENTRY\') entries FROM events GROUP BY year ORDER BY year').fetchall()];con.close();return {'summary':summary,'by_year':by_year}

@app.get('/api/scan/status')
def scan_status():return {'items':list(jobs.values())[-20:]}

@app.post('/api/scan')
def scan(req:ScanRequest):
    if not ROOT.exists():raise HTTPException(400,f'data root not found: {ROOT}')
    job=str(uuid.uuid4())[:8];jobs[job]={'job_id':job,'status':'queued','years':req.years,'started_at':datetime.now(timezone.utc).isoformat(),'events':0,'message':''}
    def run():
        jobs[job]['status']='running'
        def progress(file,stage,count):jobs[job].update(file=file,stage=stage,events=count)
        try:
            cfg=ScanConfig(contract_mode=req.contract_mode);count=scan_files(ROOT,DB,req.years,cfg,progress);jobs[job].update(status='done',events=count,finished_at=datetime.now(timezone.utc).isoformat())
        except Exception as e:jobs[job].update(status='failed',message=f'{type(e).__name__}: {e}',finished_at=datetime.now(timezone.utc).isoformat())
    threading.Thread(target=run,daemon=True).start();return jobs[job]

def main():
    import uvicorn;uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('FABIO_API_PORT','8765')))

if __name__=='__main__':main()
