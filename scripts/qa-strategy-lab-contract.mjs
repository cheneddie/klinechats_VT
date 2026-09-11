import { chromium } from 'playwright'

const launchOptions=process.env.CI?{headless:true,channel:'chrome'}:{headless:true}
const browser=await chromium.launch(launchOptions)
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
page.setDefaultTimeout(7000)
const errors=[]
const postBodies=[]
page.on('console',msg=>{if(msg.type()==='error'&&!msg.text().includes('ERR_CONNECTION_REFUSED'))errors.push(`console:${msg.text()}`)})
page.on('pageerror',err=>errors.push(`pageerror:${err.message}`))

const strategy={
  strategy_key:'MR_BROAD@V3',strategy_id:'MR_BROAD',name:'MR Broad',description:'QA strategy',family:'MR',version:'V3',definition_hash:'a'.repeat(64),
  parameters:[
    {path:'target.r',kind:'float',default:.75,minimum:.25,maximum:5,requires_rescan:false},
    {path:'lvn.depth',kind:'float',default:.55,minimum:0,maximum:1,requires_rescan:true},
  ],
}
const response=(body,status=200)=>({status,contentType:'application/json',body:JSON.stringify(body)})
await page.route('**/api/v5/strategy-lab/**',async route=>{
  const u=new URL(route.request().url()),p=u.pathname,method=route.request().method()
  if(method==='POST'){
    try{postBodies.push({path:p,body:JSON.parse(route.request().postData()||'{}')})}catch{}
  }
  if(p.endsWith('/health'))return route.fulfill(response({engine:'STRATEGY_LAB_V1'}))
  if(p.endsWith('/strategies'))return route.fulfill(response({items:[strategy]}))
  if(p.includes('/backtests')&&!p.includes('/trades'))return route.fulfill(response({items:[]}))
  if(p.endsWith('/optimizations'))return route.fulfill(response({items:[]}))
  if(p.endsWith('/candidates')&&method==='GET')return route.fulfill(response({items:[{candidate_id:'cand-qa',strategy_key:strategy.strategy_key}]}))
  if(p.includes('/jobs')&&method==='GET')return route.fulfill(response({items:[]}))
  if(p.endsWith('/evidence/parity')&&method==='POST')return route.fulfill(response({parity_evidence_id:'parity-qa',status:'PASS'}))
  if(p.endsWith('/evidence/paper')&&method==='POST')return route.fulfill(response({paper_evidence_id:'paper-qa',status:'PASS'}))
  if(p.includes('/production-gates')&&method==='POST')return route.fulfill(response({status:'PASS',checklist:[{name:'LIVE_PARITY',passed:true},{name:'PAPER_TRADING',passed:true}]}))
  if(p.endsWith('/jobs')&&method==='POST')return route.fulfill(response({job_id:'job-qa',status:'QUEUED'}))
  return route.fulfill(response({items:[]}))
})

try{
  await page.goto('http://127.0.0.1:4173/strategy-lab.html#/library',{waitUntil:'domcontentloaded'})
  await page.waitForSelector('.sl-shell')
  await page.waitForFunction(()=>document.querySelector('#slHealth')?.textContent?.includes('STRATEGY_LAB_V1'))
  if(await page.locator('[data-page]').count()<8)throw new Error('Strategy Lab navigation incomplete')

  await page.evaluate(()=>location.hash='#/backtest')
  await page.waitForSelector('#btParams')
  const disabled=await page.locator('[data-param][disabled]').count()
  if(disabled<1)throw new Error('rescan parameter is not hard locked in Backtest Studio')
  await page.waitForSelector('[data-portfolio-scope="backtest"]')
  await page.selectOption('[data-portfolio-scope="backtest"] [data-pf="mode"]','SINGLE_POSITION')
  await page.waitForSelector('[data-portfolio-scope="backtest"] [data-pf="overlap_policy"]')
  await page.fill('[data-portfolio-scope="backtest"] [data-pf="reentry_cooldown_seconds"]','120')
  await page.fill('[data-portfolio-scope="backtest"] [data-pf="fixed_quantity"]','2')
  await page.fill('[data-portfolio-scope="backtest"] [data-pf="force_flat_time"]','13:40:00')
  await page.locator('[data-portfolio-scope="backtest"] [data-pf="force_flat_time"]').dispatchEvent('change')
  await page.fill('#btResearch','qa-research')
  await page.click('#btRun')
  await page.waitForFunction(()=>document.querySelector('#btResult')?.textContent?.includes('job-qa'))
  const backtestPost=postBodies.filter(x=>x.path.endsWith('/jobs')&&x.body?.job_type==='BACKTEST').at(-1)?.body
  if(!backtestPost)throw new Error('Backtest POST was not captured')
  const pf=backtestPost.payload?.portfolio_policy
  if(pf?.mode!=='SINGLE_POSITION')throw new Error(`portfolio mode missing from Backtest request: ${JSON.stringify(pf)}`)
  if(pf?.overlap_policy!=='SKIP_WHILE_OPEN'||pf?.max_open_positions!==1)throw new Error(`single-position arbitration contract invalid: ${JSON.stringify(pf)}`)
  if(pf?.reentry_cooldown_seconds!==120||pf?.fixed_quantity!==2||pf?.force_flat_time!=='13:40:00')throw new Error(`portfolio controls not propagated: ${JSON.stringify(pf)}`)

  await page.evaluate(()=>location.hash='#/optimize')
  await page.waitForSelector('#optParams')
  if(await page.locator('#optParams input[disabled]').count()<1)throw new Error('rescan parameter is not hard locked in Optimization Lab')
  await page.waitForSelector('[data-portfolio-scope="optimize"]')
  if(await page.locator('[data-portfolio-scope="optimize"] [data-pf="mode"]').inputValue()!=='SINGLE_POSITION')throw new Error('Optimization Lab did not reuse pinned portfolio policy')

  await page.evaluate(()=>location.hash='#/candidates')
  await page.waitForSelector('#productionEvidenceCard')
  await page.waitForSelector('[data-portfolio-scope="candidate"]')
  if(await page.locator('[data-portfolio-scope="candidate"] [data-pf="mode"]').inputValue()!=='SINGLE_POSITION')throw new Error('Candidate Lab did not reuse pinned portfolio policy')
  await page.waitForSelector('#gateParityEvidence')
  await page.waitForSelector('#gatePaperEvidence')
  if(await page.locator('#gateLive').count())throw new Error('unsafe naked live-parity pass control remains')
  if(await page.locator('#gatePaper').count())throw new Error('unsafe naked paper-trading pass control remains')

  await page.fill('#evHistorical',JSON.stringify([{state:'ENTRY',node_id:'MR_ENTRY',answer:true,decision_seq:1,decision_price:100,entry_seq:1,entry_price:100}]))
  await page.fill('#evLive',JSON.stringify([{state:'ENTRY',node_id:'MR_ENTRY',answer:true,decision_seq:1,decision_price:100,entry_seq:1,entry_price:100}]))
  await page.click('#evParitySave')
  await page.waitForFunction(()=>document.querySelector('#gateParityEvidence')?.value==='parity-qa')

  await page.fill('#evPaperSource','qa-paper-export')
  await page.fill('#evPaperSha','b'.repeat(64))
  await page.fill('#evPaperEV','0.2')
  await page.fill('#evPaperPF','1.4')
  await page.fill('#evPaperDD','3')
  await page.click('#evPaperSave')
  await page.waitForFunction(()=>document.querySelector('#gatePaperEvidence')?.value==='paper-qa')
  await page.click('#gateRun')
  await page.waitForFunction(()=>document.querySelector('#gateBody')?.textContent?.includes('LIVE_PARITY'))

  await page.evaluate(()=>location.hash='#/jobs')
  await page.waitForSelector('#jobsBody')

  if(errors.length)throw new Error(`Browser console errors: ${errors.join(' | ')}`)
  console.log('STRATEGY_LAB_PORTFOLIO_REQUEST',JSON.stringify(pf))
  console.log('STRATEGY_LAB_BROWSER_QA PASS')
}catch(err){
  console.error('STRATEGY_LAB_BROWSER_QA FAIL',err.message,errors)
  await browser.close()
  process.exit(2)
}
await browser.close()
