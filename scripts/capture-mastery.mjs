import { chromium } from 'playwright'
import fs from 'node:fs'

async function launchBrowser(){
  if(process.env.CI)return chromium.launch({headless:true,channel:'chrome'})
  try{return await chromium.launch({headless:true})}catch{return chromium.launch({headless:true,channel:'chrome'})}
}
const browser=await launchBrowser()
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[]
page.on('console',msg=>{if(msg.type()==='error'&&!msg.text().includes('ERR_CONNECTION_REFUSED'))errors.push(`console: ${msg.text()}`)})
page.on('pageerror',err=>errors.push(`pageerror: ${err.message}`))
fs.mkdirSync('screenshots',{recursive:true})

await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded'})
await page.waitForSelector('.gym',{timeout:15000})
await page.waitForFunction(()=>window.FabioV3?.mastery&&window.FabioMasteryCore,{timeout:15000})

// Seed browser-only training evidence so the adaptive planner can be verified deterministically.
await page.evaluate(()=>{
  const st=FabioV2.store.state
  const nodeId='MR_CLEAR_RECLAIM'
  const base=st.cases.find(c=>typeof c.nodes?.[nodeId]==='boolean')||st.cases[0]
  if(!base)return
  const now=Date.now()
  for(let i=0;i<8;i++)st.history.push({id:`v33-${i}`,at:new Date(now-i*60000).toISOString(),caseId:base.id,nodeId,answer:Boolean(base.nodes?.[nodeId]),correct:i<3,ms:1200+i*100,confidence:i>=3?5:3,mode:'practice'})
  st.spaced.push({caseId:base.id,nodeId,level:2,dueAt:new Date(now-60000).toISOString(),done:false})
  FabioV2.store.recalc()
  FabioV2.app.render()
})
await page.waitForSelector('#v33Mastery',{timeout:10000})
await page.waitForTimeout(500)
const dashboard={
  panel:await page.locator('#v33Mastery').count(),
  sessions:await page.locator('#v33Mastery .v33-session').count(),
  skills:await page.locator('#v33Mastery .v33-skill').count(),
  primary:await page.locator('#v33Mastery [data-v33-practice]').count(),
  reviewCta:await page.locator('#v33Mastery [data-v33-review]').count(),
  score:await page.locator('#v33Mastery .v33-score b').textContent().catch(()=>null),
  version:await page.locator('.v33-version').textContent().catch(()=>null),
  plan:await page.evaluate(()=>{const p=FabioV3.mastery.plan();return{overall:p.overall,todayAttempts:p.todayAttempts,dueCount:p.dueCount,first:p.sessions[0]?.nodeId,wrongQueue:p.wrongQueue.length}})
}
await page.screenshot({path:'screenshots/decision-gym-v3-3-mastery-dashboard.png',fullPage:true})

await page.evaluate(()=>{location.hash='#/review'})
await page.waitForSelector('#v33WeakReview',{timeout:10000})
await page.waitForTimeout(400)
const review={
  panel:await page.locator('#v33WeakReview').count(),
  rows:await page.locator('#v33WeakReview .v33-review-row').count(),
  practiceButtons:await page.locator('#v33WeakReview [data-v33-practice]').count(),
  replayButtons:await page.locator('#v33WeakReview [data-v33-replay]').count(),
}
await page.screenshot({path:'screenshots/decision-gym-v3-3-weak-review.png',fullPage:true})

if(dashboard.panel!==1)errors.push('V3.3 mastery dashboard missing')
if(dashboard.sessions<1)errors.push('V3.3 adaptive session plan is empty')
if(dashboard.skills<1)errors.push('V3.3 mastery map is empty')
if(dashboard.primary<1)errors.push('V3.3 primary training CTA missing')
if(dashboard.reviewCta!==1)errors.push('V3.3 review CTA missing')
if(!dashboard.version?.includes('V3.3'))errors.push(`V3.3 version badge missing: ${dashboard.version}`)
if(dashboard.plan.first!=='MR_CLEAR_RECLAIM')errors.push(`Expected seeded weak node first, got ${dashboard.plan.first}`)
if(dashboard.plan.dueCount<1)errors.push('V3.3 due review signal not included')
if(dashboard.plan.wrongQueue<1)errors.push('V3.3 wrong-answer queue not included')
if(review.panel!==1)errors.push('V3.3 weakness review panel missing')
if(review.practiceButtons<1)errors.push('V3.3 weakness practice actions missing')
if(review.replayButtons<1)errors.push('V3.3 wrong-case Replay actions missing')

const report={dashboard,review,errors}
fs.writeFileSync('screenshots/decision-gym-v3-3-mastery.json',JSON.stringify(report,null,2))
console.log(JSON.stringify(report,null,2))
await browser.close()
if(errors.length)process.exitCode=2
