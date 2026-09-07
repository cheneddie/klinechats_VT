(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const short=s=>s?`${String(s).slice(0,10)}…${String(s).slice(-6)}`:'—';
  const fmt=(v,d=3)=>v==null||Number.isNaN(Number(v))?'—':Number(v).toFixed(d);
  let rendering=false;

  function apiBase(){
    return (document.getElementById('slApi')?.value||localStorage.getItem('strategyLabApi')||'http://127.0.0.1:8765/api').replace(/\/$/,'');
  }
  async function api(path,opts={}){
    const r=await fetch(apiBase()+path,{headers:{'Content-Type':'application/json',...(opts.headers||{})},...opts});
    if(!r.ok)throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
    return r.json();
  }
  function pill(value,kind='state'){
    const s=String(value??'—').toUpperCase();
    const good=s==='ACTIVE'||s==='NORMAL'||s==='YES'||s==='TRUE'||s==='PASS';
    const warn=s==='WATCH';
    return `<span class="pill ${good?'yes':warn?'watch':'no'}" data-${kind}="${esc(s)}">${esc(s)}</span>`;
  }
  function insertNav(){
    const nav=document.querySelector('.sl-nav');
    if(!nav||nav.querySelector('[data-page="deployments"]'))return;
    const a=document.createElement('a');
    a.href='#/deployments';a.dataset.page='deployments';a.textContent='Production Deployments';
    const health=nav.querySelector('[data-page="monitor"]');
    if(health)health.insertAdjacentElement('afterend',a);else nav.appendChild(a);
  }
  function identityRows(d){
    return [
      ['Deployment',d.deployment_id],
      ['Candidate',d.candidate_id],
      ['Production Gate',d.production_gate_id],
      ['Strategy',d.strategy_key],
      ['Strategy hash',d.strategy_hash],
      ['Parameters hash',d.parameters_hash],
      ['Execution hash',d.execution_hash],
      ['Execution model',`${d.execution_model_id||'—'} @ ${d.execution_model_version||'—'}`],
      ['Portfolio policy hash',d.portfolio_policy_hash],
      ['Code commit',d.code_commit||'UNPINNED'],
      ['Deployment identity hash',d.identity_hash],
    ].map(([k,v])=>`<div class="check"><span>${esc(k)}</span><b title="${esc(v)}">${esc(k.includes('hash')||k==='Code commit'?short(v):v)}</b></div>`).join('');
  }
  function deploymentCard(d,selected){
    const latest=d.latest_health||{};
    const computed=latest.details?.computed_state||latest.state||'—';
    const effective=latest.state||'NO SNAPSHOT';
    const lifecycle=d.control?.lifecycle_state||'—';
    return `<button class="sl-card deployment-card ${selected?'selected':''}" data-deployment-id="${esc(d.deployment_id)}">
      <div class="toolbar"><b>${esc(d.deployment_id)}</b>${pill(d.production_eligible?'YES':'NO','eligible')}</div>
      <small>${esc(d.strategy_key)} · ${esc(d.candidate_id)}</small>
      <div class="metric-grid compact">
        <div class="metric"><small>Lifecycle</small><b>${esc(lifecycle)}</b></div>
        <div class="metric"><small>Computed</small><b>${esc(computed)}</b></div>
        <div class="metric"><small>Effective</small><b>${esc(effective)}</b></div>
      </div>
    </button>`;
  }
  function healthTable(items){
    if(!items.length)return '<div class="sl-empty">No deployment health snapshots yet.</div>';
    return `<table><thead><tr><th>As of</th><th>Effective</th><th>Computed</th><th>EV</th><th>PF</th><th>DD</th><th>Signals/day</th><th>Slippage</th></tr></thead><tbody>${items.map(x=>`<tr><td>${esc(x.as_of_date)}</td><td>${pill(x.state)}</td><td>${pill(x.details?.computed_state||x.state)}</td><td>${fmt(x.expectancy_r)}</td><td>${fmt(x.profit_factor)}</td><td>${fmt(x.max_drawdown_r)}</td><td>${fmt(x.signal_frequency,2)}</td><td>${fmt(x.avg_slippage_points,2)}</td></tr>`).join('')}</tbody></table>`;
  }
  function actionRows(items){
    if(!items.length)return '<div class="sl-empty">No deployment governance actions.</div>';
    return items.map(x=>`<div class="job-row"><div><b>${esc(x.action)}</b><br><small>${esc(x.created_at)}</small></div><div>${pill(x.previous_state)} → ${pill(x.next_state)}</div><div><small>${esc(x.reason)}</small></div></div>`).join('');
  }

  async function render(selected=''){
    if(!location.hash.startsWith('#/deployments')||rendering)return;
    const host=document.getElementById('slMain');
    if(!host)return;
    rendering=true;
    try{
      insertNav();
      host.innerHTML='<div class="sl-empty">Loading Production Deployments…</div>';
      const list=await api('/v5/strategy-lab/deployments?limit=200');
      const deployments=list.items||[];
      const id=selected||deployments[0]?.deployment_id||'';
      const detail=id?await api(`/v5/strategy-lab/deployments/${encodeURIComponent(id)}`):null;
      const health=id?await api(`/v5/strategy-lab/deployments/${encodeURIComponent(id)}/monitor-health?limit=200`):{items:[]};
      const actions=id?await api(`/v5/strategy-lab/deployments/${encodeURIComponent(id)}/actions?limit=100`):{items:[]};
      const lifecycle=detail?.control?.lifecycle_state||'—';
      const latest=detail?.latest_health||null;
      const computed=latest?.details?.computed_state||latest?.state||'—';
      const effective=latest?.state||'NO SNAPSHOT';
      const identityValid=detail?.identity_verification?.valid===true;

      host.innerHTML=`<div data-production-deployments-page="1" data-deployment-id="${esc(id)}" data-production-eligible="${detail?.production_eligible?'YES':'NO'}" data-deployment-lifecycle="${esc(lifecycle)}" data-deployment-computed="${esc(computed)}" data-deployment-effective="${esc(effective)}">
        <div class="sl-grid">
          <section class="sl-card">
            <h2>Production Deployments · Exact Identity Governance</h2>
            <p class="muted">Deployment is not “the strategy name”. It is one exact candidate + parameter hash + execution hash + portfolio hash approved by one immutable Production Gate.</p>
            ${deployments.length?`<div class="deployment-list">${deployments.map(d=>deploymentCard(d,d.deployment_id===id)).join('')}</div>`:'<div class="sl-empty">No PASS Production Gate has been deployed.</div>'}
          </section>

          ${detail?`<section class="sl-card">
            <div class="toolbar"><h2>${esc(detail.deployment_id)}</h2>${pill(detail.production_eligible?'YES':'NO','eligible')}</div>
            <div class="metric-grid">
              <div class="metric"><small>Production Eligible</small><b>${esc(detail.production_eligible?'YES':'NO')}</b></div>
              <div class="metric"><small>Lifecycle</small><b>${esc(lifecycle)}</b></div>
              <div class="metric"><small>Computed Health</small><b>${esc(computed)}</b></div>
              <div class="metric"><small>Effective Health</small><b>${esc(effective)}</b></div>
              <div class="metric"><small>Gate</small><b>${esc(detail.production_gate_pass?'PASS':'FAIL')}</b></div>
              <div class="metric"><small>Identity</small><b>${esc(identityValid?'VALID':'INVALID')}</b></div>
            </div>
          </section>

          <section class="sl-card half" data-deployment-identity="1"><h2>Immutable Deployment Identity</h2>${identityRows(detail)}</section>
          <section class="sl-card half">
            <h2>Production Eligibility Rule</h2>
            <div class="check"><span>Production Gate PASS</span>${pill(detail.production_gate_pass?'PASS':'FAIL')}</div>
            <div class="check"><span>Identity hash valid</span>${pill(identityValid?'PASS':'FAIL')}</div>
            <div class="check"><span>Lifecycle ACTIVE</span>${pill(lifecycle==='ACTIVE'?'PASS':'FAIL')}</div>
            <div class="check"><span>Latest effective health not SUSPEND</span>${pill(effective!=='SUSPEND'?'PASS':'FAIL')}</div>
            <p class="muted">After a human RESUME, the old latched SUSPEND snapshot still blocks production. A fresh matching NORMAL health snapshot is required before eligibility returns.</p>
          </section>

          <section class="sl-card half">
            <h2>Human Deployment Governance</h2>
            <label>Review reason<textarea id="deployReason" placeholder="Required for ACKNOWLEDGE / MANUAL_SUSPEND / RESUME"></textarea></label>
            <div class="toolbar"><button id="deployAck" class="secondary">Acknowledge</button><button id="deploySuspend" class="danger">Manual Suspend</button><button id="deployResume" ${lifecycle==='SUSPENDED'&&computed==='NORMAL'?'':'disabled'}>Resume after NORMAL review</button></div>
            <div id="deployActionResult" class="muted"></div>
          </section>
          <section class="sl-card half"><h2>Identity Verification</h2><pre class="code">${esc(JSON.stringify(detail.identity_verification||{},null,2))}</pre></section>
          <section class="sl-card"><h2>Deployment Health Timeline</h2>${healthTable(health.items||[])}</section>
          <section class="sl-card"><h2>Append-only Deployment Actions</h2>${actionRows(actions.items||[])}</section>`:''}
        </div>
      </div>`;

      document.querySelectorAll('[data-deployment-id]').forEach(el=>{
        if(el.classList.contains('deployment-card'))el.onclick=()=>render(el.dataset.deploymentId);
      });
      async function act(action){
        const reason=document.getElementById('deployReason').value.trim();
        if(reason.length<3){document.getElementById('deployActionResult').textContent='Human review reason is required.';return;}
        const result=await api(`/v5/strategy-lab/deployments/${encodeURIComponent(id)}/actions`,{method:'POST',body:JSON.stringify({action,reason,details:{source:'STRATEGY_LAB_UI'}})});
        document.getElementById('deployActionResult').textContent=`${result.action.action}: ${result.action.previous_state} → ${result.action.next_state}`;
        await render(id);
      }
      if(detail){
        document.getElementById('deployAck').onclick=()=>act('ACKNOWLEDGE');
        document.getElementById('deploySuspend').onclick=()=>act('MANUAL_SUSPEND');
        document.getElementById('deployResume').onclick=()=>act('RESUME');
      }
    }catch(e){
      host.innerHTML=`<section class="sl-card" data-production-deployments-page="1"><h2>Production Deployments Error</h2><pre class="code">${esc(e.stack||e.message||e)}</pre></section>`;
    }finally{rendering=false;}
  }

  function schedule(){insertNav();if(location.hash.startsWith('#/deployments'))setTimeout(()=>render(),0)}
  addEventListener('hashchange',schedule);
  new MutationObserver(()=>{
    insertNav();
    if(location.hash.startsWith('#/deployments')&&!document.querySelector('[data-production-deployments-page]')&&!rendering)setTimeout(()=>render(),0);
  }).observe(document.documentElement,{subtree:true,childList:true});
  schedule();
  window.StrategyLabDeployments={render};
})();
