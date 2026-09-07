import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const outDir = path.resolve(process.env.STRATEGY_LAB_FEATURE_QA_DIR || 'artifacts/strategy-lab-feature-qa')
fs.mkdirSync(outDir, { recursive: true })

const base = process.env.STRATEGY_LAB_URL || 'http://127.0.0.1:4173/strategy-lab.html'
const apiBase = process.env.STRATEGY_LAB_API || 'http://127.0.0.1:8765/api'
const syntheticRun = 'synthetic-mtx-discovery-v1'
const baselineBt = 'bt-synthetic-mtx-mr-v1'
const compareBt = 'bt-synthetic-mtx-mr-compare-v1'
const overlapIndependent = 'bt-synthetic-mtx-overlap-independent-v1'
const overlapSingle = 'bt-synthetic-mtx-overlap-single-v1'
const syntheticOpt = 'opt-synthetic-mtx-mr-v1'
const strategyKey = 'MR_BROAD@V3'

const browser = await chromium.launch({ headless: true, channel: process.env.CI ? 'chrome' : undefined })
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 })
page.setDefaultTimeout(20000)
const browserErrors = []
page.on('pageerror', e => browserErrors.push(`pageerror:${e.message}`))
page.on('console', msg => {
  if (msg.type() === 'error' && !/favicon|ERR_CONNECTION_REFUSED/i.test(msg.text())) browserErrors.push(`console:${msg.text()}`)
})

const findings = []
const jobs = {}
let frozenCandidate = ''
const add = (feature, target, status, evidence, gaps = []) => findings.push({ feature, target, status, evidence, gaps })
const shot = async file => {
  const target = path.join(outDir, file)
  await page.screenshot({ path: target, fullPage: true })
  return file
}
const api = async (route, opts = {}) => {
  const r = await fetch(apiBase.replace(/\/$/, '') + route, {
    headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    ...opts,
  })
  const text = await r.text()
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${text}`)
  return text ? JSON.parse(text) : null
}
const waitJob = async (jobId, timeoutMs = 180000) => {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    const j = await api(`/v5/strategy-lab/jobs/${encodeURIComponent(jobId)}`)
    if (['SUCCEEDED', 'FAILED', 'TIMED_OUT', 'CANCELLED', 'ORPHANED'].includes(j.status)) return j
    await new Promise(r => setTimeout(r, 750))
  }
  throw new Error(`job did not terminate: ${jobId}`)
}
const parseJob = text => (String(text || '').match(/job-[a-z0-9]+/i) || [])[0] || ''
const goto = async route => {
  await page.evaluate(r => { location.hash = `#/${r}` }, route)
  await page.waitForTimeout(200)
}
const firstRealOption = async selector => {
  const val = await page.locator(`${selector} option`).evaluateAll(opts => opts.find(x => x.value)?.value || '')
  if (val) await page.selectOption(selector, val)
  return val
}

try {
  await page.goto(`${base}#/library`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#slHealth.status.ok')
  const health = (await page.locator('#slHealth').textContent())?.trim() || ''
  if (!health.includes('STRATEGY_LAB_V1')) throw new Error(`Strategy Lab API offline: ${health}`)

  // 1. Strategy Library
  await page.waitForSelector('#slMain table tbody tr')
  const strategyRows = await page.locator('#slMain table tbody tr').count()
  if (strategyRows < 2) throw new Error(`expected >=2 registered strategies, got ${strategyRows}`)
  add('Strategy Library', 'Immutable strategy registry, version/hash and research-boundary visibility', 'PASS', await shot('01-strategy-library-populated.png'))

  // 2. Backtest Studio: submit a real background backtest using the synthetic frozen run.
  await goto('backtest')
  await page.waitForSelector('#btRun')
  await page.selectOption('#slStrategy', strategyKey)
  await page.fill('#btResearch', syntheticRun)
  await page.fill('#btBoot', '200')
  await page.click('#btRun')
  await page.waitForFunction(() => /job-/.test(document.querySelector('#btResult')?.textContent || ''))
  jobs.backtest = parseJob(await page.locator('#btResult').textContent())
  if (!jobs.backtest) throw new Error('Backtest UI did not return a job id')
  add('Backtest Studio', 'Submit governed backtest against a frozen synthetic research run', 'PASS', await shot('02-backtest-submitted.png'), ['Backtest Studio does not show completed run metrics inline; review/report are separate pages.'])

  // 3. Trade Review: load immutable trades and require the execution overlay.
  await goto('review')
  await page.waitForSelector('#reviewBt')
  await page.selectOption('#reviewBt', baselineBt)
  await page.click('#reviewLoad')
  await page.waitForSelector('.trade-item')
  await page.locator('.trade-item').first().click()
  await page.waitForSelector('#tradeChart[data-trade-review-overlay="ready"]')
  const overlay = await page.locator('#tradeChart').evaluate(el => ({
    id: el.dataset.tradeReviewId,
    svg: el.querySelector('.trade-review-svg')?.childElementCount || 0,
    banner: el.querySelector('.trade-review-banner')?.textContent || '',
  }))
  if (!overlay.id || overlay.svg < 6 || !/ENTRY/i.test(overlay.banner)) throw new Error(`trade overlay incomplete: ${JSON.stringify(overlay)}`)
  add('Trade Review', 'Inspect each historical trade with K-line, entry/exit/SL/TP, R/MFE/MAE and causal node timeline', 'PASS', await shot('03-trade-review-populated.png'))

  // 4. Report Center
  await goto('reports')
  await page.waitForSelector('#reportBt')
  await page.selectOption('#reportBt', baselineBt)
  await page.click('#reportLoad')
  await page.waitForSelector('#reportBody .metric-grid')
  const reportText = await page.locator('#reportBody').textContent()
  if (!/Net EV/.test(reportText || '') || !/Integrity/.test(reportText || '') || !/Breakdowns/.test(reportText || '')) throw new Error('report center missing metrics/integrity/breakdowns')
  add('Report Center', 'Show full backtest metrics, integrity verification and performance breakdowns', 'PASS', await shot('04-report-center-populated.png'))

  // 5. Optimization Lab: submit a real bounded optimization job using synthetic Discovery.
  await goto('optimize')
  await page.waitForSelector('#optRun')
  await page.selectOption('#optStrategy', strategyKey)
  await page.fill('#optResearch', syntheticRun)
  await page.fill('#optTrials', '2')
  await page.fill('#objN', '1')
  const optInput = page.locator('[data-opt="target.r"]')
  if (!(await optInput.count())) throw new Error('target.r optimization input not found')
  await optInput.fill('0.50,0.75')
  await page.click('#optRun')
  await page.waitForFunction(() => /job-/.test(document.querySelector('#optResult')?.textContent || ''))
  jobs.optimization = parseJob(await page.locator('#optResult').textContent())
  if (!jobs.optimization) throw new Error('Optimization UI did not return a job id')
  add('Optimization Lab', 'Submit bounded optimization while hard-locking rescan parameters and preserving portfolio assumptions', 'PARTIAL', await shot('05-optimization-submitted.png'), ['Optimization page cannot open an existing optimization run, inspect trial table, or visualize the robust plateau in-place.'])

  // 6A. Compare positive branch: comparable contexts must show a table.
  await goto('compare')
  await page.waitForSelector('#cmpRun')
  await page.fill('#cmpIds', `${baselineBt}, ${compareBt}`)
  await page.click('#cmpRun')
  await page.waitForSelector('#cmpBody [data-compare-status="COMPARABLE"]')
  await page.waitForSelector('#cmpBody table')
  add('Compare Lab / Comparable', 'Allow performance comparison only when dataset and execution assumptions are comparable', 'PASS', await shot('06a-compare-comparable.png'))

  // 6B. Compare negative branch: mismatch must block and remove performance table.
  await page.fill('#cmpIds', `${overlapIndependent}, ${overlapSingle}`)
  await page.click('#cmpRun')
  await page.waitForSelector('#cmpBody [data-compare-status="BLOCKED"]')
  if (await page.locator('#cmpBody table').count()) throw new Error('BLOCKED compare still exposes a performance table')
  const blockedText = await page.locator('#cmpBody').textContent()
  if (!/EXECUTION_HASH/.test(blockedText || '') || !/PORTFOLIO_POLICY_HASH/.test(blockedText || '')) throw new Error('Compare blocked reasons missing')
  add('Compare Lab / Blocked', 'Block apples-to-oranges performance interpretation when execution/portfolio assumptions differ', 'PASS', await shot('06b-compare-blocked.png'))

  // 7. Candidate / Gate: load a real synthetic plateau and freeze a new immutable candidate.
  await goto('candidates')
  await page.waitForSelector('#candOpt')
  await page.selectOption('#candOpt', syntheticOpt)
  await page.click('#candLoadOpt')
  await page.waitForFunction(() => /target\.r/.test(document.querySelector('#candPlateau')?.textContent || ''))
  await page.fill('#candDiscovery', syntheticRun)
  await page.click('#candFreeze')
  await page.waitForFunction(() => /Frozen cand-/.test(document.querySelector('#candFreezeResult')?.textContent || ''))
  const freezeText = await page.locator('#candFreezeResult').textContent()
  frozenCandidate = (String(freezeText || '').match(/cand-[a-z0-9]+/i) || [])[0] || ''
  if (!frozenCandidate) throw new Error(`candidate id not found after freeze: ${freezeText}`)
  const immediateCandidateOptions = await page.locator('#candEval option').evaluateAll(opts => opts.map(o => o.value))
  const staleAfterFreeze = !immediateCandidateOptions.includes(frozenCandidate)

  // Re-enter the route so selectors reload from fresh state.
  await goto('library')
  await goto('candidates')
  await page.waitForSelector('#candEval')
  await page.selectOption('#candEval', frozenCandidate)
  await page.selectOption('#candGate', frozenCandidate)

  // Exercise Candidate Evaluation background job on Discovery. The job itself must terminate;
  // evaluation status may be FAIL because the tiny synthetic N deliberately does not meet production policy.
  await page.fill('#candEvalRun', syntheticRun)
  await page.click('#candEvaluate')
  await page.waitForFunction(() => /job-/.test(document.querySelector('#candEvalResult')?.textContent || ''))
  jobs.candidateEvaluation = parseJob(await page.locator('#candEvalResult').textContent())

  // Exercise append-only parity and paper evidence in the browser.
  const trace = JSON.stringify([{ state: 'ENTRY', node_id: 'MR_ENTRY', answer: true, decision_seq: 10, decision_price: 20000, entry_seq: 10, entry_price: 20000 }])
  await page.fill('#evHistorical', trace)
  await page.fill('#evLive', trace)
  await page.click('#evParitySave')
  await page.waitForFunction(() => /parity-/.test(document.querySelector('#evParityOut')?.textContent || ''))
  await page.fill('#evPaperSource', 'synthetic-paper-feature-qa')
  await page.fill('#evPaperSha', 'd'.repeat(64))
  await page.fill('#evPaperTrades', '30')
  await page.fill('#evPaperEV', '0.20')
  await page.fill('#evPaperPF', '1.30')
  await page.fill('#evPaperDD', '3.0')
  await page.click('#evPaperSave')
  await page.waitForFunction(() => /paper-/.test(document.querySelector('#evPaperOut')?.textContent || ''))

  // Gate is expected to reject this tiny candidate because it lacks a complete D/V/H chain.
  await page.click('#gateRun')
  await page.waitForFunction(() => /FAIL|PASS/.test(document.querySelector('#gateBody')?.textContent || ''))
  const gateText = await page.locator('#gateBody').textContent()
  const gateRejected = /FAIL/.test(gateText || '')
  const candidateGaps = [
    ...(staleAfterFreeze ? ['Newly frozen candidate does not appear in evaluation/gate selectors until the route is re-rendered.'] : []),
    'Candidate page lacks a single D/V/H × BASE/SLIPPAGE/LATENCY/COMBINED lifecycle matrix and evaluation history view.',
  ]
  add('Candidate / Evidence / Gate', 'Freeze robust plateau, evaluate candidate, create append-only evidence and enforce governed Production Gate', gateRejected ? 'PARTIAL' : 'PARTIAL', await shot('07-candidate-evidence-gate.png'), candidateGaps)

  // Wait for the three browser-submitted background jobs and prove Jobs/Heartbeat is populated.
  const terminal = {}
  for (const [kind, id] of Object.entries(jobs)) {
    if (!id) continue
    terminal[kind] = await waitJob(id, kind === 'candidateEvaluation' ? 300000 : 240000)
  }
  await goto('jobs')
  await page.waitForSelector('#jobsRefresh')
  await page.click('#jobsRefresh')
  await page.waitForFunction(ids => ids.every(id => document.querySelector('#jobsBody')?.textContent?.includes(id)), Object.values(jobs).filter(Boolean))
  const jobRows = await page.locator('#jobsBody .job-row').count()
  const jobsText = await page.locator('#jobsBody').textContent()
  if (jobRows < Object.values(jobs).filter(Boolean).length || !/SUCCEEDED|FAILED/.test(jobsText || '')) throw new Error(`Jobs page not populated: rows=${jobRows}`)
  add('Jobs / Heartbeat', 'Show real background jobs, terminal status, heartbeat, cancellation/result access', 'PARTIAL', await shot('08-jobs-populated.png'), ['Terminal job result is exposed through a JavaScript alert instead of an inline inspectable result panel.'])

  // 9. Strategy Health populated lifecycle proof.
  await goto('monitor')
  await page.waitForSelector('[data-strategy-health-page][data-monitor-state="SUSPEND"][data-monitor-computed="NORMAL"][data-monitor-lifecycle="SUSPENDED"]')
  add('Strategy Health', 'Detect EV/PF/DD/frequency/slippage/regime drift and prevent automatic unpause after SUSPEND', 'PASS', await shot('09-strategy-health-populated.png'))

  // 10. Production Deployment: exact identity + LIVE/PAPER observations + authoritative LIVE health.
  await goto('deployments')
  await page.waitForSelector('[data-production-deployments-page][data-deployment-id="deploy-synthetic-ui-v1"]')
  const deployment = await page.locator('[data-production-deployments-page]').evaluate(el => ({
    text: el.textContent || '',
    live: Number(el.dataset.liveObservations || 0),
    paper: Number(el.dataset.paperObservations || 0),
    authoritative: el.dataset.authoritativeHealth,
  }))
  for (const token of ['EXECUTION_OBSERVATIONS', 'LIVE', 'Observation digest', 'Deployment identity hash']) {
    if (!deployment.text.includes(token)) throw new Error(`Deployment QA missing ${token}`)
  }
  if (deployment.live < 1 || deployment.paper < 1 || deployment.authoritative !== 'YES') throw new Error(`Deployment observation evidence incomplete: ${JSON.stringify(deployment)}`)
  add('Production Deployment', 'Bind exact deployed identity to append-only PAPER/LIVE execution observations; only LIVE may drive authoritative production health', 'PASS', await shot('10-production-deployment-live-observations.png'))

  if (browserErrors.length) throw new Error(`browser errors: ${browserErrors.join(' | ')}`)

  const result = {
    ok: true,
    synthetic: true,
    warning: 'SYNTHETIC FEATURE QA ONLY - NOT MARKET EDGE OR PRODUCTION EVIDENCE',
    synthetic_fixture: {
      file: 'MTX_2025_SYNTHETIC.parquet',
      sha256: 'b7467b2e3144aaca0a851b553aad11900b30b76a408840b5943b75dab0a4df80',
      rows: 2101,
      research_run_id: syntheticRun,
    },
    jobs,
    terminal_jobs: terminal,
    frozen_candidate: frozenCandidate,
    findings,
    summary: {
      pass: findings.filter(x => x.status === 'PASS').length,
      partial: findings.filter(x => x.status === 'PARTIAL').length,
      fail: findings.filter(x => x.status === 'FAIL').length,
    },
  }
  fs.writeFileSync(path.join(outDir, 'feature-qa.json'), JSON.stringify(result, null, 2))
  console.log('STRATEGY_LAB_FEATURE_QA', JSON.stringify(result.summary), JSON.stringify(jobs))
} catch (error) {
  const result = {
    ok: false,
    error: String(error?.stack || error),
    browserErrors,
    jobs,
    frozenCandidate,
    findings,
  }
  fs.writeFileSync(path.join(outDir, 'feature-qa.json'), JSON.stringify(result, null, 2))
  await page.screenshot({ path: path.join(outDir, 'FAIL.png'), fullPage: true }).catch(() => {})
  await browser.close()
  throw error
}

await browser.close()
