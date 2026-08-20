from pathlib import Path
import sys
import tempfile

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import pyarrow as pa
import pyarrow.parquet as pq

from server.v4_replay import replay_trading_window


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        path = root / 'MTX_2025.parquet'
        dt=[];price=[];product=[];expiry=[];volume=[];side=[]
        rows=[
            ('2025-01-01 09:00:00',100),('2025-01-01 09:00:00',102),('2025-01-01 09:00:00',101),
            ('2025-01-02 09:00:00',110),('2025-01-02 09:00:01',111),('2025-01-02 09:00:02',109),
            ('2025-01-03 09:00:00',120),('2025-01-03 09:00:01',121),('2025-01-03 09:00:02',119),
        ]
        for t,p in rows:
            dt.append(t);price.append(float(p));product.append('MTX');expiry.append('202501');volume.append(1);side.append(0)
        table=pa.table({'datetime':pa.array(dt,type=pa.string()),'product':product,'expiry':expiry,'price':price,'volume':volume,'side':side})
        pq.write_table(table,path,row_group_size=3)
        event={'source_file':path.name,'trading_date':'2025-01-02','date':'2025-01-02','contract':'202501'}
        meta={'AUC_ATTEMPT':{'decision_time':'2025-01-02 09:00:01'}}
        out=replay_trading_window(root,event,meta,node_id='AUC_ATTEMPT',before=1,after=1,timeframe='1s',session='full')
        assert out['dates']==['2025-01-01','2025-01-02','2025-01-03'],out['dates']
        assert len(out['bars'])==7
        first=out['bars'][0]
        assert first['open']==100.0 and first['close']==101.0 and first['high']==102.0,first
        assert first['firstSeq']==0 and first['lastSeq']==2
        out5=replay_trading_window(root,event,meta,node_id='AUC_ATTEMPT',before=1,after=1,timeframe='5s',session='full')
        assert len(out5['bars'])==3,out5['bars']
        assert out5['bars'][0]['open']==100.0 and out5['bars'][0]['close']==101.0
    print('V4 replay windows/timeframes: PASS')


if __name__=='__main__':
    main()
