// Real-browser driver for tests/test_live_ws_browser_e2e.py (docs/DECISIONS.md
// ADR-057). Not a pytest file itself — invoked as a subprocess by the pytest
// test, which has no JS test tooling of its own and does not want to grow one
// for a single file. Drives the ACTUAL /live/{call_id} page against a REAL
// running server (real sockets, real WebSocket auth handshake) through a
// headless browser: login -> real JWT -> open page -> paste token -> click
// Verbinden -> observe the real client-visible outcome for each case.
//
// Usage: node e2e_live_ws_auth.js <baseUrl> <callId> <cleanToken>
// Prints one JSON object to stdout: { cases: { clean, bearerPrefixed, invalid }, error }
const { chromium } = require('playwright');

async function waitForStatusText(page, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let last = null;
  while (Date.now() < deadline) {
    last = await page.$eval('#statusText', (el) => el.textContent);
    if (last && (last.includes('Bereit') || last.includes('Authentifizierung fehlgeschlagen'))) {
      return last;
    }
    await page.waitForTimeout(150);
  }
  return last;
}

async function runCase(browser, baseUrl, callId, token) {
  const page = await browser.newPage();
  try {
    await page.goto(`${baseUrl}/live/${callId}`);
    await page.fill('#callId', String(callId));
    await page.fill('#token', token);
    await page.click('#connectBtn');
    // 12s, not 4s: this is a correctness check, not a latency benchmark — a
    // busy CI/dev machine running the full suite must not flake this.
    const statusText = await waitForStatusText(page, 12000);
    const connectCardHidden = await page.$eval('#connectCard', (el) => el.hidden);
    return { statusText, connectCardHidden };
  } finally {
    await page.close();
  }
}

(async () => {
  const [, , baseUrl, callId, cleanToken] = process.argv;
  let browser;
  try {
    browser = await chromium.launch();
  } catch (e) {
    console.log(JSON.stringify({ error: 'browser_launch_failed', message: String(e) }));
    process.exit(0);
  }
  try {
    const clean = await runCase(browser, baseUrl, callId, cleanToken);
    const bearerPrefixed = await runCase(browser, baseUrl, callId, 'Bearer ' + cleanToken);
    const whitespaceWrapped = await runCase(browser, baseUrl, callId, '  ' + cleanToken + '\n');
    const invalid = await runCase(browser, baseUrl, callId, 'not-a-real-jwt-at-all');
    console.log(JSON.stringify({ cases: { clean, bearerPrefixed, whitespaceWrapped, invalid } }));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.log(JSON.stringify({ error: 'script_failed', message: String(e) }));
  process.exit(0);
});
