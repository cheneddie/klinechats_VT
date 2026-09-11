(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt=(v,d=3)=>v==null||Number.isNaN(Number(v))?'—':Number(v).toFixed(d);
  const ratio=v=>v==null?'—':`${Number(v).toFixed(2)}×`;
  const pct=v=>v==null?'—':`${(Number(v)*100).toFixed(1)}%`;
  let rendering=false;

  function apiBase(){
    return (document.getElementById('slApi')?.value||localStorage.getItem('strategyLabApi')||'http://127.0.0.1:8765/api').replace(/\/$/,'');
  }
  async function api(path,opts={}){
    const r=await fetch(apiBase()+path,{headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});
    if(!r.ok)throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
    return r.json();
  }
  function pill(state){
    const s=String(state||'—').toUpperCase();
    const cls=s==='NORMAL'||s==='ACTIVE'?'yes':s==='WATCH'?'watch':'no';
    return `<span class="pill ${cls}">${esc(s)}</span>`;
  }
  function metric(label,value,sub=''){
    return `<div class="metric"><small>${esc(label)}</small><b>${esc(value)}</b>${sub?`<small class="muted">${esc(sub)}</small>`:''}</div>`;
  }
  function insertNav(){
    const nav=document.querySelector('.sl-nav');
    if(!nav||nav.querySelector('[data-page="monitor"]'))return;
    const a=document.createElement('a');
    a.href='#/monitor';a.dataset.page='monitor';a.textContent='Strategy Health';
    const compare=nav.querySelector('[data-page="compare"]');
    if(compare)compare.insertAdjacentElement('afterend',a);else nav.appendChild(a);
  }
  function driftRows(latest){
    const d=latest?.details?.drift||{};
    const rows=[
      ['Expectancy ratio',ratio(d.expectancy_ratio)],
      ['PF ratio',ratio(d.profit_factor_ratio)],
      ['Drawdown multiple',ratio(d.drawdown_multiple)],
      ['Signal frequency ratio',ratio(d.signal_frequency_ratio)],
      ['Slippage multiple',ratio(d.slippage_multiple)],
      ['Slippage Δ points',fmt(d.slippage_delta_points)],
      ['Regime mix TVD',pct(d.regime_tvd)],
    ];
    return rows.map(([k,v])=>`<div class="check"><span>${esc(k)}</span><b>${esc(v)}</b></div>`).join('');
  }
  function historyTable(items){
    if(!items.length)return '<div class="sl-empty">No monitoring snapshots yet.</div>';
    return `<table><thead><tr><th>As of</th><th>Effective</th><th>Computed</th><th>EV</th><th>PF</th><th>DD</th><th>Signals/day</th><th>Slippage</th><th>Regime TVD</th></tr></thead><tbody>${items.map(x=>{
      const d=x.details?.drift||{};
      return `<tr><td>${esc(x.as_of_date)}</td><td>${pill(x.state)}</td><td>${pill(x.details?.computed_state||x.state)}</td><td>${fmt(x.expectancy_r)}</td><td>${fmt(x.profit_factor)}</td><td>${fmt(x.max_drawdown_r)}</td><td>${fmt(x.signal_frequency,2)}</td><td>${fmt(x.avg_slippage_points,2)}</td><td>${pct(d.regime_tvd)}</td></tr>`;
    }).join('')}</tbody></table>`;
  }
  function actionTable(items){
    if(!items.length)return '<div class="sl-empty">No human governance actions.</div>';
    return items.map(x=>`<div class="job-row"><div><b>${esc(x.action)}</b><br><small>${esc(x.created_at)}</small></div><div>${pill(x.previous_state)} → ${pill(x.next_state)}</div><div><small>${esc(x.reason)}</small></div></div>`).join('');
  }

  async function render(selectedKey=''){
    if(!location.hash.startsWith('#/monitor')||rendering)return;
    const host=document.getElementById('slMain');
    if(!host)return;
    rendering=true;
    try{
      insertNav();
      host.innerHTML='<div class="sl-empty">Loading Strategy Health…</div>';
      const [strategies,allHealth]=await Promise.all([
        api('/v5/strategy-lab/strategies'),
        api('/v5/strategy-lab/monitor-health?limit=500'),
      ]);
      const strategyItems=strategies.items||[];
      const snapshotKeys=[...new Set((allHealth.items||[]).map(x=>x.strategy_key))];
      const keys=[...new Set([...snapshotKeys,...strategyItems.map(x=>x.strategy_key)])];
      const key=selectedKey||snapshotKeys[0]||keys[0]||'';
      const health=key?await api(`/v5/strategy-lab/monitor-health?strategy_key=${encodeURIComponent(key)}&limit=200`):{items:[],controls:{}};
      const actions=key?await api(`/v5/strategy-lab/monitor-health/actions?strategy_key=${encodeURIComponent(key)}&limit=100`):{items:[]};
      const items=health.items||[];
      const latest=items[0]||null;
      const control=health.controls?.[key]||{lifecycle_state:'ACTIVE'};
      const reasons=latest?.details?.reasons||[];
      const computed=latest?.details?.computed_state||latest?.state||'—';
      const effective=latest?.state||'—';
      const lifecycle=control.lifecycle_state||'ACTIVE';
      const current=latest?.details?.current||{};
      const baseline=latest?.details?.baseline||{};
      const currentProfile=latest?.details?.current_profile||{};
      const baselineProfile=latest?.details?.baseline_profile||{};

      host.innerHTML=`<div data-strategy-health-page="1" data-monitor-state="${esc(effective)}" data-monitor-computed="${esc(computed)}" data-monitor-lifecycle="${esc(lifecycle)}">
        <div class="sl-grid">
          <section class="sl-card">
            <h2>Strategy Health · Live Lifecycle Governance</h2>
            <div class="toolbar"><label>Strategy<select id="healthStrategy">${keys.map(k=>`<option value="${esc(k)}" ${k===key?'selected':''}>${esc(k)}</option>`).join('')}</select></label><button id="healthRefresh" class="secondary">Refresh</button></div>
            <p class="muted">Rolling health can degrade or suspend a strategy. Once suspended, a later healthy window cannot auto-resume it; explicit human review is required.</p>
            <div class="metric-grid">
              ${metric('Effective state',effective,`computed ${computed}`)}
              ${metric('Lifecycle control',lifecycle,'sticky suspension latch')}
              ${metric('Current EV',`${fmt(latest?.expectancy_r)}R`,`baseline ${fmt(baseline.net_expectancy_r)}R`)}
              ${metric('Current PF',fmt(latest?.profit_factor),`baseline ${fmt(baseline.profit_factor)}`)}
              ${metric('Max DD',`${fmt(latest?.max_drawdown_r)}R`,`baseline ${fmt(baseline.max_drawdown_r)}R`)}
              ${metric('Signals/day',fmt(latest?.signal_frequency,2),`baseline ${fmt(baselineProfile.signal_frequency,2)}`)}
              ${metric('Avg slippage',`${fmt(latest?.avg_slippage_points,2)} pts`,`baseline ${fmt(baselineProfile.avg_slippage_points,2)} pts`)}
              ${metric('Regime TVD',pct(latest?.details?.drift?.regime_tvd),'0%=same mix · 100%=disjoint')}
            </div>
          </section>

          <section class="sl-card half" data-monitor-drift="1"><h2>Drift Diagnostics</h2>${latest?driftRows(latest):'<div class="sl-empty">No snapshot</div>'}</section>
          <section class="sl-card half"><h2>Health Reasons</h2>${reasons.length?reasons.map(r=>`<div class="check"><span>${esc(r)}</span><b class="no">ACTIVE</b></div>`).join(''):'<div class="check"><span>No active degradation reason</span><b class="yes">CLEAR</b></div>'}</section>

          <section class="sl-card half">
            <h2>Human Governance · No Auto-Unpause</h2>
            <label>Review reason<textarea id="healthReason" placeholder="Required for ACKNOWLEDGE / MANUAL_SUSPEND / RESUME"></textarea></label>
            <div class="toolbar"><button id="healthAck" class="secondary">Acknowledge</button><button id="healthSuspend" class="danger">Manual Suspend</button><button id="healthResume" ${lifecycle==='SUSPENDED'?'':'disabled'}>Resume after review</button></div>
            <div id="healthActionResult" class="muted"></div>
          </section>
          <section class="sl-card half"><h2>Current vs Baseline Profile</h2><pre class="code">${esc(JSON.stringify({current:currentProfile,baseline:baselineProfile},null,2))}</pre></section>

          <section class="sl-card"><h2>Health Timeline</h2>${historyTable(items)}</section>
          <section class="sl-card"><h2>Append-only Human Actions</h2><div id="healthActions">${actionTable(actions.items||[])}</div></section>
        </div>
      </div>`;

      document.getElementById('healthStrategy').onchange=e=>render(e.target.value);
      document.getElementById('healthRefresh').onclick=()=>render(key);
      async function act(action){
        const reason=document.getElementById('healthReason').value.trim();
        if(reason.length<3){document.getElementById('healthActionResult').textContent='Human review reason is required.';return;}
        const r=await api('/v5/strategy-lab/monitor-health/actions',{method:'POST',body:JSON.stringify({strategy_key:key,action,reason,details:{source:'STRATEGY_LAB_UI'}})});
        document.getElementById('healthActionResult').textContent=`${r.action.action}: ${r.action.previous_state} → ${r.action.next_state}`;
        await render(key);
      }
      document.getElementById('healthAck').onclick=()=>act('ACKNOWLEDGE');
      document.getElementById('healthSuspend').onclick=()=>act('MANUAL_SUSPEND');
      document.getElementById('healthResume').onclick=()=>act('RESUME');
    }catch(e){
      host.innerHTML=`<section class="sl-card" data-strategy-health-page="1"><h2>Strategy Health Error</h2><pre class="code">${esc(e.stack||e.message||e)}</pre></section>`;
    }finally{
      rendering=false;
    }
  }

  function schedule(){insertNav();if(location.hash.startsWith('#/monitor'))setTimeout(()=>render(),0)}
  addEventListener('hashchange',schedule);
  new MutationObserver(()=>{
    insertNav();
    if(location.hash.startsWith('#/monitor')&&!document.querySelector('[data-strategy-health-page]')&&!rendering)setTimeout(()=>render(),0);
  }).observe(document.documentElement,{subtree:true,childList:true});
  schedule();
  window.StrategyLabHealth={render};
})();
