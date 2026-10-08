/* Chromium E2E of the real built frontend against explicit synthetic API/SSE.
   No production requests, model calls or application database writes. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

async function main() {
  const arg = process.argv.indexOf('--output');
  if (arg < 0) throw new Error('--output <new-directory> required');
  const out = path.resolve(process.argv[arg + 1]);
  fs.mkdirSync(out, { recursive: false });
  const dist = path.resolve('web/dist');
  const state = { phase: 'awaiting_plan', content: '已保存正文：林川扶着栏杆，许宁检查接线盒。', version: 1, rejected: false, saves: 0 };
  const auth = { token: 'synthetic-browser-token', user_id: 'user-p1', username: 'p1_tester', role: 'user', tier: 'pro', expires_in: 3600 };
  const project = { id: 'project-p1', title: 'P1 合成观测站', genre: '现实', current_chapter: 1, target_words: 800, creation_status: 'ready', form: 'long' };
  const plan = { project_id: project.id, chapter_seq: 1, goals: ['检查漏水接线盒'], scenes: [], characters: [], hooks_to_plant: [], hooks_to_resolve: [], expected_events: ['林川与许宁合作检修'], hard_constraints: ['现实题材无超能力'], transition: { mode: 'opening', anchor_quote: '', pending_action: '', opening_beat: '林川扶住栏杆，许宁检查接线盒。', bridge: '' } };
  const candidate = { candidate_id: 'candidate-p1', kind: 'fact', source_chapter: 1, payload: { content: '林川获得瞬间移动能力' }, confidence: 1, status: 'pending', created_at: null };
  const streams = new Set(); const receipt = { kind: 'chromium_frontend_e2e_with_synthetic_api', checks: [], api_calls: [], unknown_routes: [], page_errors: [], limits: ['API/SSE controlled fixture, not deployed backend E2E', 'No real model or database calls'] };
  let frameId = 0; const frames = [];
  function emit(payload) {
    const frame = `id: ${++frameId}-0\ndata: ${JSON.stringify({ task_id: 'task-p1', node: '', status: '', message: '', stage: '', chapter_seq: 1, attempt: 1, offset: 0, artifact_id: 'draft-p1', ...payload })}\n\n`;
    frames.push({ id: frameId, frame });
    for (const res of streams) res.write(frame);
  }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname === '/api/v1/tasks/task-p1/events') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      res.write(': synthetic stream\n\n'); streams.add(res); res.on('close', () => streams.delete(res));
      const cursor = Number((url.searchParams.get('last_event_id') || '0').split('-')[0]);
      for (const saved of frames) if (saved.id > cursor) res.write(saved.frame);
      return;
    }
    let file = path.resolve(dist, '.' + decodeURIComponent(url.pathname));
    if (!file.startsWith(dist + path.sep) && file !== dist) { res.writeHead(403); res.end(); return; }
    if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) file = path.join(dist, 'index.html');
    const mime = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png' };
    res.writeHead(200, { 'Content-Type': mime[path.extname(file)] || 'application/octet-stream' }); fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  let browser; let page;
  try {
    browser = await chromium.launch({ headless: true, ...(process.env.P1_CHROMIUM_EXECUTABLE ? { executablePath: process.env.P1_CHROMIUM_EXECUTABLE } : {}) });
    page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    page.on('pageerror', e => receipt.page_errors.push(e.message));
    await page.route('**/*', async route => {
      const request = route.request(); const url = new URL(request.url());
      if (url.origin !== origin) return route.abort();
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const endpoint = url.pathname.replace('/api/v1', ''); const method = request.method();
      receipt.api_calls.push({ endpoint, method });
      if (endpoint.endsWith('/events') && endpoint.startsWith('/tasks/')) return route.continue();
      let data; let status = 200;
      const chapter = { id: 'chapter-p1', chapter_seq: 1, title: '雨夜', status: state.phase === 'awaiting_plan' ? 'planning' : state.phase === 'running' ? 'writing' : 'confirmed', word_count: state.content.length, summary: '两人检修', content: state.content, version: state.version };
      const task = { task_id: 'task-p1', task_type: 'chapter_generate', status: state.phase, chapter_seq: 1, batch_size: null, batch_current: null, cost_total: 0, error: null, created_at: null };
      if (endpoint === '/auth/token' || endpoint === '/auth/session') data = auth;
      else if (endpoint === '/projects') data = [project];
      else if (endpoint === '/projects/project-p1/chapters') data = [chapter];
      else if (endpoint === '/projects/project-p1/chapters/chapter-p1' && method === 'GET') data = chapter;
      else if (endpoint === '/projects/project-p1/tasks') data = [task];
      else if (endpoint === '/tasks/task-p1') data = { ...task, payload: { seq: 1, mode: 'manual' }, retry_count: 0, trace_id: null, batch_task_id: null, runs: [{ task_id: 'task-p1', node: 'plan_chapter', model_id: 'synthetic', input_tokens: 0, output_tokens: 0, cost_est: 0, duration_ms: 0, retry_count: 0, degraded: false, cache_hit: false, error: null, detail: { plan, plan_attempt: 1, writing_mode: 'manual' } }] };
      else if (endpoint === '/tasks/task-p1/plan/confirm') { assert.equal(request.postDataJSON().expected_attempt, 1); state.phase = 'running'; setTimeout(() => { emit({ type: 'status', status: 'running', node: 'write' }); emit({ type: 'artifact_reset', stage: 'write' }); emit({ type: 'artifact_delta', stage: 'write', content: '增量第一段：林川扶住栏杆。' }); }, 100); data = { task_id: 'task-p1', status: 'running' }; }
      else if (endpoint === '/projects/project-p1/candidates') data = state.phase === 'awaiting_review' ? [{ ...candidate, ...(state.rejected ? { status: 'rejected', review: { mode: 'revise', reason: '现实题材不允许瞬间移动', applied: false } } : {}) }] : [];
      else if (endpoint === '/projects/project-p1/candidates/candidate-p1/reject') { assert.equal(request.postDataJSON().mode, 'revise'); state.rejected = true; data = { candidate_id: candidate.candidate_id, status: 'rejected' }; }
      else if (endpoint === '/batches/task-p1/resume') { state.phase = 'done'; data = { task_id: 'task-p1', status: 'done' }; }
      else if (endpoint === '/projects/project-p1/chapters/chapter-p1/content') { state.saves++; state.version++; state.content = '另一个页面的修改'; status = 409; data = { error: 'version_conflict' }; }
      else if (endpoint === '/projects/project-p1/graph') data = { nodes: [], edges: [] };
      else if (['/projects/project-p1/foreshadows','/projects/project-p1/lessons','/projects/project-p1/characters','/projects/project-p1/entities','/projects/project-p1/events','/projects/project-p1/global-audit'].includes(endpoint)) data = [];
      else if (endpoint === '/projects/project-p1/outline') data = { volumes: [] };
      else if (endpoint === '/projects/project-p1/settings') data = { project_id: project.id, world_rules: {}, hard_constraints: ['现实题材'], style_profile: {}, model_routes: {}, version: 1 };
      else { receipt.unknown_routes.push({ endpoint, method }); status = 500; data = { error: 'unhandled_fixture_endpoint' }; }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto(origin + '/login');
    await page.getByLabel('用户名', { exact: true }).fill('p1_tester');
    await page.getByLabel('密码', { exact: true }).fill('synthetic-password');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL('**/long'); receipt.checks.push('login');
    await page.goto(origin + '/projects/project-p1');
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).waitFor();
    await page.screenshot({ path: path.join(out, '01-plan.png'), fullPage: true });
    await page.getByRole('button', { name: '确认计划并开始写作', exact: true }).click();
    await page.getByText('增量第一段：林川扶住栏杆。', { exact: false }).first().waitFor();
    receipt.checks.push('plan_confirmation', 'partial_body_before_stream_completion');
    await page.screenshot({ path: path.join(out, '02-stream.png'), fullPage: true });
    const prefix = '增量第一段：林川扶住栏杆。';
    emit({ type: 'artifact_delta', stage: 'write', offset: Array.from(prefix).length, content: '增量第二段：许宁关掉电源。' });
    await page.getByText(/增量第二段：许宁关掉电源/).first().waitFor(); receipt.checks.push('second_body_chunk');
    // Simulate stream loss: reconnect must send the last event id, not duplicate the body.
    for (const res of streams) res.end();
    await page.waitForRequest(r => r.url().includes('/events?last_event_id='), { timeout: 15000 });
    receipt.checks.push('sse_reconnect_cursor');
    state.phase = 'awaiting_review';
    for (const res of streams) res.end();
    await page.reload();
    await page.getByRole('dialog', { name: '设定确认' }).waitFor();
    await page.getByPlaceholder('例如：人物仍然受伤，需要治疗过程').fill('现实题材不允许瞬间移动');
    await page.getByRole('button', { name: '不接受，自动修改', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
    assert.equal(state.rejected, true); receipt.checks.push('human_rejection_after_reload', 'resume_request');
    state.phase = 'done'; await page.reload();
    await page.getByRole('button', { name: /第 1 章.*雨夜/ }).click();
    const editor = page.getByRole('textbox', { name: '章节正文' }); await editor.waitFor();
    assert.equal(await editor.inputValue(), state.content); receipt.checks.push('saved_body_after_refresh');
    await editor.fill('我的修改必须保留');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByText('查看服务器正文', { exact: true }).click();
    await page.getByText('另一个页面的修改', { exact: false }).first().waitFor();
    assert.equal(await editor.inputValue(), '我的修改必须保留');
    assert.equal(await page.getByRole('button', { name: '保存', exact: true }).isDisabled(), true);
    assert.equal(state.saves, 1); receipt.checks.push('409_preserves_draft_and_blocks_overwrite');
    await page.screenshot({ path: path.join(out, '03-conflict.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: path.join(out, '04-mobile.png'), fullPage: true });
    const width = await page.locator('body').evaluate(el => ({ scroll: el.scrollWidth, viewport: window.innerWidth }));
    assert.ok(width.scroll <= width.viewport + 1, JSON.stringify(width)); receipt.checks.push('390px_no_body_horizontal_overflow');
    assert.deepEqual(receipt.page_errors, []); assert.deepEqual(receipt.unknown_routes, []);
    receipt.passed = true;
  } catch (e) { receipt.passed = false; receipt.error = String(e.stack || e); receipt.sent_frames=frames; receipt.stream_count=streams.size; if (page) { fs.writeFileSync(path.join(out, 'failure.txt'), await page.locator('body').innerText()); await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}); } throw e; }
  finally {
    fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify(receipt, null, 2));
    if (browser) await browser.close();
    for (const res of streams) res.end();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
