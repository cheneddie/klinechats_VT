window.FabioV2=window.FabioV2||{};
(()=>{
function guard(){const sel=document.querySelector('#contractMode');if(!sel||sel.dataset.causalGuard)return;sel.dataset.causalGuard='1';const dominant=[...sel.options].find(o=>o.value==='dominant_volume'),strict=[...sel.options].find(o=>o.value==='strict');if(dominant)dominant.textContent='Dominant Volume — 診斷用 / 非因果';if(strict)strict.textContent='Strict — 日曆近月 / 因果（建議）';sel.value='strict';sel.addEventListener('change',()=>{const result=document.querySelector('#scanResult');if(!result)return;if(sel.value==='dominant_volume')result.innerHTML='<b>⚠ dominant_volume 會使用整日成交量排名，含 look-ahead，只能做診斷，不能當 live-causal 驗證。</b>';else result.textContent='Strict 模式依日曆近月與到期規則選合約，換月使用 blackout，適合 Replay / Research / Live-compatible Scanner。'});}
new MutationObserver(guard).observe(document.documentElement,{childList:true,subtree:true});window.addEventListener('hashchange',()=>setTimeout(guard,10));setTimeout(guard,300);
})();
