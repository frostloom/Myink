/* Chromium E2E of the real built frontend against explicit synthetic API/SSE.
   No production requests, model calls or application database writes. */
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const __dirname = fileURLToPath(new URL('.', import.meta.url));
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');

import { browserName, launchBrowser } from './browser-options.mjs';

async function main() {
  const arg = process.argv.indexOf('--output');
  if (arg < 0) throw new Error('--output <new-directory> required');
  const out = path.resolve(process.argv[arg + 1]);
  fs.mkdirSync(out, { recursive: false });
  const distArg = process.argv.indexOf('--dist');
  const sourceDist = distArg < 0 ? path.resolve(__dirname, '../dist-vue') : path.resolve(process.argv[distArg + 1]);
  if (!fs.existsSync(path.join(sourceDist, 'index.html'))) throw new Error('Build directory must contain index.html');
  const dist=path.join(out,'built-assets');fs.cpSync(sourceDist,dist,{recursive:true});
  const metrics = [];
  const state = { saveMode:'success', chapterCount:400, phase: 'awaiting_plan', content: '已保存正文：林川扶着栏杆，许宁检查接线盒。', version: 1, rejected: false, saves: 0 };
  const auth = { token: 'synthetic-browser-token', user_id: 'user-p1', username: 'p1_tester', role: 'user', tier: 'pro', expires_in: 3600 };
  const project = { id: 'project-p1', title: 'P1 合成观测站', genre: '现实', current_chapter: 1, target_words: 800, creation_status: 'ready', form: 'long' };
  const plan = { project_id: project.id, chapter_seq: 1, goals: ['检查漏水接线盒'], scenes: [], characters: [], hooks_to_plant: [], hooks_to_resolve: [], expected_events: ['林川与许宁合作检修'], hard_constraints: ['现实题材无超能力'], transition: { mode: 'opening', anchor_quote: '', pending_action: '', opening_beat: '林川扶住栏杆，许宁检查接线盒。', bridge: '' } };
  const candidate = { candidate_id: 'candidate-p1', kind: 'fact', source_chapter: 1, payload: { content: '林川获得瞬间移动能力' }, confidence: 1, status: 'pending', created_at: null };
  const streams = new Set(); const receipt = { kind: 'frontend_e2e_with_synthetic_api', browser: browserName, platform: process.platform, contextMode: 'temporary_persistent', checks: [], api_calls: [], unknown_routes: [], page_errors: [], limits: ['API/SSE controlled fixture, not deployed backend E2E', 'No real model or database calls'] };
  receipt.buildIndex=fs.readFileSync(path.join(dist,'index.html'),'utf8');
  const crypto=require('node:crypto');receipt.harnessSha256=crypto.createHash('sha256').update(fs.readFileSync(fileURLToPath(import.meta.url))).digest('hex');receipt.buildHashes=Object.fromEntries([path.join(dist,'index.html'),...fs.readdirSync(path.join(dist,'assets')).map(f=>path.join(dist,'assets',f))].filter(f=>fs.statSync(f).isFile()).map(f=>[path.relative(dist,f),crypto.createHash('sha256').update(fs.readFileSync(f)).digest('hex')]));
  let frameId = 0; const frames = [];
  function emit(payload) {
    const frame = `id: ${++frameId}-0\ndata: ${JSON.stringify({ task_id: 'task-p1', node: '', status: '', message: '', stage: '', chapter_seq: 1, attempt: 1, offset: 0, artifact_id: 'draft-p1', ...payload })}\n\n`;
    frames.push({ id: frameId, frame });
    for (const res of streams) if(!res.writableEnded)res.write(frame);
  }
  const server = http.createServer((req, res) => {
    const url = new URL(req.url, 'http://127.0.0.1');
    if (url.pathname === '/api/v1/tasks/task-p1/events' && req.method==='GET') {
      res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' });
      res.write(': synthetic stream\n\n'); streams.add(res); res.on('close', () => streams.delete(res));
      if(state.phase==='done' && !frames.some(saved=>saved.frame.includes('\"status\":\"done\"'))) emit({type:'status',status:'done'});
      const cursor = Number((url.searchParams.get('last_event_id') || '0').split('-')[0]);
      for (const saved of frames) if (saved.id > cursor) res.write(saved.frame);
      return;
    }
    if(url.pathname.startsWith('/api/')){res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'unhandled_fixture_endpoint'}));return;}
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
    browser = await launchBrowser(); receipt.browserVersion = browser.version();
    page = await browser.newPage({ viewport: { width: 1440, height: 960 } });
    await page.addInitScript(()=>{window.__mediaUrls={created:[],revoked:[]};const create=URL.createObjectURL.bind(URL),revoke=URL.revokeObjectURL.bind(URL);URL.createObjectURL=b=>{const u=create(b);window.__mediaUrls.created.push(u);return u};URL.revokeObjectURL=u=>{window.__mediaUrls.revoked.push(u);revoke(u)}});
    page.on('pageerror', e => {receipt.page_errors.push(e.message);(receipt.error_details??=[]).push({message:e.message,stack:e.stack,name:e.name,url:page.url()})});
    await page.route('**/*', async route => {
      const request = route.request(); const url = new URL(request.url());
      if (url.origin !== origin) {receipt.unknown_routes.push({external:url.origin});return route.abort();}
      if (!url.pathname.startsWith('/api/')) return route.continue();
      const endpoint = url.pathname.replace('/api/v1', ''); const method = request.method();
      receipt.api_calls.push({ endpoint, method });
      if (endpoint === '/tasks/task-p1/events' && method === 'GET') return route.continue();
      let data; let status = 200;
      const mutationMethods={'/auth/token':'POST','/tasks/task-p1/plan/confirm':'POST','/projects/project-p1/candidates/candidate-p1/reject':'POST','/batches/task-p1/resume':'POST','/projects/project-p1/chapters/chapter-p1/content':'PUT'};
      if(method!==(mutationMethods[endpoint]??'GET')){receipt.unknown_routes.push({endpoint,method});return route.fulfill({status:500,json:{error:'unhandled_fixture_method'}});}
      const chapter = { id: 'chapter-p1', chapter_seq: 1, title: '雨夜', status: state.phase === 'awaiting_plan' ? 'planning' : state.phase === 'running' ? 'writing' : 'confirmed', word_count: state.content.length, summary: '两人检修', content: state.content, version: state.version };
      const task = { task_id: 'task-p1', task_type: 'chapter_generate', status: state.phase, chapter_seq: 1, batch_size: null, batch_current: null, cost_total: 0, error: null, created_at: null };
      if (endpoint === '/auth/token' || endpoint === '/auth/session') data = auth;
      else if (endpoint === '/projects') data = [project];
      else if (endpoint === '/projects/project-p1/writing-resources/updates' && method === 'GET') data = { items: [] };
      else if (endpoint === '/projects/project-p1/writing-resources' && method === 'GET') data = { revision: 0, configured: false, selections: [] };
      else if (endpoint === '/projects/project-p1/chapters') data = [chapter, ...Array.from({length: state.chapterCount-1}, (_,i)=>({...chapter,id:`chapter-load-${i+2}`,chapter_seq:i+2,title:`负载章节${i+2}`,content:undefined}))];
      else if (endpoint === '/projects/project-p1/chapters/chapter-p1' && method === 'GET') data = chapter;
      else if (endpoint === '/projects/project-p1/tasks') data = [task];
      else if (endpoint === '/tasks/task-p1') data = { ...task, payload: { seq: 1, mode: 'manual' }, retry_count: 0, trace_id: null, batch_task_id: null, runs: [{ task_id: 'task-p1', node: 'plan_chapter', model_id: 'synthetic', input_tokens: 0, output_tokens: 0, cost_est: 0, duration_ms: 0, retry_count: 0, degraded: false, cache_hit: false, error: null, detail: { plan, plan_attempt: 1, writing_mode: 'manual' } }] };
      else if (endpoint === '/tasks/task-p1/plan/confirm') { assert.equal(request.postDataJSON().expected_attempt, 1); state.phase = 'running'; setTimeout(() => { emit({ type: 'status', status: 'running', node: 'write' }); emit({ type: 'artifact_reset', stage: 'write' }); emit({ type: 'artifact_delta', stage: 'write', content: '增量第一段：林川扶住栏杆。' }); }, 100); data = { task_id: 'task-p1', status: 'running' }; }
      else if (endpoint === '/projects/project-p1/candidates') data = state.phase === 'awaiting_review' ? [{ ...candidate, ...(state.rejected ? { status: 'rejected', review: { mode: 'revise', reason: '现实题材不允许瞬间移动', applied: false } } : {}) }] : [];
      else if (endpoint === '/projects/project-p1/candidates/candidate-p1/reject') { assert.equal(request.postDataJSON().mode, 'revise'); state.rejected = true; data = { candidate_id: candidate.candidate_id, status: 'rejected' }; }
      else if (endpoint === '/batches/task-p1/resume') { state.phase = 'done'; setTimeout(()=>emit({type:'status',status:'done'}),100); data = { task_id: 'task-p1', status: 'done' }; }
      else if (endpoint === '/projects/project-p1/chapters/chapter-p1/content') { state.saves++; state.version++; if(state.saveMode==='success'){state.content=request.postDataJSON().content;data={version:state.version};}else{state.content = '另一个页面的修改'; status = 409; data = { error: 'version_conflict' };} }
      else if (endpoint === '/projects/project-p1/graph') data = { nodes: [], edges: [] };
      else if (['/projects/project-p1/foreshadows','/projects/project-p1/lessons','/projects/project-p1/characters','/projects/project-p1/entities','/projects/project-p1/events','/projects/project-p1/global-audit'].includes(endpoint)) data = [];
      else if (endpoint === '/projects/project-p1/outline') data = { volumes: [] };
      else if (endpoint === '/projects/project-p1/settings') data = { project_id: project.id, world_rules: {}, hard_constraints: ['现实题材'], style_profile: {}, model_routes: {}, version: 1 };
      else { receipt.unknown_routes.push({ endpoint, method }); status = 500; data = { error: 'unhandled_fixture_endpoint' }; }
      await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(data) });
    });
    await page.goto(origin + '/login');
    const probeStart=receipt.unknown_routes.length;
    const probes=await page.evaluate(async()=>[await fetch('/api/v1/__readiness_unknown').then(r=>r.status),await fetch('/api/v1/projects',{method:'POST'}).then(r=>r.status)]);
    assert.deepEqual(probes,[500,500]);assert.equal(receipt.unknown_routes.length,probeStart+2);receipt.fixtureProbes={unknownEndpoint:probes[0],wrongMethod:probes[1]};receipt.unknown_routes.splice(probeStart,2);receipt.checks.push('fixture_unknown_endpoint_and_method_fail_closed');
    await page.getByLabel('用户名', { exact: true }).fill('p1_tester');
    await page.getByLabel('密码', { exact: true }).fill('synthetic-password');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.waitForURL('**/long'); receipt.checks.push('login');
    // Identical controlled data and timing process for both built clients.
    state.phase = 'done';
    const unit = '雨夜林川观察星空😀𠮷。\n';
    for (const size of [20000,50000]) {
      await page.evaluate(()=>sessionStorage.clear());
      state.content = Array.from(unit.repeat(Math.ceil(size/Array.from(unit).length))).slice(0,size).join('');
      const start = performance.now();
      await page.goto(origin + '/projects/project-p1');
      await page.getByRole('button', {name:/第 1 章.*雨夜/}).click();
      const ed = page.getByRole('textbox',{name:'章节正文'});
      await ed.waitFor(); assert.equal(await ed.inputValue(),state.content);
      assert.equal(await page.getByRole('button',{name:/负载章节/}).count(),399);
      await ed.dispatchEvent('compositionstart',{data:'中文'});await ed.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});await ed.dispatchEvent('compositionend',{data:'中文'});assert.equal(state.saves,size===20000?0:1);
      const inputMs=[];
      for(let i=0;i<20;i++) {const t=performance.now();await ed.press('End');await ed.press('a');await ed.evaluate(el=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));inputMs.push(performance.now()-t);}
      inputMs.sort((a,b)=>a-b);
      let heap={usedSize:null};if(browserName==='chromium'){const cdp=await page.context().newCDPSession(page);await cdp.send('HeapProfiler.collectGarbage');heap=await cdp.send('Runtime.getHeapUsage');await cdp.detach();}
      await page.getByRole('button',{name:'保存',exact:true}).click();await page.waitForFunction(()=>Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='保存'&&b.disabled));assert.equal(state.content,await ed.inputValue());
      metrics.push({unicodePoints:size,chapters:400,loadAndInteractionsMs:performance.now()-start,inputP50Ms:inputMs[9],inputP95Ms:inputMs[18],heapUsedBytes:heap.usedSize});
      assert.ok(inputMs[18]<1500,'Repeated input stalls exceed 1.5s usability ceiling');
    }
    receipt.metrics=metrics;
    await page.evaluate(()=>sessionStorage.clear());frames.length=0;frameId=0;
    receipt.checks.push('20k_50k_unicode_400_chapters_input_and_save');state.saves=0;state.saveMode='conflict';state.chapterCount=1;state.phase='awaiting_plan';state.content='已保存正文：林川扶着栏杆，许宁检查接线盒。';
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
    let streamText=prefix+'增量第二段：许宁关掉电源。';
    const burstStart=performance.now();
    for(let i=0;i<250;i++){const chunk=`密集增量${i}😀`+'雨夜林川观察星空😀𠮷。'.repeat(18)+'\n';emit({type:'artifact_delta',stage:'write',offset:Array.from(streamText).length,content:chunk});streamText+=chunk;}
    const preview=page.getByRole('region',{name:'正文实时预览'});
    await page.waitForFunction(()=>document.querySelector('[aria-label="正文实时预览"]')?.textContent.includes('密集增量249'));
    receipt.denseBurstRenderMs=performance.now()-burstStart;assert.ok(receipt.denseBurstRenderMs<5000,'50k SSE burst render exceeded 5s ceiling');
    await preview.evaluate(el=>{el.scrollTop=0;el.dispatchEvent(new Event('scroll'));});
    await page.getByRole('button',{name:'回到最新'}).waitFor();
    emit({type:'artifact_delta',stage:'write',offset:Array.from(streamText).length,content:'暂停跟随检查'});streamText+='暂停跟随检查';
    await page.waitForFunction(()=>document.querySelector('[aria-label="正文实时预览"]')?.textContent.includes('暂停跟随检查'));
    assert.ok(await preview.evaluate(el=>el.scrollTop<10));
    await page.getByRole('button',{name:'回到最新'}).click();
    assert.ok(await preview.evaluate(el=>el.scrollHeight-el.scrollTop-el.clientHeight<85));
    receipt.streamUnicodePoints=Array.from(streamText).length;receipt.checks.push('dense_250_unicode_deltas','pause_follow_and_return');
    // Simulate stream loss: reconnect must send the last event id, not duplicate the body.
    for (const res of streams) res.end();
    emit({type:'artifact_delta',stage:'write',offset:Array.from(streamText).length,content:'断线期间补帧😀𠮷'});streamText+='断线期间补帧😀𠮷';
    await page.waitForRequest(r => r.url().includes('/events?last_event_id='), { timeout: 15000 });
    receipt.checks.push('sse_reconnect_cursor');
    await page.waitForFunction(()=>document.querySelector('[aria-label="正文实时预览"]')?.textContent.includes('断线期间补帧😀𠮷'));
    assert.equal(await preview.locator('pre').innerText(),streamText);receipt.checks.push('replay_does_not_duplicate_body');
    state.phase = 'awaiting_review';
    emit({type:'status',status:'awaiting_review'});
    for (const res of streams) res.end();
    await page.getByRole('dialog', { name: '设定确认' }).waitFor();
    await page.waitForLoadState('networkidle');
    await page.reload();
    await page.getByRole('dialog', { name: '设定确认' }).waitFor();
    await page.getByPlaceholder('例如：人物仍然受伤，需要治疗过程').fill('现实题材不允许瞬间移动');
    await page.getByRole('button', { name: '不接受，自动修改', exact: true }).click();
    await page.waitForFunction(() => !document.querySelector('[role="dialog"]'));
    assert.equal(state.rejected, true); receipt.checks.push('human_rejection_after_reload', 'resume_request');
    state.phase = 'done'; await page.waitForLoadState('networkidle'); await page.reload();
    await page.getByRole('button', { name: /第 1 章.*雨夜/ }).click();
    const editor = page.getByRole('textbox', { name: '章节正文' }); await editor.waitFor();
    assert.equal(await editor.inputValue(), state.content); receipt.checks.push('saved_body_after_refresh');
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', {name:'导出 .md',exact:true}).click()]);
    assert.equal(download.suggestedFilename(), project.title+'.md');
    const markdown=fs.readFileSync(await download.path(),'utf8');
    assert.ok(markdown.includes('# '+project.title)&&markdown.includes('## 第 1 章 · 雨夜')&&markdown.includes(state.content));
    receipt.checks.push('actual_markdown_download_utf8_content');
    await page.setViewportSize({width:768,height:960});
    await editor.focus();assert.equal(await editor.evaluate(el=>el===document.activeElement),true);
    assert.ok(await page.locator('body').evaluate(el=>el.scrollWidth<=innerWidth+1));
    receipt.checks.push('768px_editor_focus_and_no_overflow');
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
    await page.goto(origin+'/theme');
    await page.getByRole('button',{name:'新建自定义',exact:true}).click();
    await page.getByLabel('名称',{exact:true}).fill('Browser image');
    await page.getByLabel('上传背景').setInputFiles({name:'readiness.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=','base64')});
    await page.getByRole('button',{name:'保存这套',exact:true}).click();
    await page.getByRole('button',{name:'Browser image',exact:true}).waitFor();
    await page.reload();await page.getByRole('button',{name:'Browser image',exact:true}).waitFor();
    const stored=await page.evaluate(()=>new Promise((resolve,reject)=>{const req=indexedDB.open('myink-theme');req.onsuccess=()=>{const db=req.result;const get=db.transaction('files').objectStore('files').getAll();get.onsuccess=()=>{resolve(get.result.map(v=>({size:v.size,type:v.type})));db.close()};get.onerror=reject};req.onerror=reject}));
    assert.ok(stored.some(v=>v.size>0&&v.type==='image/png'));receipt.checks.push('actual_png_upload_indexeddb_reload');
    // Create a real browser-encoded WebM without external media/network dependencies.
    const video=await page.evaluate(async(types)=>{const mime=types.find(type=>MediaRecorder.isTypeSupported(type));if(!mime)throw new Error('No supported browser video encoder');const canvas=document.createElement('canvas');canvas.width=160;canvas.height=90;const ctx=canvas.getContext('2d');const stream=canvas.captureStream(12);const rec=new MediaRecorder(stream,{mimeType:mime});const chunks=[];rec.ondataavailable=e=>chunks.push(e.data);const done=new Promise(r=>rec.onstop=r);rec.start();for(let i=0;i<8;i++){ctx.fillStyle=i%2?'#aa3366':'#3388aa';ctx.fillRect(0,0,160,90);await new Promise(r=>setTimeout(r,60))}rec.stop();await done;stream.getTracks().forEach(t=>t.stop());return {mime:mime.split(';')[0],bytes:Array.from(new Uint8Array(await new Blob(chunks,{type:mime}).arrayBuffer()))}},browserName==='webkit'?['video/mp4','video/webm;codecs=vp8','video/webm']:['video/webm;codecs=vp8','video/webm','video/mp4']);
    receipt.videoMime=video.mime;
    await page.getByRole('button',{name:'新建自定义',exact:true}).click();await page.getByLabel('名称',{exact:true}).fill('Browser video');
    await page.getByLabel('上传背景').setInputFiles({name:'readiness.'+(video.mime==='video/mp4'?'mp4':'webm'),mimeType:video.mime,buffer:Buffer.from(video.bytes)});
    await page.getByRole('button',{name:'保存这套',exact:true}).click();await page.getByRole('button',{name:'Browser video',exact:true}).waitFor();await page.reload();
    const canvasVideo=page.locator('video').first();await canvasVideo.waitFor();
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('video')).some(v=>v.readyState>=2&&!v.paused));
    await page.emulateMedia({reducedMotion:'reduce'});
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('video')).every(v=>v.paused));
    await page.emulateMedia({reducedMotion:'no-preference'});
    await page.waitForFunction(()=>Array.from(document.querySelectorAll('video')).some(v=>!v.paused));
    const videoUrls=await page.evaluate(()=>Array.from(document.querySelectorAll('video')).map(v=>v.src));
    await page.getByRole('button',{name:'Browser image',exact:true}).click();await page.getByRole('button',{name:'应用这套',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('video').length===0);
    const revoked=await page.evaluate(()=>window.__mediaUrls.revoked);assert.ok(videoUrls.every(u=>revoked.includes(u)));
    receipt.checks.push('actual_encoded_video_upload_decode_indexeddb_reload_play','reduced_motion_stops_video_resume_plays','switch_image_removes_video_revokes_url');
    await page.getByRole('button',{name:'反馈',exact:true}).click();
    const dialog=page.getByRole('dialog',{name:'问题反馈',exact:true});
    await page.getByRole('button',{name:'关闭',exact:true}).focus();await page.keyboard.press('Shift+Tab');assert.equal(await page.getByRole('button',{name:'提交',exact:true}).evaluate(el=>el===document.activeElement),true);await page.keyboard.press('Tab');assert.equal(await page.getByRole('button',{name:'关闭',exact:true}).evaluate(el=>el===document.activeElement),true);
    const desc=page.getByLabel('问题描述',{exact:true});await desc.fill('浏览器保留反馈草稿');
    await page.getByLabel('上传图片或视频').setInputFiles({name:'feedback.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=','base64')});
    await desc.dispatchEvent('compositionstart',{data:'中文'});await desc.dispatchEvent('keydown',{key:'Enter',code:'Enter',isComposing:true});await desc.dispatchEvent('compositionend',{data:'中文'});
    assert.equal(await page.getByRole('dialog',{name:'问题反馈',exact:true}).count(),1);
    await page.getByRole('button',{name:'关闭',exact:true}).click();await page.getByRole('button',{name:'反馈',exact:true}).click();
    assert.equal(await desc.inputValue(),'浏览器保留反馈草稿');await page.getByText('feedback.png',{exact:true}).waitFor();
    await page.getByRole('button',{name:'关闭',exact:true}).click();
    await page.getByRole('link',{name:'返回长篇',exact:true}).click();
    await page.getByRole('button',{name:'反馈',exact:true}).click();assert.equal(await desc.inputValue(),'浏览器保留反馈草稿');await page.getByText('feedback.png',{exact:true}).waitFor();
    await desc.focus();await page.setViewportSize({width:390,height:500});await desc.scrollIntoViewIfNeeded();assert.ok(await desc.evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight}));await page.screenshot({path:path.join(out,'05-mobile-feedback-focused.png'),fullPage:true});await page.keyboard.press('Escape');await dialog.waitFor({state:'hidden'});await page.screenshot({path:path.join(out,'05-mobile-feedback-closed.png'),fullPage:true});
    receipt.checks.push('keyboard_tab_trap_escape','390px_short_viewport_focused_description_visible','chapter_composition_enter_no_save','feedback_text_file_close_reopen_route_retention','synthetic_composition_enter_does_not_submit');
    assert.deepEqual(receipt.page_errors, []); assert.deepEqual(receipt.unknown_routes, []);
    receipt.buildIndex=fs.readFileSync(path.join(dist,'index.html'),'utf8'); receipt.passed = true;
  } catch (e) { receipt.passed = false; receipt.error = String(e.stack || e); receipt.sent_frames=frames; receipt.stream_count=streams.size; if (page) { receipt.media_diagnostic=await page.evaluate(()=>({reduced:matchMedia('(prefers-reduced-motion: reduce)').matches,videos:Array.from(document.querySelectorAll('video')).map(v=>({paused:v.paused,ready:v.readyState,network:v.networkState,error:v.error?.message,muted:v.muted,autoplay:v.autoplay,current:v.currentTime,duration:v.duration,rect:v.getBoundingClientRect().toJSON()}))})).catch(()=>null);fs.writeFileSync(path.join(out, 'failure.txt'), await page.locator('body').innerText()); await page.screenshot({path:path.join(out,'failure.png'),fullPage:true}); } throw e; }
  finally {
    fs.writeFileSync(path.join(out, 'receipt.json'), JSON.stringify(receipt, null, 2));
    if (browser) await browser.close();
    for (const res of streams) res.end();
    await new Promise(resolve => server.close(resolve));
  }
}
main().catch(e => { console.error(e.message); process.exitCode = 1; });
