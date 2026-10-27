// Actual built Vue UI against an explicit, read-only loopback fixture whitelist.
import assert from 'node:assert/strict'
import { assertFixedRail } from './rail-layout-assertions.mjs'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createHash } from 'node:crypto'
import { finalizeBrowserReceipt } from './browser-receipt.mjs'
import { browserName, launchBrowser } from './browser-options.mjs'

const dist = path.resolve(process.env.MYINK_BROWSER_DIST ?? fileURLToPath(new URL('../dist-vue/', import.meta.url)))
assert.ok(fs.existsSync(path.join(dist, 'index.html')), 'Build Vue before running this test')
const outputIndex = process.argv.indexOf('--output')
const output = outputIndex < 0 ? fs.mkdtempSync(path.join(os.tmpdir(), 'myink-admin-feedback-')) : path.resolve(process.argv[outputIndex + 1])
if (outputIndex >= 0) fs.mkdirSync(output, { recursive: false })
const receipt = { kind: 'admin_feedback_synthetic_browser', browser: browserName, checks: [], requests: [], unknownApi: [], pageErrors: [], screenshots: [], limits: ['Synthetic read-only loopback fixtures; no production/backend/database/model calls', 'Desktop and mobile layout checks in the selected engine only'] }
const token = 'synthetic-admin-feedback-token'
const metrics = { run_count: 25, input_tokens: 100, output_tokens: 100, cost_est: 0.01, duration_ms: 1000 }
const user = { id: 'u', username: '测试作者', tier: 'vip', role: 'user', project_count: 50, chapter_count: 1, word_count: 1000, task_count: 1, metrics, task_averages: { avg_cost_per_task: 0.01, avg_duration_ms_per_task: 1000, avg_runs_per_task: 25 } }
const project = { id: 'p', user_id: 'u', username: user.username, title: '后台交互测试作品', genre: '悬疑', creation_status: 'legacy_ready', chapter_count: 1, word_count: 1000, task_count: 1, metrics }
const captured = data => ({ data, truncated: false, redacted: false, limits: { max_depth: 10, max_items: 80, max_text: 12000, max_bytes: 65536 } })
const chapter = { id: 'ch', project_id: 'p', chapter_seq: 1, title: '第一章', status: 'confirmed', word_count: 1000, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z' }
const run = id => ({ id, user_id: 'u', username: user.username, project_id: 'p', project_title: project.title, task_id: 't', node: 'short_write', role: 'writer', model_id: 'synthetic-model', input_tokens: 100, output_tokens: 100, cost_est: 0.01, duration_ms: 1000, cache_hit: false, degraded: false, retry_count: 0, created_at: '2026-10-27T00:00:00Z', updated_at: '2026-10-27T00:00:00Z' })
const collection = (items = []) => ({ items, total: items.length, limit: 25, truncated: false })
const pageOf = (items, offset = 0, total = items.length) => ({ items, offset, total, limit: 25 })
const resourceCards = ['简短规则', '包含较长标题的创作规则示例', '第三份规则'].map((name,i)=>({id:`rule-${i}`,name,kind:'writing_rule',source:'platform',status:'published',generation:1,current_version:1,body:{roles:{writer:i===0?'简短要求。':'人物通过有代价的行动推进情节，避免重复解释。'.repeat(12)}}}))
const fixtures = new Map([
  ['GET /api/v1/admin/writing-resources', () => ({items:resourceCards})],
  ['GET /api/v1/auth/session', () => ({ token, user_id: 'admin', username: '管理员', tier: 'vip', role: 'admin', expires_in: 3600 })],
  ['GET /api/v1/admin/users/u', () => user],
  ['GET /api/v1/admin/projects', url => pageOf(Array.from({ length: 25 }, (_, i) => ({ ...project, id: i === 24 ? 'p' : `p${i}`, title: i === 24 ? project.title : `列表作品 ${i + 1}` })), Number(url.searchParams.get('offset') ?? 0), 50)],
  ['GET /api/v1/admin/projects/p', () => project],
  ['GET /api/v1/admin/projects/p/chapters', () => pageOf([chapter])],
  ['GET /api/v1/admin/projects/p/chapters/ch', () => ({ ...chapter, version: 1, summary: '章节摘要', content: '章节全文验收内容。'.repeat(120) })],
  ['GET /api/v1/admin/projects/p/context', () => ({ project_id: 'p', settings: captured({ title: project.title }), outlines: collection(Array.from({ length: 20 }, (_, i) => captured({ title: `大纲 ${i + 1}`, content: '这是较长的作品上下文，用于验证纵向阅读布局。'.repeat(8) }))), events: collection(), facts: collection(), characters: collection(), foreshadows: collection(), threads: collection() })],
  ['GET /api/v1/admin/runs', () => pageOf(Array.from({ length: 25 }, (_, i) => run(i + 1)))],
  ['GET /api/v1/admin/runs/25', () => ({ ...run(25), detail: captured({ response: { content: '运行输出验收内容。'.repeat(150) } }), error: captured(null), detail_missing: false, prompt_missing: false })],
])
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1')
  if (url.pathname.startsWith('/api/')) {
    const key = `${req.method} ${url.pathname}`
    receipt.requests.push({ method: req.method, path: url.pathname, query: url.search })
    const fixture = fixtures.get(key)
    if (!fixture) { receipt.unknownApi.push(key); res.writeHead(500, { 'Content-Type': 'application/json' }); res.end(JSON.stringify({ error: 'unhandled_fixture_endpoint' })); return }
    if (req.headers.authorization !== `Bearer ${token}`) { res.writeHead(401); res.end('{}'); return }
    res.writeHead(200, { 'Content-Type': 'application/json' }); res.end(JSON.stringify(fixture(url))); return
  }
  let file
  try { file = path.resolve(dist, '.' + decodeURIComponent(url.pathname)) } catch { res.writeHead(400); res.end(); return }
  if (file !== dist && !file.startsWith(dist + path.sep)) { res.writeHead(403); res.end(); return }
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) {
    if (url.pathname.startsWith('/assets/')) { res.writeHead(404); res.end(); return }
    file = path.join(dist, 'index.html')
  }
  res.writeHead(200, { 'Content-Type': ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[path.extname(file)] ?? 'application/octet-stream' })
  fs.createReadStream(file).pipe(res)
})
let browser
try {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  const origin = `http://127.0.0.1:${server.address().port}`
  const probe = await fetch(origin + '/api/v1/__unknown_fixture_probe')
  assert.equal(probe.status, 500)
  assert.equal((await probe.json()).error, 'unhandled_fixture_endpoint')
  assert.equal(receipt.unknownApi.pop(), 'GET /api/v1/__unknown_fixture_probe')
  receipt.requests.pop()
  receipt.checks.push('fixture_rejects_unknown_API_before_auth')
  browser = await launchBrowser()
  receipt.browserVersion = browser.version()
  receipt.indexSha256 = createHash('sha256').update(fs.readFileSync(path.join(dist, 'index.html'))).digest('hex')
  for (const [name, viewport] of [['desktop', { width: 1440, height: 960 }], ['mobile', { width: 390, height: 844 }]]) {
    const page = await browser.newPage({ viewport })
    page.setDefaultTimeout(10000)
    page.on('pageerror', error => receipt.pageErrors.push(error.message))
    await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
    await page.addInitScript(({ token }) => localStorage.setItem('myink.session', JSON.stringify({ token, userId: 'admin', username: '管理员', tier: 'vip', role: 'admin', roleVerified: false, expiresAt: Date.now() + 3600000 })), { token })
    await page.goto(origin + '/admin/writing-resources')
    await page.getByRole('button',{name:'编辑 简短规则',exact:true}).waitFor()
    const cardSizes=await page.locator('button[class*=resourceCard]').evaluateAll(cards=>cards.map(card=>({width:card.getBoundingClientRect().width,height:card.getBoundingClientRect().height})))
    assert.equal(cardSizes.length,3)
    assert.ok(cardSizes.every(size=>Math.abs(size.height-cardSizes[0].height)<1&&Math.abs(size.width-cardSizes[0].width)<1),'Resource cards must have equal dimensions across short and long content')
    await page.screenshot({path:path.join(output,`${name}-equal-resource-cards.png`)})
    receipt.checks.push(`${name}:resource_cards_equal_dimensions`)
    await page.goto(origin + '/admin/users/u')
    await page.getByRole('heading', { name: '测试作者 · 账号详情' }).waitFor()
    assert.equal(await page.getByRole('table').count(), 0)
    assert.equal(await page.getByRole('navigation', { name: '账号关联记录' }).count(), 0)
    assert.equal(await page.getByText('管理导航', { exact: true }).count(), 0)
    await page.getByRole('link', { name: '作品', exact: true }).click()
    await page.getByRole('textbox', { name: '用户 ID', exact: true }).fill('u')
    await page.getByRole('button', { name: '筛选', exact: true }).click()
    await page.getByRole('button', { name: `查看《${project.title}》` }).waitFor()
    assert.equal(new URL(page.url()).searchParams.get('userId'), 'u')
    assert.equal(await page.getByRole('textbox', { name: '用户 ID', exact: true }).inputValue(), 'u')
    await page.getByRole('button', { name: '下一页', exact: true }).click()
    await page.waitForURL(url => url.searchParams.get('offset') === '25')
    const listURL = page.url()
    await page.getByRole('table', { name: '测试作者的作品' }).waitFor()
    assert.equal(await page.getByRole('table', { name: '测试作者的作品' }).count(), 1)
    await assertFixedRail(page, viewport)
    const navShot = path.join(output, `${name}-navigation.png`)
    await page.screenshot({ path: navShot, fullPage: true }); receipt.screenshots.push(navShot)

    await page.getByRole('button', { name: `查看《${project.title}》` }).click()
    await page.getByRole('heading', { name: '作品详情', exact: true }).waitFor()
    const sections = page.locator('[class*="projectSections"] > section')
    await sections.nth(1).getByText('大纲 20', { exact: true }).waitFor()
    const first = await sections.nth(0).boundingBox(), second = await sections.nth(1).boundingBox()
    assert.ok(second.y >= first.y + first.height, 'Project context must follow the chapter list vertically')
    await page.screenshot({ path: path.join(output, `${name}-project.png`) })
    receipt.screenshots.push(`${name}-project.png`)
    await page.getByRole('button', { name: '查看第一章全文' }).click()
    await page.getByRole('heading', { name: '章节全文', exact: true }).waitFor()
    await page.getByText('章节全文验收内容。'.repeat(120), { exact: true }).waitFor()
    assert.equal(await page.getByRole('heading', { name: '受限上下文快照' }).count(), 0)
    await page.getByRole('main').locator('..').evaluate(el => { el.scrollTop = el.scrollHeight })
    await page.goBack()
    await page.getByRole('button', { name: '查看第一章全文' }).click()
    await page.getByRole('heading', { name: '章节全文', exact: true }).waitFor()
    assert.equal(await page.getByRole('main').locator('..').evaluate(el => el.scrollTop), 0, 'Deliberately reopening a chapter must start at its heading')
    receipt.checks.push(`${name}: repeated_chapter_open_starts_at_top`)

    await page.getByRole('link', { name: '返回', exact: true }).click()
    await page.getByRole('heading', { name: '作品详情', exact: true }).waitFor()
    await page.getByRole('link', { name: '返回', exact: true }).click()
    await page.waitForURL(listURL)
    await page.getByRole('button', { name: `查看《${project.title}》` }).waitFor()
    receipt.checks.push(`${name}: account_summary_related_filter_project_chapter_return_context`, `${name}: project_single_column`)
    await page.goto(origin + '/admin?tab=runs&userId=u')
    const trigger = page.getByRole('button', { name: '查看节点 short_write #25' })
    await trigger.click()
    const dialog = page.getByRole('dialog', { name: '运行详情 #25' })
    await dialog.waitFor()
    await dialog.getByText('运行输出验收内容。'.repeat(150), { exact: true }).waitFor()
    const bounds = await dialog.boundingBox()
    assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= viewport.height + 1, 'Dialog must fit the viewport')
    assert.equal(await dialog.evaluate(el => el.matches(':modal')), true)
    await dialog.evaluate(el => { el.scrollTop = el.scrollHeight })
    const close = dialog.getByRole('button', { name: '关闭', exact: true })
    const closeBox = await close.boundingBox()
    assert.ok(closeBox.y >= 0 && closeBox.y + closeBox.height <= viewport.height, 'Close control must remain visible after scrolling')
    await page.screenshot({ path: path.join(output, `${name}-run-dialog.png`) })
    receipt.screenshots.push(`${name}-run-dialog.png`)
    await close.click()
    await dialog.waitFor({ state: 'detached' })
    assert.equal(await trigger.evaluate(el => el === document.activeElement), true)
    await trigger.click()
    await dialog.waitFor()
    await page.keyboard.press('Escape')
    await dialog.waitFor({ state: 'detached' })
    receipt.checks.push(`${name}: run_modal_visible_close_sticky_focus_restore_escape`)
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), 'Page must not overflow horizontally')
    await page.goto(origin + '/admin/projects/p/chapters/ch')
    await page.getByRole('heading', { name: '章节全文', exact: true }).waitFor()
    assert.equal(await page.getByRole('link', { name: '返回', exact: true }).getAttribute('href'), '/admin/projects/p')
    receipt.checks.push(`${name}: chapter_direct_link`)
    await page.close()
  }
  assert.deepEqual(receipt.unknownApi, [])
  assert.deepEqual(receipt.pageErrors, [])
  receipt.passed = true
} catch (error) {
  receipt.passed = false
  receipt.error = error instanceof Error ? error.stack ?? error.message : String(error)
  throw error
} finally {
  await finalizeBrowserReceipt(receipt, output, [
    () => browser?.close(),
    () => { server.closeAllConnections(); return new Promise((resolve, reject) => server.close(error => error ? reject(error) : resolve())) },
  ])
  if (!receipt.passed) process.exitCode = 1
  console.log(JSON.stringify({ result: receipt.passed ? 'passed' : 'failed', checks: receipt.checks, output }, null, 2))
}
