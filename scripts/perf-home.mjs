import { chromium } from 'playwright'

async function launch(){
  if(process.env.CI)return chromium.launch({headless:true,channel:'chrome'})
  try{return await chromium.launch({headless:true})}catch{return chromium.launch({headless:true,channel:'chrome'})}
}

const browser=await launch()
const page=await browser.newPage({viewport:{width:1600,height:1000}})
const cdp=await page.context().newCDPSession(page)
await cdp.send('Performance.enable')

await page.addInitScript(()=>{
  const NativeMO=window.MutationObserver
  const stats=window.__FABIO_PERF__={moCreated:0,moCallbacks:0,moRecords:0,longTasks:0,longTaskMs:0}
  window.MutationObserver=class extends NativeMO{
    constructor(cb){
      stats.moCreated++
      super((records,observer)=>{
        stats.moCallbacks++
        stats.moRecords+=records.length
        cb(records,observer)
      })
    }
  }
  try{
    new PerformanceObserver(list=>{
      for(const e of list.getEntries()){
        stats.longTasks++
        stats.longTaskMs+=e.duration
      }
    }).observe({entryTypes:['longtask']})
  }catch{}
})

await page.goto('http://127.0.0.1:4173/#/dashboard',{waitUntil:'domcontentloaded',timeout:15000})
await page.waitForSelector('.gym',{timeout:15000})
await page.waitForSelector('#v33Mastery',{timeout:15000})
await page.waitForTimeout(1200)

await page.evaluate(()=>{
  const s=window.__FABIO_PERF__
  s.moCallbacks=0;s.moRecords=0;s.longTasks=0;s.longTaskMs=0
})
const before=await cdp.send('Performance.getMetrics')
const map=m=>Object.fromEntries(m.metrics.map(x=>[x.name,x.value]))
const b=map(before)

const fps=await page.evaluate(()=>new Promise(resolve=>{
  let frames=0,start=performance.now()
  const tick=now=>{
    frames++
    if(now-start>=2000)return resolve(frames/((now-start)/1000))
    requestAnimationFrame(tick)
  }
  requestAnimationFrame(tick)
}))

const after=await cdp.send('Performance.getMetrics')
const a=map(after)
const stats=await page.evaluate(()=>({
  ...window.__FABIO_PERF__,
  badgeCount:document.querySelectorAll('.v33-version').length,
  logoText:document.querySelector('.logo small')?.textContent||'',
  domNodes:document.querySelectorAll('*').length,
  canvasCount:document.querySelectorAll('canvas').length,
}))
const delta=name=>Number(((a[name]||0)-(b[name]||0)).toFixed(4))
const report={
  fps:Number(fps.toFixed(1)),
  ...stats,
  taskDuration:delta('TaskDuration'),
  scriptDuration:delta('ScriptDuration'),
  layoutDuration:delta('LayoutDuration'),
  recalcStyleDuration:delta('RecalcStyleDuration'),
}
console.log(JSON.stringify(report,null,2))

const errors=[]
if(report.badgeCount!==1)errors.push(`V3.3 badge unstable: ${report.badgeCount}`)
if(report.moCallbacks>30)errors.push(`Idle MutationObserver callbacks too high: ${report.moCallbacks}`)
if(report.longTasks>2)errors.push(`Idle long tasks too high: ${report.longTasks} (${report.longTaskMs.toFixed(1)}ms)`)
if(report.fps<40)errors.push(`Idle FPS too low: ${report.fps}`)
if(report.taskDuration>0.6)errors.push(`Idle Chrome task time too high: ${report.taskDuration}s / 2s`)

await browser.close()
if(errors.length){console.error(errors.join('\n'));process.exit(2)}
