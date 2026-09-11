(()=>{
  const pairs=new Map(Object.entries({
    'Optimization Lab · Robust Plateau':'最佳化實驗室 · 穩健平台區',
    'Frozen Discovery / Validation Run':'凍結 Discovery / Validation Run',
    'Max trials':'最大試驗次數',
    'Only parameters that do not change the causal event universe may be optimized directly. Detector/rescan parameters are hard-locked here.':'只有不改變 causal event universe 的參數可直接最佳化。Detector/rescan parameters 在此硬鎖。',
    'Objective gates':'目標門檻',
    'Min trades':'最少交易筆數',
    'Min EV R':'最低 EV R',
    'Min PF':'最低 PF',
    'Open Jobs →':'開啟工作列表 →',
    'independent events may overlap':'獨立事件可能重疊',
    'single-position arbitration ON':'單一持倉仲裁已啟用',
    'Backtest IDs (comma-separated, up to 20)':'Backtest IDs（逗號分隔，最多20組）',
    'Comparability Gate':'可比性閘門',
    'Warnings:':'警告：',
    'Freeze Candidate from Plateau':'從平台區凍結候選策略',
    'Select optimization':'選擇最佳化結果',
    'Discovery Research Run':'Discovery 研究 Run',
    'Submit 4-scenario evaluation job':'提交四情境評估工作',
    'Live parity':'即時一致性',
    'Not passed':'未通過',
    'Passed':'已通過',
    'Paper trading':'模擬交易',
    'Create append-only gate decision':'建立僅追加閘門決策',
    'Load optimization first':'請先載入最佳化結果',
    'No robust plateau':'沒有穩健平台區',
    'Freezing candidate and synchronizing registry…':'正在凍結候選策略並同步註冊表…',
    'Long Jobs · heartbeat / hard timeout / cancellation':'長任務 · 心跳 / 強制逾時 / 取消',
    'Long-running tasks are isolated in child processes; timeout actually terminates the process.':'長任務以 child process 隔離；timeout 會實際 terminate process。',
    'No jobs':'沒有工作',
    'heartbeat':'心跳',
    'Slice':'切片',
    'Signal':'訊號',
    'Entry':'進場',
    'Stop':'停損',
    'Target':'目標',
    'Exit':'出場',
    'sticky suspension latch':'黏性暫停鎖',
    '0%=same mix · 100%=disjoint':'0%=相同組合 · 100%=完全不同',
    'Rolling health can degrade or suspend a strategy. Once suspended, a later healthy window cannot auto-resume it; explicit human review is required.':'滾動健康度可將策略降級或暫停。一旦暫停，後續健康視窗不得自動恢復，必須經過明確人工審查。',
    'Deployment is not “the strategy name”. It is one exact candidate + parameter hash + execution hash + portfolio hash approved by one immutable Production Gate.':'部署不是只有「策略名稱」，而是由不可變 Production Gate 核准的一組精確候選策略 + 參數 hash + 執行 hash + 投資組合 hash。',
    'PAPER observations are stored for analysis. Only LIVE observations may persist authoritative Production Deployment Health. Backtest monitoring is preview-only.':'PAPER 觀測會保留供分析；只有 LIVE 觀測可寫入權威 Production Deployment Health。回測監控僅供預覽。',
    'After a human RESUME, the old latched SUSPEND snapshot still blocks production. A fresh matching LIVE NORMAL health snapshot is required before eligibility returns.':'人工 RESUME 後，舊的黏性 SUSPEND 快照仍會阻擋生產；必須取得新的、身份匹配的 LIVE NORMAL 健康度快照後才可恢復資格。'
  }));
  const reverse=new Map([...pairs.entries()].map(([en,zh])=>[zh,en]));
  let applying=false;

  function lang(){return localStorage.getItem('strategyLabLanguage')==='en'?'en':'zh-TW'}
  function convert(text){
    const m=String(text).match(/^(\s*)([\s\S]*?)(\s*)$/),lead=m?.[1]||'',core=m?.[2]||'',trail=m?.[3]||'';
    const map=lang()==='en'?reverse:pairs;
    return map.has(core)?lead+map.get(core)+trail:text;
  }
  function skip(node){const p=node.parentElement;return !p||Boolean(p.closest('script,style,code,pre,[data-i18n-skip="1"]'))}
  function walk(root=document.documentElement){
    if(!root)return;
    const nodes=[];
    if(root.nodeType===Node.TEXT_NODE)nodes.push(root);
    else if([Node.ELEMENT_NODE,Node.DOCUMENT_NODE,Node.DOCUMENT_FRAGMENT_NODE].includes(root.nodeType)){
      const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;while((n=w.nextNode()))nodes.push(n);
    }
    for(const n of nodes){if(skip(n))continue;const next=convert(n.nodeValue||'');if(next!==n.nodeValue)n.nodeValue=next;}
  }
  function apply(){if(applying)return;applying=true;try{walk(document.documentElement)}finally{applying=false}}
  const observer=new MutationObserver(ms=>{if(applying)return;applying=true;try{for(const m of ms)for(const n of m.addedNodes)walk(n)}finally{applying=false}});
  observer.observe(document.documentElement,{subtree:true,childList:true});
  document.addEventListener('strategy-lab-language-change',apply);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',apply,{once:true});else apply();
  window.StrategyLabI18nExtra={apply};
})();
