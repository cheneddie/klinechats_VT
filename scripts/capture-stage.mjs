import { chromium } from 'playwright'
import fs from 'node:fs'

const phase=(fs.readFileSync('PHASE.txt','utf8').trim()||'decision-gym-v3').replace(/[^a-zA-Z0-9_-]/g,'_')
const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[],expectedOffline=[]
page.on('console',msg=>{
  if(msg.type()!=='error')return
  const text=msg.text()
  if(text.includes('ERR_CONNECTION_REFUSED'))expectedOffline.push(text)
  else errors.push(`console: ${text}`)
})
page.on('pageerror',err=>errors.push(`pageerror: ${err.message}`))
fs.mkdirSync('screenshots',{recursive:true})

async function goto(route,suffix,wait=700){
  await page.goto(`http://127.0.0.1:4173/#/${route}`,{waitUntil:'domcontentloaded'})
  await page.waitForSelector('.gym',{timeout:15000})
  await page.waitForTimeout(wait)
  if(suffix)await page.screenshot({path:`screenshots/${phase}-${suffix}.png`,fullPage:true})
  return {
    title:await page.locator('#pageTitle').textContent().catch(()=>null),
    buttons:await page.locator('#content button').count(),
    selects:await page.locator('#content select').count(),
    inputs:await page.locator('#content input').count(),
  }
}

await goto('dashboard','dashboard',5600)
const dashboard={
  skills:await page.locator('.skill').count(),
  nav:await page.locator('.side nav a').count(),
  title:await page.locator('#pageTitle').textContent(),
  apiState:await page.locator('.side-foot').textContent(),
  pixiPill:await page.locator('.pixi-pill').textContent().catch(()=>null),
  pixiVersion:await page.evaluate(()=>window.PIXI?.VERSION||null)
}

await page.goto('http://127.0.0.1:4173/#/nodes',{waitUntil:'domcontentloaded'})
await page.waitForSelector('.node-card',{timeout:15000});await page.waitForTimeout(800)
await page.screenshot({path:`screenshots/${phase}-nodes.png`,fullPage:true})
const nodes={
  cards:await page.locator('.node-card').count(),
  title:await page.locator('#pageTitle').textContent(),
  hasMR:await page.getByText('Clear Reclaim',{exact:true}).count()
}

await page.goto('http://127.0.0.1:4173/#/nodes/MR_CLEAR_RECLAIM',{waitUntil:'domcontentloaded'})
await page.waitForSelector('#patternLab',{timeout:15000});await page.waitForTimeout(1000)
const pattern={
  tiles:await page.locator('.pl-tile').count(),
  filterButtons:await page.locator('[data-filter]').count(),
  wallSizeButtons:await page.locator('[data-limit]').count(),
  drillButtons:await page.locator('[data-drill]').count(),
  countText:await page.locator('#patternLabCount').textContent()
}
await page.screenshot({path:`screenshots/${phase}-node-detail.png`,fullPage:true})
const compareButtons=page.locator('[data-compare]')
if(await compareButtons.count()>=2){
  await compareButtons.nth(0).click();await compareButtons.nth(1).click();await page.waitForTimeout(300)
  pattern.compareOpen=await page.locator('#patternCompareModal.open').count()
  await page.screenshot({path:`screenshots/${phase}-compare.png`,fullPage:true})
  await page.locator('#plClose').click()
}else pattern.compareOpen=0

await page.goto('http://127.0.0.1:4173/#/practice/MR_CLEAR_RECLAIM',{waitUntil:'domcontentloaded'})
await page.waitForTimeout(1900)
let practice={
  chartCanvasCount:await page.locator('#gymChart canvas').count(),
  pixiCanvasCount:await page.locator('#gymChart .decision-pixi-canvas').count(),
  question:await page.locator('.question-panel h2').textContent().catch(()=>null),
  answerButtons:await page.locator('.answer-buttons button').count()
}
if(practice.answerButtons===2){
  await page.locator('#ansYes').click();await page.waitForTimeout(1200)
  practice.feedback=await page.locator('#practiceFeedback').textContent()
  practice.pixiAfterAnswer=await page.locator('#gymChart .decision-pixi-canvas').count()
}
await page.screenshot({path:`screenshots/${phase}-practice.png`,fullPage:true})

await page.goto('http://127.0.0.1:4173/#/replay',{waitUntil:'domcontentloaded'})
await page.waitForSelector('.node-outcomes',{timeout:15000});await page.waitForTimeout(1800)
const replay={
  pixiCanvasCount:await page.locator('#replayChart .decision-pixi-canvas').count(),
  visualRows:await page.locator('.visual-node-row').count(),
  modeButtons:await page.locator('[data-vmode]').count(),
  focusedRows:0,
  detail:null
}
if(replay.visualRows){
  await page.locator('.visual-node-row').nth(Math.min(1,replay.visualRows-1)).click();
  await page.waitForTimeout(700)
  replay.focusedRows=await page.locator('.visual-node-row.focused').count()
  replay.detail=await page.locator('#nodeVisualDetail').textContent().catch(()=>null)
}
await page.screenshot({path:`screenshots/${phase}-replay-visual.png`,fullPage:true})

const zones={
  tree:await goto('tree','tree'),
  exam:await goto('exam','exam'),
  settings:await goto('settings','settings'),
  data:await goto('data','data'),
  review:await goto('review','review'),
  cases:await goto('cases','cases'),
  research:await goto('research','research'),
}

if(dashboard.pixiVersion!=='8.19.0')errors.push(`PixiJS version mismatch: ${dashboard.pixiVersion}`)
if(replay.pixiCanvasCount<1)errors.push('Replay Pixi canvas missing')
if(replay.visualRows<1)errors.push('Replay visual node rows missing')
if(replay.focusedRows!==1)errors.push(`Expected one focused visual row, got ${replay.focusedRows}`)
if(!replay.detail||!replay.detail.includes('定位時間'))errors.push('Decision visual detail did not reveal locator metadata')

const report={
  phase,
  title:await page.title(),
  dashboard,nodes,pattern,practice,replay,zones,
  expectedOfflineRequests:expectedOffline.length,
  errors
}
fs.writeFileSync(`screenshots/${phase}.json`,JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2))
await browser.close()
if(errors.length)process.exitCode=2
