// Real Vue build + explicit loopback API fixtures. No production/model/database calls.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { browserName, launchBrowser } from './browser-options.mjs'
import { createHash } from 'node:crypto'

const web = fileURLToPath(new URL('..', import.meta.url))
const dist = path.join(web, 'dist-vue')
assert.ok(fs.existsSync(path.join(dist, 'index.html')), 'Run npm run build:vue first')
const outputArg = process.argv.indexOf('--output')
const out = outputArg < 0 ? fs.mkdtempSync(path.join(os.tmpdir(), 'myink-vue-browser-')) : path.resolve(process.argv[outputArg + 1])
if (outputArg >= 0) fs.mkdirSync(out, { recursive: false })
const receipt = { kind: 'vue_synthetic_api_browser', browser: browserName, platform: process.platform, contextMode: 'temporary_persistent', checks: [], requests: [], pageErrors: [], unknownApi: [], limits: ['Synthetic loopback API only', 'No real backend, queue, database or model calls', 'Only explicitly listed browser flows are covered; renewal timing tested separately with fake timers'] }
const books = [
  { id: 'long-ready', title: '长篇测试作品', genre: '现实', current_chapter: 2, target_words: 800, form: 'long', creation_status: 'ready' },
  { id: 'short-ready', title: '短篇测试作品', genre: '悬疑', current_chapter: 1, target_words: 1000, form: 'short', creation_status: 'ready' },
  { id: 'long-draft', title: '长篇测试草稿', genre: '现实', current_chapter: 0, target_words: 800, form: 'long', creation_status: 'draft' },
  { id: 'short-draft', title: '短篇测试草稿', genre: '悬疑', current_chapter: 0, target_words: 1000, form: 'short', creation_status: 'draft' },
]
const token = 'synthetic-vue-browser-token'
const auth = { token, user_id: 'synthetic-user', username: 'browser-tester', tier: 'pro', role: 'user', expires_in: 3600 }
const knownRequests = new Set([
  'POST /api/v1/auth/token', 'POST /api/v1/auth/register', 'POST /api/v1/auth/mfa/verify',
  'GET /api/v1/short/creation', 'GET /api/v1/style-library', 'GET /api/v1/admin/overview', 'GET /api/v1/admin/trends',
  'GET /api/v1/environment', 'GET /api/v1/auth/session', 'POST /api/v1/auth/logout', 'GET /api/v1/projects', 'DELETE /api/v1/projects/long-ready',
])
let identity = { ...auth }
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    receipt.requests.push({ path: url.pathname, method: req.method })
    if (!knownRequests.has(`${req.method} ${url.pathname}`)) {
      receipt.unknownApi.push(url.pathname)
      res.writeHead(500, { 'Content-Type': 'application/json' })
      res.end(JSON.stringify({ error: 'unhandled_fixture_endpoint' }))
      return
    }
    let body
    let status = 200
    const publicAuth = ['/api/v1/auth/token', '/api/v1/auth/register', '/api/v1/auth/mfa/verify'].includes(url.pathname)
    if (publicAuth && req.method === 'POST') {
      let raw = ''
      for await (const chunk of req) { raw += chunk; if (raw.length > 16384) break }
      let input
      try { input = JSON.parse(raw) } catch { res.writeHead(400); res.end('{}'); return }
      if (url.pathname === '/api/v1/auth/token') {
        if (input.password !== 'browser-password1') { status = 401; body = { error: 'INVALID_CREDENTIALS' } }
        else if (input.username === 'root') body = { mfa_required: true, mfa_token: 'synthetic-mfa-challenge', expires_in: 300 }
        else { identity = { ...auth, username: 'browser-tester' }; body = identity }
      } else if (url.pathname === '/api/v1/auth/register') {
        if (input.invitation_code !== 'invite-browser') { status = 400; body = { error: 'INVITATION_INVALID' } }
        else { identity = { ...auth, username: 'registered-user' }; body = identity }
      } else if (input.mfa_token === 'synthetic-mfa-challenge' && input.code === '123456') {
        identity = { ...auth, username: 'root', role: 'admin' }; body = identity
      } else { status = 401; body = { error: 'MFA_INVALID' } }
    } else if (req.headers.authorization !== `Bearer ${token}`) { status = 401; body = { error: 'unauthorized' } }
    else if (url.pathname === '/api/v1/auth/session' && req.method === 'GET') body = identity
    else if (url.pathname === '/api/v1/projects' && req.method === 'GET') body = books
    else if (url.pathname === '/api/v1/environment') body = { model_routes: {}, model_connections: [], thinking_enabled: false, rankings: { enabled: true, timeout: 10, limit: 10 } }
    else if (url.pathname === '/api/v1/style-library') body = { items: [] }
    else if (url.pathname === '/api/v1/short/creation') body = { session: { id: 's1', status: 'active', card: {}, style_item_id: null, style_name: null, book_id: null }, messages: [{ id: 1, role: 'assistant', content: '想写个什么样的短篇？', card: null, model_id: null, cost_est: 0, error: null, created_at: '2026-01-01T00:00:00Z' }], sessions: [], ready: false }
    else if (url.pathname === '/api/v1/admin/overview') body = { user_count: 1, project_count: 4, chapter_count: 3, task_count: 0, metrics: { run_count: 0, input_tokens: 0, output_tokens: 0, cost_est: 0, duration_ms: 0 }, task_status_counts: {} }
    else if (url.pathname === '/api/v1/admin/trends') body = { start_date: url.searchParams.get('start_date'), end_date: url.searchParams.get('end_date'), timezone: 'UTC', items: [] }
    else if (url.pathname === '/api/v1/projects/long-ready' && req.method === 'DELETE') { status = 409; body = { error: 'active_task' } }
    else if (url.pathname === '/api/v1/auth/logout' && req.method === 'POST') body = { ok: true }
    else { status = 500; body = {}; receipt.unknownApi.push(url.pathname) }
    res.writeHead(status, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(body)); return
  }
  let file
  try { file = path.resolve(dist, '.' + decodeURIComponent(url.pathname)) } catch { res.writeHead(400); res.end(); return }
  if (file !== dist && !file.startsWith(dist + path.sep)) { res.writeHead(403); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    if (url.pathname.startsWith('/assets/')) { res.writeHead(404); res.end(); return }
    file = path.join(dist, 'index.html')
  }
  const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' }
  res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})
let browser
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  // Probe the fixture before any UI runs: an unknown unauthenticated API must
  // fail the whitelist rather than disappear behind a generic 401.
  const probePath = '/api/v1/__unknown_fixture_probe'
  const probe = await fetch(origin + probePath)
  assert.equal(probe.status, 500)
  assert.deepEqual(receipt.unknownApi, [probePath])
  assert.deepEqual(receipt.requests, [{ path: probePath, method: 'GET' }])
  receipt.fixtureProbes = [{ path: probePath, status: probe.status, rejected: true }]
  receipt.unknownApi.pop(); receipt.requests.pop()
  receipt.checks.push('fixture_rejects_unknown_api_before_auth')
  browser = await launchBrowser()
  receipt.browserVersion = browser.version()
  receipt.indexSha256 = createHash('sha256').update(fs.readFileSync(path.join(dist, 'index.html'))).digest('hex')
  const anonymous = await browser.newPage()
  await anonymous.goto(origin + '/long')
  await anonymous.getByRole('heading', { name: '长篇', exact: true }).waitFor()
  await anonymous.getByRole('link', { name: '新建长篇' }).click()
  await anonymous.getByRole('dialog').waitFor()
  await anonymous.getByRole('button', { name: '关闭', exact: true }).click()
  assert.equal(receipt.requests.length, 0)
  receipt.checks.push('anonymous_sends_no_protected_requests')
  await anonymous.close()

  const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  page.on('pageerror', error => receipt.pageErrors.push(error.message))
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  await page.goto(origin + '/login')
  await page.getByLabel('用户名', { exact: true }).fill('Browser_tester')
  await page.getByLabel('密码', { exact: true }).fill('wrong-password')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('alert').getByText('用户名或密码不正确').waitFor()
  assert.equal(receipt.requests.filter(r => r.path === '/api/v1/projects').length, 0)
  await page.getByLabel('密码', { exact: true }).fill('browser-password1')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/long')
  receipt.checks.push('public_login_page', 'invalid_password_keeps_guest', 'password_login_uses_real_session_store')
  const main = page.getByRole('main')
  await main.getByText('长篇测试作品', { exact: true }).waitFor()
  assert.equal(await main.getByText('短篇测试作品', { exact: true }).count(), 0)
  assert.equal(await page.getByRole('navigation', { name: '作品列表' }).getByText('长篇测试草稿').count(), 0)
  assert.equal(await page.getByRole('region', { name: '待完成作品' }).getByRole('link').getAttribute('href'), '/long/new?draft=long-draft')
  receipt.checks.push('deep_link_loads_vue', 'server_verified_session', 'long_form_and_draft_links')

  await page.getByRole('navigation', { name: '作品分区' }).getByRole('link', { name: '短篇', exact: true }).click()
  await main.getByText('短篇测试作品', { exact: true }).waitFor()
  assert.equal(await main.getByText('长篇测试作品', { exact: true }).count(), 0)
  assert.equal(await page.getByRole('region', { name: '待完成作品' }).getByRole('link').getAttribute('href'), '/projects/short-draft')
  await page.reload(); await main.getByText('短篇测试作品', { exact: true }).waitFor()
  receipt.checks.push('short_form_navigation', 'short_deep_link_refresh')
  await page.getByRole('link', { name: '新建短篇', exact: true }).click()
  await page.getByRole('heading', { name: '新建短篇', exact: true }).waitFor()
  await page.getByText('想写个什么样的短篇？', { exact: true }).waitFor()
  await page.reload(); await page.getByRole('heading', { name: '新建短篇', exact: true }).waitFor()
  receipt.checks.push('short_creation_and_refresh')
  await page.goto(origin + '/theme')
  await page.getByRole('button', { name: '新建自定义', exact: true }).click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('浏览器配色')
  await page.getByLabel('上传背景', { exact: true }).setInputFiles({ name: 'wallpaper.png', mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=', 'base64') })
  await page.getByRole('button', { name: '保存这套', exact: true }).click()
  await page.waitForFunction(() => JSON.stringify(localStorage).includes('浏览器配色'))
  await page.screenshot({ path: path.join(out, 'vue-theme.png'), fullPage: true })
  await page.waitForFunction(() => document.documentElement.style.getPropertyValue('--canvas-image').includes('blob:'))
  await page.reload()
  await page.waitForFunction(() => document.documentElement.style.getPropertyValue('--canvas-image').includes('blob:'))
  receipt.checks.push('theme_custom_preset_persists', 'indexeddb_wallpaper_survives_refresh')
  await page.goto(origin + '/styles')
  await page.getByRole('heading', { name: '文风库', exact: true }).waitFor()
  await page.getByText('尚未保存个人文风', { exact: true }).waitFor()
  receipt.checks.push('style_library_loads')
  await page.goto(origin + '/account')
  await page.getByLabel('当前密码', { exact: true }).fill('browser-draft-password1')
  await page.getByLabel('新密码', { exact: true }).fill('new-draft-password2')
  let validation = page.waitForResponse(response => response.url().endsWith('/api/v1/auth/session'))
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' })))
  await validation; await page.waitForLoadState('networkidle')
  assert.equal(await page.getByLabel('当前密码', { exact: true }).inputValue(), 'browser-draft-password1')
  assert.equal(await page.getByLabel('新密码', { exact: true }).inputValue(), 'new-draft-password2')
  receipt.checks.push('account_edit_survives_same_owner_revalidation')
  // Explicitly discard these fixture-only password edits when leaving.
  const discardEdits = async action => {
    const accept = dialog => { assert.equal(dialog.type(), 'beforeunload'); return dialog.accept() }
    page.on('dialog', accept)
    try { await action() } finally { page.off('dialog', accept) }
  }
  await discardEdits(() => page.goto(origin + '/environment'))
  await page.getByRole('button', { name: '展开高级设置', exact: true }).click()
  await page.getByLabel('扫榜超时', { exact: true }).fill('8')
  validation = page.waitForResponse(response => response.url().endsWith('/api/v1/auth/session'))
  await page.evaluate(() => window.dispatchEvent(new StorageEvent('storage', { key: 'myink.session' })))
  await validation; await page.waitForLoadState('networkidle')
  assert.equal(await page.getByLabel('扫榜超时', { exact: true }).inputValue(), '8')
  receipt.checks.push('environment_edit_survives_same_owner_revalidation')



  await discardEdits(() => page.goto(origin + '/long')); await main.getByText('长篇测试作品', { exact: true }).waitFor()
  page.once('dialog', dialog => dialog.dismiss())
  await page.getByRole('button', { name: '删除《长篇测试作品》' }).click()
  assert.equal(receipt.requests.filter(r => r.method === 'DELETE').length, 0)
  page.once('dialog', dialog => dialog.accept())
  await page.getByRole('button', { name: '删除《长篇测试作品》' }).click()
  await page.getByRole('alert').getByText(/进行中任务/).waitFor()
  assert.equal(await main.getByText('长篇测试作品', { exact: true }).count(), 1)
  receipt.checks.push('delete_cancel_has_no_request', 'delete_409_preserves_book')
  await page.setViewportSize({ width: 768, height: 960 })
  await page.getByRole('link', { name: '短篇', exact: true }).click()
  await main.getByRole('heading', { name: '短篇', exact: true }).waitFor()
  await page.getByRole('link', { name: '长篇', exact: true }).click()
  await main.getByText('长篇测试作品', { exact: true }).waitFor()
  assert.ok(await page.locator('body').evaluate(el => el.scrollWidth <= innerWidth + 1))
  await page.screenshot({ path: path.join(out, 'vue-list-768.png'), fullPage: true })
  receipt.checks.push('768px_navigation_and_no_horizontal_overflow')
  await page.setViewportSize({ width: 390, height: 844 })
  const width = await page.locator('body').evaluate(el => ({ scroll: el.scrollWidth, viewport: window.innerWidth }))
  assert.ok(width.scroll <= width.viewport + 1, JSON.stringify(width))
  await page.screenshot({ path: path.join(out, 'vue-list-390.png'), fullPage: true })
  receipt.checks.push('390px_no_horizontal_overflow')
  await page.getByRole('button', { name: '登出', exact: true }).click()
  await page.getByText('未登录', { exact: true }).waitFor()
  assert.equal(await page.evaluate(() => localStorage.getItem('myink.session')), null)
  receipt.checks.push('logout_clears_session')

  await page.goto(origin + '/login?mode=register')
  await page.getByLabel('用户名', { exact: true }).fill('Registered_user')
  await page.getByLabel('密码', { exact: true }).fill('browser-password1')
  await page.getByLabel('确认密码', { exact: true }).fill('different-password2')
  await page.getByLabel('邀请码', { exact: true }).fill('  invite-browser  ')
  const registrationsBefore = receipt.requests.filter(r => r.path === '/api/v1/auth/register').length
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.getByRole('alert').getByText('两次输入的密码不一致').waitFor()
  assert.equal(receipt.requests.filter(r => r.path === '/api/v1/auth/register').length, registrationsBefore)
  await page.getByLabel('确认密码', { exact: true }).fill('browser-password1')
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.waitForURL('**/long')
  await page.getByRole('button', { name: '登出', exact: true }).click()
  await page.getByText('未登录', { exact: true }).waitFor()
  receipt.checks.push('registration_validation_before_request', 'invitation_registration')

  await page.goto(origin + '/login')
  await page.getByLabel('用户名', { exact: true }).fill('root')
  await page.getByLabel('密码', { exact: true }).fill('browser-password1')
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.getByRole('heading', { name: '输入验证码' }).waitFor()
  assert.equal(await page.evaluate(() => localStorage.getItem('myink.session')), null)
  await page.getByLabel('验证码', { exact: true }).fill('000000')
  await page.getByRole('button', { name: '验证', exact: true }).click()
  await page.getByRole('alert').getByText('验证码不正确，请重新输入').waitFor()
  await page.getByLabel('验证码', { exact: true }).fill('123456')
  await page.getByRole('button', { name: '验证', exact: true }).click()
  await page.waitForURL('**/admin')
  await page.getByRole('heading', { name: '概览', exact: true }).waitFor()
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('myink.session')).role), 'admin')
  const storage = await page.evaluate(() => JSON.stringify(localStorage))
  assert.ok(!storage.includes('browser-password1') && !storage.includes('invite-browser') && !storage.includes('synthetic-mfa-challenge'))
  await page.reload(); await page.getByRole('heading', { name: '概览', exact: true }).waitFor()
  receipt.checks.push('mfa_challenge_is_not_a_session', 'mfa_error_stays_in_step', 'mfa_success_routes_verified_admin', 'credentials_and_challenge_not_persisted', 'authenticated_admin_refresh')
  assert.deepEqual(receipt.pageErrors, []); assert.deepEqual(receipt.unknownApi, [])
  receipt.passed = true
  console.log(JSON.stringify({ result: 'passed', checks: receipt.checks, output: out }, null, 2))
} catch (error) {
  receipt.error = String(error)
  throw error
} finally {
  fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify(receipt, null, 2))
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
