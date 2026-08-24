window.FabioV4=window.FabioV4||{};
(()=>{
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const pct=v=>v==null?'—':`${(Number(v)*100).toFixed(1)}%`;
const num=(v,d=2)=>v==null?'—':Number(v).toFixed(d);
const route=()=>location.hash.replace(/^#\/?/,'').split('/').filter(Boolean)[0]||'dashboard';
const state={years:'2025',busy:false,jobId:null,timer:null};
function statusOf(r){return r?.details?.status||'neutral'}
function statusText(x){return({candidate_keep:'候選保留',redundant:'高度重複',harmful:'可能有害',insufficient:'樣本不足',neutral:'中性 / 待 OOS'})[x]||x}
function panel(){const content=$('#content');if(!content)return null;let host=$('#v4EdgeAudit');if(host)return host;host=document.createElement('section');host.id='v4EdgeAudit';host.className='v4-edge-audit';content.prepend(host);return host}
async function load(){
  const host=panel();if(!host)return;
  host.innerHTML=`<div class="v4-audit-head"><div><span>V4.1 · REVERSE NODE EDGE AUDIT</span><h2>從寬鬆終端機會逆推：每個 Gate 留下什麼、刪掉什麼？</h2>
    <p>母體不要求完整策略，也不要求 BO Response；先用 physical tick 算結果，再回頭套每個嚴格 Node，避免循環論證。</p></div>
    <div class="v4-audit-actions"><label>年份 <input id="v4AuditYears" value="${esc(state.years)}" placeholder="2024,2025"></label>
      <label>追蹤 <select id="v4AuditDays"><option value="1" selected>進場後1交易日</option><option value="2">2交易日</option><option value="3">3交易日</option></select></label>
      <button id="v4RunAudit" class="primary">執行完整 Audit</button><button id="v4Refresh">重新整理</button></div></div>
    <div id="v4AuditJob"></div><div id="v4AuditBody"><div class="v4-audit-empty">讀取研究資料…</div></div>`;
  $('#v4AuditYears').onchange=e=>state.years=e.target.value;
  $('#v4RunAudit').onclick=()=>runAudit();$('#v4Refresh').onclick=()=>refresh();
  await resumeJob();await refresh();
}
function jobHtml(j){
  if(!j)return'';const done=Number(j.done||0),total=Number(j.total||0),p=total?Math.min(100,done/total*100):(j.status==='done'?100:0);
  return `<div class="v4-job ${esc(j.status)}"><div><b>${esc(j.phase||j.status)}</b><span>${esc(j.message||'')}</span></div>
    <div class="v4-job-bar"><i style="width:${p}%"></i></div><small>${done.toLocaleString()} / ${total.toLocaleString()} · ${Number(j.elapsed_seconds||0).toFixed(1)}s${j.audit_id?' · '+esc(j.audit_id):''}</small></div>`;
}
async function runAudit(){
  if(state.busy)return;state.busy=true;
  const years=$('#v4AuditYears')?.value||state.years;state.years=years;
  const days=+($('#v4AuditDays')?.value||1);const box=$('#v4AuditJob');
  if(box)box.innerHTML=jobHtml({status:'queued',phase:'queued',message:'建立 V4 reverse-audit job…'});
  try{
    const q=new URLSearchParams({years,max_after_days:String(days)});const j=await FabioV2.store.api('/v4/audit/run?'+q,{method:'POST'});
    state.jobId=j.job_id;try{sessionStorage.setItem('fabioV4AuditJob',state.jobId)}catch{};pollJob();
  }catch(e){if(box)box.innerHTML=`<div class="v4-audit-empty">Audit 啟動失敗：${esc(e.message||e)}</div>`;state.busy=false}
}
async function resumeJob(){
  try{state.jobId=sessionStorage.getItem('fabioV4AuditJob')}catch{}
  if(!state.jobId)return;
  try{const j=await FabioV2.store.api('/v4/audit/jobs/'+encodeURIComponent(state.jobId));if(j.status==='queued'||j.status==='running'){state.busy=true;pollJob()}else{$('#v4AuditJob').innerHTML=jobHtml(j)}}catch{state.jobId=null}
}
async function pollJob(){
  if(state.timer)clearTimeout(state.timer);if(!state.jobId)return;
  try{
    const j=await FabioV2.store.api('/v4/audit/jobs/'+encodeURIComponent(state.jobId));const box=$('#v4AuditJob');if(box)box.innerHTML=jobHtml(j);
    if(j.status==='done'){state.busy=false;try{sessionStorage.removeItem('fabioV4AuditJob')}catch{};await refresh();return}
    if(j.status==='failed'){state.busy=false;return}
    state.timer=setTimeout(pollJob,1000);
  }catch(e){state.timer=setTimeout(pollJob,2000)}
}
function ciText(d){const ci=d?.delta_control_avg_r_ci95;if(!Array.isArray(ci)||ci.length<2)return'—';return `[${num(ci[0],3)}, ${num(ci[1],3)}]`}
function perYearText(d){const y=d?.per_year||{};const keys=Object.keys(y);if(!keys.length)return'—';return keys.map(k=>`${k}: ${num(y[k].filter_score,2)} / Δ${num(y[k].delta_control_avg_r,2)}R`).join(' · ')}
function auditTable(items){
  if(!items.length)return'<div class="v4-audit-empty">尚無 Audit。按「執行完整 Audit」會先算 physical-tick Outcomes，再逆推全部 Node。</div>';
  return `<div class="v4-table-wrap"><table class="v4-audit-table"><thead><tr><th>Node</th><th>策略</th><th>Universe</th><th>Pass / Fail</th>
    <th>≥2R 保留</th><th>≥3R 保留</th><th>Stop&lt;1R 排除</th><th>正收益保留</th><th>基準 Avg R Δ</th><th>95% CI</th>
    <th>Pass/Fail 2R</th><th>同 Parent 同點</th><th>Filter</th><th>跨年</th><th>判讀</th></tr></thead><tbody>${items.map(r=>{
      const d=r.details||{},bw=+r.big_winners||0,bl=+r.big_losers||0,hw=+d.huge_winners||0,pos=+d.positive_trades||0,status=statusOf(r);
      return `<tr><td><b>${esc(FabioV2.nodeMap?.[r.node_id]?.code||r.node_id)}</b><small>${esc(FabioV2.nodeMap?.[r.node_id]?.short||'')}</small></td>
        <td>${esc(r.strategy)}</td><td>${(+r.universe||0).toLocaleString()}</td><td>${r.pass_count} / ${r.fail_count}</td>
        <td>${bw?`${r.big_winners_kept}/${bw} (${pct(r.big_winners_kept/bw)})`:'—'}</td>
        <td>${hw?`${d.huge_winners_kept}/${hw} (${pct(d.huge_winners_kept/hw)})`:'—'}</td>
        <td>${bl?`${r.big_losers_rejected}/${bl} (${pct(r.big_losers_rejected/bl)})`:'—'}</td>
        <td>${pos?`${d.positive_trades_kept}/${pos} (${pct(d.positive_trades_kept/pos)})`:'—'}</td>
        <td>${num(d.delta_control_avg_r,3)}R</td><td>${ciText(d)}</td>
        <td>${pct(r.pass_2r_rate)} / ${pct(r.fail_2r_rate)}</td><td>${pct(r.same_seq_parent_rate)}</td><td>${num(r.filter_score,3)}</td>
        <td><small>${esc(perYearText(d))}</small></td><td><span class="v4-audit-badge ${esc(status)}">${esc(statusText(status))}</span></td></tr>`}).join('')}</tbody></table></div>`;
}
function mgmtTable(items){
  if(!items.length)return'<div class="v4-audit-empty">尚無 Trade Management 統計。</div>';
  return `<div class="v4-table-wrap"><table class="v4-audit-table"><thead><tr><th>策略</th><th>管理法</th><th>N</th><th>Avg R</th><th>Total R</th><th>PF</th><th>Win</th><th>P10</th><th>Median</th><th>P90</th><th>Max</th></tr></thead><tbody>${items.map(x=>`<tr>
    <td>${esc(x.strategy)}</td><td>${esc(x.name)}</td><td>${x.n}</td><td>${num(x.avg_r)}R</td><td>${num(x.total_r)}R</td><td>${num(x.profit_factor)}</td>
    <td>${pct(x.win_rate)}</td><td>${num(x.p10_r)}R</td><td>${num(x.median_r)}R</td><td>${num(x.p90_r)}R</td><td>${num(x.max_r)}R</td></tr>`).join('')}</tbody></table></div>`;
}
function ablationTable(data){
  const blocks=[];for(const st of['MR','BO']){const rows=data?.[st]||[];if(!rows.length)continue;blocks.push(`<div class="v4-ablation"><h4>${st} Ablation</h4><table class="v4-audit-table"><thead><tr>
    <th>移除 Gate</th><th>N</th><th>1R</th><th>2R</th><th>3R</th><th>Avg MFE</th><th>Avg MAE</th><th>Avg Control R</th><th>Total R</th><th>新增機會</th></tr></thead><tbody>${rows.map(x=>`<tr>
    <td>${esc(x.removed)}</td><td>${x.n}</td><td>${pct(x.hit_1r_rate)}</td><td>${pct(x.hit_2r_rate)}</td><td>${pct(x.hit_3r_rate)}</td>
    <td>${num(x.avg_mfe_r)}R</td><td>${num(x.avg_mae_r)}R</td><td>${num(x.avg_control_r)}R</td><td>${num(x.total_control_r)}R</td><td>${x.added_vs_full}</td></tr>`).join('')}</tbody></table></div>`)}return blocks.join('')||'<div class="v4-audit-empty">尚無 Ablation 資料。</div>';
}
async function refresh(){
  const body=$('#v4AuditBody');if(!body)return;
  try{
    const [a,m,ab]=await Promise.all([FabioV2.store.api('/v4/audit/latest'),FabioV2.store.api('/v4/management/summary'),FabioV2.store.api('/v4/audit/ablation?'+new URLSearchParams({years:state.years}))]);
    body.innerHTML=`<section><div class="v4-sec-head"><h3>Reverse Node Edge Audit</h3><span>${esc(a.audit_id||'NO AUDIT')}</span></div>
      <p class="note">Filter Score 只是直觀篩選指標；是否留下 Node 要同時看基準 R、右尾 ≥2R/3R、虧損尾、同點冗餘、bootstrap CI 與跨年一致性。</p>${auditTable(a.items||[])}</section>
      <section><div class="v4-sec-head"><h3>Trade Management Lab</h3><span>MR 0.75R / BO 1R 是 control；其餘測 trailing / runner</span></div>${mgmtTable(m.items||[])}</section>
      <section><div class="v4-sec-head"><h3>Ablation Test</h3><span>完整 Gate Chain vs 每次拿掉一個 Node</span></div>${ablationTable(ab)}</section>`;
  }catch(e){body.innerHTML='<div class="v4-audit-empty">V4 API 尚未啟動或沒有資料：'+esc(e.message||e)+'</div>'}
}
function ensure(){if(route()!=='research')return;if(!$('#v4EdgeAudit'))load()}
const mo=new MutationObserver(()=>{if(route()==='research'&&!$('#v4EdgeAudit'))setTimeout(ensure,0)});mo.observe(document.documentElement,{subtree:true,childList:true});
window.addEventListener('hashchange',()=>setTimeout(ensure,40));setTimeout(ensure,1000);
FabioV4.research={load,refresh,runAudit,get state(){return state}};
})();
