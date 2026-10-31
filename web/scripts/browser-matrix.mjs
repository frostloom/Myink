// Execute real engines serially against built Vue + loopback fixtures only.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'
const web = fileURLToPath(new URL('..', import.meta.url))
const index = process.argv.indexOf('--output')
const output = index < 0 ? fs.mkdtempSync(path.join(os.tmpdir(), 'myink-browser-matrix-')) : path.resolve(process.argv[index + 1])
if (index >= 0) fs.mkdirSync(output, { recursive: false })
const receipt = { kind: 'three_engine_frontend_acceptance', passed: false, results: [] }
for (const browser of ['chromium', 'firefox', 'webkit']) {
  const directory = path.join(output, browser)
  fs.mkdirSync(directory)
  for (const [stage, script, extra] of [
    ['smoke', 'scripts/vue-browser-smoke.mjs', []],
    ['workspace', '../scripts/evaluate-browser.cjs', ['--dist', 'dist-vue']],
    ['readiness', 'scripts/vue-readiness-browser.mjs', ['--dist', 'dist-vue']],
    ['release', 'scripts/release-safety-browser.mjs', []],
    ['admin-feedback', 'scripts/admin-feedback-browser.mjs', []],
    ['pi-console', 'scripts/pi-console-browser.mjs', []],
    ['resource-feedback', 'scripts/resource-feedback-browser.mjs', []],
    ['guest', 'scripts/guest-browser.mjs', []],
  ]) {
    const target = path.join(directory, stage)
    const result = spawnSync(process.execPath, [script, ...extra, '--output', target], {
      cwd: web, env: { ...process.env, MYINK_TEST_BROWSER: browser }, encoding: 'utf8', timeout: 180000,
    })
    fs.writeFileSync(path.join(directory, stage + '.log'), (result.stdout ?? '') + (result.stderr ?? '') + (result.error?.message ?? ''))
    let detail
    try { detail = JSON.parse(fs.readFileSync(path.join(target, 'receipt.json'), 'utf8')) } catch { /* failed before receipt */ }
    const passed = result.status === 0 && detail?.passed === true && detail.browser === browser
    receipt.results.push({ browser, stage, passed, exitCode: result.status, checks: detail?.checks?.length ?? 0, receipt: path.join(target, 'receipt.json') })
    console.log(`${browser}/${stage}: ${passed ? 'passed' : 'FAILED'}`)
    if (!passed) console.error(detail?.error || result.stderr || result.error?.message || 'Stage failed without diagnostics')
  }
}
receipt.passed = receipt.results.every(result => result.passed)
fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2))
console.log(JSON.stringify({ output, ...receipt }, null, 2))
assert.ok(receipt.passed, 'Every engine/stage must pass; see individual failure receipts')
