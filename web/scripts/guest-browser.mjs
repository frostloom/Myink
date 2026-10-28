// Built Vue acceptance with synthetic loopback APIs only; no accounts or models.
import assert from 'node:assert/strict'
import fs from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { launchBrowser, browserName } from './browser-options.mjs'
import { finalizeBrowserReceipt } from './browser-receipt.mjs'
import { assertFixedRail } from './rail-layout-assertions.mjs'
const dist = path.resolve(fileURLToPath(new URL('../dist-vue/', import.meta.url)))
const outputIndex = process.argv.indexOf('--output')
const output = outputIndex < 0 ? fs.mkdtempSync(path.join(os.tmpdir(), 'myink-guest-browser-')) : path.resolve(process.argv[outputIndex + 1])
if (outputIndex >= 0) fs.mkdirSync(output)
const receipt = { kind: 'guest_synthetic_browser', browser: browserName, passed: false, checks: [], requests: [], unknownApi: [], pageErrors: [], output }
const guest = { user_id: 'g', username: 'guest-g', token: 'guest-token', tier: 'normal', role: 'user', is_guest: true, expires_in: 3600 }
const member = { ...guest, username: 'alice', token: 'member-token', is_guest: false }
const book = { id: 's', title: '游客的渡船故事', form: 'short', genre: '悬疑', current_chapter: 0, target_words: 2000, creation_status: 'ready' }
let upgraded = false, failedInvite = true, quotaUnavailable = false, shortRemaining = 1
const server = http.createServer(async (req, res) => {
 const url = new URL(req.url, 'http://127.0.0.1')
 if (url.pathname.startsWith('/api/')) {
  const key = `${req.method} ${url.pathname}`
  const chunks=[]; for await (const chunk of req) chunks.push(chunk)
  const raw=Buffer.concat(chunks).toString(), body=raw?JSON.parse(raw):{}
  receipt.requests.push({ key, body, authorization: req.headers.authorization })
  let result, status=200
  if(key==='POST /api/v1/auth/guest') result=guest
  else if(key==='GET /api/v1/auth/session') result=upgraded?member:guest
  else if(key==='POST /api/v1/auth/register') {
   assert.equal(req.headers.authorization,'Bearer guest-token')
   if(failedInvite){status=400;result={error:'INVITATION_INVALID'}}
   else{upgraded=true;result=member}
  }
  else if(key==='POST /api/v1/auth/logout') result={ok:true}
  else if(key==='POST /api/v1/auth/token') result={...member,user_id:'b',username:'bob',token:'b-token'}
  else if(key==='GET /api/v1/auth/guest/quota') {
   if(quotaUnavailable){status=503;result={error:'GUEST_QUOTA_UNAVAILABLE'}}
   else result={short:{limit:2,used:2-shortRemaining,remaining:shortRemaining},long:{limit:10,used:3,remaining:7}}
  }
  else if(key==='GET /api/v1/projects') result=[book]
  else if(key==='GET /api/v1/short/creation') result={session:{id:'session',status:'active',card:{}},messages:[],sessions:[],ready:false}
  else if(key==='POST /api/v1/projects/s/short/generate'){shortRemaining=0;status=429;result={error:'GUEST_QUOTA_EXHAUSTED'}}
  else if(key==='GET /api/v1/style-library') result={items:[]}
  else if(key==='GET /api/v1/projects/s/settings') result={style_profile:{},genre_pack:{},skill_pack:null,model_routes:{},model_connections:[],version:1}
  else if(key==='GET /api/v1/projects/s/writing-resources') result={revision:1,configured:true,selections:[]}
  else if(key==='GET /api/v1/projects/s/writing-resources/updates') result={items:[]}
  else if(/^GET \/api\/v1\/projects\/s\/(chapters|tasks|candidates|lessons|foreshadows)$/.test(key)) result=[]
  else if(key==='GET /api/v1/projects/s/graph') result={nodes:[],edges:[]}
  else {receipt.unknownApi.push(key);status=500;result={error:'unhandled_fixture_endpoint'}}
  res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(result));return
 }
 let file=path.resolve(dist,'.'+decodeURIComponent(url.pathname))
 if(file!==dist&&!file.startsWith(dist+path.sep)){res.writeHead(403);res.end();return}
 if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(dist,'index.html')
 res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(file)]??'application/octet-stream'})
 fs.createReadStream(file).pipe(res)
})
let browser, activePage
try {
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
 const origin=`http://127.0.0.1:${server.address().port}`
 browser=await launchBrowser();receipt.browserVersion=browser.version()
 for(const [name,viewport] of [['desktop',{width:1440,height:960}],['mobile',{width:390,height:844}],['short-mobile',{width:390,height:600}]]) {
  const page=await browser.newPage({viewport});activePage=page;page.setDefaultTimeout(10000)
  page.on('pageerror',error=>receipt.pageErrors.push(error.message))
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort())
  await page.goto(origin+'/login');await page.evaluate(()=>localStorage.clear());await page.reload()
  upgraded=false;failedInvite=true;quotaUnavailable=false;shortRemaining=1
  await page.getByRole('button',{name:'游客体验',exact:true}).click()
  await page.waitForURL('**/long')
  assert.equal(await page.getByRole('region',{name:'游客体验额度',exact:true}).count(),0)
  assert.equal(await page.getByText(/短篇剩余|长篇剩余|同一 IP/).count(),0)
  await assertFixedRail(page,viewport)
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'短篇',exact:true}).click()
  await page.getByRole('link',{name:'新建短篇',exact:true}).click()
  const composer=page.getByRole('textbox',{name:'对助手说',exact:true})
  await composer.fill('升级时不能丢失的草稿')
  await page.screenshot({path:path.join(output,`${name}-guest-workspace.png`)})
  await page.evaluate(()=>window.dispatchEvent(new Event('myink:guest-upgrade')))
  const dialog=page.getByRole('dialog',{name:'注册保留作品',exact:true})
  await dialog.getByLabel('用户名',{exact:true}).fill('alice')
  await dialog.getByLabel('密码',{exact:true}).fill('password1')
  await dialog.getByLabel('确认密码',{exact:true}).fill('password1')
  await dialog.getByLabel('邀请码',{exact:true}).fill('fixture-invite')
  await dialog.getByRole('button',{name:'创建账号',exact:true}).click()
  await dialog.getByText('邀请码无效',{exact:true}).waitFor()
  assert.equal(await composer.inputValue(),'升级时不能丢失的草稿')
  assert.ok((await dialog.boundingBox()).width<=viewport.width-16)
  const modalBounds=await dialog.boundingBox()
  assert.ok(modalBounds.height<=viewport.height-32,'Registration dialog must fit short viewport')
  await dialog.getByLabel('用户名',{exact:true}).focus()
  for(let step=0;step<9;step++){
   await page.keyboard.press('Tab')
   assert.ok(await dialog.evaluate(el=>{
    const active=document.activeElement
    if(!active||!el.contains(active))return false
    const bounds=active.getBoundingClientRect(),modal=el.getBoundingClientRect()
    return bounds.top>=modal.top&&bounds.bottom<=modal.bottom+1
   }),'Each focused registration control stays inside the visible dialog')
  }
  receipt.checks.push(`${name}:registration_keyboard_focus_and_short_viewport_scroll`)
  await page.screenshot({path:path.join(output,`${name}-upgrade-error.png`)})
  failedInvite=false
  await dialog.getByRole('button',{name:'创建账号',exact:true}).click()
  await dialog.waitFor({state:'hidden'})
  assert.equal(await composer.inputValue(),'升级时不能丢失的草稿')
  assert.equal(new URL(page.url()).pathname,'/short/new')
  assert.equal(await page.getByText('短篇剩余 1 次',{exact:true}).count(),0)
  receipt.checks.push(`${name}:entry_without_quota_fixed_rail_upgrade_failure_and_same_id_success_preserve_draft`)
  // Simulate a reload with an expired JWT and a remaining HttpOnly recovery cookie.
  upgraded=false
  await page.evaluate(()=>localStorage.setItem('myink.session',JSON.stringify({token:'expired-guest',userId:'g',username:'guest-g',tier:'normal',role:'user',isGuest:true,expiresAt:Date.now()-1000})))
  const beforeRestore=receipt.requests.length
  await page.reload();await composer.fill('额度用尽也保留的草稿')
  assert.ok(receipt.requests.slice(beforeRestore).some(item=>item.key==='POST /api/v1/auth/guest'&&item.body.restore_only===true))
  await page.getByRole('navigation',{name:'作品列表'}).getByRole('link',{name:book.title,exact:true}).click()
  await page.getByRole('button',{name:'开始写',exact:true}).click()
  await dialog.waitFor()
  await dialog.getByText(/短篇体验额度已用完/).waitFor()
  assert.equal(await dialog.getByText(/长篇体验额度已用完/).count(),0)
  const balance=await page.request.get(origin+'/api/v1/auth/guest/quota',{headers:{Authorization:'Bearer guest-token'}})
  assert.equal((await balance.json()).short.remaining,0)
  await page.screenshot({path:path.join(output,`${name}-exhausted-upgrade.png`)})
  await dialog.getByRole('button',{name:'关闭注册',exact:true}).click()
  quotaUnavailable=true
  await page.evaluate(()=>{window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'))})
  assert.equal(await dialog.count(),0)
  assert.equal(await page.getByText(/短篇剩余|体验额度暂时无法读取/).count(),0)
  quotaUnavailable=false
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'短篇',exact:true}).click()
  await page.getByRole('link',{name:'新建短篇',exact:true}).click()
  assert.equal(await composer.inputValue(),'额度用尽也保留的草稿')
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
  receipt.checks.push(`${name}:restore_only_exhaustion_preserved_draft_and_dismissed_dialog_stays_closed`)
  await composer.fill('')
  await page.getByRole('link',{name:'账号',exact:true}).click()
  await page.getByLabel('确认密码',{exact:true}).waitFor()
  assert.equal(await page.getByLabel('当前密码',{exact:true}).count(),0)
  assert.equal(await page.getByText('忘记密码',{exact:true}).count(),0)
  assert.ok((await page.getByRole('region',{name:'注册账号',exact:true}).boundingBox()).width<=512)
  assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1))
  await page.screenshot({path:path.join(output,`${name}-account-registration.png`)})
  await page.getByRole('button',{name:'登出',exact:true}).click()
  // Logout is deliberately synthetic and follows ordinary account UI semantics.
  await page.close()
 }
 assert.deepEqual(receipt.unknownApi,[]);assert.deepEqual(receipt.pageErrors,[])
 receipt.passed=true
} catch(error) {receipt.error=String(error);receipt.pageText=await activePage?.locator('body').innerText().catch(()=>null);await activePage?.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});process.exitCode=1}
finally {
 await finalizeBrowserReceipt(receipt,output,[()=>browser?.close(),()=>new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()))])
 if(!receipt.passed)process.exitCode=1
 console.log(JSON.stringify(receipt,null,2))
}
