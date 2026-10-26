// Real HTTP proxy: no API responses are mocked. Infrastructure and seed are isolated externally.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright'

assert.ok(process.env.MYINK_REAL_METADATA, 'Set MYINK_REAL_METADATA to the isolated fixture metadata JSON')
const metadata = JSON.parse(fs.readFileSync(process.env.MYINK_REAL_METADATA, 'utf8'))
const upstream = new URL(process.env.MYINK_REAL_API ?? 'http://127.0.0.1:28100')
assert.ok(['127.0.0.1', 'localhost'].includes(upstream.hostname) && upstream.port === '28100', 'Only dedicated loopback test API port 28100 is permitted')
const web = fileURLToPath(new URL('..', import.meta.url))
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-vue-real-browser-'))
const vueDist = path.join(output, 'dist-vue')
const reactDist = path.join(output, 'dist-react')
fs.cpSync(path.join(web, 'dist-vue'), vueDist, { recursive: true })
fs.cpSync(path.join(web, 'dist'), reactDist, { recursive: true })
let dist = vueDist
const buildIdentity = root => {
  const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8')
  return { entry: html.match(/src="([^"]*\/assets\/index-[^"]+\.js)"/)?.[1] ?? null, indexSha256: createHash('sha256').update(html).digest('hex') }
}
const receipt = { kind: 'vue_real_isolated_api_browser', builds: { vue: buildIdentity(vueDist), react: buildIdentity(reactDist) }, checks: [], api: [], pageErrors: [], limits: ['Real API/PostgreSQL/Redis with isolated test fixtures', 'No model or production calls; generation worker/Caddy/TLS not exercised'], passed: false }
const types = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.woff2': 'font/woff2' }
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    const proxy = http.request(new URL(req.url, upstream), { method: req.method, headers: { ...req.headers, host: upstream.host } }, response => {
      receipt.api.push({ method: req.method, path: url.pathname, status: response.statusCode })
      res.writeHead(response.statusCode, response.headers); response.pipe(res)
    })
    proxy.on('error', error => { res.writeHead(502); res.end(error.message) })
    req.pipe(proxy); return
  }
  let file = path.resolve(dist, '.' + decodeURIComponent(url.pathname))
  if (!file.startsWith(dist + path.sep)) file = path.join(dist, 'index.html')
  if (!fs.existsSync(file) && url.pathname.startsWith('/assets/')) {
    const fallback = path.resolve(dist === vueDist ? reactDist : vueDist, '.' + url.pathname)
    if (fs.existsSync(fallback)) file = fallback
  }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html')
  res.writeHead(200, { 'Content-Type': types[path.extname(file)] ?? 'application/octet-stream', 'Cache-Control': 'no-store' })
  fs.createReadStream(file).pipe(res)
})
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
const origin = `http://127.0.0.1:${server.address().port}`
let browser
let page
try {
  browser = await chromium.launch({ headless: true })
  page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
  page.on('pageerror', error => receipt.pageErrors.push(error.message))
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  await page.goto(origin + '/login?mode=register')
  await page.getByLabel('用户名', { exact: true }).fill(metadata.registerUsername + Date.now())
  await page.getByLabel('密码', { exact: true }).fill(metadata.password)
  await page.getByLabel('确认密码', { exact: true }).fill(metadata.password)
  await page.getByLabel('邀请码', { exact: true }).fill(metadata.invitation)
  await page.getByRole('button', { name: '创建账号', exact: true }).click()
  await page.waitForURL('**/long')
  await page.getByText(/还没有长篇作品/).waitFor()
  receipt.checks.push('vue_real_invitation_registration_empty_account')
  await page.getByRole('button', { name: '登出', exact: true }).click()
  await page.getByText('未登录', { exact: true }).waitFor()
  receipt.checks.push('vue_real_logout')
  await page.goto(origin + '/login')
  await page.getByLabel('用户名', { exact: true }).fill(metadata.username)
  await page.getByLabel('密码', { exact: true }).fill(metadata.password)
  await page.getByRole('button', { name: '登录', exact: true }).click()
  await page.waitForURL('**/long')
  await page.getByRole('main').getByText('Vue真实隔离作品', { exact: true }).waitFor()
  receipt.checks.push('vue_real_login_and_account_switch_list')
  await page.goto(origin + `/projects/${metadata.projectId}`)
  await page.getByRole('button', { name: /第 1 章.*隔离雨夜/ }).click()
  const text = page.getByRole('textbox', { name: '章节正文' })
  await text.waitFor()
  assert.equal(await text.inputValue(), '真实接口第一次写入。')
  receipt.checks.push('vue_real_workspace_deep_link_and_chapter')
  await text.fill('Vue浏览器保存到真实隔离数据库。')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('已保存', { exact: true }).waitFor()
  await page.reload()
  await page.getByRole('button', { name: /第 1 章.*隔离雨夜/ }).click()
  assert.equal(await text.inputValue(), 'Vue浏览器保存到真实隔离数据库。')
  receipt.checks.push('vue_real_editor_save_persists_after_reload')
  await page.getByRole('button', { name: '历史版本', exact: true }).click()
  await page.getByRole('dialog', { name: '版本历史' }).getByText('v2', { exact: true }).waitFor()
  receipt.checks.push('vue_real_version_history')
  await page.screenshot({ path: path.join(output, 'real-workspace-history.png'), fullPage: true })
  await page.goto(origin + `/projects/${metadata.projectId}/settings#writing-resources`)
  await page.getByRole('heading', { name: /创作设置/ }).waitFor()
  await page.getByRole('button', { name: '移除本书选择 隔离文风', exact: true }).waitFor()
  receipt.checks.push('vue_real_settings_resource_snapshot')
  await page.goto(origin + '/environment')
  await page.getByRole('heading', { name: '高级设置', exact: true }).waitFor()
  assert.equal(await page.getByRole('alert').count(), 0)
  receipt.checks.push('vue_real_environment_contract')
  await page.goto(origin + '/styles')
  await page.getByRole('heading', { name: '文风库', exact: true }).waitFor()
  receipt.checks.push('vue_real_style_library_contract')
  await page.goto(origin + '/admin')
  await page.getByText('只有管理员可以打开控制台。', { exact: true }).waitFor()
  receipt.checks.push('vue_real_ordinary_account_admin_denied')
  await page.goto(origin + '/theme')
  await page.getByRole('button', { name: '新建自定义', exact: true }).click()
  await page.getByRole('textbox', { name: '名称', exact: true }).fill('真实往返配色')
  await page.getByRole('button', { name: '保存这套', exact: true }).click()
  await page.goto(origin + `/projects/${metadata.projectId}`)
  await page.getByRole('button', { name: /第 1 章.*隔离雨夜/ }).click()
  await text.fill('Vue到React再到Vue的同源未提交草稿。')
  dist = reactDist
  page.once('dialog', dialog => dialog.accept())
  await page.reload()
  await page.getByRole('button', { name: /第 1 章.*隔离雨夜/ }).click()
  assert.equal(await text.inputValue(), 'Vue到React再到Vue的同源未提交草稿。')
  assert.ok(await page.evaluate(() => JSON.stringify(localStorage).includes('真实往返配色')))
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('myink.session')).username), metadata.username)
  receipt.checks.push('same_origin_vue_to_react_session_draft_theme_rollback')
  dist = vueDist
  page.once('dialog', dialog => dialog.accept())
  await page.reload()
  await page.getByRole('button', { name: /第 1 章.*隔离雨夜/ }).click()
  assert.equal(await text.inputValue(), 'Vue到React再到Vue的同源未提交草稿。')
  assert.ok(await page.evaluate(() => JSON.stringify(localStorage).includes('真实往返配色')))
  receipt.checks.push('same_origin_react_to_vue_session_draft_theme_return')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('已保存', { exact: true }).waitFor()

  assert.deepEqual(receipt.pageErrors, [])
  assert.equal(receipt.api.filter(item => item.status >= 500).length, 0)
  receipt.passed = true
  console.log(JSON.stringify({ passed: true, checks: receipt.checks.length, output }, null, 2))
} catch (error) {
  receipt.error = String(error)
  if (page) { await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {}); fs.writeFileSync(path.join(output, 'failure.txt'), await page.locator('body').innerText().catch(() => '')) }
  throw error
} finally {
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2))
  await browser?.close()
  server.closeAllConnections()
  await new Promise(resolve => server.close(resolve))
}
