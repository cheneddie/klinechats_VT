import { chromium } from 'playwright'
import fs from 'node:fs'

const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[]
const warnings=[]
const expectedOffline=[]
const browserEvents=[]
fs.mkdirSync('screenshots',{recursive:true})

page.on('console',msg=>{
  const text=msg.text()
  browserEvents.push(`console:${msg.type()}:${text}`)
  if(msg.type()!=='error')return
  if(text.includes('ERR_CONNECTION_REFUSED'))expectedOffline.push(text)
  else errors.push(`console: ${text}`)
})
page.on('pageerror',err=>{browserEvents.push(`pageerror:${err.message}`);errors.push(`pageerror: ${err.message}`)})

async function hashGo(route,selector,wait=350){
  await page.evaluate(r=>{location.hash='#/'+r},route)
  if(selector)await page.waitForSelector(selector,{timeout:15000})
  if(wait)await page.waitForTimeout(wait)
}
async function shot(name){
  try{await page.screenshot({path:`screenshots/${name}.png`,fullPage:false,animations:'disabled',caret:'hide',timeout:12000})}
  catch(e){warnings.push(`screenshot ${name}: ${e.message}`)}
}
async function inspectElement(selector){
  return page.evaluate(selector=>[...document.querySelectorAll(selector)].map((el,index)=>{const rect=el.getBoundingClientRect(),cs=getComputedStyle(el);return{index,connected:el.isConnected,text:el.textContent?.trim(),display:cs.display,visibility:cs.visibility,opacity:cs.opacity,pointerEvents:cs.pointerEvents,width:rect.width,height:rect.height,x:rect.x,y:rect.y,clientRects:el.getClientRects().length}}),selector)
}
async function pointerClick(selector){
  const diagnostics=await inspectElement(selector)
  const first=diagnostics[0]
  if(!first)throw new Error(`Element missing for ${selector}: ${JSON.stringify(diagnostics)}`)
  if(first.width<=0||first.height<=0||first.display==='none'||first.visibility==='hidden'||Number(first.opacity)===0)throw new Error(`Element not visibly boxed for ${selector}: ${JSON.stringify(diagnostics)}`)
  const loc=page.locator(selector).first();await loc.scrollIntoViewIfNeeded().catch(()=>{});const box=await loc.boundingBox()
  if(!box)throw new Error(`No bounding box for ${selector}: ${JSON.stringify(diagnostics)}`)
  const x=box.x+box.width/2,y=box.y+box.height/2
  const hit=await page.evaluate(({x,y,selector})=>{const el=document.elementFromPoint(x,y);return{tag:el?.tagName||null,id:el?.id||null,cls:el?.className||null,text:el?.textContent?.trim()||null,matches:Boolean(el?.matches?.(selector)||el?.closest?.(selector))}},{x,y,selector})
  if(!hit.matches)throw new Error(`Pointer hit-test failed for ${selector}: ${JSON.stringify({hit,diagnostics})}`)
  await page.mouse.click(x,y);return{box,hit,diagnostics}
}

await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded'})
await page.waitForSelector('.gym',{timeout:15000})
await page.waitForFunction(()=>window.FabioV2?.store?.state?.cases?.length>0&&window.FabioV3?.pixi,{timeout:15000})
const dashboard={pixiVersion:await page.evaluate(()=>window.PIXI?.VERSION||null),cases:await page.evaluate(()=>FabioV2.store.state.cases.length),nav:await page.locator('.side nav a').count()}

await page.evaluate(()=>{const s=FabioV2.store.state,node='MR_CLEAR_RECLAIM',base=s.cases.find(c=>c.nodes?.[node]===true)||s.cases[0];if(!base||s.cases.some(c=>c.id===base.id+'-QA-NO'))return;const x=structuredClone(base);x.id=base.id+'-QA-NO';x.event_id=x.id;x.nodes={...x.nodes,[node]:false};x.result='WAIT';x.difficulty=4;s.cases.push(x);FabioV2.store.recalc()})

await hashGo('nodes/MR_CLEAR_RECLAIM','#patternLab',700)
await page.waitForFunction(()=>document.querySelectorAll('.pl-tile').length>=2,{timeout:10000})
const runtimeBefore=await page.evaluate(()=>({hash:location.hash,patternActions:!!window.FabioV3?.patternActions,drill:!!window.FabioV3?.drill,toolbar:document.querySelector('#patternLab .pl-toolbar')?.outerHTML||null,buttons:document.querySelectorAll('[data-v32-yn]').length,patternLab:!!document.querySelector('#patternLab')}))
let manualMount=null
if(!runtimeBefore.buttons){
  manualMount=await page.evaluate(()=>({available:!!window.FabioV3?.patternActions?.mount,result:window.FabioV3?.patternActions?.mount?.()??null}))
  await page.waitForTimeout(250)
}
const runtimeAfter=await page.evaluate(()=>({hash:location.hash,buttons:document.querySelectorAll('[data-v32-yn]').length,toolbar:document.querySelector('#patternLab .pl-toolbar')?.outerHTML||null}))
console.log('V32_MOUNT_DIAGNOSTIC='+JSON.stringify({runtimeBefore,manualMount,runtimeAfter,browserEvents}))
const pattern={tiles:await page.locator('.pl-tile').count(),actions:await page.locator('.pl-v32-actions button').count(),runtimeBefore,manualMount,runtimeAfter,actionDiagnostics:await inspectElement('[data-v32-yn]')}
if(runtimeBefore.buttons===0)errors.push(`V3.2 actions did not auto-mount: ${JSON.stringify({runtimeBefore,manualMount,runtimeAfter})}`)
if(runtimeAfter.buttons===0){fs.writeFileSync('screenshots/decision-gym-v3-2-browser-qa.json',JSON.stringify({dashboard,pattern,browserEvents,warnings,errors},null,2));console.log(JSON.stringify({dashboard,pattern,browserEvents,warnings,errors},null,2));await browser.close();process.exit(2)}
pattern.pointer=await pointerClick('[data-v32-yn]')
await page.waitForSelector('#v32Compare',{timeout:10000});await page.waitForFunction(()=>document.querySelectorAll('#v32Compare .decision-pixi-canvas').length===2,{timeout:10000});await page.waitForTimeout(350)
pattern.compareOpen=await page.locator('#v32Compare').count();pattern.pixi=await page.locator('#v32Compare .decision-pixi-canvas').count();pattern.answers=await page.locator('#v32Compare .v32-answer').allTextContents();pattern.reason=await page.locator('#v32ExplainA').textContent().catch(()=>null);await shot('decision-gym-v3-2-yes-no-compare');await page.locator('#v32Close').click({force:true})

await hashGo('practice/MR_CLEAR_RECLAIM','#gymChart',250);await page.waitForSelector('#gymChart .decision-pixi-canvas',{timeout:10000});await page.waitForFunction(()=>FabioV3?.pixi?.current?.()?.mode==='blind',{timeout:10000})
const practice={modeBefore:await page.evaluate(()=>FabioV3.pixi.current()?.mode||null),chipBefore:await page.locator('.practice-reveal-chip').textContent().catch(()=>null),answerButtons:await page.locator('.answer-buttons button').count()}
await pointerClick('#ansYes');await page.waitForSelector('#practiceFeedback.correct, #practiceFeedback.wrong',{timeout:10000});await page.waitForFunction(()=>FabioV3?.pixi?.current?.()?.mode==='single',{timeout:10000});await page.waitForTimeout(300);practice.modeAfter=await page.evaluate(()=>FabioV3.pixi.current()?.mode||null);practice.chipAfter=await page.locator('.practice-reveal-chip').textContent().catch(()=>null);practice.feedback=await page.locator('#practiceFeedback').textContent().catch(()=>null);await shot('decision-gym-v3-2-practice-reveal')

await hashGo('nodes/MR_CLEAR_RECLAIM','#patternLab',350);await page.evaluate(()=>FabioV3?.patternActions?.mount?.());await pointerClick('.pl-open');await page.waitForSelector('#replayChart .decision-pixi-canvas',{timeout:12000});await page.waitForSelector('#nodeDrillbar',{timeout:10000});await page.waitForFunction(()=>document.querySelectorAll('.visual-node-row.focused').length===1,{timeout:10000})
const replay={pixi:await page.locator('#replayChart .decision-pixi-canvas').count(),drillbar:await page.locator('#nodeDrillbar').count(),drillButtons:await page.locator('#nodeDrillbar button').count(),focused:await page.locator('.visual-node-row.focused').count(),node:await page.evaluate(()=>sessionStorage.getItem('fabioV3FocusNode')),detail:await page.locator('#nodeVisualDetail').textContent().catch(()=>null)};await shot('decision-gym-v3-2-replay-drill')

if(dashboard.pixiVersion!=='8.19.0')errors.push(`PixiJS version mismatch: ${dashboard.pixiVersion}`)
if(pattern.tiles<2)errors.push(`Pattern Wall needs YES and NO cases, got ${pattern.tiles}`)
if(pattern.actions<2)errors.push(`Pattern V3.2 actions missing: ${pattern.actions}`)
if(pattern.compareOpen!==1||pattern.pixi!==2)errors.push(`YES/NO compare mount failed: open=${pattern.compareOpen}, pixi=${pattern.pixi}`)
if(!pattern.answers.includes('YES')||!pattern.answers.includes('NO'))errors.push(`YES/NO compare pair invalid: ${pattern.answers.join(',')}`)
if(practice.modeBefore!=='blind')errors.push(`Practice pre-answer mode=${practice.modeBefore}`)
if(practice.modeAfter!=='single')errors.push(`Practice post-answer mode=${practice.modeAfter}`)
if(practice.chipBefore!=='裸圖判斷中')errors.push(`Practice pre-answer chip=${practice.chipBefore}`)
if(practice.chipAfter!=='已揭露 Decision Visual')errors.push(`Practice post-answer chip=${practice.chipAfter}`)
if(replay.drillbar!==1||replay.focused!==1)errors.push(`Replay focus contract failed: drillbar=${replay.drillbar}, focused=${replay.focused}`)
if(replay.node!=='MR_CLEAR_RECLAIM')errors.push(`Replay node context lost: ${replay.node}`)
if(!replay.detail?.includes('深度'))errors.push('Reason Layer missing actual-vs-threshold reclaim depth')

const report={dashboard,pattern,practice,replay,expectedOfflineRequests:expectedOffline.length,browserEvents,warnings,errors};fs.writeFileSync('screenshots/decision-gym-v3-2-browser-qa.json',JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();if(errors.length)process.exitCode=2
