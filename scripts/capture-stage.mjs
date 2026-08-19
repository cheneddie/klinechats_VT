import { chromium } from 'playwright'
import fs from 'node:fs'

const phase=(fs.readFileSync('PHASE.txt','utf8').trim()||'decision-gym-v2').replace(/[^a-zA-Z0-9_-]/g,'_')
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

await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded'})
await page.waitForSelector('.gym',{timeout:15000});await page.waitForTimeout(5600)
await page.screenshot({path:`screenshots/${phase}-dashboard.png`,fullPage:true})
const dashboard={
  skills:await page.locator('.skill').count(),
  nav:await page.locator('.side nav a').count(),
  title:await page.locator('#pageTitle').textContent(),
  apiState:await page.locator('.side-foot').textContent()
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
await page.waitForTimeout(1600)
let practice={
  chartCanvasCount:await page.locator('#gymChart canvas').count(),
  question:await page.locator('.question-panel h2').textContent().catch(()=>null),
  answerButtons:await page.locator('.answer-buttons button').count()
}
if(practice.answerButtons===2){
  await page.locator('#ansYes').click();await page.waitForTimeout(900)
  practice.feedback=await page.locator('#practiceFeedback').textContent()
}
await page.screenshot({path:`screenshots/${phase}-practice.png`,fullPage:true})

const report={phase,title:await page.title(),dashboard,nodes,pattern,practice,expectedOfflineRequests:expectedOffline.length,errors}
fs.writeFileSync(`screenshots/${phase}.json`,JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2))
await browser.close()
if(errors.length)process.exitCode=2
