import glob, pandas as pd, numpy as np, json
from datetime import date,timedelta
import pyarrow as pa, pyarrow.parquet as pq
files=sorted(glob.glob('/mnt/data/min_*.parquet'))
frames=[pq.read_table(f).to_pandas() for f in files]
x=pd.concat(frames,ignore_index=True)
x=x.sort_values(['minute','expiry','seq_first'],kind='stable')
first=x.drop_duplicates(['minute','expiry'],keep='first')[['minute','expiry','open']]
last=x.sort_values(['minute','expiry','seq_last'],kind='stable').drop_duplicates(['minute','expiry'],keep='last')[['minute','expiry','close']]
agg=x.groupby(['minute','expiry'],as_index=False,sort=False).agg(high=('high','max'),low=('low','min'),volume=('volume','sum'),pv=('pv','sum'),p2v=('p2v','sum'),ticks=('ticks','sum'),seq_first=('seq_first','min'),seq_last=('seq_last','max'))
agg=agg.merge(first,on=['minute','expiry']).merge(last,on=['minute','expiry'])
agg=agg[['minute','expiry','open','high','low','close','volume','pv','p2v','ticks','seq_first','seq_last']]
agg['day']=pd.to_datetime(agg['minute']).dt.date

def third_wed(y,m):
 d=date(y,m,1); return d+timedelta(days=((2-d.weekday())%7)+14)
def front_for(d):
 if d<=third_wed(d.year,d.month): return f'{d.year:04d}{d.month:02d}'
 return f'{d.year+1:04d}01' if d.month==12 else f'{d.year:04d}{d.month+1:02d}'
agg['front']=agg['day'].map(front_for)
qa=[]
for d,g in agg.groupby('day',sort=True):
 if d.year!=2024: continue
 exps=sorted(g['expiry'].unique()); fr=front_for(d); vols=g.groupby('expiry')['volume'].sum().to_dict()
 qa.append({'day':str(d),'front':fr,'front_present':fr in exps,'expiries':exps,'volumes':{k:round(float(v),2) for k,v in vols.items()},'dominant':max(vols,key=vols.get) if vols else None})
active=agg[(agg['day'].map(lambda d:d.year)==2024)&(agg['expiry']==agg['front'])].copy()
active=active.sort_values(['minute','seq_first'],kind='stable')
pq.write_table(pa.Table.from_pandas(active.drop(columns=['day','front']),preserve_index=False),'/mnt/data/MTX_2024_front_day_1m.parquet',compression='zstd')
summary={
 'partial_files':files,'all_outright_day_minute_contract_bars':int(len(agg)),
 'active_front_1m_bars':int(len(active)),'trading_days':int(active['day'].nunique()),
 'front_missing_days':sum(not q['front_present'] for q in qa),
 'multi_outright_days':sum(len(q['expiries'])>1 for q in qa),
 'dominant_differs_from_front_days':sum(q['dominant']!=q['front'] for q in qa),
 'first_minute':str(active['minute'].min()),'last_minute':str(active['minute'].max()),
 'days_examples':qa[:5],
 'roll_window_examples':[q for q in qa if len(q['expiries'])>1][:20]
}
open('/mnt/data/minute_qa_2024.json','w').write(json.dumps(summary,ensure_ascii=False,indent=2))
print(json.dumps(summary,ensure_ascii=False,indent=2))
