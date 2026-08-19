(function(){
  const top=document.querySelector('.top-actions'),engine=document.querySelector('#engineBadge')
  if(top&&engine){const v=document.createElement('span');v.className='version-chip';v.textContent='Trainer v1.0.0';engine.after(v)}
  const feedback=document.querySelector('#feedback');if(feedback)feedback.setAttribute('aria-live','polite')
  const yes=document.querySelector('#yesBtn'),no=document.querySelector('#noBtn');yes?.setAttribute('aria-keyshortcuts','Y');no?.setAttribute('aria-keyshortcuts','N')
  document.querySelector('#playBtn')?.setAttribute('aria-label','播放或暫停 Replay');document.querySelector('#stepBtn')?.setAttribute('aria-label','下一根');document.querySelector('#backBtn')?.setAttribute('aria-label','上一根')

  const title=document.querySelector('.mistakes .case-title')
  if(title){
    const clear=document.querySelector('#clearHistoryBtn'),box=document.createElement('div');box.className='history-actions'
    const exp=document.createElement('button');exp.className='export';exp.id='exportHistoryBtn';exp.textContent='匯出 JSON'
    clear?.replaceWith(box);if(clear)box.append(clear);box.append(exp)
    exp.addEventListener('click',()=>{
      const data={exportedAt:new Date().toISOString(),version:'1.0.0',history:window.TrainerCore?.loadHistory?.()||[]}
      const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`fabio-training-${Date.now()}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)
    })
  }

  const card=document.createElement('section');card.className='integrity-card';card.id='integrityCard';card.innerHTML=`<div class="integrity-head"><b>DATA INTEGRITY</b><span id="integrityStatus">檢查中</span></div><div class="integrity-grid"><div><em>Source rows</em><strong id="qaRows">—</strong></div><div><em>Contract</em><strong id="qaContract">—</strong></div><div><em>Physical order</em><strong id="qaOrder">—</strong></div><div><em>Clock</em><strong id="qaClock">—</strong></div></div><div class="integrity-warning" id="qaWarning">載入資料 QA…</div>`
  document.querySelector('.shortcut-note')?.before(card)
  async function loadQA(){
    try{
      const q=await fetch('./reports/MTX_2027_DATA_QA.json').then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.json()})
      document.querySelector('#qaRows').textContent=Number(q.rows).toLocaleString('zh-TW')
      document.querySelector('#qaContract').textContent=`${q.products[0]} ${q.expiries[0]}`
      document.querySelector('#qaOrder').textContent=q.physicalTimestampNondecreasing?'保留 ✓':'異常'
      document.querySelector('#qaClock').textContent=q.timestampResolutionObserved
      document.querySelector('#qaWarning').textContent='side = Tick Direction proxy；不可當成 Bid/Ask Delta / CVD。'
      const s=document.querySelector('#integrityStatus');s.textContent='VERIFIED';window.__APP_QA__={dataVerified:true,rows:q.rows,order:q.physicalTimestampNondecreasing}
    }catch(err){document.querySelector('#integrityStatus').textContent='ERROR';document.querySelector('#qaWarning').textContent=`QA report 載入失敗：${err.message}`;window.__APP_QA__={dataVerified:false,error:err.message}}
  }
  loadQA()
  window.addEventListener('resize',()=>{try{state.chart?.resize?.()}catch{}})
  document.addEventListener('visibilitychange',()=>{if(document.hidden&&state.playing)stopPlay()})
})()
