import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { createHash } from 'node:crypto'
import { fileURLToPath } from 'node:url'
import { fixtureServer, data, token } from './pi-console-fixture.mjs'
import { browserName, launchBrowser } from './browser-options.mjs'
import { finalizeBrowserReceipt } from './browser-receipt.mjs'
const index=process.argv.indexOf('--output')
const output=index<0?fs.mkdtempSync(path.join(os.tmpdir(),'myink-pi-browser-')):path.resolve(process.argv[index+1])
if(index>=0)fs.mkdirSync(output,{recursive:false})
const receipt={kind:'pi_console_synthetic_browser',browser:browserName,checks:[],requests:[],unknownApi:[],pageErrors:[],screenshots:[],limits:['Synthetic loopback fixtures; no real publication, database, host credential or model call']}
const {server,state}=fixtureServer(receipt)
let browser
try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
 const origin=`http://127.0.0.1:${server.address().port}`
 assert.equal((await fetch(origin+'/api/v1/unknown-probe')).status,500);assert.equal(receipt.unknownApi.pop(),'GET /api/v1/unknown-probe');receipt.requests.pop()
 browser=await launchBrowser();receipt.browserVersion=browser.version()
 receipt.indexSha256=createHash('sha256').update(fs.readFileSync(fileURLToPath(new URL('../dist-vue/index.html',import.meta.url)))).digest('hex')
 for(const [name,viewport] of [['desktop',{width:1440,height:960}],['tablet',{width:768,height:960}],['mobile',{width:390,height:844}],['narrow',{width:320,height:740}]]){
  Object.assign(state,{phase:'awaiting_approval',operation:null,unavailable:false,forbidden:false,decisions:[]})
  const page=await browser.newPage({viewport});page.setDefaultTimeout(10000)
  page.on('pageerror',error=>receipt.pageErrors.push(error.message))
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort())
  await page.addInitScript(({token})=>localStorage.setItem('myink.session',JSON.stringify({token,userId:'admin',username:'管理员',tier:'vip',role:'admin',roleVerified:false,expiresAt:Date.now()+3600000})),{token})
  await page.goto(origin+'/admin/pi');await page.getByRole('heading',{name:'Pi 管理',exact:true}).waitFor()
  await page.getByText('0 / 20',{exact:true}).waitFor();await page.getByText('证据不足',{exact:true}).waitFor()
  assert.equal(await page.locator('img[src="x"]').count(),0)
  assert.equal(await page.evaluate(()=>window.pwned),undefined)
  await page.getByText(/每日版本与变更/).click();await page.getByRole('table',{name:'每日变更范围'}).waitFor()
  assert.ok(await page.getByText('线上效果尚未验证',{exact:true}).isVisible())
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`${name}: horizontal viewport overflow`)
  const screenshot=path.join(output,`${name}-pi-console.png`);await page.screenshot({path:screenshot,fullPage:true});receipt.screenshots.push(screenshot)
  receipt.checks.push(`${name}:audit_evidence_version_changes_no_overflow_or_html_execution`)
  await page.getByRole('button',{name:'暂不发布',exact:true}).click();await page.getByText('已记录暂不发布，Pi 继续等待确认。',{exact:true}).waitFor()
  assert.equal(state.decisions.length,1);assert.equal(state.decisions[0].decision,'defer')
  await page.getByRole('button',{name:'查看并发布',exact:true}).click()
  const dialog=page.getByRole('dialog',{name:'确认发布镜像'});await dialog.waitFor();assert.equal(state.decisions.length,1)
  assert.ok(await dialog.getByText(data.status.candidate.image_id,{exact:true}).isVisible())
  await page.keyboard.press('Escape');await dialog.waitFor({state:'detached'});assert.equal(state.decisions.length,1)
  await page.getByRole('button',{name:'查看并发布',exact:true}).click();await dialog.getByRole('button',{name:'确认发布镜像',exact:true}).click()
  await page.getByText('等待宿主处理',{exact:true}).waitFor();assert.equal(state.decisions.length,2)
  assert.equal(state.decisions[1].package_sha256,data.status.package_sha256)
  assert.equal(state.decisions[1].image_id,data.status.candidate.image_id)
  assert.ok(!Object.hasOwn(state.decisions[1],'actor_id'));assert.ok(await page.getByRole('button',{name:'查看并发布',exact:true}).isDisabled())
  receipt.checks.push(`${name}:explicit_confirmation_escape_hold_queue_no_duplicate`)
  state.operation={...state.operation,status:'succeeded'};state.phase='observing'
  await page.getByText('发布已核验',{exact:true}).waitFor();await page.getByText('观察已部署版本',{exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'查看并发布',exact:true}).count(),0)
  state.unavailable=true;await page.getByRole('button',{name:'刷新 Pi 状态'}).click();await page.getByRole('alert').filter({hasText:'Pi 宿主控制台暂时不可用'}).waitFor()
  assert.equal(await page.getByText('暂无运行记录',{exact:true}).count(),0)
  state.unavailable=false;state.forbidden=true;await page.getByRole('button',{name:'刷新 Pi 状态'}).click()
  await page.getByText(/管理员权限|没有管理员权限|管理员身份|权限已/).first().waitFor()
  assert.equal(await page.getByRole('table',{name:'每日变更范围'}).count(),0)
  receipt.checks.push(`${name}:terminal_receipt_outage_and_revoked_role_clear_data`)
  await page.close()
 }
 assert.deepEqual(receipt.unknownApi,[]);assert.deepEqual(receipt.pageErrors,[]);receipt.passed=true
}catch(error){receipt.passed=false;receipt.error=String(error.stack??error);throw error}
finally{
 await finalizeBrowserReceipt(receipt,output,[()=>browser?.close(),()=>{server.closeAllConnections();return new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()))}])
 if(!receipt.passed)process.exitCode=1
 console.log(JSON.stringify({passed:receipt.passed,checks:receipt.checks,output},null,2))
}
