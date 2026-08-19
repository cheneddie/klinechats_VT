(function(){
  const core=window.TrainerCore
  if(!core)return
  Object.assign(state,{mode:'practice',confidence:3,history:core.loadHistory(),caseFinished:false})

  const baseAnswer=answer,baseRenderDecisionLog=renderDecisionLog,baseRevealOutcome=revealOutcome,baseLoadCase=loadCase,baseDrawStructure=drawStructure

  function currentQ(){return qlist()[state.q]}
  function setMode(mode){
    state.mode=mode
    document.querySelectorAll('.mode-btn').forEach(b=>b.classList.toggle('active',b.dataset.mode===mode))
    const panel=document.querySelector('.coach-panel');panel.classList.remove('exam','review');if(mode!=='practice')panel.classList.add(mode)
    nextCase()
  }
  function setConfidence(v){state.confidence=v;document.querySelectorAll('#confidenceButtons button').forEach(b=>b.classList.toggle('active',+b.dataset.confidence===v))}
  function reviewCandidate(){const wrong=core.summarize(state.history).wrong;for(const r of wrong){const c=state.data.cases.find(x=>x.id===r.caseId);if(c&&c.id!==state.case?.id)return c}return null}
  function nextCase(){const cases=state.data?.cases||[];let c=state.mode==='review'?reviewCandidate():null;if(!c)c=core.randomCase(cases,{excludeId:state.case?.id});if(c){document.querySelector('#caseSelect').value=c.id;loadCase(c.id)}}
  function renderStats(){
    const s=core.summarize(state.history)
    document.querySelector('#statTotal').textContent=s.n
    document.querySelector('#statAccuracy').textContent=s.n?`${Math.round(s.accuracy*100)}%`:'—'
    document.querySelector('#statSpeed').textContent=s.n?`${(s.avgMs/1000).toFixed(1)}s`:'—'
    document.querySelector('#statWeak').textContent=s.weakest?`${s.weakest.node} ${Math.round(s.weakest.accuracy*100)}%`:'—'
    const list=document.querySelector('#mistakeList')
    if(!s.wrong.length)list.textContent='目前沒有錯題'
    else list.innerHTML=s.wrong.slice(0,5).map(x=>`<div class="mistake-row"><span>${x.caseId} · ${x.tag}</span><b>信心${x.confidence||3} · ${((x.ms||0)/1000).toFixed(1)}s</b></div>`).join('')
  }

  answer=function(v){
    if(state.caseFinished)return
    const q=currentQ();if(!q)return
    const ms=Math.max(0,Math.round(performance.now()-state.qStartedAt)),ok=v===q[3]
    const rec={caseId:state.case.id,strategy:state.case.strategy,q:state.q+1,tag:q[0],choice:v?'YES':'NO',ok,ms,confidence:state.confidence,mode:state.mode,ts:Date.now()}
    state.history=core.appendDecision(state.history,rec)
    baseAnswer(v)
    renderStats()
    if(state.mode==='exam')setTimeout(()=>{const f=document.querySelector('#feedback');f.className='feedback muted';f.textContent='已記錄。考試模式不立即揭曉正確答案。';renderDecisionLog()},20)
  }

  renderDecisionLog=function(){
    if(state.mode!=='exam'||state.caseFinished)return baseRenderDecisionLog()
    const e=document.querySelector('#decisionLog');document.querySelector('#decisionCount').textContent=state.answers.length
    if(!state.answers.length){e.textContent='尚未作答';return}
    e.innerHTML=state.answers.map((a,i)=>`<div class="log-row"><span>Q${i+1} ${a.choice||'已作答'}</span><span>答案已封存</span></div>`).join('')
  }

  drawStructure=function(chart,bars,showTrade){
    if(state.mode!=='exam'||state.caseFinished)return baseDrawStructure(chart,bars,showTrade)
    const r=state.revealed,s=state.showTrade;state.revealed=0;state.showTrade=false;try{return baseDrawStructure(chart,bars,false)}finally{state.revealed=r;state.showTrade=s}
  }

  revealOutcome=function(){
    state.caseFinished=true;baseRevealOutcome();
    if(state.mode==='exam')setTimeout(()=>{const f=document.querySelector('#feedback');f.className='feedback good';f.textContent=`考試完成：${state.score}/${state.answered}，正確率 ${state.answered?Math.round(state.score/state.answered*100):0}%。現在才揭曉市場結構。`;baseRenderDecisionLog()},30)
  }

  loadCase=async function(id){state.caseFinished=false;await baseLoadCase(id);setConfidence(state.confidence);renderStats()}

  document.querySelectorAll('.mode-btn').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)))
  document.querySelectorAll('#confidenceButtons button').forEach(b=>b.addEventListener('click',()=>setConfidence(+b.dataset.confidence)))
  document.querySelector('#nextCaseBtn').addEventListener('click',nextCase)
  document.querySelector('#clearHistoryBtn').addEventListener('click',()=>{state.history=core.reset();renderStats()})
  document.addEventListener('keydown',e=>{
    if(['INPUT','SELECT','TEXTAREA'].includes(e.target.tagName)||e.repeat)return
    const k=e.key.toLowerCase();if(k==='y')answer(true);else if(k==='n')answer(false);else if(k==='r')nextCase();else if(e.key===' '){e.preventDefault();togglePlay()}else if(e.key==='ArrowRight')step(1);else if(e.key==='ArrowLeft')step(-1)
  })
  renderStats();setConfidence(3)
})()
