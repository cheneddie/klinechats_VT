import { chromium } from 'playwright'
import fs from 'node:fs'

const phase=(fs.readFileSync('PHASE.txt','utf8').trim()||'phase').replace(/[^a-zA-Z0-9_-]/g,'_')
const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[]
page.on('console',msg=>{if(msg.type()==='error')errors.push(`console: ${msg.text()}`)})
page.on('pageerror',err=>errors.push(`pageerror: ${err.message}`))
await page.goto('http://127.0.0.1:4173',{waitUntil:'networkidle'})
await page.waitForTimeout(1800)
await page.screenshot({path:`screenshots/${phase}.png`,fullPage:true})
const report={phase,title:await page.title(),engine:await page.locator('#engineBadge').textContent(),chartCanvasCount:await page.locator('#chart canvas').count(),question:await page.locator('#questionText').textContent(),errors}
fs.mkdirSync('screenshots',{recursive:true})
fs.writeFileSync(`screenshots/${phase}.json`,JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2))
await browser.close()
if(errors.length)process.exitCode=2
