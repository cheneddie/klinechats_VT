import { chromium } from 'playwright'

async function launch(){
  if(process.env.CI)return chromium.launch({headless:true,channel:'chrome'})
  try{return await chromium.launch({headless:true})}catch{return chromium.launch({headless:true,channel:'chrome'})}
}
const browser=await launch()
const page=await browser.newPage({viewport:{width:1440,height:900}})

await page.route('http://127.0.0.1:8765/api/health',async route=>{
  await new Promise(r=>setTimeout(r,4000))
  await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:false})})
})

const start=Date.now()
await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded',timeout:10000})
await page.waitForSelector('.hero',{timeout:1500})
const dashboardMs=Date.now()-start
const state=await page.evaluate(()=>({
  title:document.querySelector('#pageTitle')?.textContent||'',
  cases:window.FabioV2?.store?.state?.cases?.length||0,
  mastery:Boolean(document.querySelector('#v33Mastery')),
}))
console.log(JSON.stringify({dashboardMs,...state},null,2))
await browser.close()
if(dashboardMs>1500||!state.title)process.exit(2)
