import { chromium } from 'playwright'
import fs from 'node:fs'

const phase=(fs.readFileSync('PHASE.txt','utf8').trim()||'phase').replace(/[^a-zA-Z0-9_-]/g,'_')
const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[]
page.on('console',msg=>{if(msg.type()==='error')errors.push(`console: ${msg.text()}`)})
page.on('pageerror',err=>errors.push(`pageerror: ${err.message}`))
await page.goto('http://127.0.0.1:4173',{waitUntil:'networkidle'})
await page.waitForTimeout(1400)

if(phase.startsWith('phase2')){
  for(let i=0;i<4;i++){await page.locator('#yesBtn').click();await page.waitForTimeout(850)}
  await page.waitForTimeout(600)
}
if(phase.startsWith('phase3')){
  await page.locator('[data-confidence="5"]').click()
  await page.locator('#yesBtn').click();await page.waitForTimeout(850)
  await page.locator('[data-mode="exam"]').click();await page.waitForTimeout(900)
  await page.locator('#yesBtn').click();await page.waitForTimeout(500)
}

await page.screenshot({path:`screenshots/${phase}.png`,fullPage:true})
const report={
  phase,
  title:await page.title(),
  engine:await page.locator('#engineBadge').textContent(),
  chartCanvasCount:await page.locator('#chart canvas').count(),
  question:await page.locator('#questionText').textContent(),
  session:await page.locator('#sessionLabel').textContent(),
  decisionCount:await page.locator('#decisionCount').textContent().catch(()=>null),
  strategy:await page.locator('#strategyBadge').textContent(),
  extreme:await page.locator('#extremeText').textContent(),
  lvn:await page.locator('#lvnText').textContent(),
  mode:await page.locator('.mode-btn.active').textContent().catch(()=>null),
  statTotal:await page.locator('#statTotal').textContent().catch(()=>null),
  statAccuracy:await page.locator('#statAccuracy').textContent().catch(()=>null),
  statSpeed:await page.locator('#statSpeed').textContent().catch(()=>null),
  feedback:await page.locator('#feedback').textContent().catch(()=>null),
  errors
}
fs.mkdirSync('screenshots',{recursive:true})
fs.writeFileSync(`screenshots/${phase}.json`,JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2))
await browser.close()
if(errors.length)process.exitCode=2
