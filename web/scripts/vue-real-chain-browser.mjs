// Full-chain browser: actual Caddy TLS/API/AMQP worker/local-model HTTP, no API mocking.
import assert from 'node:assert/strict';
import { createHash, createHmac } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';
import { finalizeBrowserReceipt } from './browser-receipt.mjs';
const metadata = JSON.parse(fs.readFileSync(process.env.MYINK_CHAIN_METADATA ?? '/tmp/myink-vue-chain-metadata-0025.json', 'utf8'));
const site = process.env.MYINK_CHAIN_SITE ?? '/tmp/myink-vue-chain-site-0025';
assert.ok(site.startsWith('/tmp/') || site.startsWith('/private/tmp/'));
const origin = 'https://localhost:28443';
const runTag = Date.now().toString();
const draftText = '实际队列活动任务期间，Vue刷新保留的草稿。' + runTag;
const themeName = '活动任务往返主题' + runTag;
const goalText = '浏览器核对实际HTTP计划' + runTag;
assert.ok(metadata.admin.username && /^[A-Z2-7]+$/.test(metadata.admin.mfaSecret));
const web = fileURLToPath(new URL('..', import.meta.url));
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-vue-chain-browser-'));
const identity = root => { const html = fs.readFileSync(path.join(root, 'index.html'), 'utf8'); return { entry: html.match(/src="([^\"]*\/assets\/index-[^\"]+\.js)"/)?.[1], sha256: createHash('sha256').update(html).digest('hex') }; };
const vue = path.join(output, 'vue');
fs.cpSync(path.join(web, 'dist-vue'), vue, { recursive: true });
fs.mkdirSync(site, { recursive: true });
fs.cpSync(vue, site, { recursive: true });
const receipt = { kind: 'actual_tls_full_queue_worker_vue_browser', builds: { vue: identity(vue) }, checks: [], requests: [], httpFailures: [], pageErrors: [], passed: false };
let browser, page;
const check = name => { receipt.checks.push(name); console.log(name); };
function totp(secret, now = Date.now()) { let bits = ''; const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'; for (const char of secret.replace(/=+$/, ''))
    bits += alphabet.indexOf(char).toString(2).padStart(5, '0'); const key = Buffer.from((bits.match(/.{8}/g) ?? []).map(b => parseInt(b, 2))); const counter = Buffer.alloc(8); counter.writeBigUInt64BE(BigInt(Math.floor(now / 30000))); const hmac = createHmac('sha1', key).update(counter).digest(); const offset = hmac.at(-1) & 15; return ((hmac.readUInt32BE(offset) & 0x7fffffff) % 1000000).toString().padStart(6, '0'); }
assert.equal(totp('GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ', 59000), '287082');
async function api(method, url, body) { return page.evaluate(async ({ method, url, body }) => { const token = JSON.parse(localStorage.getItem('myink.session')).token; const response = await fetch('/api/v1' + url, { method, headers: { Authorization: 'Bearer ' + token, 'Content-Type': 'application/json' }, body: body === undefined ? undefined : JSON.stringify(body) }); return { status: response.status, body: await response.json() }; }, { method, url, body }); }
async function waitTask(tid, states, ms = 120000) { const start = Date.now(); let last; while (Date.now() - start < ms) {
    last = await api('GET', '/tasks/' + tid);
    if (last.status === 200 && states.includes(last.body.status))
        return last.body;
    if (last.status === 200 && last.body.status === 'failed')
        throw new Error('real worker failed: ' + last.body.error);
    await new Promise(resolve => setTimeout(resolve, 300));
} throw new Error('worker timeout ' + JSON.stringify(last)); }
async function reload() { page.once('dialog', dialog => dialog.accept()); await page.reload(); }
async function openSide() { const dock = page.getByRole('button', { name: '生成与校验', exact: true }); if (await dock.count())
    await dock.click(); }
try {
    assert.ok(process.env.MYINK_CHAIN_SPKI, 'Provide the dedicated local TLS certificate SPKI pin');
    browser = await chromium.launch({ headless: true, args: ['--disable-quic', '--ignore-certificate-errors-spki-list=' + process.env.MYINK_CHAIN_SPKI] });
    const context = await browser.newContext({ viewport: { width: 1600, height: 1050 } });
    page = await context.newPage();
    page.setDefaultNavigationTimeout(90000);
    page.on('pageerror', error => receipt.pageErrors.push(error.message));
    page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/api/'))
        receipt.requests.push({ method: request.method(), path: url.pathname }); });
    page.on('response', response => { const url = new URL(response.url()); if (url.pathname.startsWith('/api/') && response.status() >= 400)
        receipt.httpFailures.push({ path: url.pathname, status: response.status() }); });
    await page.route('**/*', route => { const url = route.request().url(); return url.startsWith(origin) || url.startsWith('blob:') ? route.continue() : route.abort(); });
    await page.goto(origin + '/login');
    assert.deepEqual(await page.evaluate(() => JSON.parse(document.querySelector('meta[name=myink-release]').content)), JSON.parse(fs.readFileSync(path.join(vue, 'release.json'), 'utf8')));
    await page.getByLabel('用户名', { exact: true }).fill(metadata.user.username);
    await page.getByLabel('密码', { exact: true }).fill(metadata.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL('**/long');
    check('vue_login_through_actual_local_ca_tls');
    const staleTasks = (await api('GET', '/projects/' + metadata.longProjectId + '/tasks')).body;
    for (const task of staleTasks.filter(t => ['queued', 'running', 'awaiting_plan', 'awaiting_review', 'paused'].includes(t.status))) {
        const cancelled = await api('POST', '/tasks/' + task.task_id + '/cancel');
        assert.ok([200, 409].includes(cancelled.status));
    }
    await page.goto(origin + '/theme');
    await page.getByRole('button', { name: '新建自定义', exact: true }).click();
    await page.getByRole('textbox', { name: '名称', exact: true }).fill(themeName);
    await page.getByRole('button', { name: '保存这套', exact: true }).click();
    await page.goto(origin + '/projects/' + metadata.longProjectId);
    await page.getByRole('button', { name: /第 1 章/ }).click();
    const text = page.getByRole('textbox', { name: '章节正文' });
    await text.fill(draftText);
    const chapters = (await api('GET', '/projects/' + metadata.longProjectId + '/chapters')).body;
    const tail = chapters.reduce((a, b) => a.chapter_seq > b.chapter_seq ? a : b);
    const reuse = (tail.word_count ?? 0) === 0 && ['planning', 'writing', 'failed', 'cancelled'].includes(tail.status);
    const next = reuse ? tail.chapter_seq : tail.chapter_seq + 1;
    await openSide();
    await page.getByRole('button', { name: '手动确认 Plan', exact: true }).click();
    const [enqueue] = await Promise.all([page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/generate') && response.status() === 202, { timeout: 90000 }), page.getByRole('button', { name: new RegExp(`写下一章（第 ${next} 章）|继续生成第 ${next} 章`) }).click()]);
    const task = await enqueue.json();
    const tid = task.task_id;
    receipt.longTaskId = tid;
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).waitFor({ timeout: 90000 });
    check('vue_actual_queue_manual_plan');
    const generatedBefore = receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/generate')).length;
    await reload();
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).waitFor({ timeout: 90000 });
    assert.ok(await page.evaluate(expected => JSON.stringify(sessionStorage).includes(expected), draftText));
    assert.ok(await page.evaluate(expected => JSON.stringify(localStorage).includes(expected), themeName));
    check('active_task_vue_reload_preserves_session_draft_theme');
    await reload();
    assert.ok(await page.evaluate(expected => JSON.stringify(sessionStorage).includes(expected), draftText));
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).waitFor({ timeout: 90000 });
    assert.equal(receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/generate')).length, generatedBefore);
    check('active_task_vue_repeated_reload_without_duplicate_enqueue');
    await page.getByLabel(/本章目标/).fill(goalText);
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).click();
    await page.getByText('实时写作', { exact: true }).first().waitFor({ timeout: 60000 });
    const finished = await waitTask(tid, ['done']);
    assert.ok(finished.payload.approved_plan.goals.includes(goalText));
    check('vue_plan_edit_confirm_actual_worker_stream_to_done');
    await page.getByRole('button', { name: new RegExp(`第 ${next} 章.*已确认`) }).waitFor({ timeout: 60000 });
    await page.getByRole('button', { name: /第 1 章/ }).click();
    assert.equal(await text.inputValue(), draftText);
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByText('已保存', { exact: true }).waitFor();
    const savedChapter = await api('GET', `/projects/${metadata.longProjectId}/chapters/${chapters.find(c => c.chapter_seq === 1).id}`);
    assert.equal(savedChapter.status, 200);
    assert.equal(savedChapter.body.content, draftText);
    check('vue_preserved_draft_saved_to_actual_database');
    // Create a short story through the actual chat/card API, choose resources first, then manual start.
    await page.goto(origin + '/short/new');
    await page.getByRole('button', { name: '新建会话', exact: true }).click();
    await page.getByRole('textbox', { name: '对助手说', exact: true }).fill('写一个两章的渡口故事，每章一千字');
    await page.getByRole('button', { name: '发送', exact: true }).click();
    await page.getByRole('button', { name: '开始建书', exact: true }).click();
    await page.getByLabel('暂定名', { exact: true }).fill('浏览器全链短篇' + Date.now());
    const shortPostsBefore = receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/short/generate')).length;
    await page.getByRole('button', { name: '确认方案，先选写作资源', exact: true }).click();
    await page.waitForURL(/\/projects\/[^/]+\/settings/, { timeout: 90000 });
    const shortId = new URL(page.url()).pathname.split('/')[2];
    receipt.shortProjectId = shortId;
    const [selectionResponse] = await Promise.all([page.waitForResponse(response => response.request().method() === 'PUT' && new URL(response.url()).pathname === `/api/v1/projects/${shortId}/writing-resources` && response.status() === 200, { timeout: 90000 }), page.getByRole('button', { name: '保存本书资源选择', exact: true }).click()]);
    assert.equal((await selectionResponse.json()).configured, true);
    await page.getByText('资源快照已保存，后续生成使用此版本。', { exact: true }).waitFor();
    await page.getByRole('link', { name: '选好后返回工作台开写', exact: true }).click();
    await page.getByRole('button', { name: '开始写', exact: true }).waitFor();
    assert.equal(receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/short/generate')).length, shortPostsBefore);
    check('vue_short_resources_first_requires_manual_start');
    const [shortEnqueue] = await Promise.all([page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/short/generate') && response.status() === 202, { timeout: 90000 }), page.getByRole('button', { name: '开始写', exact: true }).click()]);
    const shortTask = await shortEnqueue.json();
    await reload();
    await waitTask(shortTask.task_id, ['done'], 180000);
    await page.getByRole('region', { name: '整篇检查摘要', exact: true }).waitFor({ timeout: 60000 });
    assert.equal(receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/short/generate')).length, shortPostsBefore + 1);
    const shortChapters = (await api('GET', '/projects/' + shortId + '/chapters')).body;
    assert.equal(shortChapters.length, 2);
    check('vue_short_actual_worker_reload_recovery_no_duplicate_post');
    // Multipart submission and authenticated blob attachment through actual API/file storage.
    const attachmentName = 'browser-chain-' + Date.now() + '.png';
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(origin + '/long');
    await page.locator('aside[data-guest-exempt]').getByRole('button', { name: '反馈', exact: true }).click();
    const feedback = page.getByRole('dialog', { name: '问题反馈' });
    await feedback.getByRole('textbox', { name: '问题描述' }).fill('真实TLS全链浏览器附件' + runTag);
    await feedback.getByLabel('上传图片或视频').setInputFiles({ name: attachmentName, mimeType: 'image/png', buffer: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aZ1cAAAAASUVORK5CYII=', 'base64') });
    await feedback.getByRole('button', { name: '提交', exact: true }).click();
    await feedback.getByText(/已提交，我们会/).waitFor();
    await feedback.getByRole('button', { name: '我的反馈', exact: true }).click();
    const [popup] = await Promise.all([context.waitForEvent('page'), feedback.getByRole('button', { name: new RegExp(attachmentName) }).click()]);
    await popup.waitForFunction(() => location.href.startsWith('blob:'));
    await popup.close();
    await feedback.getByRole('button', { name: '关闭', exact: true }).click();
    check('vue_real_feedback_multipart_authenticated_blob_attachment');
    await page.setViewportSize({ width: 1600, height: 1050 });
    await page.goto(origin + '/projects/' + metadata.longProjectId);
    const workspaceLogoutBefore = receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/auth/logout')).length;
    const [logoutResponse] = await Promise.all([page.waitForResponse(response => response.url().endsWith('/api/v1/auth/logout') && response.request().method() === 'POST'), page.getByRole('button', { name: '登出', exact: true }).click()]);
    assert.equal(logoutResponse.status(), 200);
    assert.equal(receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/auth/logout')).length, workspaceLogoutBefore + 1);
    await page.goto(origin + '/login');
    await page.getByLabel('用户名', { exact: true }).fill(metadata.admin.username);
    await page.getByLabel('密码', { exact: true }).fill(metadata.password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.getByRole('heading', { name: '输入验证码' }).waitFor();
    await page.getByLabel('验证码', { exact: true }).fill(totp(metadata.admin.mfaSecret));
    await page.getByRole('button', { name: '验证', exact: true }).click();
    await page.waitForURL('**/admin');
    await page.getByRole('heading', { name: '概览', exact: true }).waitFor();
    for (const name of ['新增记录与模型调用', '每日输入与输出 Token', '每日估算费用'])
        await page.getByRole('img', { name, exact: true }).locator('svg').waitFor();
    check('vue_actual_admin_totp_login_and_three_live_trend_charts');
    await page.screenshot({ path: path.join(output, 'actual-admin-tls.png'), fullPage: true });
    const adminLogoutBefore = receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/auth/logout')).length;
    const [adminLogoutResponse] = await Promise.all([page.waitForResponse(response => response.url().endsWith('/api/v1/auth/logout') && response.request().method() === 'POST'), page.getByRole('button', { name: '退出登录', exact: true }).click()]);
    assert.equal(adminLogoutResponse.status(), 200);
    assert.equal(receipt.requests.filter(r => r.method === 'POST' && r.path.endsWith('/auth/logout')).length, adminLogoutBefore + 1);
    check('vue_workspace_and_admin_rail_logout_single_actual_post');
    assert.deepEqual(receipt.pageErrors, []);
    assert.equal(receipt.httpFailures.filter(f => f.status >= 500).length, 0);
    receipt.passed = true;
}
catch (error) {
    receipt.error = String(error);
    if (page) {
        await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => { });
        fs.writeFileSync(path.join(output, 'failure.txt'), await page.locator('body').innerText().catch(() => ''));
    }
    throw error;
}
finally {
    await finalizeBrowserReceipt(receipt, output, [() => browser?.close()]);
    if (!receipt.passed) process.exitCode = 1;
    console.log(JSON.stringify({ passed: receipt.passed, checks: receipt.checks.length, output }, null, 2));
}
