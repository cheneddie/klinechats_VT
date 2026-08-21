import fs from 'node:fs';
import path from 'node:path';
import { chromium } from 'playwright';

const OUT = path.resolve(process.env.QA_OUT || 'qa-artifacts');
const BASE = process.env.QA_BASE_URL || 'http://127.0.0.1:4173';
const API = process.env.QA_API_URL || 'http://127.0.0.1:8765/api';
const manifestPath = process.env.QA_MANIFEST || path.join(OUT, 'seed.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
fs.mkdirSync(OUT, { recursive: true });

const rows = [];
const ignored = [/favicon\.ico/i];
const shouldIgnore = url => ignored.some(x => x.test(url));
const add = row => {
  if (!shouldIgnore(row.url || '')) rows.push({ at: new Date().toISOString(), ...row });
};
const save = () => fs.writeFileSync(path.join(OUT, 'network-errors.json'), JSON.stringify({ ok: rows.length === 0, errors: rows }, null, 2));
const wait = ms => new Promise(resolve => setTimeout(resolve, ms));

let browser;
try {
  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  page.on('requestfailed', req => {
    add({
      kind: 'requestfailed',
      method: req.method(),
      url: req.url(),
      failure: req.failure()?.errorText || 'unknown',
    });
    save();
  });
  page.on('response', res => {
    if (res.status() >= 400) {
      add({
        kind: 'http',
        method: res.request().method(),
        url: res.url(),
        status: res.status(),
        statusText: res.statusText(),
      });
      save();
    }
  });

  const visit = async url => {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 20000 });
    await wait(1500);
  };

  await visit(BASE);
  await visit(`${BASE}/#/practice/MR_REJECTION`);
  await visit(`${BASE}/#/replay/${encodeURIComponent(manifest.mr_yes)}`);
  await visit(`${BASE}/#/research`);

  // Exercise research-governance endpoints too; any >=400 is captured above only
  // for browser requests, so direct fetches are explicitly checked here.
  for (const route of ['/v4/health', '/v4/research/provenance', '/v4/sanity/latest', '/v4/management/capture']) {
    const res = await fetch(API + route);
    if (!res.ok) add({ kind: 'api', method: 'GET', url: API + route, status: res.status, statusText: res.statusText });
  }
  save();
  if (rows.length) {
    console.error(JSON.stringify(rows, null, 2));
    process.exitCode = 1;
  } else {
    console.log('V4 network watchdog: PASS');
  }
} catch (err) {
  add({ kind: 'watchdog', method: null, url: '', failure: String(err?.stack || err) });
  save();
  console.error(err);
  process.exitCode = 1;
} finally {
  try { await browser?.close(); } catch {}
  save();
}
