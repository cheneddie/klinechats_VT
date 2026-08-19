window.FabioV3=window.FabioV3||{};
(()=>{
const routeNode=()=>{const p=location.hash.replace(/^#\/?/,'').split('/').filter(Boolean);return p[0]==='nodes'&&p[1]?decodeURIComponent(p[1]):null};
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
  if(!nodeId||!toolbar||toolbar.querySelector('.pl-v32-actions'))return false
  const actions=document.createElement('div')
  actions.className='pl-v32-actions'
  actions.innerHTML='<button class="yn" data-v32-yn>YES vs NO 視覺對照</button><button data-v32-random>隨機開一筆 Replay</button>'
  toolbar.appendChild(actions)
  actions.querySelector('[data-v32-yn]').onclick=()=>FabioV3.drill?.compareYesNo?.(nodeId)
  actions.querySelector('[data-v32-random]').onclick=()=>randomReplay(nodeId)
  document.dispatchEvent(new CustomEvent('fabio:v32-pattern-actions-mounted',{detail:{nodeId}}))
  return true
}
const observer=new MutationObserver(()=>requestAnimationFrame(mount))
observer.observe(document.documentElement,{subtree:true,childList:true})
window.addEventListener('hashchange',()=>setTimeout(mount,30))
setTimeout(mount,250)
setTimeout(mount,900)
FabioV3.patternActions={mount,randomReplay}
})();
