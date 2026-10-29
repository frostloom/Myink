// Real isolated API/DB acceptance. The proxy forbids every model-generating write.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import http from 'node:http'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'
import { finalizeBrowserReceipt } from './browser-receipt.mjs'

const root = fileURLToPath(new URL('../../', import.meta.url))
const dist = path.join(root, 'web/dist-vue')
const metadataPath = process.env.MYINK_GUEST_METADATA
const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'))
const upstream = new URL(process.env.MYINK_GUEST_REAL_API)
assert.equal(upstream.hostname, '127.0.0.1')
assert.ok(upstream.port && upstream.port !== '8000' && upstream.port !== '80')
const output = path.resolve(process.argv[process.argv.indexOf('--output') + 1])
const index = fs.readFileSync(path.join(dist, 'index.html'))
const receipt = { kind: 'guest_real_isolated_api_browser', browser: 'chromium', passed: false,
  build: { indexSha256: createHash('sha256').update(index).digest('hex') }, checks: [], api: [], pageErrors: [],
  limits: ['Real API/PostgreSQL/Redis, clean browser contexts; no synthetic API responses',
    'Quota reserves use the real DB helper without a model worker; generation and production Caddy/TLS not exercised'] }
const allowedWrites = new Set(['/api/v1/auth/guest', '/api/v1/auth/register'])
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    if (req.method !== 'GET' && !allowedWrites.has(url.pathname)) {
      res.writeHead(405); res.end('Model and other writes forbidden by acceptance proxy'); return
    }
    const proxy = http.request(new URL(req.url, upstream), { method: req.method, timeout: 15000,
      headers: { ...req.headers, host: upstream.host, 'x-myink-client-ip': metadata.ip } }, response => {
      receipt.api.push({ method: req.method, path: url.pathname, status: response.statusCode })
      if (url.pathname === '/api/v1/auth/guest' && response.statusCode === 200) {
        const chunks = []
        response.on('data', chunk => chunks.push(chunk))
        response.on('end', () => {
          const uid = JSON.parse(Buffer.concat(chunks).toString()).user_id
          if (!metadata.users.includes(uid)) metadata.users.push(uid)
          fs.writeFileSync(metadataPath, JSON.stringify(metadata))
        })
      }
      res.writeHead(response.statusCode, response.headers); response.pipe(res)
    })
    proxy.on('timeout', () => proxy.destroy(new Error('Isolated upstream timeout')))
    proxy.on('error', error => { res.writeHead(502); res.end(error.message) })
    req.pipe(proxy); return
  }
  let file = path.resolve(dist, '.' + decodeURIComponent(url.pathname))
  if (file !== dist && !file.startsWith(dist + path.sep)) { res.writeHead(403); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html')
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[path.extname(file)] ?? 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})
let browser
let finalizing
function finalize() {
  return finalizing ??= finalizeBrowserReceipt(receipt, output, [
    async () => { await browser?.close(); receipt.browserClosed = true },
    async () => { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); receipt.proxyClosed = true },
  ])
}
async function stop(reason, code) {
  receipt.passed = false; receipt.error = reason
  await finalize()
  process.exit(code)
}
const deadline = setTimeout(() => { void stop('Browser verifier exceeded its 165-second deadline', 1) }, 165000)
const onTerm = () => { void stop('Browser verifier interrupted with SIGTERM', 143) }
const onInt = () => { void stop('Browser verifier interrupted with SIGINT', 130) }
process.on('SIGTERM', onTerm); process.on('SIGINT', onInt)
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  browser = await chromium.launch({ headless: true })
  const contexts = await Promise.all([browser.newContext(), browser.newContext()])
  for (const context of contexts) {
    context.setDefaultTimeout(10000)
    context.setDefaultNavigationTimeout(15000)
    await context.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  }
  // Intentional local failure probe: no guest/API/DB fixture or model calls.
  if (process.env.MYINK_GUEST_FAILURE_PROBE === 'missing-navigation') {
    const page = await contexts[0].newPage()
    await page.goto(origin + '/login')
    await page.waitForURL('**/intentionally-missing', { timeout: 100 })
    throw new Error('Missing-navigation probe unexpectedly succeeded')
  }
  const pages = []
  const identities = []
  for (const context of contexts) {
    const page = await context.newPage(); pages.push(page)
    page.on('pageerror', error => receipt.pageErrors.push(error.message))
    await page.goto(origin + '/login')
    await page.getByRole('button', { name: '游客体验', exact: true }).click()
    await page.waitForURL('**/long')
    const identity = await page.evaluate(() => JSON.parse(localStorage.getItem('myink.session')))
    identities.push(identity)
    if (!metadata.users.includes(identity.userId)) metadata.users.push(identity.userId)
    fs.writeFileSync(metadataPath, JSON.stringify(metadata))
  }
  assert.notEqual(identities[0].userId, identities[1].userId)
  receipt.checks.push('same_ip_clean_contexts_have_distinct_guest_ids')
  const oldCookie = (await contexts[0].cookies()).find(cookie => cookie.name === 'myink_guest')
  assert.ok(oldCookie.httpOnly)
  execFileSync(process.env.MYINK_GUEST_PYTHON, ['scripts/verify_guest_browser.py', '--fixture', 'seed', '--metadata', metadataPath], { cwd: root, timeout: 30000 })
  Object.assign(metadata, JSON.parse(fs.readFileSync(metadataPath, 'utf8')))
  for (const [i, page] of pages.entries()) {
    await page.reload()
    await page.getByRole('main').getByText(`真实游客隔离作品${i + 1}`, { exact: true }).waitFor()
    assert.equal(await page.getByRole('main').getByText(`真实游客隔离作品${2 - i}`, { exact: true }).count(), 0)
    const quotaResponse = await contexts[i].request.get(origin + '/api/v1/auth/guest/quota', { headers: { Authorization: 'Bearer ' + identities[i].token }, timeout: 10000 })
    assert.equal(quotaResponse.status(), 200)
    const quota = await quotaResponse.json()
    assert.equal(quota.short.remaining, 1); assert.equal(quota.long.remaining, 7)
    assert.equal(await page.getByText(/短篇剩余|长篇剩余/).count(), 0)
    const ownProjects = await contexts[i].request.get(origin + '/api/v1/projects', { headers: { Authorization: 'Bearer ' + identities[i].token }, timeout: 10000 })
    assert.deepEqual((await ownProjects.json()).map(project => project.id), [metadata.projects[i]])
  }
  receipt.checks.push('same_ip_shared_real_quota_and_separate_owned_projects')
  await pages[0].evaluate(() => { const session = JSON.parse(localStorage.getItem('myink.session')); session.expiresAt = Date.now() - 1000; localStorage.setItem('myink.session', JSON.stringify(session)) })
  const restore = pages[0].waitForResponse(response => response.url() === origin + '/api/v1/auth/guest' && response.request().postDataJSON()?.restore_only === true)
  await pages[0].reload()
  assert.equal((await restore).status(), 200)
  await pages[0].getByRole('main').getByText('真实游客隔离作品1', { exact: true }).waitFor()
  assert.equal(await pages[0].evaluate(() => JSON.parse(localStorage.getItem('myink.session')).userId), identities[0].userId)
  assert.ok(await pages[0].evaluate(() => JSON.parse(localStorage.getItem('myink.session')).expiresAt > Date.now()))
  receipt.checks.push('expired_guest_restores_same_id_with_httponly_cookie')
  await pages[0].screenshot({ path: path.join(output, 'real-guest-quota.png') })
  await pages[0].getByRole('link', { name: '账号', exact: true }).click()
  const dialog = pages[0].getByRole('region', { name: '注册账号', exact: true })
  await dialog.getByLabel('用户名', { exact: true }).fill('guest-real-' + Date.now())
  await dialog.getByLabel('密码', { exact: true }).fill('browser acceptance password 123')
  await dialog.getByLabel('确认密码', { exact: true }).fill('browser acceptance password 123')
  await dialog.getByLabel('邀请码', { exact: true }).fill(metadata.invitation)
  await dialog.getByRole('button', { name: '创建账号', exact: true }).click()
  await dialog.waitFor({ state: 'hidden' })
  const upgraded = await pages[0].evaluate(() => JSON.parse(localStorage.getItem('myink.session')))
  assert.equal(upgraded.userId, identities[0].userId); assert.equal(upgraded.isGuest, false)
  await pages[0].getByRole('navigation', { name: '作品分区' }).getByRole('link', { name: '长篇', exact: true }).click()
  await pages[0].getByRole('main').getByText('真实游客隔离作品1', { exact: true }).waitFor()
  assert.equal(await pages[0].getByRole('region', { name: '游客体验额度', exact: true }).count(), 0)
  assert.equal((await contexts[0].request.get(origin + '/api/v1/auth/session', { headers: { Authorization: 'Bearer ' + identities[0].token }, timeout: 10000 })).status(), 401)
  await contexts[0].addCookies([oldCookie])
  assert.equal((await contexts[0].request.post(origin + '/api/v1/auth/guest', { data: { restore_only: true }, timeout: 10000 })).status(), 401)
  const projects = await contexts[0].request.get(origin + '/api/v1/projects', { headers: { Authorization: 'Bearer ' + upgraded.token }, timeout: 10000 })
  assert.deepEqual((await projects.json()).map(project => project.id), [metadata.projects[0]])
  receipt.checks.push('real_invitation_upgrade_keeps_id_and_project_revokes_old_token_and_recovery')
  await pages[0].screenshot({ path: path.join(output, 'real-upgraded-project.png') })
  assert.deepEqual(receipt.pageErrors, [])
  receipt.passed = true
} catch (error) { receipt.error = String(error); throw error }
finally {
  clearTimeout(deadline)
  process.off('SIGTERM', onTerm); process.off('SIGINT', onInt)
  await finalize()
  if (!receipt.passed) process.exitCode = 1
}
