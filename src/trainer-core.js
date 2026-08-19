(function(g){
  const KEY='fabio-replay-history-v1'
  function safeParse(raw,fallback=[]){try{return JSON.parse(raw)||fallback}catch{return fallback}}
  function loadHistory(){try{return safeParse(localStorage.getItem(KEY),[])}catch{return[]}}
  function saveHistory(items){try{localStorage.setItem(KEY,JSON.stringify(items.slice(-2000)))}catch{}return items}
  function appendDecision(history,record){const next=[...history,record];saveHistory(next);return next.slice(-2000)}
  function summarize(history){
    const n=history.length,correct=history.filter(x=>x.ok).length,avgMs=n?history.reduce((a,b)=>a+(b.ms||0),0)/n:0
    const byNode={};for(const x of history){const k=x.tag||'UNKNOWN';const o=byNode[k]||(byNode[k]={n:0,correct:0,ms:0});o.n++;o.correct+=x.ok?1:0;o.ms+=x.ms||0}
    const nodes=Object.entries(byNode).map(([node,o])=>({node,n:o.n,accuracy:o.n?o.correct/o.n:0,avgMs:o.n?o.ms/o.n:0})).sort((a,b)=>a.accuracy-b.accuracy||b.n-a.n)
    const byStrategy={};for(const s of ['MR','BO']){const arr=history.filter(x=>x.strategy===s);byStrategy[s]={n:arr.length,accuracy:arr.length?arr.filter(x=>x.ok).length/arr.length:0}}
    return{n,correct,accuracy:n?correct/n:0,avgMs,nodes,weakest:nodes[0]||null,byStrategy,wrong:history.filter(x=>!x.ok).slice(-20).reverse()}
  }
  function randomCase(cases,{strategy='ALL',excludeId=null}={}){const pool=cases.filter(c=>(strategy==='ALL'||c.strategy===strategy)&&c.id!==excludeId);if(!pool.length)return cases.find(c=>c.id!==excludeId)||cases[0]||null;return pool[Math.floor(Math.random()*pool.length)]}
  function confidenceCalibration(history){const buckets=[1,2,3,4,5].map(level=>{const a=history.filter(x=>x.confidence===level);return{level,n:a.length,accuracy:a.length?a.filter(x=>x.ok).length/a.length:0}});return buckets}
  function reset(){try{localStorage.removeItem(KEY)}catch{}return[]}
  g.TrainerCore={KEY,loadHistory,saveHistory,appendDecision,summarize,randomCase,confidenceCalibration,reset}
})(typeof window!=='undefined'?window:globalThis)
