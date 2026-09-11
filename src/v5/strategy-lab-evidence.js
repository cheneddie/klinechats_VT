(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const apiBase=()=>String(localStorage.getItem('strategyLabApi')||'http://127.0.0.1:8765/api').replace(/\/$/,'');
  async function api(path,body){
    const r=await fetch(apiBase()+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),signal:AbortSignal.timeout(30000)});
    if(!r.ok)throw new Error(`${r.status} ${r.statusText}: ${await r.text()}`);
    return r.json();
  }
  function activeCandidate(){return document.getElementById('candGate')?.value||document.getElementById('candEval')?.value||''}
  function status(target,text,ok=true){if(target)target.innerHTML=`<span class="pill ${ok?'pass':'fail'}">${ok?'OK':'FAIL'}</span> ${esc(text)}`}
  function install(){
    const gate=document.getElementById('gateRun');
    if(!gate||gate.dataset.evidenceV2)return;
    gate.dataset.evidenceV2='1';
    const card=gate.closest('.sl-card');
    if(!card)return;
    const oldLive=document.getElementById('gateLive')?.closest('label');
    const oldPaper=document.getElementById('gatePaper')?.closest('label');
    if(oldLive)oldLive.outerHTML='<label>Parity evidence ID<input id="gateParityEvidence" placeholder="parity-..."></label>';
    if(oldPaper)oldPaper.outerHTML='<label>Paper evidence ID<input id="gatePaperEvidence" placeholder="paper-..."></label>';

    if(!document.getElementById('gateProductionValuePolicy')){
      const valuePolicy=document.createElement('div');
      valuePolicy.id='gateProductionValuePolicy';
      valuePolicy.innerHTML=`
        <h3>Production Value Policy</h3>
        <p class="muted">ATR 交易價值使用 frozen event-time ATR，禁止在 Gate 時重算。NET points / ATR 預設最低 10%。月份與年度集中度必須由研究政策明確填入；留白即 FAIL，不會自動猜門檻。</p>
        <div class="params">
          <label>Min avg NET points / ATR<input id="gateMinAtrValue" type="number" step="0.01" min="0" value="0.10"></label>
          <label>Max positive month profit share<input id="gateMaxMonthShare" type="number" step="0.01" min="0.01" max="1" placeholder="required, 0 < share ≤ 1"></label>
          <label>Max positive year profit share<input id="gateMaxYearShare" type="number" step="0.01" min="0.01" max="1" placeholder="required, 0 < share ≤ 1"></label>
        </div>`;
      gate.parentElement?.insertBefore(valuePolicy,gate);
    }

    gate.onclick=async()=>{
      const id=activeCandidate();
      const monthRaw=document.getElementById('gateMaxMonthShare')?.value.trim()||'';
      const yearRaw=document.getElementById('gateMaxYearShare')?.value.trim()||'';
      const atrRaw=document.getElementById('gateMinAtrValue')?.value.trim()||'0.10';
      const body={
        parity_evidence_id:document.getElementById('gateParityEvidence')?.value.trim()||null,
        paper_evidence_id:document.getElementById('gatePaperEvidence')?.value.trim()||null,
        policy:{
          min_avg_net_points_over_atr:Number(atrRaw),
          max_positive_month_profit_share:monthRaw===''?null:Number(monthRaw),
          max_positive_year_profit_share:yearRaw===''?null:Number(yearRaw),
        },
      };
      try{
        const r=await api(`/v5/strategy-lab/candidates/${encodeURIComponent(id)}/production-gates`,body);
        const valueAudit=r.production_value?.audit||r.production_value?.audit_json||null;
        const valueHtml=valueAudit?`<h3>Production Value</h3>${(valueAudit.checks||[]).map(x=>`<div class="check"><span>${esc(x.name)}</span><b class="${x.passed?'yes':'no'}">${x.passed?'PASS':'FAIL'}</b></div>`).join('')}`:'';
        document.getElementById('gateBody').innerHTML=`<h3><span class="pill ${String(r.status).toLowerCase()}">${esc(r.status)}</span></h3>${(r.checklist||[]).map(x=>`<div class="check"><span>${esc(x.name)}</span><b class="${x.passed?'yes':'no'}">${x.passed?'PASS':'FAIL'}</b></div>`).join('')}${valueHtml}`;
      }catch(e){status(document.getElementById('gateBody'),e.message,false)}
    };

    if(document.getElementById('productionEvidenceCard'))return;
    const evidence=document.createElement('section');
    evidence.id='productionEvidenceCard';
    evidence.className='sl-card';
    evidence.innerHTML=`
      <h2>Production Evidence Registry</h2>
      <p class="muted">Production Gate 不接受手動 PASS。Live parity 與 Paper Trading 必須先形成 append-only evidence。</p>
      <div class="split">
        <div>
          <h3>Historical ↔ Live Parity</h3>
          <label>Historical trace JSON<textarea id="evHistorical" placeholder='[{"event_id":"...","node_id":"..."}]'></textarea></label>
          <label>Live trace JSON<textarea id="evLive" placeholder='[{"event_id":"...","node_id":"..."}]'></textarea></label>
          <button id="evParitySave">Verify + Freeze Parity Evidence</button>
          <div id="evParityOut"></div>
        </div>
        <div>
          <h3>Paper Trading</h3>
          <div class="params">
            <label>Source<input id="evPaperSource" placeholder="paper broker export / simulator"></label>
            <label>Artifact SHA-256<input id="evPaperSha" placeholder="64 hex chars"></label>
            <label>Trades<input id="evPaperTrades" type="number" value="30"></label>
            <label>Expectancy R<input id="evPaperEV" type="number" step="0.01"></label>
            <label>Profit Factor<input id="evPaperPF" type="number" step="0.01"></label>
            <label>Max DD R<input id="evPaperDD" type="number" step="0.1"></label>
          </div>
          <button id="evPaperSave">Validate + Freeze Paper Evidence</button>
          <div id="evPaperOut"></div>
        </div>
      </div>`;
    card.parentElement?.appendChild(evidence);

    document.getElementById('evParitySave').onclick=async()=>{
      const out=document.getElementById('evParityOut');
      try{
        const historical=JSON.parse(document.getElementById('evHistorical').value||'[]');
        const live=JSON.parse(document.getElementById('evLive').value||'[]');
        const r=await api('/v5/strategy-lab/evidence/parity',{candidate_id:activeCandidate(),historical,live});
        document.getElementById('gateParityEvidence').value=r.parity_evidence_id;
        status(out,`${r.parity_evidence_id} · ${r.status}`,r.status==='PASS');
      }catch(e){status(out,e.message,false)}
    };
    document.getElementById('evPaperSave').onclick=async()=>{
      const out=document.getElementById('evPaperOut');
      try{
        const r=await api('/v5/strategy-lab/evidence/paper',{
          candidate_id:activeCandidate(),source:document.getElementById('evPaperSource').value.trim(),
          artifact_sha256:document.getElementById('evPaperSha').value.trim().toLowerCase(),
          trades:+document.getElementById('evPaperTrades').value,
          expectancy_r:+document.getElementById('evPaperEV').value,
          profit_factor:+document.getElementById('evPaperPF').value,
          max_drawdown_r:+document.getElementById('evPaperDD').value,
        });
        document.getElementById('gatePaperEvidence').value=r.paper_evidence_id;
        status(out,`${r.paper_evidence_id} · ${r.status}`,r.status==='PASS');
      }catch(e){status(out,e.message,false)}
    };
  }
  const observer=new MutationObserver(install);
  observer.observe(document.documentElement,{childList:true,subtree:true});
  install();
})();