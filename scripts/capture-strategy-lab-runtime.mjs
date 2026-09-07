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
]

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
