import sys, os, time
import numpy as np, pandas as pd
import pyarrow.parquet as pq, pyarrow as pa
P='/mnt/data/MTX_2024(2).parquet'
start=int(sys.argv[1]); end=int(sys.argv[2]); out=sys.argv[3]
pf=pq.ParquetFile(P)
off=[0]
for i in range(pf.metadata.num_row_groups): off.append(off[-1]+pf.metadata.row_group(i).num_rows)
t0=time.time(); frames=[]
for rg in range(start,end):
    t=pf.read_row_group(rg,columns=['datetime','expiry','price','volume'])
    n=t.num_rows; seq0=off[rg]
    dt=t['datetime'].to_numpy(zero_copy_only=False)
    expiry=np.array(t['expiry'].to_pylist(),dtype=object)
    price=t['price'].to_numpy(zero_copy_only=False)
    vol=t['volume'].to_numpy(zero_copy_only=False)
    dmin=dt.astype('datetime64[m]'); day=dmin.astype('datetime64[D]'); mins=(dmin-day).astype('timedelta64[m]').astype(np.int16)
    sec=(dt.astype('datetime64[s]')-dmin.astype('datetime64[s]')).astype('timedelta64[s]').astype(np.int16)
    valid=np.fromiter((isinstance(e,str) and len(e)==6 and e.isdigit() for e in expiry),dtype=bool,count=n)
    mask=valid & (mins>=525) & ((mins<825) | ((mins==825)&(sec==0)))
    if not mask.any(): continue
    idx=np.flatnonzero(mask)
    df=pd.DataFrame({'minute':dmin[mask], 'expiry':expiry[mask], 'price':price[mask], 'volume':vol[mask], 'seq':seq0+idx})
    df['pv']=df['price']*df['volume']; df['p2v']=df['price']*df['price']*df['volume']
    g=df.groupby(['minute','expiry'],sort=False,observed=True).agg(
      open=('price','first'), high=('price','max'), low=('price','min'), close=('price','last'),
      volume=('volume','sum'), pv=('pv','sum'), p2v=('p2v','sum'), ticks=('price','size'),
      seq_first=('seq','min'), seq_last=('seq','max')).reset_index()
    frames.append(g)
if frames:
    x=pd.concat(frames,ignore_index=True)
    # Only aggregated bars are sorted. Raw tick rows are never re-sorted.
    x=x.sort_values(['minute','expiry','seq_first'],kind='stable')
    first=x.drop_duplicates(['minute','expiry'],keep='first')[['minute','expiry','open']]
    last=x.sort_values(['minute','expiry','seq_last'],kind='stable').drop_duplicates(['minute','expiry'],keep='last')[['minute','expiry','close']]
    agg=x.groupby(['minute','expiry'],as_index=False,sort=False).agg(high=('high','max'),low=('low','min'),volume=('volume','sum'),pv=('pv','sum'),p2v=('p2v','sum'),ticks=('ticks','sum'),seq_first=('seq_first','min'),seq_last=('seq_last','max'))
    agg=agg.merge(first,on=['minute','expiry']).merge(last,on=['minute','expiry'])
    agg=agg[['minute','expiry','open','high','low','close','volume','pv','p2v','ticks','seq_first','seq_last']]
    pq.write_table(pa.Table.from_pandas(agg,preserve_index=False),out,compression='zstd')
    rows=len(agg)
else:
    rows=0
print(f'chunk {start}:{end} bars={rows:,} elapsed={time.time()-t0:.2f}s out={out}')
