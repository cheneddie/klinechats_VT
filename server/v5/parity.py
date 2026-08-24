from __future__ import annotations
from typing import Any
from pydantic import BaseModel,Field

FIELDS=('state','node_id','answer','decision_seq','decision_price','entry_seq','entry_price')

class ParityRequest(BaseModel):
    historical:list[dict[str,Any]]=Field(default_factory=list)
    live:list[dict[str,Any]]=Field(default_factory=list)


def compare_traces(historical:list[dict[str,Any]],live:list[dict[str,Any]]):
    diffs=[];n=max(len(historical),len(live))
    for i in range(n):
        h=historical[i] if i<len(historical) else None;l=live[i] if i<len(live) else None
        if h is None or l is None:
            diffs.append({'index':i,'field':'row_presence','historical':h,'live':l});continue
        for f in FIELDS:
            if h.get(f)!=l.get(f):diffs.append({'index':i,'field':f,'historical':h.get(f),'live':l.get(f)})
    return {'identical':not diffs,'historical_rows':len(historical),'live_rows':len(live),'diff_count':len(diffs),'diffs':diffs[:500],
            'production_gate':'PASS' if not diffs and historical and live else 'FAIL'}


def install_parity(app):
    @app.post('/api/v5/research/parity')
    def parity(req:ParityRequest):return compare_traces(req.historical,req.live)
    return app
