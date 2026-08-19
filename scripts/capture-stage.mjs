import { chromium } from 'playwright'
import fs from 'node:fs'

const phase=(fs.readFileSync('PHASE.txt','utf8').trim()||'decision-gym-v3').replace(/[^a-zA-Z0-9_-]/g,'_')
const browser=await chromium.launch({headless:true})
const page=await browser.newPage({viewport:{width:1600,height:1000},deviceScaleFactor:1})
const errors=[],expectedOffline=[]
page.on('console',msg=>{if(msg.type()!=='error')return;const text=msg.text();if(text.includes('ERR_CONNECTION_REFUSED'))expectedOffline.push(text);else errors.push(`console: ${text}`)})
page.on('pageerror',err=>errors.push(`pageerror: ${err.message}`))
fs.mkdirSync('screenshots',{recursive:true})

async function goto(route,suffix,wait=700){await page.goto(`http://127.0.0.1:4173/#/${route}`,{waitUntil:'domcontentloaded'});await page.waitForSelector('.gym',{timeout:15000});await page.waitForTimeout(wait);if(suffix)await page.screenshot({path:`screenshots/${phase}-${suffix}.png`,fullPage:true});return{title:await page.locator('#pageTitle').textContent().catch(()=>null),buttons:await page.locator('#content button').count(),selects:await page.locator('#content select').count(),inputs:await page.locator('#content input').count()}}

await goto('dashboard','dashboard',5200)
const dashboard={skills:await page.locator('.skill').count(),nav:await page.locator('.side nav a').count(),title:await page.locator('#pageTitle').textContent(),apiState:await page.locator('.side-foot').textContent(),pixiPill:await page.locator('.pixi-pill').textContent().catch(()=>null),pixiVersion:await page.evaluate(()=>window.PIXI?.VERSION||null)}

// Offline QA gets a second same-date case so YES/NO visual compare is testable without private MTX data.
await page.evaluate(()=>{const s=FabioV2.store.state,base=s.cases.find(c=>c.nodes?.MR_CLEAR_RECLAIM===true)||s.cases[0];if(base&&!s.cases.some(c=>c.id===base.id+'-QA-NO')){const x=structuredClone(base);x.id=base.id+'-QA-NO';x.event_id=x.id;x.nodes={...x.nodes,MR_CLEAR_RECLAIM:false};x.result='WAIT';x.difficulty=4;s.cases.push(x);FabioV2.store.recalc()}})

await goto('nodes','nodes',800)
const nodes={cards:await page.locator('.node-card').count(),title:await page.locator('#pageTitle').textContent(),hasMR:await page.getByText('Clear Reclaim',{exact:true}).count()}

await page.goto('http://127.0.0.1:4173/#/nodes/MR_CLEAR_RECLAIM',{waitUntil:'domcontentloaded'});await page.waitForSelector('#patternLab',{timeout:15000});await page.waitForTimeout(1000)
const pattern={tiles:await page.locator('.pl-tile').count(),filterButtons:await page.locator('[data-filter]').count(),wallSizeButtons:await page.locator('[data-limit]').count(),drillButtons:await page.locator('[data-drill]').count(),v32Actions:await page.locator('.pl-v32-actions button').count(),countText:await page.locator('#patternLabCount').textContent()}
await page.screenshot({path:`screenshots/${phase}-node-detail.png`,fullPage:true})
if(pattern.v32Actions){await page.locator('[data-v32-yn]').click();await page.waitForSelector('#v32Compare',{timeout:10000});await page.waitForTimeout(1500);pattern.visualCompareOpen=await page.locator('#v32Compare').count();pattern.comparePixiCanvases=await page.locator('#v32Compare .decision-pixi-canvas').count();pattern.compareAnswers=await page.locator('#v32Compare .v32-answer').allTextContents();pattern.compareReason=await page.locator('#v32ExplainA').textContent();await page.screenshot({path:`screenshots/${phase}-yes-no-compare.png`,fullPage:true});await page.locator('#v32Close').click()}else{pattern.visualCompareOpen=0;pattern.comparePixiCanvases=0}

await page.goto('http://127.0.0.1:4173/#/practice/MR_CLEAR_RECLAIM',{waitUntil:'domcontentloaded'});await page.waitForTimeout(1800)
let practice={chartCanvasCount:await page.locator('#gymChart canvas').count(),pixiCanvasCount:await page.locator('#gymChart .decision-pixi-canvas').count(),question:await page.locator('.question-panel h2').textContent().catch(()=>null),answerButtons:await page.locator('.answer-buttons button').count(),modeBefore:await page.evaluate(()=>window.FabioV3?.pixi?.current?.()?.mode||null),chipBefore:await page.locator('.practice-reveal-chip').textContent().catch(()=>null)}
if(practice.answerButtons===2){await page.locator('#ansYes').click();await page.waitForTimeout(1200);practice.feedback=await page.locator('#practiceFeedback').textContent();practice.pixiAfterAnswer=await page.locator('#gymChart .decision-pixi-canvas').count();practice.modeAfter=await page.evaluate(()=>window.FabioV3?.pixi?.current?.()?.mode||null);practice.chipAfter=await page.locator('.practice-reveal-chip').textContent().catch(()=>null)}
await page.screenshot({path:`screenshots/${phase}-practice-reveal.png`,fullPage:true})

// Open a case from Pattern Lab context so V3.2 keeps the node focus across Replay navigation.
await page.goto('http://127.0.0.1:4173/#/nodes/MR_CLEAR_RECLAIM',{waitUntil:'domcontentloaded'});await page.waitForSelector('.pl-open',{timeout:15000});await page.locator('.pl-open').first().click();await page.waitForSelector('.node-outcomes',{timeout:15000});await page.waitForTimeout(1600)
const replay={pixiCanvasCount:await page.locator('#replayChart .decision-pixi-canvas').count(),visualRows:await page.locator('.visual-node-row').count(),modeButtons:await page.locator('[data-vmode]').count(),drillbar:await page.locator('#nodeDrillbar').count(),drillButtons:await page.locator('#nodeDrillbar button').count(),focusedRows:await page.locator('.visual-node-row.focused').count(),detail:await page.locator('#nodeVisualDetail').textContent().catch(()=>null),counter:await page.locator('#nodeDrillbar .counter').textContent().catch(()=>null),selectedNode:await page.evaluate(()=>sessionStorage.getItem('fabioV3FocusNode'))}
await page.screenshot({path:`screenshots/${phase}-replay-drill.png`,fullPage:true})

const zones={tree:await goto('tree','tree'),exam:await goto('exam','exam'),settings:await goto('settings','settings'),data:await goto('data','data'),review:await goto('review','review'),cases:await goto('cases','cases'),research:await goto('research','research')}

if(dashboard.pixiVersion!=='8.19.0')errors.push(`PixiJS version mismatch: ${dashboard.pixiVersion}`)
if(pattern.tiles<2)errors.push(`Expected >=2 Pattern cases after QA injection, got ${pattern.tiles}`)
if(pattern.visualCompareOpen!==1)errors.push('V3.2 YES/NO compare did not open')
if(pattern.comparePixiCanvases!==2)errors.push(`Expected 2 Pixi compare canvases, got ${pattern.comparePixiCanvases}`)
if(!pattern.compareAnswers?.includes('YES')||!pattern.compareAnswers?.includes('NO'))errors.push(`Visual compare lacks YES/NO pair: ${pattern.compareAnswers}`)
if(practice.modeBefore!=='blind')errors.push(`Practice must be blind before answer, got ${practice.modeBefore}`)
if(practice.modeAfter!=='single')errors.push(`Practice must reveal single node after answer, got ${practice.modeAfter}`)
if(replay.drillbar!==1)errors.push('Same-node drill bar missing on Replay')
if(replay.focusedRows!==1)errors.push(`Expected focused node from Pattern context, got ${replay.focusedRows}`)
if(replay.selectedNode!=='MR_CLEAR_RECLAIM')errors.push(`Expected MR_CLEAR_RECLAIM persisted focus, got ${replay.selectedNode}`)
if(!replay.detail?.includes('深度'))errors.push('Reason Layer did not expose actual-vs-threshold reclaim depth')

const report={phase,title:await page.title(),dashboard,nodes,pattern,practice,replay,zones,expectedOfflineRequests:expectedOffline.length,errors}
fs.writeFileSync(`screenshots/${phase}.json`,JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));await browser.close();if(errors.length)process.exitCode=2
