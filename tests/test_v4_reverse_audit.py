from pathlib import Path
import sys
import tempfile
import json

ROOT_DIR=Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:sys.path.insert(0,str(ROOT_DIR))

from server.engine import connect
from server.v4_engine import migrate_v4_schema
from server.v4_audit import reverse_node_audit


def add_event(con,event_id,mfe,mae,gate):
    con.execute("""INSERT INTO events(event_id,source_file,year,trading_date,contract,strategy,direction,result,difficulty,attempt_start_seq,attempt_start_time,context_start_seq,context_end_seq,features_json,nodes_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id,'MTX_2025.parquet',2025,'2025-01-02','202501','MR','long','OPPORTUNITY',2,1,'2025-01-02T09:00:00',0,10,json.dumps({'terminal_signal':True}),json.dumps({'AUC_ATTEMPT':True,'MR_REJECTION':gate}), 'now'))
    con.execute("INSERT INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty,node_schema_version) VALUES(?,?,?,?,?,?,?)",(event_id,'AUC_ATTEMPT',1,1,'2025-01-02T09:00:01',2,4))
    con.execute("INSERT INTO node_instances(event_id,node_id,answer,decision_seq,decision_time,difficulty,node_schema_version) VALUES(?,?,?,?,?,?,?)",(event_id,'MR_REJECTION',1 if gate else 0,2,'2025-01-02T09:00:02',2,4))
    con.execute("""INSERT INTO opportunity_outcomes(event_id,strategy,direction,entry_seq,entry_time,entry_price,risk_points,mfe_points,mae_points,mfe_r,mae_r,hit_1r,hit_2r,hit_3r,hit_stop,management_json,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (event_id,'MR','long',3,'2025-01-02T09:00:03',100,10,mfe*10,mae*10,mfe,mae,int(mfe>=1),int(mfe>=2),int(mfe>=3),int(mae>=1),'{}','now'))


def main():
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/'a.sqlite3';con=connect(db);migrate_v4_schema(con)
        # Gate keeps two >=2R winners and rejects two large losers.
        add_event(con,'w1',3.0,.3,True);add_event(con,'w2',2.5,.5,True)
        add_event(con,'l1',.4,1.5,False);add_event(con,'l2',.2,1.2,False)
        # One small neutral on each side to ensure the score is not hard-coded.
        add_event(con,'n1',.8,.4,True);add_event(con,'n2',.7,.4,False)
        con.commit();con.close()
        out=reverse_node_audit(db,[2025],audit_id='test')
        r=next(x for x in out['rows'] if x['node_id']=='MR_REJECTION')
        assert r['universe']==6
        assert r['big_winners']==2 and r['big_winners_kept']==2 and r['big_winners_rejected']==0
        assert r['big_losers']==2 and r['big_losers_rejected']==2 and r['big_losers_kept']==0
        assert abs(r['filter_score']-1.0)<1e-9,r
        assert r['pass_2r_rate']>r['fail_2r_rate']
    print('V4 reverse audit: PASS')


if __name__=='__main__':main()
