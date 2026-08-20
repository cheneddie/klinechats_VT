import { chromium } from 'playwright'

const launchOptions=process.env.CI?{headless:true,channel:'chrome'}:{headless:true}
const browser=await chromium.launch(launchOptions)
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
page.setDefaultTimeout(7000)
const errors=[]
page.on('console',msg=>{if(msg.type()==='error'&&!msg.text().includes('ERR_CONNECTION_REFUSED'))errors.push(`console:${msg.text()}`)})
page.on('pageerror',err=>errors.push(`pageerror:${err.message}`))
const checkpoint=(name,data={})=>console.log(`BROWSER_QA ${name} ${JSON.stringify(data)}`)

async function hashGo(route,selector){
  await page.evaluate(r=>{location.hash='#/'+r},route)
  if(selector)await page.waitForSelector(selector)
}
async function realClick(selector){
  const el=page.locator(selector).first()
  await el.waitFor({state:'visible'})
  await el.scrollIntoViewIfNeeded()
  const box=await el.boundingBox()
  if(!box)throw new Error(`No clickable box: ${selector}`)
  const x=box.x+box.width/2,y=box.y+box.height/2
  const hit=await page.evaluate(({x,y,selector})=>{const e=document.elementFromPoint(x,y);return Boolean(e?.matches?.(selector)||e?.closest?.(selector))},{x,y,selector})
  if(!hit)throw new Error(`Pointer hit-test failed: ${selector}`)
  await page.mouse.click(x,y)
}

try{
  checkpoint('BOOT_START')
  await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded'})
  await page.waitForSelector('.gym')
  await page.waitForFunction(()=>window.FabioV2?.store?.state?.cases?.length>0&&window.FabioV3?.pixi&&window.FabioV3?.drill)
  checkpoint('BOOT_OK',{pixi:await page.evaluate(()=>PIXI.VERSION),cases:await page.evaluate(()=>FabioV2.store.state.cases.length)})

  await page.evaluate(()=>{
    const s=FabioV2.store.state,node='MR_CLEAR_RECLAIM'
    const base=s.cases.find(c=>c.nodes?.[node]===true)||s.cases[0]
    if(!base||s.cases.some(c=>c.id===base.id+'-QA-NO'))return
    const x=structuredClone(base);x.id=base.id+'-QA-NO';x.event_id=x.id;x.nodes={...x.nodes,[node]:false};x.result='WAIT';x.difficulty=4;s.cases.push(x);FabioV2.store.recalc()
  })

  checkpoint('PATTERN_START')
  await hashGo('nodes/MR_CLEAR_RECLAIM','#patternLab')
  await page.waitForFunction(()=>document.querySelectorAll('.pl-tile').length>=2)
  await page.waitForSelector('[data-v32-yn]',{state:'visible'})
  const patternState=await page.evaluate(()=>({actions:document.querySelectorAll('.pl-v32-actions button').length,owner:document.querySelector('.pl-v32-actions')?.dataset.nodeId||null,yes:FabioV2.store.casesForNode('MR_CLEAR_RECLAIM').filter(c=>c.nodes?.MR_CLEAR_RECLAIM===true).length,no:FabioV2.store.casesForNode('MR_CLEAR_RECLAIM').filter(c=>c.nodes?.MR_CLEAR_RECLAIM===false).length}))
  if(patternState.actions<2)throw new Error(`Pattern actions missing: ${JSON.stringify(patternState)}`)
  await realClick('[data-v32-yn]')
  await page.waitForSelector('#v32Compare')
  await page.waitForFunction(()=>document.querySelectorAll('#v32Compare .decision-pixi-canvas').length===2)
  const answers=await page.locator('#v32Compare .v32-answer').allTextContents()
  if(!answers.includes('YES')||!answers.includes('NO'))throw new Error(`Compare pair invalid: ${answers}`)
  checkpoint('PATTERN_OK',{...patternState,answers})
  await page.locator('#v32Close').click({force:true})

  checkpoint('PRACTICE_START')
  await hashGo('practice/MR_CLEAR_RECLAIM','#gymChart')
  await page.waitForSelector('#gymChart .decision-pixi-canvas')
  await page.waitForFunction(()=>FabioV3.pixi.current()?.mode==='blind')
  const beforeChip=await page.locator('.practice-reveal-chip').textContent()
  await realClick('#ansYes')
  await page.waitForSelector('#practiceFeedback.correct, #practiceFeedback.wrong')
  await page.waitForFunction(()=>FabioV3.pixi.current()?.mode==='single')
  const afterChip=await page.locator('.practice-reveal-chip').textContent()
  if(beforeChip!=='裸圖判斷中'||afterChip!=='已揭露 Decision Visual')throw new Error(`Practice reveal chips invalid: ${beforeChip} -> ${afterChip}`)
  checkpoint('PRACTICE_OK',{before:'blind',after:'single',beforeChip,afterChip})

  checkpoint('REPLAY_START')
  await hashGo('nodes/MR_CLEAR_RECLAIM','#patternLab')
  await page.waitForSelector('.pl-open',{state:'visible'})
  await realClick('.pl-open')
  await page.waitForSelector('#replayChart .decision-pixi-canvas')
  await page.waitForSelector('#nodeDrillbar')
  await page.waitForFunction(()=>document.querySelectorAll('.visual-node-row.focused').length===1)
  const replay=await page.evaluate(()=>({node:sessionStorage.getItem('fabioV3FocusNode'),drillButtons:document.querySelectorAll('#nodeDrillbar button').length,focused:document.querySelectorAll('.visual-node-row.focused').length,detail:document.querySelector('#nodeVisualDetail')?.textContent||''}))
  if(replay.node!=='MR_CLEAR_RECLAIM')throw new Error(`Replay node context lost: ${replay.node}`)
  if(replay.focused!==1||replay.drillButtons<6)throw new Error(`Replay drill invalid: ${JSON.stringify(replay)}`)
  if(!replay.detail.includes('深度'))throw new Error('Reason Layer missing reclaim-depth evidence')
  checkpoint('REPLAY_OK',{node:replay.node,drillButtons:replay.drillButtons,focused:replay.focused})

  if(errors.length)throw new Error(`Browser console errors: ${errors.join(' | ')}`)
  checkpoint('PASS')
}catch(err){
  checkpoint('FAIL',{message:err.message,errors,hash:await page.evaluate(()=>location.hash).catch(()=>null),title:await page.locator('#pageTitle').textContent().catch(()=>null)})
  await browser.close()
  process.exit(2)
}
await browser.close()
