from __future__ import annotations
from calendar import monthcalendar, WEDNESDAY
from datetime import date


def third_wednesday(year:int, month:int) -> date:
    weeks=monthcalendar(year,month)
    days=[w[WEDNESDAY] for w in weeks if w[WEDNESDAY]]
    return date(year,month,days[2])


def next_yyyymm(yyyymm:str)->str:
    y=int(yyyymm[:4]);m=int(yyyymm[4:])
    if m==12:return f'{y+1}01'
    return f'{y}{m+1:02d}'


def causal_front_month(day:str, available:list[str])->str|None:
    """Choose calendar front month without using future same-day volume ranking.

    For MTX monthly contracts, the current month remains the front contract on
    the third-Wednesday expiration date. The scanner keeps that contract only;
    any post-13:30 next-month prints are therefore not mixed into the expiring
    contract's profile. The next trading day rolls to the next month.
    """
    d=date.fromisoformat(day);current=f'{d.year}{d.month:02d}'
    target=current if d<=third_wednesday(d.year,d.month) else next_yyyymm(current)
    valid=sorted(e for e in available if len(e)==6 and e.isdigit() and e>=target)
    return valid[0] if valid else (sorted(available)[0] if available else None)


def choose_contracts(volume_map,mode='strict'):
    """Return one outright contract per trading date.

    strict/front_month are causal calendar modes. `dominant_volume` intentionally
    uses whole-day volume and is provided only as a research diagnostic; it must
    not be used to claim live-causal performance.
    """
    out={};previous=None
    for day in sorted(volume_map):
        vols=volume_map[day];available=sorted(vols)
        ranked=sorted(vols.items(),key=lambda x:(-x[1],x[0]))
        if mode=='dominant_volume':
            pick=ranked[0][0] if ranked else None
            ambiguous=len(ranked)>1 and ranked[0][1] < ranked[1][1]*1.10
            causal=False
        else:
            pick=causal_front_month(day,available)
            ambiguous=False
            causal=True
        changed=previous is not None and pick!=previous
        out[day]={
            'contract':pick,
            'roll':changed,
            'ambiguous':ambiguous,
            'causal':causal,
            'mode':mode,
            'volume':float(vols.get(pick,0)) if pick else 0.0,
            'second':float(ranked[1][1]) if len(ranked)>1 else 0.0,
        }
        previous=pick
    return out
