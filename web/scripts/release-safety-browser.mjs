// Real production bundles, controlled local deployment switch and delayed API.
import fs from 'node:fs'
import path from 'node:path'
import http from 'node:http'
import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'
import { browserName, launchBrowser } from './browser-options.mjs'
const web = fileURLToPath(new URL('..', import.meta.url))
const arg = process.argv.indexOf('--output')
assert.ok(arg >= 0, '--output <new directory> required')
const output = path.resolve(process.argv[arg + 1]); fs.mkdirSync(output, { recursive: false })
// Build a second real Vue release with distinct HTML identity. The active source
// and default dist remain untouched; version safety is no longer tied to frameworks.
const nextRoot = path.join(output, 'next-vue')
await build({
  configFile: path.join(web, 'vite.config.ts'), logLevel: 'silent',
  plugins: [{ name: 'test-release-identity', transformIndexHtml: html => html.replace('</head>', '<meta name="myink-test-release" content="next">\n</head>') }],
  build: { outDir: nextRoot },
})
const builds = Object.fromEntries([['current', path.join(web, 'dist-vue')], ['next', nextRoot]].map(([version, root]) => [version, {
  root, html: fs.readFileSync(path.join(root, 'index.html'), 'utf8'), release: JSON.parse(fs.readFileSync(path.join(root, 'release.json'), 'utf8')),
}]))
assert.notEqual(builds.current.release.id, builds.next.release.id)
assert.equal(builds.current.release.client, 'vue'); assert.equal(builds.next.release.client, 'vue')
const receipt = { kind: 'production_release_safety', browser: browserName, passed: false, checks: [], pageErrors: [], releases: { current: builds.current.release, next: builds.next.release }, unexpected: [] }
let served = builds.current, manifest = served.release, pendingLogin, loginReceived
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://localhost')
  if (url.pathname === '/api/v1/auth/token' && req.method === 'POST') {
    for await (const _chunk of req) { /* drain fixture credentials */ }
    pendingLogin = res; loginReceived?.(); return
  }
  if (url.pathname.startsWith('/api/')) {
    receipt.unexpected.push(`${req.method} ${url.pathname}`)
    res.writeHead(500, { 'Content-Type': 'application/json' }); res.end('{"error":"unknown_fixture_api"}'); return
  }
  res.setHeader('Cache-Control', 'no-store')
  if (url.pathname === '/release.json') { res.setHeader('Content-Type', 'application/json'); res.end(JSON.stringify(manifest)); return }
  if (url.pathname.startsWith('/assets/')) {
    const file = Object.values(builds).map(build => path.resolve(build.root, '.' + url.pathname)).find(file => fs.existsSync(file))
    if (!file || !Object.values(builds).some(build => file.startsWith(build.root + path.sep))) { res.writeHead(404); res.end(); return }
    res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : 'text/css'); fs.createReadStream(file).pipe(res); return
  }
  if (url.pathname === '/favicon.svg') { res.setHeader('Content-Type', 'image/svg+xml'); res.end(fs.readFileSync(path.join(served.root, 'favicon.svg'))); return }
  res.setHeader('Content-Type', 'text/html'); res.end(served.html)
})
let browser
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  browser = await launchBrowser(); receipt.browserVersion = browser.version()
  for (const client of ['current', 'next']) {
    const next = client === 'current' ? 'next' : 'current'
    served = builds[client]; manifest = served.release
    const page = await browser.newPage()
    await page.context().clearCookies()
    await page.goto(origin + '/login')
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear() })
    await page.reload()
    page.on('pageerror', e => receipt.pageErrors.push(`${client}: ${e.message}`))
    const user = page.getByLabel('用户名', { exact: true }), password = page.getByLabel('密码', { exact: true })
    await user.fill('safe-release-user'); await password.fill('browser-password1')
    assert.equal(await page.evaluate(() => Boolean(document.querySelector('#root')?.__vue_app__)), true)
    const update = page.getByRole('button', { name: '刷新到新版本', exact: true })
    // A new manifest paired with old HTML is an interrupted deployment.
    manifest = builds[next].release
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await page.waitForLoadState('networkidle')
    assert.equal(await update.count(), 0)
    assert.equal(await user.inputValue(), 'safe-release-user')
    receipt.checks.push(`${client}: mixed_manifest_html_does_not_offer_update`)
    served = builds[next]
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
    await update.waitFor()
    assert.equal(await user.inputValue(), 'safe-release-user')
    assert.equal(await password.inputValue(), 'browser-password1')
    assert.equal(await page.evaluate(() => Boolean(document.querySelector('#root')?.__vue_app__)), true)
    receipt.checks.push(`${client}: update_only_prompts_preserves_input`)
    let cancelMessage = ''
    page.once('dialog', async dialog => { assert.equal(dialog.type(), 'confirm'); cancelMessage = dialog.message(); await dialog.dismiss() })
    await update.click()
    assert.match(cancelMessage, /章节/); assert.match(cancelMessage, /附件/); assert.match(cancelMessage, /备份|导出/)
    assert.equal(await user.inputValue(), 'safe-release-user')
    receipt.checks.push(`${client}: cancelled_update_retains_form`)
    const received = new Promise(resolve => { loginReceived = resolve })
    await page.getByRole('button', { name: '登录', exact: true }).click()
    await received
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === '刷新到新版本' && b.disabled))
    assert.equal(await update.isDisabled(), true)
    const unloadProtected = await page.evaluate(() => { const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); return event.defaultPrevented })
    assert.equal(unloadProtected, true)
    pendingLogin.writeHead(401, { 'Content-Type': 'application/json' }); pendingLogin.end('{"error":"INVALID_CREDENTIALS"}'); pendingLogin = undefined
    await page.waitForFunction(() => [...document.querySelectorAll('button')].some(b => b.textContent === '刷新到新版本' && !b.disabled))
    receipt.checks.push(`${client}: write_blocks_update_and_unload_then_unlocks`)
    const dialogs = []
    page.on('dialog', async dialog => { dialogs.push(dialog.type()); await dialog.accept() })
    await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle' }), update.click()])
    assert.ok(dialogs.includes('confirm'))
    // Firefox can finish an intermediate navigation before the new SPA has mounted.
    await page.waitForFunction(({ id }) => {
      const meta = document.querySelector('meta[name="myink-release"]')?.getAttribute('content')
      return meta && JSON.parse(meta).id === id && Boolean(document.querySelector('#root')?.__vue_app__) === true && document.querySelector('input')
    }, { client: next, id: builds[next].release.id })
    assert.equal(await page.evaluate(() => Boolean(document.querySelector('#root')?.__vue_app__)), true)
    const active = await page.locator('meta[name="myink-release"]').getAttribute('content')
    assert.deepEqual(JSON.parse(active), builds[next].release)
    await page.screenshot({ path: path.join(output, `${client}-to-${next}.png`), fullPage: true })
    receipt.checks.push(`${client}: confirmed_update_loads_paired_next_runtime`)
    await page.close()
  }
  assert.deepEqual(receipt.pageErrors, []); assert.deepEqual(receipt.unexpected, [])
  receipt.passed = true
} catch (error) { receipt.error = String(error); receipt.errorStack = error.stack; process.exitCode = 1 }
finally {
  if (pendingLogin) { pendingLogin.destroy(); pendingLogin = undefined }
  try { await browser?.close() } catch (e) { receipt.passed = false; receipt.cleanupError = String(e); process.exitCode = 1 }
  server.closeAllConnections(); await new Promise(resolve => server.close(resolve))
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2)); console.log(JSON.stringify({ output, ...receipt }, null, 2))
}
