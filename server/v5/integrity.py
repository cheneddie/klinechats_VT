from __future__ import annotations
import re
from pathlib import Path
from typing import Any

OUTRIGHT=re.compile(r'^\d{6}$')

def inspect_parquet(path:str|Path, *, sample_rows:int=200000)->dict[str,Any]:
    p=Path(path)
    if not p.exists(): return {'file':p.name,'status':'MISSING','path':str(p)}
    try:
        import pyarrow.parquet as pq
    except Exception as exc: return {'file':p.name,'status':'ERROR','error':f'pyarrow unavailable: {exc}'}
    pf=pq.ParquetFile(p); names=pf.schema.names
    required={'datetime','product','expiry','price','volume'}; missing=sorted(required-set(names))
    total=int(pf.metadata.num_rows)
    first=last=None; products=set(); expiries=set(); mt_rows=out_rows=spread_rows=0
    remain=max(0,int(sample_rows))
    for rg in range(pf.num_row_groups):
        if remain<=0: break
        cols=[x for x in ('datetime','product','expiry','volume') if x in names]
        t=pf.read_row_group(rg,columns=cols)
        n=min(len(t),remain); remain-=n
        if n<=0: continue
        if 'datetime' in cols:
            vals=t.column('datetime'); first=first if first is not None else vals[0].as_py(); last=vals[n-1].as_py()
        pro=t.column('product').slice(0,n).to_pylist() if 'product' in cols else []
        ex=t.column('expiry').slice(0,n).to_pylist() if 'expiry' in cols else []
        for x in pro:
            if x is not None: products.add(str(x))
        for x in ex:
            if x is not None: expiries.add(str(x))
        for prod,expiry in zip(pro,ex):
            if str(prod)=='MTX':
                mt_rows+=1
                if OUTRIGHT.match(str(expiry or '')): out_rows+=1
                else: spread_rows+=1
    status='PASS' if not missing else 'FAIL'
    return {'file':p.name,'path':str(p),'status':status,'rows':total,'row_groups':pf.num_row_groups,'columns':names,
            'missing_columns':missing,'sampled_rows':max(0,int(sample_rows)-remain),'sample_products':sorted(products)[:50],
            'sample_expiries':sorted(expiries)[:100],'sample_mtx_rows':mt_rows,'sample_outright_rows':out_rows,'sample_spread_rows':spread_rows,
            'first_time':str(first) if first is not None else None,'last_time':str(last) if last is not None else None,
            'invariants':{'physical_order':'PRESERVE_AS_STORED','seq_assignment':'BEFORE_FILTER','volume_normalization':'vendor_volume/2','side_semantics':'tick_direction_proxy'}}

def inspect_root(root:str|Path, years:list[int]|None=None)->dict[str,Any]:
    r=Path(root); items=[]
    if r.exists():
        for p in sorted(r.glob('MTX_*.parquet')):
            if years:
                try:y=int(re.search(r'(20\d{2})',p.stem).group(1))
                except Exception:continue
                if y not in years: continue
            items.append(inspect_parquet(p))
    return {'root':str(r),'files':items,'status':'PASS' if items and all(x['status']=='PASS' for x in items) else ('EMPTY' if not items else 'FAIL')}
