(()=>{
  const STORAGE_KEY='strategyLabLanguage';
  const SUPPORTED=new Set(['zh-TW','en']);
  let language=SUPPORTED.has(localStorage.getItem(STORAGE_KEY))?localStorage.getItem(STORAGE_KEY):'zh-TW';
  let applying=false;
  const originals=new WeakMap();
  const rendered=new WeakMap();
  const attrOriginals=new WeakMap();

  const exact=new Map(Object.entries({
    'Governed Strategy Research Workbench':'治理式策略研究工作台',
    'Research':'研究',
    'Strategy Library':'策略庫',
    'Backtest Studio':'回測工作室',
    'Trade Review':'交易檢視',
    'Report Center':'報告中心',
    'Optimization Lab':'最佳化實驗室',
    'Compare Lab':'比較實驗室',
    'Candidate / Gate':'候選策略 / 生產閘門',
    'Jobs / Heartbeat':'工作 / 心跳監控',
    'Strategy Health':'策略健康度',
    'Production Deployments':'生產部署',
    'Decision Gym V5':'決策訓練場 V5',
    'checking…':'檢查中…',
    'API Offline':'API 離線',
    'Loading…':'載入中…',
    'Error':'錯誤',
    'Strategy Registry':'策略註冊表',
    'Strategy':'策略',
    'Family':'策略族群',
    'Version':'版本',
    'Parameters':'參數',
    'Hash':'雜湊',
    'No strategies':'沒有策略',
    'Research Boundary':'研究邊界',
    'Detector / structural parameter':'偵測器 / 結構參數',
    'requires rescan':'需要重新掃描',
    'Execution / management parameter':'執行 / 管理參數',
    'snapshot reuse allowed':'允許重用快照',
    'Final Holdout':'最終保留集',
    'optimizer access denied':'禁止最佳化器存取',
    'Architecture':'架構',
    'A strategy is more than a JSON name; each version is fixed by an immutable definition hash. Parameters that change the causal event universe cannot be optimized directly on an existing snapshot.':'策略不是只有 JSON 名稱；每一版以 immutable definition hash 固定。任何會改變 causal event universe 的參數禁止直接在既有 snapshot 上最佳化。',
    'Frozen Research Run':'凍結研究 Run',
    'Bootstrap reps':'Bootstrap 次數',
    'Timeout sec':'逾時（秒）',
    'Execution Model':'執行模型',
    'Fill':'成交方式',
    'Entry slippage':'進場滑價',
    'Exit slippage':'出場滑價',
    'Commission / side':'單邊手續成本',
    'Latency ms':'延遲（ms）',
    'Submit governed backtest job':'提交治理式回測工作',
    'Backtest':'回測',
    'Load Trades':'載入交易',
    'Select a backtest':'請選擇回測',
    'Select backtest':'請選擇回測',
    'Loading trades…':'載入交易中…',
    'No trades':'沒有交易',
    'Choose a trade':'選擇一筆交易',
    'Execution':'執行',
    'Causal Node Timeline':'因果節點時間軸',
    'Backtest Report Center':'回測報告中心',
    'Open Report':'開啟報告',
    'Integrity':'完整性',
    'Breakdowns':'分解統計',
    'Trades':'交易筆數',
    'Win Rate':'勝率',
    'Capture':'捕捉率',
    'EV CI Low':'EV 信賴區間下限',
    'EV CI High':'EV 信賴區間上限',
    'Research Run':'研究 Run',
    'Trials':'試驗次數',
    'Objective N':'目標數量',
    'Optimization Parameters':'最佳化參數',
    'Submit optimization job':'提交最佳化工作',
    'Run optimization':'執行最佳化',
    'Robust Plateau':'穩健平台區',
    'Optimization':'最佳化',
    'Load Plateau':'載入平台區',
    'Compare':'比較',
    'Run Compare':'執行比較',
    'Comparable':'可比較',
    'Comparability':'可比性',
    'Blocked':'已阻擋',
    'Reasons':'原因',
    'Candidate':'候選策略',
    'Candidate Evaluation':'候選策略評估',
    'Discovery Run':'Discovery 研究 Run',
    'Freeze Candidate':'凍結候選策略',
    'Evaluate Candidate':'評估候選策略',
    'Production Gate':'生產閘門',
    'Run Gate':'執行閘門',
    'Production Value Policy':'生產價值政策',
    'Production Value':'生產價值',
    'ATR trading value uses frozen event-time ATR and must never be recomputed at Gate time. NET points / ATR defaults to a 10% minimum. Month/year concentration limits must be explicitly supplied by research policy; blank values FAIL closed and the system never guesses thresholds.':'ATR 交易價值使用 frozen event-time ATR，禁止在 Gate 時重算。NET points / ATR 預設最低 10%。月份與年度集中度必須由研究政策明確填入；留白即 FAIL，不會自動猜門檻。',
    'Production Evidence Registry':'生產證據註冊表',
    'Production Gate does not accept a manual PASS. Live parity and Paper Trading must first create append-only evidence.':'Production Gate 不接受手動 PASS。Live parity 與 Paper Trading 必須先形成 append-only evidence。',
    'Historical ↔ Live Parity':'歷史 ↔ 即時一致性',
    'Historical trace JSON':'歷史 trace JSON',
    'Live trace JSON':'即時 trace JSON',
    'Verify + Freeze Parity Evidence':'驗證並凍結一致性證據',
    'Paper Trading':'模擬交易',
    'Source':'來源',
    'Artifact SHA-256':'成品 SHA-256',
    'Expectancy R':'期望值 R',
    'Profit Factor':'獲利因子',
    'Max DD R':'最大回撤 R',
    'Validate + Freeze Paper Evidence':'驗證並凍結模擬交易證據',
    'Portfolio Execution Policy':'投資組合執行政策',
    'This is an execution-arbitration assumption and does not change the causal event universe. A formal Candidate freezes the policy hash; Discovery / Validation / Final Holdout must use the same policy.':'這是成交仲裁假設，不會改動 causal event universe。正式 Candidate 會凍結 policy hash，Discovery / Validation / Final Holdout 必須一致。',
    'Position mode':'持倉模式',
    'INDEPENDENT_EVENT (legacy independent behavior)':'INDEPENDENT_EVENT（保留舊行為）',
    'SINGLE_POSITION (skip new signals while position is open)':'SINGLE_POSITION（持倉中跳過新訊號）',
    'Overlap policy':'重疊政策',
    'Max open positions':'最大同時持倉數',
    'Re-entry cooldown (sec)':'再次進場冷卻（秒）',
    'Fixed quantity':'固定數量',
    'Force flat clock':'強制平倉時間',
    'Execution-assumption fingerprint':'執行假設指紋',
    'Production realism':'生產真實度',
    'The data, execution assumptions, and Portfolio Policy match; only then may performance differences be interpreted.':'資料、執行假設與 Portfolio Policy 一致；績效差異才可進一步解讀。',
    'Comparison blocked: the values below must not be interpreted as strategy superiority until inconsistent data or execution assumptions are corrected.':'比較被阻擋：以下數值不可直接解讀為策略優劣，先修正不一致的資料或成交假設。',
    'Background Jobs':'背景工作',
    'Refresh':'重新整理',
    'Status':'狀態',
    'Progress':'進度',
    'Heartbeat':'心跳',
    'Result':'結果',
    'Cancel':'取消',
    'Strategy Health · Live Lifecycle Governance':'策略健康度 · 即時生命週期治理',
    'Loading Strategy Health…':'載入策略健康度中…',
    'Effective state':'有效狀態',
    'Lifecycle control':'生命週期控制',
    'Current EV':'目前 EV',
    'Current PF':'目前 PF',
    'Max DD':'最大 DD',
    'Signals/day':'每日訊號數',
    'Avg slippage':'平均滑價',
    'Regime TVD':'市場狀態 TVD',
    'Drift Diagnostics':'漂移診斷',
    'Expectancy ratio':'期望值比率',
    'PF ratio':'PF 比率',
    'Drawdown multiple':'回撤倍數',
    'Signal frequency ratio':'訊號頻率比率',
    'Slippage multiple':'滑價倍數',
    'Slippage Δ points':'滑價差異點數',
    'Regime mix TVD':'市場狀態組合 TVD',
    'Health Reasons':'健康度原因',
    'No snapshot':'沒有快照',
    'No active degradation reason':'目前沒有退化原因',
    'Human Governance · No Auto-Unpause':'人工治理 · 禁止自動解除暫停',
    'Review reason':'審查原因',
    'Acknowledge':'確認',
    'Manual Suspend':'人工暫停',
    'Resume after review':'審查後恢復',
    'Current vs Baseline Profile':'目前 vs 基準輪廓',
    'Health Timeline':'健康度時間軸',
    'Append-only Human Actions':'僅追加人工操作紀錄',
    'No monitoring snapshots yet.':'尚無監控快照。',
    'No human governance actions.':'尚無人工治理操作。',
    'As of':'截至',
    'Effective':'有效狀態',
    'Computed':'計算狀態',
    'Slippage':'滑價',
    'Strategy Health Error':'策略健康度錯誤',
    'Production Deployments · Exact Identity Governance':'生產部署 · 精確身份治理',
    'Loading Production Deployments…':'載入生產部署中…',
    'Deployment':'部署',
    'Production Eligible':'可進入生產',
    'Lifecycle':'生命週期',
    'Computed Health':'計算健康度',
    'Effective Health':'有效健康度',
    'Gate':'閘門',
    'Identity':'身份',
    'Execution Observation Evidence':'執行觀測證據',
    'LIVE observations':'LIVE 觀測數',
    'PAPER observations':'PAPER 觀測數',
    'Authoritative health':'權威健康度',
    'Evidence kind':'證據類型',
    'Health source':'健康度來源',
    'Observation digest':'觀測摘要雜湊',
    'Immutable observation batches':'不可變觀測批次',
    'Exact deployment identity required at ingestion':'匯入時必須符合精確部署身份',
    'Immutable Deployment Identity':'不可變部署身份',
    'Deployment identity hash':'部署身份雜湊',
    'Strategy hash':'策略雜湊',
    'Parameters hash':'參數雜湊',
    'Execution hash':'執行雜湊',
    'Execution model':'執行模型',
    'Portfolio policy hash':'投資組合政策雜湊',
    'Code commit':'程式 commit',
    'Production Eligibility Rule':'生產資格規則',
    'Production Gate PASS':'生產閘門 PASS',
    'Identity hash valid':'身份雜湊有效',
    'Lifecycle ACTIVE':'生命週期 ACTIVE',
    'Latest effective health not SUSPEND':'最新有效健康度不是 SUSPEND',
    'Human Deployment Governance':'人工部署治理',
    'Resume after LIVE NORMAL review':'LIVE NORMAL 審查後恢復',
    'Identity Verification':'身份驗證',
    'Authoritative Deployment Health Timeline':'權威部署健康度時間軸',
    'Recent PAPER / LIVE Execution Observations':'近期 PAPER / LIVE 執行觀測',
    'Append-only Deployment Actions':'僅追加部署操作紀錄',
    'No authoritative deployment health snapshots yet.':'尚無權威部署健康度快照。',
    'No deployment governance actions.':'尚無部署治理操作。',
    'No PAPER/LIVE execution observations yet.':'尚無 PAPER/LIVE 執行觀測。',
    'No PASS Production Gate has been deployed.':'尚未部署任何 PASS 的生產閘門。',
    'Trading date':'交易日期',
    'Direction':'方向',
    'Net R':'淨 R',
    'Payload hash':'Payload 雜湊',
    'Obs.':'觀測數',
    'Digest':'摘要雜湊',
    'Production Deployments Error':'生產部署錯誤',
    'Human review reason is required.':'必須填寫人工審查原因。',
    '— select —':'— 請選擇 —'
  }));
  const reverseExact=new Map([...exact.entries()].map(([en,zh])=>[zh,en]));

  const replacements=[
    [/^(\d+) strategies$/,(_,n)=>`${n} 個策略`],
    [/^(.+?) · (\d+) strategies$/,(_,prefix,n)=>`${prefix} · ${n} 個策略`],
    [/^Job (job-[A-Za-z0-9_-]+) submitted\. Open Jobs →$/,(_,id)=>`工作 ${id} 已提交。開啟工作列表 →`],
    [/^Job (job-[A-Za-z0-9_-]+) submitted\.$/,(_,id)=>`工作 ${id} 已提交。`],
    [/^computed (.+)$/,(m,x)=>`計算狀態 ${x}`],
    [/^baseline (.+)$/,(m,x)=>`基準 ${x}`],
    [/^Loading (.+)…$/,(m,x)=>`載入 ${x} 中…`]
  ];

  const placeholders=new Map(Object.entries({
    'research_run_id':'research_run_id',
    'Required for ACKNOWLEDGE / MANUAL_SUSPEND / RESUME':'ACKNOWLEDGE / MANUAL_SUSPEND / RESUME 必填',
    'required, 0 < share ≤ 1':'必填，0 < 比例 ≤ 1',
    'paper broker export / simulator':'模擬券商匯出 / 模擬器',
    '64 hex chars':'64 位十六進位字元'
  }));
  const reversePlaceholders=new Map([...placeholders.entries()].map(([en,zh])=>[zh,en]));

  function split(source){
    const m=String(source).match(/^(\s*)([\s\S]*?)(\s*)$/);
    return {lead:m?.[1]||'',core:m?.[2]||'',trail:m?.[3]||''};
  }
  function toZh(source){
    const {lead,core,trail}=split(source);
    if(exact.has(core))return lead+exact.get(core)+trail;
    for(const [rx,fn] of replacements){if(rx.test(core)){rx.lastIndex=0;return lead+core.replace(rx,fn)+trail;}}
    return source;
  }
  function toEn(source){
    const {lead,core,trail}=split(source);
    return reverseExact.has(core)?lead+reverseExact.get(core)+trail:source;
  }

  function shouldSkip(node){
    const parent=node.parentElement;
    return !parent||Boolean(parent.closest('script,style,code,pre,[data-i18n-skip="1"]'));
  }

  function translateTextNode(node){
    if(shouldSkip(node))return;
    const current=node.nodeValue||'';
    const last=rendered.get(node);
    if(!originals.has(node)||last!==undefined&&current!==last)originals.set(node,current);
    const source=originals.get(node)||'';
    const next=language==='zh-TW'?toZh(source):toEn(source);
    if(current!==next)node.nodeValue=next;
    rendered.set(node,next);
  }

  function translateAttributes(el){
    if(!(el instanceof Element))return;
    if(el.matches('code,pre,[data-i18n-skip="1"]')||el.closest('code,pre,[data-i18n-skip="1"]'))return;
    let store=attrOriginals.get(el);
    if(!store){store={};attrOriginals.set(el,store);}
    for(const attr of ['placeholder','aria-label']){
      if(!el.hasAttribute(attr))continue;
      const current=el.getAttribute(attr)||'';
      if(!(attr in store))store[attr]=current;
      const source=store[attr];
      const next=language==='zh-TW'?(placeholders.get(source)||toZh(source)):(reversePlaceholders.get(source)||toEn(source));
      if(current!==next)el.setAttribute(attr,next);
    }
  }

  function walk(root=document.documentElement){
    if(!root)return;
    if(root.nodeType===Node.TEXT_NODE){translateTextNode(root);return;}
    if(root.nodeType!==Node.ELEMENT_NODE&&root.nodeType!==Node.DOCUMENT_NODE&&root.nodeType!==Node.DOCUMENT_FRAGMENT_NODE)return;
    if(root instanceof Element)translateAttributes(root);
    const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);
    let n;
    while((n=walker.nextNode())){
      if(n.nodeType===Node.TEXT_NODE)translateTextNode(n);else translateAttributes(n);
    }
  }

  function installStyle(){
    if(document.getElementById('strategyLabLanguageStyle'))return;
    const style=document.createElement('style');
    style.id='strategyLabLanguageStyle';
    style.textContent='.sl-lang-control{display:flex;align-items:center;gap:6px;white-space:nowrap}.sl-lang-control small{opacity:.72;font-size:11px}.sl-lang-control select{min-width:94px;max-width:110px;padding:7px 8px;border-radius:8px;background:#0d1724;color:#eaf3ff;border:1px solid #2a3a50}';
    document.head.appendChild(style);
  }

  function installToggle(){
    const tools=document.querySelector('.sl-header-tools');
    if(!tools||document.getElementById('slLanguage'))return;
    const wrap=document.createElement('label');
    wrap.className='sl-lang-control';
    wrap.dataset.i18nSkip='1';
    wrap.innerHTML='<small data-lang-label>語言</small><select id="slLanguage" aria-label="Language"><option value="zh-TW">中文</option><option value="en">English</option></select>';
    const api=document.getElementById('slApi');
    if(api)tools.insertBefore(wrap,api);else tools.prepend(wrap);
    const select=wrap.querySelector('select');
    select.value=language;
    select.addEventListener('change',()=>setLanguage(select.value));
  }

  function setLanguage(next){
    if(!SUPPORTED.has(next))return;
    language=next;
    localStorage.setItem(STORAGE_KEY,language);
    document.documentElement.lang=language==='zh-TW'?'zh-Hant':'en';
    const select=document.getElementById('slLanguage');
    if(select&&select.value!==language)select.value=language;
    const label=document.querySelector('[data-lang-label]');
    if(label)label.textContent=language==='zh-TW'?'語言':'Language';
    applying=true;
    try{walk(document.documentElement);}finally{applying=false;}
    document.dispatchEvent(new CustomEvent('strategy-lab-language-change',{detail:{language}}));
  }

  function boot(){
    installStyle();
    installToggle();
    setLanguage(language);
  }

  const observer=new MutationObserver(mutations=>{
    if(applying)return;
    installToggle();
    applying=true;
    try{
      for(const mutation of mutations){
        for(const node of mutation.addedNodes)walk(node);
      }
    }finally{applying=false;}
  });
  observer.observe(document.documentElement,{subtree:true,childList:true});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
  window.StrategyLabI18n={getLanguage:()=>language,setLanguage,apply:()=>walk(document.documentElement)};
})();
