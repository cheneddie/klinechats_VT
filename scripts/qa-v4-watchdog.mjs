import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const OUT = path.resolve(process.env.QA_OUT || 'qa-artifacts');
const BASE = process.env.QA_BASE_URL || 'http://127.0.0.1:4173';
const API = process.env.QA_API_URL || 'http://127.0.0.1:8765/api';
const MANIFEST = JSON.parse(fs.readFileSync(process.env.QA_MANIFEST || path.join(OUT,'seed.json'),'utf8'));
fs.mkdirSync(OUT,{recursive:true});

const state={startedAt:new Date().toISOString(),stage:'boot',ok:false,history:[],errors:[],console:[],screenshots:[],api:{},checks:{}};
function persist(extra={}){Object.assign(state,extra);fs.writeFileSync(path.join(OUT,'qa-status.json'),JSON.stringify(state,null,2));}
function mark(stage,detail={}){state.stage=stage;state.history.push({at:new Date().toISOString(),stage,...detail});persist();console.log(`[QA] ${stage}`,detail);}
function withTimeout(promise,ms,label){let t;return Promise.race([promise,new Promise((_,rej)=>{t=setTimeout(()=>rej(new Error(`timeout ${ms}ms: ${label}`)),ms)})]).finally(()=>clearTimeout(t));}
async function api(pathname,opts={}){const r=await withTimeout(fetch(API+pathname,opts),12000,`API ${pathname}`);if(!r.ok)throw new Error(`${r.status} ${r.statusText} ${pathname}`);return r.json();}
async function shot(page,name,fullPage=true){const file=path.join(OUT,`${String(state.screenshots.length+1).padStart(2,'0')}-${name}.png`);await withTimeout(page.screenshot({path:file,fullPage}),12000,`screenshot ${name}`);state.screenshots.push(path.basename(file));persist();return file;}
async function waitSel(page,sel,ms=15000){return withTimeout(page.waitForSelector(sel,{state:'visible',timeout:ms}),ms+1000,`selector ${sel}`)}
async function step(page,name,fn){mark(name+':start');try{await withTimeout(fn(),30000,name);await shot(page,name.replace(/[^a-z0-9]+/gi,'-').toLowerCase());mark(name+':pass');return true}catch(e){state.errors.push({stage:name,message:String(e?.stack||e)});try{await shot(page,`FAIL-${name.replace(/[^a-z0-9]+/gi,'-').toLowerCase()}`)}catch{}persist();throw e}}

let browser,page;
try{
  mark('api-health:start');
  const h=await api('/v4/health');
  if(!h?.ok||!String(h.version||'').startsWith('4.'))throw new Error(`unexpected V4 health ${JSON.stringify(h)}`);
  state.api.health=h;
  const cases=await api('/cases?limit=20');
  state.api.caseCount=cases.items?.length||0;
  if(state.api.caseCount<3)throw new Error(`seed cases missing: ${state.api.caseCount}`);
  mark('api-health:pass',{version:h.version,cases:state.api.caseCount});

  browser=await chromium.launch({headless:true});
  const context=await browser.newContext({viewport:{width:1600,height:1000}});
  page=await context.newPage();
  page.on('console',msg=>{const row={type:msg.type(),text:msg.text()};state.console.push(row);if(state.console.length>200)state.console.shift();if(msg.type()==='error')state.errors.push({stage:'console',message:row.text});persist();});
  page.on('pageerror',err=>{state.errors.push({stage:'pageerror',message:String(err.stack||err)});persist();});
  page.setDefaultTimeout(15000);

  await step(page,'dashboard',async()=>{
    await page.goto(BASE,{waitUntil:'domcontentloaded'});
    await waitSel(page,'#content');
    await withTimeout(page.waitForFunction(()=>window.FabioV2?.store?.state?.apiOnline===true),15000,'store hydration');
    state.checks.dashboardApiOnline=await page.evaluate(()=>FabioV2.store.state.apiOnline);
    state.checks.dashboardCases=await page.evaluate(()=>FabioV2.store.state.cases.length);
  });

  await step(page,'practice-load',async()=>{
    await page.goto(`${BASE}/#/practice/MR_REJECTION`,{waitUntil:'domcontentloaded'});
    await waitSel(page,'.v4-practice-root');
    await withTimeout(page.waitForFunction(()=>window.FabioV4?.practice?.state?.queue?.length>=2),20000,'practice balanced queue');
    state.checks.practiceQueue=await page.evaluate(()=>FabioV4.practice.state.queue.map(c=>({id:c.id,truth:c.nodes.MR_REJECTION})));
    const truths=state.checks.practiceQueue.map(x=>x.truth);
    if(!truths.includes(true)||!truths.includes(false))throw new Error(`practice queue not YES/NO balanced: ${JSON.stringify(truths)}`);
    await waitSel(page,'#v4PracticeChart canvas');
    state.checks.practiceCanvases=await page.locator('#v4PracticeChart canvas').count();
    state.checks.practiceCutoff=await page.evaluate(()=>FabioV4.chart.current()?.payload?.cutoff_time||null);
    if(!state.checks.practiceCutoff)throw new Error('practice replay is not using server causal cutoff');
  });

  await step(page,'practice-5m-hide-future',async()=>{
    await page.selectOption('#v4PracticeTf','5m');
    await withTimeout(page.waitForFunction(()=>window.FabioV4?.chart?.current?.()?.opts?.timeframe==='5m'),15000,'practice 5m render');
    const cur=await page.evaluate(()=>({
      cutoff:FabioV4.chart.current()?.payload?.cutoff_time,
      tf:FabioV4.chart.current()?.payload?.timeframe,
      last:FabioV4.chart.current()?.bars?.at(-1),
      sourceRows:FabioV4.chart.current()?.payload?.source_rows,
    }));
    state.checks.practice5m=cur;
    if(cur.tf!=='5m'||!cur.cutoff)throw new Error(`5m causal replay invalid ${JSON.stringify(cur)}`);
    const truth=await page.evaluate(()=>Boolean(FabioV4.practice.state.queue[FabioV4.practice.state.i].nodes.MR_REJECTION));
    await page.click(truth?'#v4Yes':'#v4No');
    await waitSel(page,'.v4-feedback.correct');
    await withTimeout(page.waitForFunction(()=>window.FabioV4?.chart?.current?.()?.opts?.hideFuture===false),15000,'practice reveal');
  });

  await step(page,'replay-multiday-multiframe',async()=>{
    await page.goto(`${BASE}/#/replay/${encodeURIComponent(MANIFEST.mr_yes)}`,{waitUntil:'domcontentloaded'});
    await waitSel(page,'#v4ReplayControls');
    await waitSel(page,'#replayChart canvas');
    await page.selectOption('#v4ReplayTf','15m');
    await withTimeout(page.waitForFunction(()=>window.FabioV4?.replay?.state?.timeframe==='15m'&&window.FabioV4?.chart?.current?.()?.payload?.timeframe==='15m'),15000,'replay 15m');
    const cur=await page.evaluate(()=>({dates:FabioV4.chart.current()?.payload?.dates,tf:FabioV4.chart.current()?.payload?.timeframe,definition:FabioV4.chart.current()?.payload?.trading_day_definition,bars:FabioV4.chart.current()?.bars?.length}));
    state.checks.replay=cur;
    if(!Array.isArray(cur.dates)||cur.dates.length<3)throw new Error(`expected previous/current/next trading day: ${JSON.stringify(cur)}`);
    if(cur.tf!=='15m')throw new Error(`timeframe failed: ${JSON.stringify(cur)}`);
  });

  await step(page,'trade-management',async()=>{
    await page.click('#v4Mgmt');
    await withTimeout(page.waitForFunction(()=>document.querySelectorAll('.v4-mgmt-table tbody tr').length>0),15000,'management table');
    state.checks.managementRows=await page.locator('.v4-mgmt-table tbody tr').count();
    if(state.checks.managementRows<4)throw new Error(`management strategies missing: ${state.checks.managementRows}`);
  });

  await step(page,'research-audit-job',async()=>{
    await page.goto(`${BASE}/#/research`,{waitUntil:'domcontentloaded'});
    await waitSel(page,'#v4EdgeAudit');
    await page.fill('#v4AuditYears','2025');
    await page.click('#v4RunAudit');
    await withTimeout(page.waitForFunction(()=>window.FabioV4?.research?.state?.jobId),12000,'audit job id');
    const jobId=await page.evaluate(()=>FabioV4.research.state.jobId);
    mark('research-audit-job:running',{jobId});
    const deadline=Date.now()+60000;
    let j;
    while(Date.now()<deadline){
      j=await api('/v4/audit/jobs/'+encodeURIComponent(jobId));
      mark('research-audit-heartbeat',{jobId,status:j.status,phase:j.phase,done:j.done,total:j.total,message:j.message});
      if(j.status==='done')break;
      if(j.status==='failed')throw new Error(`audit failed: ${j.message}`);
      await new Promise(r=>setTimeout(r,1000));
    }
    if(j?.status!=='done')throw new Error(`audit timeout: ${JSON.stringify(j)}`);
    await withTimeout(page.waitForFunction(()=>document.querySelectorAll('.v4-audit-table tbody tr').length>0),15000,'audit results render');
    state.checks.auditJob=j;
    state.checks.auditRows=await page.locator('.v4-audit-table tbody tr').count();
  });

  await step(page,'api-contracts',async()=>{
    const meta=await api('/v4/node-meta/'+encodeURIComponent(MANIFEST.mr_yes));
    const m=meta.items?.MR_REJECTION;
    if(!m||m.decision_price==null||m.anchor_seq==null||!m.reason_code)throw new Error(`node visual metadata incomplete ${JSON.stringify(m)}`);
    state.checks.nodeMeta=m;
    const latest=await api('/v4/audit/latest');
    state.checks.latestAuditItems=latest.items?.length||0;
    if(!state.checks.latestAuditItems)throw new Error('latest reverse audit empty');
  });

  const hardErrors=state.errors.filter(e=>e.stage!=='console'||!/favicon|ERR_CONNECTION_REFUSED/i.test(e.message)===false);
  if(hardErrors.length)throw new Error(`browser/runtime errors: ${JSON.stringify(hardErrors.slice(0,10))}`);
  state.ok=true;state.finishedAt=new Date().toISOString();mark('FINAL:PASS',{screenshots:state.screenshots.length});
}catch(e){
  state.ok=false;state.finishedAt=new Date().toISOString();state.errors.push({stage:state.stage,message:String(e?.stack||e)});mark('FINAL:FAIL',{message:String(e?.message||e)});console.error(e);process.exitCode=1;
}finally{
  try{await browser?.close()}catch{}
  persist();
}
