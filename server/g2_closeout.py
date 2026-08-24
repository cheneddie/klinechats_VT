from __future__ import annotations
from copy import deepcopy
from typing import Any
import pandas as pd

REACHABILITY_VERSION = 'G2_NODE_REACHABILITY_V1_20260823'
CAUSAL_REPAIR_VERSION = 'G2_CAUSAL_ORDERING_AMENDMENT_001'

MR_CHAIN=['AUC_ATTEMPT','MR_REJECTION','MR_CLEAR_RECLAIM','MR_RECLAIM_LEG','MR_LVN','MR_PULLBACK','MR_ENTRY']
BO_CHAIN=['AUC_ATTEMPT','BO_DISPLACEMENT','BO_ACCEPTANCE','BO_IMPULSE_LEG','BO_LVN','BO_PULLBACK','BO_RESPONSE','BO_ENTRY']
# Frozen node-registry structural parents. AUC_EXTREME is structural/contextual, not a blocking edge.
PARENTS={
 'AUC_ATTEMPT':'CTX_VALUE','AUC_EXTREME':'AUC_ATTEMPT',
 'MR_REJECTION':'AUC_ATTEMPT','MR_CLEAR_RECLAIM':'MR_REJECTION','MR_RECLAIM_LEG':'MR_CLEAR_RECLAIM','MR_LVN':'MR_RECLAIM_LEG','MR_PULLBACK':'MR_LVN','MR_ENTRY':'MR_PULLBACK',
 'BO_DISPLACEMENT':'AUC_ATTEMPT','BO_ACCEPTANCE':'BO_DISPLACEMENT','BO_IMPULSE_LEG':'BO_ACCEPTANCE','BO_LVN':'BO_IMPULSE_LEG','BO_PULLBACK':'BO_LVN','BO_RESPONSE':'BO_PULLBACK','BO_ENTRY':'BO_RESPONSE',
}
BLOCKING_EDGES=set((PARENTS[c],c) for c in MR_CHAIN[1:]+BO_CHAIN[1:]) | {('CTX_VALUE','AUC_ATTEMPT')}
VALID_STATUSES={'EVALUATED','NOT_REACHED','NOT_APPLICABLE','TERMINAL'}

def _iso(v):
    if v is None:return None
    return pd.Timestamp(v).isoformat()

def _phys_map(g: pd.DataFrame):
    # once per day; physical _seq -> (time, price)
    return {int(s):(_iso(t),float(p)) for s,t,p in zip(g['_seq'].to_numpy(),g['dt'].to_numpy(),g['price'].to_numpy())}

def _at(pm,seq):
    if seq is None:return (None,None,None)
    r=pm.get(int(seq))
    if r is None:return (None,None,None)
    return int(seq),r[0],r[1]

def _preserve_observation(n:dict[str,Any]):
    n['observation_decision_seq']=n.get('seq'); n['observation_decision_time']=n.get('time'); n['observation_decision_price']=n.get('decision_price')
    n['observation_anchor_seq']=n.get('anchor_seq'); n['observation_anchor_time']=n.get('anchor_time'); n['observation_anchor_price']=n.get('anchor_price')
    n['counterfactual_answer']=n.get('answer'); n['counterfactual_reason_code']=n.get('reason_code')

def _physicalize_anchor(n,pm,formal_decision_seq):
    obs=n.get('observation_anchor_seq')
    # Preserve the legacy semantic/structural price separately if it is not the raw price at its claimed physical seq.
    if obs is not None and int(obs) in pm:
        raw=pm[int(obs)][1]
        old=n.get('observation_anchor_price')
        if old is not None and abs(float(old)-float(raw))>1e-9:
            n['reference_price']=float(old)
    # A formal anchor may not come after the formal decision.
    aseq=obs if obs is not None and formal_decision_seq is not None and int(obs)<=int(formal_decision_seq) else formal_decision_seq
    aseq,at,ap=_at(pm,aseq)
    n['anchor_seq']=aseq;n['anchor_time']=at;n['anchor_price']=ap

def _set_formal_decision(n,pm,seq):
    s,t,p=_at(pm,seq); n['seq']=s;n['time']=t;n['decision_price']=p
    n['resolution_seq']=s;n['resolution_time']=t;n['resolution_price']=p
    _physicalize_anchor(n,pm,s)

def _mark_not_reached(n,blocker_id,blocker):
    n['evaluation_status']='NOT_REACHED';n['answer']=None;n['blocker_node_id']=blocker_id;n['blocker_reason_code']=blocker.get('reason_code')
    n['seq']=None;n['time']=None;n['decision_price']=None;n['anchor_seq']=None;n['anchor_time']=None;n['anchor_price']=None
    n['resolution_seq']=blocker.get('resolution_seq');n['resolution_time']=blocker.get('resolution_time');n['resolution_price']=blocker.get('resolution_price')

def _mark_not_applicable(n,pm):
    n['evaluation_status']='NOT_APPLICABLE';n['answer']=None;n['blocker_node_id']=None;n['blocker_reason_code']=None
    # applicability becomes knowable no later than the legacy contextual observation; keep a causal resolution but no decision assertion.
    s=n.get('observation_decision_seq') or n.get('observation_anchor_seq')
    s,t,p=_at(pm,s);n['seq']=None;n['time']=None;n['decision_price']=None;n['anchor_seq']=None;n['anchor_time']=None;n['anchor_price']=None
    n['resolution_seq']=s;n['resolution_time']=t;n['resolution_price']=p

def _init_nodes(event,pm):
    for nid,n in (event.get('nodes') or {}).items():
        _preserve_observation(n)
        n['parent_node_id']=PARENTS.get(nid);n['blocker_node_id']=None;n['blocker_reason_code']=None;n['reachability_version']=REACHABILITY_VERSION
        # default formal decision = legacy physical decision; parent gating may shift it later.
        _set_formal_decision(n,pm,n.get('observation_decision_seq'))
        n['evaluation_status']='EVALUATED'

def _formalize_chain(event,chain,pm):
    nodes=event.get('nodes') or {}; blocker_id=None; blocker=None
    for nid in chain:
        n=nodes.get(nid)
        if not n: continue
        if blocker_id is not None:
            _mark_not_reached(n,blocker_id,blocker); continue
        parent=PARENTS.get(nid); parent_n=nodes.get(parent) if parent else None
        obs=n.get('observation_decision_seq')
        pseq=parent_n.get('resolution_seq') if parent_n and (parent,nid) in BLOCKING_EDGES else None
        candidates=[int(x) for x in (obs,pseq) if x is not None]
        fseq=max(candidates) if candidates else None
        _set_formal_decision(n,pm,fseq)
        n['evaluation_status']='EVALUATED'
        if n.get('answer') is False:
            blocker_id=nid;blocker=n
    return blocker_id

def _repair_bo_entry(event,g,pm,cfg):
    if event.get('strategy')!='BO': return None
    nodes=event.get('nodes') or {}; entry=nodes.get('BO_ENTRY')
    if not entry or entry.get('evaluation_status')!='EVALUATED': return None
    # Repair only when every prerequisite is EVALUATED/YES; otherwise reachability already blocks Entry.
    prereq=[]
    for nid in BO_CHAIN[:-1]:
        n=nodes.get(nid)
        if not n or n.get('evaluation_status')!='EVALUATED' or n.get('answer') is not True: return None
        if n.get('resolution_seq') is not None: prereq.append(int(n['resolution_seq']))
    if not prereq:return None
    causal_seq=max(prereq)
    legacy_seq=entry.get('observation_decision_seq')
    if legacy_seq is not None and int(legacy_seq)>=causal_seq:return None
    # Exact physical row exists inside this day frame.
    if causal_seq not in pm: raise RuntimeError(f'causal eligibility seq {causal_seq} absent from day frame')
    _,ct,ep=_at(pm,causal_seq)
    lvn=event.get('lvn'); direction=event.get('direction')
    if lvn is None: raise RuntimeError('BO causal repair requires LVN')
    lvn=float(lvn); ep=float(ep)
    stop=float(lvn-cfg.bo_stop_points if direction=='long' else lvn+cfg.bo_stop_points)
    risk=abs(ep-stop); width=max(float(event.get('value_width') or 0),1e-9)
    boundary=float(event.get('vah') if direction=='long' else event.get('val'))
    extension=abs(ep-boundary)/width
    outside=ep>float(event.get('vah')) if direction=='long' else ep<float(event.get('val'))
    quality=bool(risk<=cfg.bo_entry_max_risk_points and extension<=cfg.bo_entry_max_extension_vw and outside)
    before={'answer':entry.get('counterfactual_answer'),'reason_code':entry.get('counterfactual_reason_code'),'decision_seq':legacy_seq,'event_entry_seq':event.get('entry_seq'),'result':event.get('result')}
    entry['evaluation_status']='EVALUATED';entry['answer']=quality;entry['reason_code']='ENTRY_QUALITY_PASS_CAUSAL' if quality else 'ENTRY_EXTENSION_OR_RISK_FAIL_CAUSAL'
    entry['metrics']={'risk_points':risk,'extension_vw':extension,'max_extension_vw':cfg.bo_entry_max_extension_vw,'outside_old_value':outside,'entry_basis':'all_required_gates_causally_complete'}
    _set_formal_decision(entry,pm,causal_seq)
    entry['anchor_seq']=causal_seq;entry['anchor_time']=ct;entry['anchor_price']=ep
    target=ep+cfg.bo_target_r*risk if direction=='long' else ep-cfg.bo_target_r*risk
    event.setdefault('features',{})['g2_bo_entry_repair_applied']=True
    event['features']['g2_bo_entry_legacy_decision_seq']=legacy_seq
    event['features']['g2_bo_entry_causal_eligibility_seq']=causal_seq
    event['features']['g2_bo_entry_repair_version']=CAUSAL_REPAIR_VERSION
    # Recompute strict terminal state after causal repair.
    full=all((nodes.get(x) or {}).get('evaluation_status')=='EVALUATED' and (nodes.get(x) or {}).get('answer') is True for x in BO_CHAIN)
    event['features']['strict_chain_pass']=bool(full)
    if full and quality:
        event.update(entry_seq=causal_seq,entry_time=ct,entry_price=ep,stop=stop,target=target,result='ENTRY')
    else:
        event.update(entry_seq=None,entry_time=None,entry_price=None,stop=None,target=None)
        event['result']='OPPORTUNITY' if event.get('features',{}).get('terminal_signal') else 'WAIT'
    return {'event_id':event.get('event_id'),'code':'EXPECTED_BO_STRICT_ENTRY_CAUSAL_REPAIR','before':before,'after':{'answer':quality,'reason_code':entry['reason_code'],'decision_seq':causal_seq,'event_entry_seq':event.get('entry_seq'),'result':event.get('result')}}

def apply_g2_closeout(event:dict[str,Any],g:pd.DataFrame,cfg,pm=None):
    e=deepcopy(event);pm=pm if pm is not None else _phys_map(g);nodes=e.get('nodes') or {};_init_nodes(e,pm)
    # BO contains MR_REJECTION as contextual observation; it is not part of the BO decision branch.
    if e.get('strategy')=='BO' and 'MR_REJECTION' in nodes:_mark_not_applicable(nodes['MR_REJECTION'],pm)
    blocker=None
    if e.get('strategy')=='MR': blocker=_formalize_chain(e,MR_CHAIN,pm)
    elif e.get('strategy')=='BO': blocker=_formalize_chain(e,BO_CHAIN,pm)
    # AUC_EXTREME is a structural/context state, not a blocking child of AUC_ATTEMPT.
    if 'AUC_EXTREME' in nodes:
        nodes['AUC_EXTREME']['evaluation_status']='EVALUATED'
    repair=_repair_bo_entry(e,g,pm,cfg)
    # Causal repair can change BO_ENTRY answer and therefore first failure.
    chain=MR_CHAIN if e.get('strategy')=='MR' else BO_CHAIN if e.get('strategy')=='BO' else []
    first=None
    for nid in chain:
        n=nodes.get(nid)
        if n and n.get('evaluation_status')=='EVALUATED' and n.get('answer') is False:
            first=nid;break
    e.setdefault('features',{})['first_failure_node']=first
    e['features']['reachability_version']=REACHABILITY_VERSION;e['features']['causal_repair_version']=CAUSAL_REPAIR_VERSION;e['features']['g3_node_edge_universe']='EVALUATED_ONLY'
    if chain:
        full=all((nodes.get(x) or {}).get('evaluation_status')=='EVALUATED' and (nodes.get(x) or {}).get('answer') is True for x in chain if x in nodes)
        e['features']['strict_chain_pass']=bool(full)
    # terminal state is resolved at first failure or strict entry / existing terminal observation.
    term=nodes.get('NO_TRADE')
    if term:
        _preserve_observation(term) if 'observation_decision_seq' not in term else None
        term['legacy_answer']=term.get('counterfactual_answer',term.get('answer'));term['evaluation_status']='TERMINAL';term['answer']=None;term['parent_node_id']=None
        term['blocker_node_id']=first;term['blocker_reason_code']=(nodes.get(first) or {}).get('reason_code') if first else None
        if first:
            src=nodes[first]; rs=src.get('resolution_seq')
        elif e.get('entry_seq') is not None: rs=e.get('entry_seq')
        else: rs=term.get('observation_decision_seq') or term.get('observation_anchor_seq')
        rs,rt,rp=_at(pm,rs);term['seq']=None;term['time']=None;term['decision_price']=None;term['anchor_seq']=None;term['anchor_time']=None;term['anchor_price']=None
        term['resolution_seq']=rs;term['resolution_time']=rt;term['resolution_price']=rp
    return e,repair
