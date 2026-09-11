import fs from 'node:fs'
import path from 'node:path'
import { chromium } from 'playwright'

const outDir = path.resolve(process.env.STRATEGY_LAB_SCREENSHOT_DIR || 'artifacts/strategy-lab-runtime')
fs.mkdirSync(outDir, { recursive: true })

const browser = await chromium.launch({ headless: true, channel: process.env.CI ? 'chrome' : undefined })
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 })
page.setDefaultTimeout(15000)

const errors = []
page.on('pageerror', err => errors.push(`pageerror:${err.message}`))
page.on('console', msg => {
  if (msg.type() === 'error' && !/favicon|ERR_CONNECTION_REFUSED/i.test(msg.text())) {
    errors.push(`console:${msg.text()}`)
  }
})

const base = process.env.STRATEGY_LAB_URL || 'http://127.0.0.1:4173/strategy-lab.html'
const routes = [
  ['library', '01-strategy-library.png', '.sl-card'],
  ['backtest', '02-backtest-studio.png', '#btRun'],
  ['review', '03-trade-review.png', '#reviewBody'],
  ['reports', '04-report-center.png', '#reportBody'],
  ['optimize', '05-optimization-lab.png', '#optRun'],
  ['compare', '06-compare-lab.png', '#cmpRun'],
  ['candidates', '07-candidate-production-gate.png', '#gateRun'],
  ['jobs', '08-jobs-heartbeat.png', '#jobsBody'],
  ['monitor', '09-strategy-health.png', '[data-strategy-health-page]'],
  ['deployments', '10-production-deployment-governance.png', '[data-production-deployments-page]'],
]

async function selectFirstRealOption(selector) {
  const value = await page.locator(`${selector} option`).evaluateAll(options => {
    const hit = options.find(o => o.value)
    return hit?.value || ''
  })
  if (value) await page.selectOption(selector, value)
  return value
}

async function assertPortfolioCard(scope) {
  const selector = `[data-portfolio-scope="${scope}"]`
  await page.waitForSelector(selector)
  const state = await page.locator(selector).evaluate(el => ({
    mode: el.querySelector('[data-pf="mode"]')?.value || '',
    overlap: el.querySelector('[data-pf="overlap_policy"]')?.value || '',
    cooldown: el.querySelector('[data-pf="reentry_cooldown_seconds"]')?.value || '',
    quantity: el.querySelector('[data-pf="fixed_quantity"]')?.value || '',
    forceFlat: el.querySelector('[data-pf="force_flat_time"]')?.value || '',
    fingerprint: el.querySelector('[data-pf-hash]')?.textContent || '',
  }))
  if (state.mode !== 'SINGLE_POSITION' || state.overlap !== 'SKIP_WHILE_OPEN' || !state.fingerprint) {
    throw new Error(`Portfolio UI state incomplete for ${scope}: ${JSON.stringify(state)}`)
  }
  console.log(`STRATEGY_LAB_PORTFOLIO_UI ${scope}`, JSON.stringify(state))
  return state
}

async function hydrateRoute(route) {
  if (route === 'backtest') {
    await page.waitForSelector('[data-portfolio-scope="backtest"]')
    await page.selectOption('[data-portfolio-scope="backtest"] [data-pf="mode"]', 'SINGLE_POSITION')
    await page.fill('[data-portfolio-scope="backtest"] [data-pf="reentry_cooldown_seconds"]', '60')
    await page.fill('[data-portfolio-scope="backtest"] [data-pf="fixed_quantity"]', '2')
    await page.fill('[data-portfolio-scope="backtest"] [data-pf="force_flat_time"]', '13:40:00')
    await page.locator('[data-portfolio-scope="backtest"] [data-pf="force_flat_time"]').dispatchEvent('change')
    await assertPortfolioCard('backtest')
  }
  if (route === 'review') {
    const value = await selectFirstRealOption('#reviewBt')
    if (value) {
      await page.click('#reviewLoad')
      await page.waitForSelector('.trade-item')
      await page.locator('.trade-item').first().click()
      await page.waitForSelector('#tradeDetail h2')
      await page.waitForSelector('#tradeChart[data-trade-review-overlay="ready"]')
      await page.waitForSelector('#tradeChart .trade-review-svg')
      await page.waitForSelector('#tradeChart .trade-review-banner')
      const overlay = await page.locator('#tradeChart').evaluate(el => ({
        ready: el.dataset.tradeReviewOverlay,
        tradeId: el.dataset.tradeReviewId,
        svgChildren: el.querySelector('.trade-review-svg')?.childElementCount || 0,
        banner: el.querySelector('.trade-review-banner')?.textContent || '',
      }))
      if (overlay.ready !== 'ready' || !overlay.tradeId || overlay.svgChildren < 6 || !/ENTRY/i.test(overlay.banner)) {
        throw new Error(`Trade Review execution overlay incomplete: ${JSON.stringify(overlay)}`)
      }
      console.log('STRATEGY_LAB_TRADE_OVERLAY', JSON.stringify(overlay))
      await page.waitForTimeout(350)
    }
  }
  if (route === 'reports') {
    const value = await selectFirstRealOption('#reportBt')
    if (value) {
      await page.click('#reportLoad')
      await page.waitForSelector('#reportBody .metric-grid')
      await page.waitForTimeout(250)
    }
  }
  if (route === 'optimize') await assertPortfolioCard('optimize')
  if (route === 'compare') {
    await page.fill('#cmpIds', 'bt-synthetic-mtx-overlap-independent-v1, bt-synthetic-mtx-overlap-single-v1')
    await page.click('#cmpRun')
    await page.waitForSelector('#cmpBody [data-compare-status="BLOCKED"]')
    const gate = await page.locator('#cmpBody [data-compare-status="BLOCKED"]').textContent()
    if (!/PORTFOLIO_POLICY_HASH/.test(gate || '') || !/EXECUTION_HASH/.test(gate || '')) {
      throw new Error(`Compare Lab did not expose blocked execution mismatch: ${gate}`)
    }
    if (await page.locator('#cmpBody table').count()) {
      throw new Error('Compare Lab exposed performance table despite BLOCKED comparability gate')
    }
    console.log('STRATEGY_LAB_COMPARE_GATE BLOCKED', gate?.replace(/\s+/g, ' ').trim())
  }
  if (route === 'candidates') await assertPortfolioCard('candidate')
  if (route === 'monitor') {
    await page.waitForSelector('[data-strategy-health-page][data-monitor-state="SUSPEND"][data-monitor-computed="NORMAL"][data-monitor-lifecycle="SUSPENDED"]')
    const health = await page.locator('[data-strategy-health-page]').evaluate(el => ({
      effective: el.dataset.monitorState,
      computed: el.dataset.monitorComputed,
      lifecycle: el.dataset.monitorLifecycle,
      text: el.textContent || '',
      timelineRows: el.querySelectorAll('table tbody tr').length,
      driftRows: el.querySelectorAll('[data-monitor-drift] .check').length,
      resumeDisabled: el.querySelector('#healthResume')?.disabled ?? true,
    }))
    if (health.timelineRows < 3 || health.resumeDisabled || !/SUSPEND_LATCHED_BY_LIFECYCLE_CONTROL/.test(health.text)) {
      throw new Error(`Strategy Health sticky suspension proof incomplete: ${JSON.stringify(health)}`)
    }
    // Machine acceptance must not depend on whether the visible UI is zh-TW or English.
    // The drift panel has exactly seven governed dimensions (EV, PF, DD, signal
    // frequency, slippage multiple/delta and regime mix TVD).
    if (health.driftRows < 7) {
      throw new Error(`Strategy Health drift dimensions missing: ${JSON.stringify(health)}`)
    }
    console.log('STRATEGY_LAB_HEALTH_LATCH', JSON.stringify({
      effective: health.effective,
      computed: health.computed,
      lifecycle: health.lifecycle,
      timelineRows: health.timelineRows,
      driftRows: health.driftRows,
    }))
  }
  if (route === 'deployments') {
    await page.waitForSelector('[data-production-deployments-page][data-deployment-id="deploy-synthetic-ui-v1"][data-production-eligible="NO"][data-deployment-lifecycle="SUSPENDED"][data-deployment-computed="NORMAL"][data-deployment-effective="SUSPEND"][data-health-evidence-kind="EXECUTION_OBSERVATIONS"][data-health-source-type="LIVE"][data-health-authoritative="YES"]')
    const deployment = await page.locator('[data-production-deployments-page]').evaluate(el => {
      const identityHashTitles = [...el.querySelectorAll('[data-deployment-identity] b[title]')]
        .map(x => x.getAttribute('title') || '')
        .filter(x => /^[0-9a-f]{64}$/i.test(x))
      return {
        deploymentId: el.dataset.deploymentId,
        eligible: el.dataset.productionEligible,
        lifecycle: el.dataset.deploymentLifecycle,
        computed: el.dataset.deploymentComputed,
        effective: el.dataset.deploymentEffective,
        liveObservations: Number(el.dataset.liveObservations || 0),
        paperObservations: Number(el.dataset.paperObservations || 0),
        evidenceKind: el.dataset.healthEvidenceKind,
        healthSource: el.dataset.healthSourceType,
        authoritative: el.dataset.healthAuthoritative,
        observationDigest: el.dataset.healthObservationDigest,
        identityRows: el.querySelectorAll('[data-deployment-identity] .check').length,
        identityHashTitles,
        observationRows: el.querySelectorAll('[data-execution-observation-evidence] .metric').length,
        resumeDisabled: el.querySelector('#deployResume')?.disabled ?? true,
      }
    })
    if (deployment.identityRows < 10 || deployment.identityHashTitles.length < 5 || deployment.resumeDisabled) {
      throw new Error(`Production deployment exact identity UI incomplete: ${JSON.stringify(deployment)}`)
    }
    if (deployment.liveObservations < 1 || deployment.paperObservations < 1 || deployment.observationRows < 6) {
      throw new Error(`Production execution observation UI incomplete: ${JSON.stringify(deployment)}`)
    }
    if (deployment.evidenceKind !== 'EXECUTION_OBSERVATIONS' || deployment.healthSource !== 'LIVE' || deployment.authoritative !== 'YES' || !/^[0-9a-f]{64}$/.test(deployment.observationDigest || '')) {
      throw new Error(`Production health is not backed by authoritative LIVE observation evidence: ${JSON.stringify(deployment)}`)
    }
    console.log('STRATEGY_LAB_DEPLOYMENT_LIVE_EVIDENCE', JSON.stringify({
      deploymentId: deployment.deploymentId,
      eligible: deployment.eligible,
      lifecycle: deployment.lifecycle,
      computed: deployment.computed,
      effective: deployment.effective,
      liveObservations: deployment.liveObservations,
      paperObservations: deployment.paperObservations,
      evidenceKind: deployment.evidenceKind,
      healthSource: deployment.healthSource,
      observationDigest: deployment.observationDigest,
      identityHashCount: deployment.identityHashTitles.length,
    }))
  }
}

const manifest = []
try {
  await page.goto(`${base}#/library`, { waitUntil: 'domcontentloaded' })
  await page.waitForSelector('#slHealth.status.ok')
  const healthText = (await page.locator('#slHealth').textContent())?.trim() || ''
  if (!healthText.includes('STRATEGY_LAB_V1')) {
    throw new Error(`Strategy Lab API health did not connect: ${healthText}`)
  }

  for (const [route, file, selector] of routes) {
    await page.evaluate(r => { location.hash = `#/${r}` }, route)
    await page.waitForSelector(selector)
    await page.waitForTimeout(250)
    await hydrateRoute(route)
    const target = path.join(outDir, file)
    await page.screenshot({ path: target, fullPage: true })
    manifest.push({ route, file, url: page.url(), health: healthText })
    console.log(`STRATEGY_LAB_SCREENSHOT ${route} ${target}`)
  }

  if (errors.length) {
    throw new Error(`browser errors: ${errors.join(' | ')}`)
  }
  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify({ ok: true, health: healthText, screenshots: manifest }, null, 2))
} catch (error) {
  fs.writeFileSync(path.join(outDir, 'manifest.json'), JSON.stringify({ ok: false, error: String(error?.stack || error), errors, screenshots: manifest }, null, 2))
  await page.screenshot({ path: path.join(outDir, 'FAIL.png'), fullPage: true }).catch(() => {})
  await browser.close()
  throw error
}

await browser.close()
