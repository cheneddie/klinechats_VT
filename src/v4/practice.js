window.FabioV4=window.FabioV4||{};
(()=>{
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const route=()=>{const p=location.hash.replace(/^#\/?/,'').split('/').filter(Boolean);return{page:p[0]||'dashboard',id:p[1]?decodeURIComponent(p[1]):null}};
const state={nodeId:null,queue:[],i:0,confidence:3,answered:false,loading:false,timeframe:'1m',token:0};
function shuffle(a){return a.map(x=>[Math.random(),x]).sort((a,b)=>a[0]-b[0]).map(x=>x[1])}
async function balancedQueue(nodeId,count){
  const half=Math.ceil(count/2);
  const [yes,no]=await Promise.all([
    FabioV2.store.loadNodeCases(nodeId,{limit:Math.max(half*4,100),answer:true}),
    FabioV2.store.loadNodeCases(nodeId,{limit:Math.max(half*4,100),answer:false}),
  ]);
  const y=shuffle([...yes]),n=shuffle([...no]),out=[];
  while(out.length<count&&(y.length||n.length)){
    if(y.length&&out.length<count)out.push(y.pop());
    if(n.length&&out.length<count)out.push(n.pop());
  }
  if(out.length<count){
    const all=await FabioV2.store.loadNodeCases(nodeId,{limit:Math.max(count*5,200)});
    const seen=new Set(out.map(x=>x.id));
    for(const c of shuffle(all)){if(!seen.has(c.id)&&out.length<count){out.push(c);seen.add(c.id)}}
  }
  return shuffle(out).slice(0,count);
}
function loading(nodeId){
  const n=FabioV2.nodeMap?.[nodeId];
  const content=$('#content'); if(!content)return;
  content.innerHTML=`<div class="v4-practice-root v4-loading"><h2>${esc(n?.code||nodeId)} · 載入專項案例</h2><p>從 SQLite /api/cases 直接抓此 Node，不再只依賴瀏覽器前 2,000 筆。</p><div class="v4-spinner"></div></div>`;
}
async function start(nodeId){
  const token=++state.token;
  state.nodeId=nodeId||'MR_CLEAR_RECLAIM'; state.loading=true; state.i=0; state.answered=false;
  loading(state.nodeId);
  const count=Math.max(1,Number(FabioV2.store.state.settings.questionCount||20));
  try{state.queue=await balancedQueue(state.nodeId,count)}catch(e){state.queue=[]}
  if(token!==state.token)return;
  state.loading=false; renderQuestion();
}
function decisionCutoff(c,nodeId){
  const m=c?.nodeMeta?.[nodeId];
  return m?.decision_time||m?.anchor_time||c?.entryTime||c?.entry_time||c?.attemptStartTime||c?.attempt_start_time;
}
function explain(c,nodeId){
  try{
    const layer=FabioV4.chart.current()?.layer;
    const v=layer?.getVisual?.(nodeId)||FabioV3.nodeVisuals?.resolve?.(c,FabioV4.chart.current()?.bars||[],nodeId);
    if(!v)return'';
    return `<div class="v4-explain"><b>${esc(v.code)} · ${esc(v.label)}</b><ul>${(v.reason||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`;
  }catch{return''}
}
async function renderChart(c){
  const host=$('#v4PracticeChart'); if(!host)return;
  const current=await FabioV4.chart.render(host,c,{
    nodeId:state.nodeId,timeframe:state.timeframe,before:1,after:0,session:'full',
    hideFuture:!state.answered,visualMode:state.answered?'single':'blind'
  });
  if(state.answered&&current?.layer)current.layer.focus(state.nodeId,{scroll:true});
}
function answer(v){
  if(state.answered)return;
  const c=state.queue[state.i],truth=Boolean(c?.nodes?.[state.nodeId]);
  state.answered=true;
  const ms=Math.max(0,performance.now()-(state.started||performance.now()));
  FabioV2.store.record({caseId:c.id,nodeId:state.nodeId,answer:v,correct:v===truth,ms,confidence:state.confidence,mode:'practice-v4'});
  const fb=$('#v4PracticeFeedback');
  if(fb){fb.className='v4-feedback '+(v===truth?'correct':'wrong');fb.innerHTML=`<b>${v===truth?'✓ 正確':'✕ 錯誤'} · Machine ${truth?'YES':'NO'}</b><span>${truth?(FabioV2.nodeMap[state.nodeId]?.yes||''):(FabioV2.nodeMap[state.nodeId]?.no||'')}</span>`}
  renderChart(c).then(()=>{const e=$('#v4Explain');if(e)e.innerHTML=explain(c,state.nodeId)});
}
function next(){
  if(state.i+1>=state.queue.length){finish();return}
  state.i++;state.answered=false;renderQuestion();
}
function finish(){
  const content=$('#content');if(!content)return;
  const rows=FabioV2.store.state.history.filter(x=>x.mode==='practice-v4'&&x.nodeId===state.nodeId).slice(-state.queue.length);
  const correct=rows.filter(x=>x.correct).length;
  content.innerHTML=`<div class="v4-practice-root v4-finish"><span>NODE DRILL COMPLETE</span><h2>${esc(FabioV2.nodeMap[state.nodeId]?.code)} · ${esc(FabioV2.nodeMap[state.nodeId]?.short)}</h2><strong>${rows.length?Math.round(correct/rows.length*100):0}%</strong><p>${correct} / ${rows.length} 正確</p><button id="v4Again" class="primary">再練一組</button></div>`;
  $('#v4Again').onclick=()=>start(state.nodeId);
}
function renderQuestion(){
  const content=$('#content');if(!content)return;
  const n=FabioV2.nodeMap?.[state.nodeId],c=state.queue[state.i];
  if(!c){
    content.innerHTML=`<div class="v4-practice-root v4-empty"><h2>沒有可練案例</h2><p>${esc(n?.code||state.nodeId)} 在目前 Event Store 沒有案例；請先完成 Scanner。</p></div>`;
    return;
  }
  state.started=performance.now();
  content.innerHTML=`<div class="v4-practice-root">
    <div class="v4-practice-top">
      <select id="v4PracticeNode">${FabioV2.nodes.map(x=>`<option value="${x.id}" ${x.id===state.nodeId?'selected':''}>${x.code} · ${esc(x.short)}</option>`).join('')}</select>
      <span>第 ${state.i+1} / ${state.queue.length} 題</span>
      <span>${esc(c.date)} · ${esc(c.strategy)} · ${c.direction==='long'?'多':'空'}</span>
      <label>週期 <select id="v4PracticeTf">${FabioV4.chart.timeframes.map(x=>`<option ${x===state.timeframe?'selected':''}>${x}</option>`).join('')}</select></label>
      <span class="v4-hide">HIDE FUTURE · 前1交易日背景</span>
    </div>
    <div class="v4-practice-layout">
      <section><div id="v4PracticeChart" class="chart"></div></section>
      <aside class="v4-question">
        <span>${esc(n?.code)} · ${esc(n?.stage)}</span>
        <h2>${esc(n?.question)}</h2>
        <p>${FabioV2.store.state.settings.hints?esc(n?.definition):'只依盤面判斷。'}</p>
        <div class="confidence">${[1,2,3,4,5].map(x=>`<button data-conf="${x}" class="${x===state.confidence?'active':''}">${x}</button>`).join('')}</div>
        <div class="v4-answer"><button id="v4Yes" class="yes">YES</button><button id="v4No" class="no">NO</button></div>
        <div id="v4PracticeFeedback"></div><div id="v4Explain"></div>
        <button id="v4Next" class="primary wide" disabled>下一題 →</button>
      </aside>
    </div>
  </div>`;
  $('#v4PracticeNode').onchange=e=>start(e.target.value);
  $('#v4PracticeTf').onchange=e=>{state.timeframe=e.target.value;renderChart(c)};
  document.querySelectorAll('[data-conf]').forEach(b=>b.onclick=()=>{state.confidence=+b.dataset.conf;document.querySelectorAll('[data-conf]').forEach(x=>x.classList.toggle('active',x===b))});
  $('#v4Yes').onclick=()=>{answer(true);$('#v4Next').disabled=false};
  $('#v4No').onclick=()=>{answer(false);$('#v4Next').disabled=false};
  $('#v4Next').onclick=next;
  renderChart(c);
}
function ensure(){
  const r=route(); if(r.page!=='practice')return;
  const node=r.id||'MR_CLEAR_RECLAIM';
  if($('.v4-practice-root')&&state.nodeId===node)return;
  start(node);
}
document.addEventListener('keydown',e=>{
  if(route().page!=='practice'||!$('.v4-practice-root')||e.target?.matches?.('input,select,textarea'))return;
  if(e.key.toLowerCase()==='y'){e.preventDefault();e.stopImmediatePropagation();if(!state.answered){answer(true);const b=$('#v4Next');if(b)b.disabled=false}}
  if(e.key.toLowerCase()==='n'){e.preventDefault();e.stopImmediatePropagation();if(!state.answered){answer(false);const b=$('#v4Next');if(b)b.disabled=false}}
  if((e.key==='Enter'||e.key==='ArrowRight')&&state.answered){e.preventDefault();e.stopImmediatePropagation();next()}
},true);
const mo=new MutationObserver(()=>{if(route().page==='practice'&&!$('.v4-practice-root'))setTimeout(ensure,0)});
mo.observe(document.documentElement,{subtree:true,childList:true});
window.addEventListener('hashchange',()=>setTimeout(ensure,30));
setTimeout(ensure,800);
FabioV4.practice={start,get state(){return state},balancedQueue};
})();
