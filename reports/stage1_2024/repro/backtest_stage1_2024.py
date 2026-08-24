import pandas as pd, numpy as np, math, json
import pyarrow.parquet as pq
from collections import defaultdict

P='/mnt/data/MTX_2024_front_day_1m.parquet'
df=pq.read_table(P).to_pandas()
df['minute']=pd.to_datetime(df['minute'])
df['day']=df['minute'].dt.date
df['tod']=df['minute'].dt.strftime('%H:%M')
daily=df.groupby('day',sort=True).agg(open=('open','first'),high=('high','max'),low=('low','min'),close=('close','last'),volume=('volume','sum')).reset_index()
daily['prev_close']=daily['close'].shift(1)
daily['tr']=np.maximum(daily['high']-daily['low'], np.maximum((daily['high']-daily['prev_close']).abs(),(daily['low']-daily['prev_close']).abs()))
daily['atr14']=daily['tr'].rolling(14,min_periods=10).mean().shift(1)
daily_map=daily.set_index('day')[['atr14','prev_close','tr']].to_dict('index')
df['cum_vol']=df.groupby('day')['volume'].cumsum()
df['cum_pv']=df.groupby('day')['pv'].cumsum()
df['cum_p2v']=df.groupby('day')['p2v'].cumsum()
df['vwap']=df['cum_pv']/df['cum_vol']
var=df['cum_p2v']/df['cum_vol']-df['vwap']**2
df['sigma']=np.sqrt(np.maximum(var,0))

def exit_bar_at_or_before(g, hhmm='13:40'):
    z=g[g['tod']<=hhmm]
    return z.iloc[-1] if len(z) else g.iloc[-1]

def simulate(g, entry_pos, side, entry, stop, target, risk, exit_hhmm='13:40'):
    # Baseline minute-bar generator used conservative stop-first on same-bar ambiguity.
    # Canonical published results were subsequently corrected with raw physical tick order.
    bars=g.iloc[entry_pos:]
    last=exit_bar_at_or_before(g,exit_hhmm)
    for _,r in bars.iterrows():
        if r['minute']>last['minute']: break
        if side==1:
            hit_s=r['low']<=stop; hit_t=r['high']>=target
            if hit_s: return stop, r['minute'], 'STOP', stop-entry
            if hit_t: return target, r['minute'], 'TARGET', target-entry
        else:
            hit_s=r['high']>=stop; hit_t=r['low']<=target
            if hit_s: return stop, r['minute'], 'STOP', entry-stop
            if hit_t: return target, r['minute'], 'TARGET', entry-target
    px=float(last['close']); pnl=(px-entry)*side
    return px,last['minute'],'EOD',pnl

def rec(strategy,param,day,signal_time,entry_time,side,entry,stop,target,exit_px,exit_time,reason,pnl,risk,extra=None):
    atr=daily_map.get(day,{}).get('atr14',np.nan)
    return {'strategy':strategy,'param':param,'day':str(day),'signal_time':str(signal_time),'entry_time':str(entry_time),'side':'LONG' if side==1 else 'SHORT',
            'entry':entry,'stop':stop,'target':target,'exit':exit_px,'exit_time':str(exit_time),'exit_reason':reason,
            'risk_pts':risk,'pnl_pts':pnl,'R':pnl/risk if risk>0 else np.nan,'atr14':atr,'pnl_atr':pnl/atr if atr and not np.isnan(atr) else np.nan, **(extra or {})}

trades=[]
for day,g0 in df.groupby('day',sort=True):
    g=g0.reset_index(drop=True)
    if len(g)<100: continue
    start=g.iloc[0]['minute']
    for orn in [5,15,30,60]:
        end=start+pd.Timedelta(minutes=orn)
        orbars=g[(g['minute']>=start)&(g['minute']<end)]
        if len(orbars)<max(3,int(orn*0.6)): continue
        H=float(orbars['high'].max()); L=float(orbars['low'].min()); W=H-L
        if W<=0: continue
        sigs=g[(g['minute']>=end)&(g['tod']<='11:30')]
        sig=None; side=0
        for i,r in sigs.iterrows():
            if r['close']>H: sig=(i,r); side=1; break
            if r['close']<L: sig=(i,r); side=-1; break
        if sig is None: continue
        si,sr=sig; ep=si+1
        if ep>=len(g): continue
        er=g.iloc[ep]; entry=float(er['open'])
        for depth in [0.5,1.0]:
            if side==1:
                stop=H-depth*W; risk=entry-stop
                if risk<=0: continue
                target=entry+2*risk
            else:
                stop=L+depth*W; risk=stop-entry
                if risk<=0: continue
                target=entry-2*risk
            ex,et,rs,pnl=simulate(g,ep,side,entry,stop,target,risk)
            trades.append(rec('ORB',f'OR{orn}_STOP{depth:g}OR_2R',day,sr['minute'],er['minute'],side,entry,stop,target,ex,et,rs,pnl,risk,{'or_width':W}))

    end15=start+pd.Timedelta(minutes=15)
    or15=g[(g['minute']>=start)&(g['minute']<end15)]
    if len(or15)>=9:
        H=float(or15['high'].max()); L=float(or15['low'].min()); W=H-L; buf=max(2.0,0.10*W)
        search=g[(g['minute']>=end15)&(g['tod']<='11:30')]
        for win in [1,3,5,10]:
            candidate=None
            for i,r in search.iterrows():
                up=r['high']>=H+buf; dn=r['low']<=L-buf
                if up and dn: continue
                if not (up or dn): continue
                s=-1 if up else 1
                sub=g.iloc[i:min(i+win+1,len(g))]
                rr=sub[sub['close']<=H] if s==-1 else sub[sub['close']>=L]
                if len(rr)==0: continue
                ri=int(rr.index[0]); rrec=g.iloc[ri]
                if (rrec['minute']-r['minute'])>pd.Timedelta(minutes=win): continue
                candidate=(i,ri,s,r,rrec); break
            if candidate:
                i,ri,side,exc,rr=candidate; ep=ri+1
                if ep>=len(g): continue
                er=g.iloc[ep]; entry=float(er['open']); path=g.iloc[i:ri+1]
                if side==-1:
                    extreme=float(path['high'].max()); stop=extreme+1.0; risk=stop-entry; target=entry-risk
                else:
                    extreme=float(path['low'].min()); stop=extreme-1.0; risk=entry-stop; target=entry+risk
                if risk<=0: continue
                ex,et,rs,pnl=simulate(g,ep,side,entry,stop,target,risk)
                trades.append(rec('FAILED_BREAKOUT',f'OR15_BUF10pctMin2_WIN{win}m_1R',day,rr['minute'],er['minute'],side,entry,stop,target,ex,et,rs,pnl,risk,{'or_width':W,'buffer':buf,'extreme':extreme}))

    for k in [1.5,2.0,2.5,3.0]:
        search=g[(g['tod']>='09:15')&(g['tod']<='12:30')&(g['sigma']>0)]
        candidate=None
        for i,r in search.iterrows():
            z=(r['close']-r['vwap'])/r['sigma']
            if z>=k: candidate=(i,r,-1,z); break
            if z<=-k: candidate=(i,r,1,z); break
        if candidate is None: continue
        si,sr,side,z=candidate; ep=si+1
        if ep>=len(g): continue
        er=g.iloc[ep]; entry=float(er['open']); vw=float(sr['vwap']); sg=float(sr['sigma'])
        if side==-1:
            stop=vw+(k+1.0)*sg; target=vw; risk=stop-entry; reward=entry-target
        else:
            stop=vw-(k+1.0)*sg; target=vw; risk=entry-stop; reward=target-entry
        if risk<=0 or reward<=0 or reward/risk<1.0: continue
        ex,et,rs,pnl=simulate(g,ep,side,entry,stop,target,risk)
        trades.append(rec('VWAP_MR',f'Z{k:g}_STOP_Z{k+1:g}_TARGET_VWAP',day,sr['minute'],er['minute'],side,entry,stop,target,ex,et,rs,pnl,risk,{'signal_z':z,'signal_vwap':vw,'signal_sigma':sg,'planned_rr':reward/risk}))

T=pd.DataFrame(trades)
T.to_csv('/mnt/data/stage1_trades_2024.csv',index=False)

def pf(v):
    pos=v[v>0].sum(); neg=-v[v<0].sum()
    return float(pos/neg) if neg>0 else (float('inf') if pos>0 else np.nan)

def summarize(gr):
    n=len(gr); win=(gr.R>0).mean() if n else np.nan
    return pd.Series({'N':n,'WinRate':win,'AvgR':gr.R.mean(),'MedianR':gr.R.median(),'TotalR':gr.R.sum(),'PF_R':pf(gr.R),
      'AvgPts':gr.pnl_pts.mean(),'MedianPts':gr.pnl_pts.median(),'AvgWinPts':gr.loc[gr.pnl_pts>0,'pnl_pts'].mean(),
      'AvgLossPts':gr.loc[gr.pnl_pts<0,'pnl_pts'].mean(),'AvgPnL_ATR':gr.pnl_atr.mean(),
      'TargetRate':(gr.exit_reason=='TARGET').mean(),'StopRate':(gr.exit_reason=='STOP').mean(),'EODRate':(gr.exit_reason=='EOD').mean(),
      'LongN':(gr.side=='LONG').sum(),'ShortN':(gr.side=='SHORT').sum()})

S=T.groupby(['strategy','param']).apply(summarize,include_groups=False).reset_index()
for cost in [1.0,2.0]:
    vals=[]
    for _,r in S.iterrows():
        g=T[(T.strategy==r.strategy)&(T.param==r.param)].copy(); net=g.pnl_pts-cost; netR=net/g.risk_pts
        vals.append({'strategy':r.strategy,'param':r.param,f'AvgR_net{cost:g}pt':netR.mean(),f'PF_net{cost:g}pt':pf(netR),f'AvgPts_net{cost:g}pt':net.mean()})
    S=S.merge(pd.DataFrame(vals),on=['strategy','param'])
S=S.sort_values(['strategy','AvgR'],ascending=[True,False])
T['month']=pd.to_datetime(T['day']).dt.to_period('M').astype(str)
M=T.groupby(['strategy','param','month']).apply(summarize,include_groups=False).reset_index()
M.to_csv('/mnt/data/stage1_monthly_2024.csv',index=False)
rob=[]
for (st,pa),g in T.groupby(['strategy','param']):
    mm=g.groupby('month').R.mean()
    h1=g[pd.to_datetime(g.day).dt.month<=6].R.mean(); h2=g[pd.to_datetime(g.day).dt.month>=7].R.mean()
    rob.append({'strategy':st,'param':pa,'positive_months':int((mm>0).sum()),'months_with_trades':int(len(mm)),'worst_month_avgR':float(mm.min()),'best_month_avgR':float(mm.max()),'H1_AvgR':float(h1),'H2_AvgR':float(h2)})
S=S.merge(pd.DataFrame(rob),on=['strategy','param'])
S.to_csv('/mnt/data/stage1_summary_2024.csv',index=False)
