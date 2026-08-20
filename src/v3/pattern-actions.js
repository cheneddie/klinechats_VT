window.FabioV3=window.FabioV3||{};
(()=>{
const routeNode=()=>{const p=location.hash.replace(/^#\/?/,'').split('/').filter(Boolean);return p[0]==='nodes'&&p[1]?decodeURIComponent(p[1]):null};
let retryToken=0;
async function randomReplay(nodeId){
  const pool=await FabioV2.store.loadNodeCases(nodeId,{limit:2500})
  if(!pool.length)return
  FabioV3.drill?.setFocusNode?.(nodeId)
  FabioV3.drill?.setFilter?.('all')
  const c=pool[Math.floor(Math.random()*pool.length)]
  location.hash='#/replay/'+encodeURIComponent(c.id)
}
function mount(){
  const nodeId=routeNode()
  const toolbar=document.querySelector('#patternLab .pl-toolbar')
  if(!nodeId||!toolbar)return false
  const existing=toolbar.querySelector('.pl-v32-actions')
  if(existing){
    if(existing.dataset.nodeId!==nodeId){
      existing.remove()
    }else return true
  }
  const actions=document.createElement('div')
  actions.className='pl-v32-actions'
  actions.dataset.nodeId=nodeId
  actions.innerHTML='<button type="button" class="yn" data-v32-yn>YES vs NO 視覺對照</button><button type="button" data-v32-random>隨機開一筆 Replay</button>'
  toolbar.appendChild(actions)
  actions.querySelector('[data-v32-yn]').onclick=()=>FabioV3.drill?.compareYesNo?.(nodeId)
  actions.querySelector('[data-v32-random]').onclick=()=>randomReplay(nodeId)
  document.dispatchEvent(new CustomEvent('fabio:v32-pattern-actions-mounted',{detail:{nodeId}}))
  return true
}
function ensureMounted(maxAttempts=50){
  const token=++retryToken
  let attempt=0
  const tick=()=>{
    if(token!==retryToken)return
    if(!routeNode())return
    if(mount())return
    attempt++
    if(attempt<maxAttempts)setTimeout(tick,100)
  }
  tick()
}
const observer=new MutationObserver(()=>{
  if(routeNode()&&!document.querySelector('#patternLab .pl-v32-actions'))requestAnimationFrame(mount)
})
observer.observe(document.documentElement,{subtree:true,childList:true})
window.addEventListener('hashchange',()=>ensureMounted())
setTimeout(()=>ensureMounted(),250)
FabioV3.patternActions={mount,ensureMounted,randomReplay}
})();
