window.FabioV2=window.FabioV2||{};
(()=>{
const loaded=new Set(),loading=new Set();
function route(){const x=location.hash.replace(/^#\/?/,'').split('/').filter(Boolean);return{page:x[0]||'dashboard',id:x[1]||null}}
async function hydrateRoute(){const r=route();if(!FabioV2.store?.state?.apiOnline)return;if(!['nodes','practice'].includes(r.page)||!r.id||loaded.has(r.id)||loading.has(r.id))return;loading.add(r.id);try{await FabioV2.store.loadNodeCases(r.id,{limit:5000});loaded.add(r.id);FabioV2.app?.render?.()}finally{loading.delete(r.id)}}
window.addEventListener('hashchange',()=>setTimeout(hydrateRoute,20));
document.addEventListener('change',async e=>{if(e.target?.id!=='caseNode'||!e.target.value||!FabioV2.store?.state?.apiOnline)return;const id=e.target.value;if(e.target.dataset.hydrated===id)return;e.target.dataset.hydrated=id;try{await FabioV2.store.loadNodeCases(id,{limit:5000});e.target.dispatchEvent(new Event('change',{bubbles:false}))}catch(err){console.warn(err)}});
setTimeout(hydrateRoute,700);
})();
