// Built Vue regression against explicit loopback API fixtures; no production calls.
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
const dist = path.resolve(fileURLToPath(new URL('../dist-vue/', import.meta.url)))
const outputIndex = process.argv.indexOf('--output')
const output = outputIndex < 0 ? fs.mkdtempSync(path.join(os.tmpdir(), 'myink-resource-feedback-')) : path.resolve(process.argv[outputIndex + 1])
if (outputIndex >= 0) fs.mkdirSync(output, { recursive: false })
const token = 'synthetic-resource-token'
const receipt = { kind:'resource_feedback_synthetic_browser', passed:false, browser:browserName, checks:[], requests:[], unknownApi:[], pageErrors:[], output, limits:['Built Vue with synthetic loopback APIs; not production/backend E2E','Desktop/mobile viewports in the selected engine'] }
const books = ['l','s','new-long','new-short'].map(id=>({id,title:`测试作品 ${id}`,form:id==='s'||id==='new-short'?'short':'long',genre:'悬疑',current_chapter:id.length===1?1:0,target_words:3000,creation_status:'ready'}))
const card = {working_title:'渡船',genre:'悬疑',direction:'寻找真相',protagonist_pressure:'追赶末班船',conflict_core:'船员隐瞒真相',emotional_payoff:'重逢',plot_sketch:'追寻失踪亲人',chapter_count:2,chars_per_chapter:2000}
const platformStyle = {id:'style',name:'已选文风',kind:'style',source:'platform',status:'published',generation:2,current_version:2,body:{profile:{tone:'克制叙事'}}}
const genreResource = {id:'genre',name:'修仙题材包',kind:'genre',source:'platform',status:'published',generation:1,current_version:1,body:JSON.parse(fs.readFileSync(new URL('./fixtures/xiuxian-resource.json',import.meta.url),'utf8'))}
const defaultRules = [
 {id:'writing',name:'创作规则',kind:'writing_rule',source:'platform',status:'published',generation:1,current_version:1,body:{roles:{writer:'人物用行动推进故事，避免无意义的解释。'}}},
 {id:'expression',name:'表达规则',kind:'expression_rule',source:'platform',status:'published',generation:1,current_version:1,body:{roles:{writer:'避免重复排比与空泛修饰。'}}},
]
const selectedResource=item=>({resource_id:item.id,origin:'platform',name:item.name,kind:item.kind,version:item.current_version,generation:item.generation,body:item.body,personal_override:false})
const snapshot = {revision:1,configured:true,selections:[selectedResource(platformStyle),...defaultRules.map(selectedResource)]}
let projectDelay = 0
let lastSelection=[]
let shortRunning=false
let chatWait=null,releaseChat=()=>{}
let updates = [], dismissStatus = 200, personal = [], platformGeneration = 2
const snapshots = new Map()
const task = {task_id:'short-task',task_type:'short_generate',status:'done',chapter_seq:null,retry_count:0,error:null,runs:[],payload:{},cost_total:0}

const fixtures = new Map([
 ['GET /api/v1/auth/session',()=>({token,user_id:'u',username:'测试作者',tier:'normal',role:'user',expires_in:3600})],
 ['GET /api/v1/projects',()=>books],
 ['GET /api/v1/genre-packs',()=>[]],
 ['GET /api/v1/rankings',()=>({items:[],source:'disabled',fetched_at:null,error:null})],
 ['GET /api/v1/style-library',()=>({items:[]})],
 ['GET /api/v1/writing-resources',()=>({items:[]})],
 ['GET /api/v1/writing-resources/catalog',()=>({items:[{...platformStyle,generation:platformGeneration,current_version:platformGeneration},genreResource,...defaultRules]})],
 ['GET /api/v1/my-writing-resources',()=>({items:personal})],
 ['POST /api/v1/my-writing-resources/from-platform',body=>{assert.equal(body.source_resource_id,'style');assert.equal(body.target_generation,2);const item={...platformStyle,...body,id:'personal-style',source_resource_id:'style',source_generation:2,generation:1,current_version:1};personal=[item];return item}],
 ['POST /api/v1/my-writing-resources/personal-style/sync',body=>{assert.equal(body.expected_generation,1);assert.equal(body.target_generation,3);assert.equal(body.acknowledge_overwrite,true);personal=[{...platformStyle,id:'personal-style',source_resource_id:'style',source_generation:3,generation:2,current_version:2}];return personal[0]}],
 ['POST /api/v1/projects/new-short/short/generate',()=>({task_id:'short-task',status:'done'})],
 ['GET /api/v1/tasks/short-task',()=>({...task,status:shortRunning?'running':'done'})],
 ['GET /api/v1/tasks/short-task/events',()=>null],
 ['GET /api/v1/short/creation',()=>({session:{id:'session',status:'active',card,style_item_id:null,style_name:null,book_id:null},messages:[],sessions:[],ready:true})],
 ['POST /api/v1/short/creation/sessions/session/messages',()=>({session:{id:'session',status:'active',card,style_item_id:null,style_name:null,book_id:null},messages:[{id:1,role:'assistant',content:'切换期间已完成的回复',card:null,model_id:null,cost_est:0,error:null,created_at:'2026-10-27T00:00:00Z'}],sessions:[],ready:true})],
 ['POST /api/v1/short/creation/sessions/session/commit',()=>({project_id:'new-short',lengths_compressed:false,plan_warning:null,style_name:null})],
 ['GET /api/v1/projects/new-long/creation',()=>({project:{...books[2],creation_status:'setup_confirmed'},context:{premise:'追寻真相',setup_draft:{world_rules:{rule:'不能瞬移'}},outline_draft:{objective:'找到真相',volumes:[{volume_seq:1,title:'第一卷',theme:'追寻',goal:'找到线索',chapter_start:1,chapter_end:20,stages:[]}]}}})],
 ['PUT /api/v1/projects/new-long/setup',()=>({})],
 ['PUT /api/v1/projects/new-long/outline',()=>({outline:null})],
])
for(const book of books){
 fixtures.set(`GET /api/v1/projects/${book.id}/settings`,()=>({style_profile:{},genre_pack:{},skill_pack:null,model_routes:{},model_connections:[],version:1}))
 fixtures.set(`GET /api/v1/projects/${book.id}/chapters`,()=>book.current_chapter?[{id:'ch',chapter_seq:1,title:'第一章',status:'confirmed',word_count:1000,summary:null}]:[])
 fixtures.set(`GET /api/v1/projects/${book.id}/tasks`,()=>book.id==='s'&&shortRunning?[{task_id:'short-task',task_type:'short_generate',status:'running',chapter_seq:null}]:book.current_chapter?[{task_id:'task',task_type:'chapter_generate',status:'done',chapter_seq:1}]:[])
 fixtures.set(`GET /api/v1/projects/${book.id}/writing-resources`,()=>snapshots.get(book.id)??(book.form==='long'?{...snapshot,selections:[...snapshot.selections,selectedResource(genreResource)]}:snapshot))
 fixtures.set(`PUT /api/v1/projects/${book.id}/writing-resources`,body=>{lastSelection=body.selections;const previous=snapshots.get(book.id)??snapshot;assert.equal(body.expected_revision,previous.revision);assert.ok(body.selections.every(item=>item.resource_id!=='genre'));const next={revision:previous.revision+1,configured:true,selections:body.selections.map(item=>({...snapshot.selections[0],...item}))};snapshots.set(book.id,next);return next})
 fixtures.set(`GET /api/v1/projects/${book.id}/candidates`,()=>[])
 fixtures.set(`GET /api/v1/projects/${book.id}/lessons`,()=>[])
 fixtures.set(`GET /api/v1/projects/${book.id}/graph`,()=>({nodes:[],edges:[]}))
 fixtures.set(`GET /api/v1/projects/${book.id}/foreshadows`,()=>[])
 fixtures.set(`GET /api/v1/projects/${book.id}/writing-resources/updates`,()=>({items:updates}))
 fixtures.set(`POST /api/v1/projects/${book.id}/writing-resources/dismiss`,()=>({ok:true}))
}
const server = http.createServer(async (req,res)=>{
 const url = new URL(req.url,'http://127.0.0.1')
 if(url.pathname.startsWith('/api/')){
  const key=`${req.method} ${url.pathname}`;receipt.requests.push(key)
  const fixture=fixtures.get(key)
  if(!fixture){receipt.unknownApi.push(key);res.writeHead(500,{'Content-Type':'application/json'});res.end(JSON.stringify({error:'unhandled_fixture_endpoint'}));return}
  if(req.headers.authorization!==`Bearer ${token}`){res.writeHead(401);res.end('{}');return}
  if(url.pathname.endsWith('/events')){res.writeHead(200,{'Content-Type':'text/event-stream'});res.end('id: 1\nevent: message\ndata: '+JSON.stringify({type:'status',status:shortRunning?'running':'done'})+'\n\n');return}
  let body={};if(req.method!=='GET'){const chunks=[];for await(const chunk of req)chunks.push(chunk);const raw=Buffer.concat(chunks).toString();if(raw)body=JSON.parse(raw)}
  if(url.pathname==='/api/v1/projects'&&projectDelay)await new Promise(resolve=>setTimeout(resolve,projectDelay))
  if(url.pathname.endsWith('/commit')||url.pathname.endsWith('/writing-resources/updates'))await new Promise(resolve=>setTimeout(resolve,600))
  if(url.pathname.endsWith('/messages')&&chatWait)await chatWait
  const status=url.pathname.endsWith('/dismiss')?dismissStatus:200
  res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(status===409?{detail:'version_conflict'}:fixture(body)));return
 }
 let file=path.resolve(dist,'.'+decodeURIComponent(url.pathname))
 if(file!==dist&&!file.startsWith(dist+path.sep)){res.writeHead(403);res.end();return}
 if(!fs.existsSync(file)||fs.statSync(file).isDirectory())file=path.join(dist,'index.html')
 res.writeHead(200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml'})[path.extname(file)]??'application/octet-stream'})
 fs.createReadStream(file).pipe(res)
})
let browser, page
try{
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve))
 const origin=`http://127.0.0.1:${server.address().port}`
 receipt.indexSha256=createHash('sha256').update(fs.readFileSync(path.join(dist,'index.html'))).digest('hex')
 browser=await launchBrowser();receipt.browserVersion=browser.version()
 for(const [name,viewport] of [['desktop',{width:1440,height:960}],['mobile',{width:390,height:844}]]){
  page=await browser.newPage({viewport});page.setDefaultTimeout(10000)
  page.on('pageerror',error=>receipt.pageErrors.push(error.message))
  await page.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort())
  await page.addInitScript(({token})=>localStorage.setItem('myink.session',JSON.stringify({token,userId:'u',username:'测试作者',tier:'normal',role:'user',roleVerified:false,expiresAt:Date.now()+3600000})),{token})
  updates=[];dismissStatus=200;personal=[];platformGeneration=2;snapshots.clear()
  await page.goto(origin+'/short/new')
  await page.getByRole('textbox',{name:'对助手说',exact:true}).fill('写一个渡船故事')
  chatWait=new Promise(resolve=>{releaseChat=resolve})
  await page.getByRole('textbox',{name:'对助手说',exact:true}).press('Enter')
  await page.getByText('正在努力构思中，请稍后',{exact:true}).waitFor()
  await page.getByRole('textbox',{name:'对助手说',exact:true}).fill('下一句草稿保留')
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'长篇',exact:true}).click()
  await page.waitForURL('**/long')
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'短篇',exact:true}).click()
  await page.getByRole('link',{name:'新建短篇',exact:true}).click()
  await page.getByText('正在努力构思中，请稍后',{exact:true}).waitFor()
  assert.equal(await page.getByRole('textbox',{name:'对助手说',exact:true}).inputValue(),'下一句草稿保留')
  releaseChat();chatWait=null
  await page.getByText('切换期间已完成的回复',{exact:true}).waitFor()
  await page.getByText('正在努力构思中，请稍后',{exact:true}).waitFor({state:'hidden'})
  await page.getByRole('textbox',{name:'对助手说',exact:true}).fill('')
  receipt.checks.push(`${name}:short_chat_survives_long_navigation_without_losing_draft_or_response`)

  await page.goto(`${origin}/projects/l/resources`)
  await page.waitForURL('**/projects/l/settings')
  await page.getByRole('region',{name:'本书题材',exact:true}).waitFor()
  await page.getByRole('button',{name:'编辑 已选文风',exact:true}).waitFor()
  const settingsRail = await assertFixedRail(page, viewport)
  await page.getByRole('button',{name:'编辑 创作规则',exact:true}).waitFor()
  await page.getByRole('button',{name:'编辑 表达规则',exact:true}).waitFor()
  const genreDetails=page.getByRole('region',{name:'本书题材',exact:true})
  assert.equal(await genreDetails.getByText('凡人流',{exact:true}).count(),0)
  await genreDetails.getByRole('button',{name:'查看 修仙题材包',exact:true}).click()
  const genreModal=page.getByRole('dialog',{name:'修仙题材包',exact:true})
  await genreModal.getByText('凡人流',{exact:true}).waitFor()
  const leaves=value=>typeof value==='string'?[value]:value&&typeof value==='object'?Object.values(value).flatMap(leaves):[]
  const allGenreText=await genreModal.textContent()
  for(const text of leaves(genreResource.body.fields))assert.ok(allGenreText.includes(text),`Missing genre content: ${text}`)

  const compactRow=genreModal.getByText('凡人流',{exact:true}).locator('..')
  assert.ok((await compactRow.boundingBox()).height<55,'Subtype name and hook should be one compact row')
  assert.equal(await genreDetails.getByText('名称',{exact:true}).count(),0)
  const genreBounds=await genreDetails.boundingBox()
  assert.ok(genreBounds.height<(name==='desktop'?800:1150),`Full genre content is too tall: ${genreBounds.height}`)
  assert.ok(await genreDetails.evaluate(el=>el.scrollWidth<=el.clientWidth+1),'Genre details must not overflow horizontally')
  await genreDetails.screenshot({path:path.join(output,`${name}-full-genre-details.png`)})
  receipt.checks.push(`${name}:full_genre_compact_complete_and_default_rules_visible`)

  await genreModal.getByRole('button',{name:'关闭',exact:true}).click()
  assert.equal(await page.getByRole('button',{name:'编辑 修仙题材包'}).count(),0)
  await page.getByRole('button',{name:'调整资源选择',exact:true}).click()
  const bookChoices=page.getByRole('dialog',{name:'调整本书写作资源'})
  await bookChoices.getByRole('checkbox',{name:'选用 已选文风'}).waitFor()
  assert.equal(await bookChoices.getByRole('checkbox',{name:/修仙题材包/}).count(),0)
  await bookChoices.getByRole('button',{name:'取消',exact:true}).click()
  receipt.checks.push(`${name}:long_resources_redirect_settings_cards_readonly_genre`)
  shortRunning=true
  const restoreStart=receipt.requests.length
  await page.goto(`${origin}/projects/s/resources`)
  await page.waitForURL('**/projects/s')
  await page.getByText('正在写整篇…',{exact:true}).waitFor()
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'长篇',exact:true}).click()
  await page.waitForURL('**/long')
  await page.getByRole('navigation',{name:'作品分区'}).getByRole('link',{name:'短篇',exact:true}).click()
  await page.getByRole('navigation',{name:'作品列表'}).getByRole('link',{name:'测试作品 s',exact:true}).click()
  await page.getByText('正在写整篇…',{exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'开始写作',exact:true}).count(),0)
  assert.equal(receipt.requests.slice(restoreStart).some(key=>key.startsWith('POST ')&&key.endsWith('/short/generate')),false)
  receipt.checks.push(`${name}:short_running_task_restored_after_long_navigation_without_new_generation`)
  assert.equal(await page.getByRole('link',{name:'写作资源',exact:true}).count(),0)
  assert.equal(await page.getByText('本书资源快照',{exact:true}).count(),0)
  shortRunning=false
  await page.goto(`${origin}/projects/l/settings`)
  await page.getByRole('region',{name:'本书题材',exact:true}).waitFor()
  assert.equal(await page.getByRole('button',{name:'查看资源更新',exact:true}).count(),0)
  const updateDialog=page.getByRole('dialog',{name:'写作资源更新'})
  assert.equal(await updateDialog.count(),0)
  updates=[{resource_id:'style',name:'已选文风',kind:'style',current_version:2,target_version:3,target_generation:3,action:'publish',note:'新版本',dismissed:false}];dismissStatus=409
  await page.reload();await updateDialog.waitFor()
  const bounds=await updateDialog.boundingBox();assert.ok(bounds.y>=0&&bounds.y+bounds.height<=viewport.height+1)
  await updateDialog.getByRole('button',{name:'关闭',exact:true}).click();await updateDialog.waitFor({state:'hidden'})
  await page.reload();await page.getByRole('region',{name:'本书题材',exact:true}).waitFor()
  assert.equal(await updateDialog.count(),0,'Declined generation must not interrupt on remount even if dismissal request failed')
  receipt.checks.push(`${name}:short_resources_hidden_and_long_updates_only_on_difference`)
  updates=[];dismissStatus=200

  await page.goto(origin+'/writing-resources')
  await page.getByRole('button',{name:'编辑 已选文风',exact:true}).waitFor()
  const catalogSizes=await page.locator('article[class*=resourceCard]').evaluateAll(cards=>cards.map(card=>card.getBoundingClientRect().height))
  assert.ok(catalogSizes.length>=4&&catalogSizes.every(height=>Math.abs(height-catalogSizes[0])<1),'Personal resource cards must share one height without overlapping')
  const categories=page.getByRole('group',{name:'资源类型筛选'})
  await categories.getByRole('button',{name:'题材包',exact:true}).click()
  assert.equal(await page.getByRole('button',{name:'编辑 已选文风',exact:true}).count(),0)
  await page.getByRole('button',{name:'编辑 修仙题材包',exact:true}).click()
  const genreEditor=page.getByRole('dialog',{name:'编辑 修仙题材包'})
  await page.evaluate(()=>{document.documentElement.dataset.theme='night';const s=document.documentElement.style;s.setProperty('--input-bg','#203039');s.setProperty('--ink','#f1eee5');s.setProperty('--surface-1','#18252b')})
  const fieldStyles=await genreEditor.locator('input:not([type=checkbox]),textarea').evaluateAll(fields=>fields.map(field=>({bg:getComputedStyle(field).backgroundColor,color:getComputedStyle(field).color})))
  assert.ok(fieldStyles.length>=8)
  assert.ok(fieldStyles.every(style=>style.bg==='rgb(32, 48, 57)'&&style.color==='rgb(241, 238, 229)'), 'Every resource editor field follows the same theme')
  await page.waitForFunction(el=>{const probe=document.createElement('span');probe.style.backgroundColor='var(--surface-2)';el.append(probe);const expected=getComputedStyle(probe).backgroundColor;probe.remove();return getComputedStyle(el).backgroundColor===expected},await genreEditor.getByRole('button',{name:'取消',exact:true}).elementHandle())
  await genreEditor.screenshot({path:path.join(output,`${name}-consistent-genre-editor.png`)})
  await page.keyboard.press('Escape');await genreEditor.waitFor({state:'hidden'})
  await page.evaluate(()=>{delete document.documentElement.dataset.theme;['--input-bg','--ink','--surface-1'].forEach(key=>document.documentElement.style.removeProperty(key))})
  await page.getByRole('textbox',{name:'搜索写作资源'}).fill('不存在的内容')
  await page.getByRole('button',{name:'清除筛选',exact:true}).click()
  await page.getByRole('button',{name:'编辑 已选文风',exact:true}).waitFor()
  receipt.checks.push(`${name}:categorized_resources_and_consistent_themed_fields`)
  await page.getByRole('button',{name:'编辑 已选文风',exact:true}).click()
  const editor=page.getByRole('dialog',{name:'编辑 已选文风'})
  await editor.locator('textarea').first().fill('我的克制叙事修改')
  await editor.getByRole('button',{name:'保存为我的版本',exact:true}).click()
  await editor.waitFor({state:'hidden'})
  assert.equal(personal[0].body.profile.tone,'我的克制叙事修改')
  assert.equal(platformStyle.body.profile.tone,'克制叙事')
  platformGeneration=3
  await page.reload()
  await page.getByRole('button',{name:'更新 已选文风',exact:true}).click()
  const overwrite=page.getByRole('dialog',{name:'更新我的资源版本'})
  await overwrite.getByText(/覆盖你对这份资源的个人修改/).waitFor()
  const syncKey='POST /api/v1/my-writing-resources/personal-style/sync'
  const previousSyncs=receipt.requests.filter(key=>key===syncKey).length
  await overwrite.getByRole('button',{name:'保留我的修改',exact:true}).click()
  assert.equal(receipt.requests.filter(key=>key===syncKey).length,previousSyncs)
  await page.getByRole('button',{name:'更新 已选文风',exact:true}).click()
  await overwrite.getByRole('button',{name:'确认覆盖我的修改',exact:true}).click()
  await overwrite.waitFor({state:'hidden'})
  assert.equal(personal[0].source_generation,3)
  await page.screenshot({path:path.join(output,`${name}-personal-resources.png`)})
  receipt.checks.push(`${name}:personal_resource_edit_and_explicit_CAS_overwrite`)

  const rail=page.getByRole('complementary')
  await rail.evaluate(el=>{el.dataset.identity='retained-navigation'})
  projectDelay=600
  const projectsReady=page.waitForResponse(response=>response.url().endsWith('/api/v1/projects'))
  await rail.getByRole('link',{name:'主题',exact:true}).click()
  await page.getByRole('heading',{name:'主题',exact:true}).waitFor()
  assert.equal(await page.getByRole('complementary').getAttribute('data-identity'),'retained-navigation')
  await page.getByRole('navigation',{name:'作品列表'}).getByRole('link',{name:'测试作品 l',exact:true}).waitFor()
  await projectsReady;projectDelay=0
  const night=page.getByRole('button',{name:'夜间',exact:true});await night.focus();await page.keyboard.press('Enter')
  const themeDialog=page.getByRole('dialog',{name:'夜间',exact:true});await themeDialog.waitFor()
  assert.ok(await themeDialog.evaluate(el=>el.matches(':modal')),'Theme preview must isolate the background natively')
  for(let i=0;i<8;i++){await page.keyboard.press('Tab');assert.ok(await themeDialog.evaluate(el=>el.contains(document.activeElement)),`Tab must stay inside preview: ${name} step ${i} ${await page.evaluate(()=>document.activeElement?.outerHTML.slice(0,400))}`)}
  await page.keyboard.press('Escape');await themeDialog.waitFor({state:'hidden'})
  assert.ok(await night.evaluate(el=>el===document.activeElement),'Preview returns focus to opener')
  await night.click();await themeDialog.waitFor();await page.mouse.click(1,1);await themeDialog.waitFor({state:'hidden'})
  await page.screenshot({path:path.join(output,`${name}-stable-navigation-theme.png`)})
  receipt.checks.push(`${name}:delayed_route_navigation_retained_and_theme_focus_trapped`)

  const shortStart=receipt.requests.length
  await page.goto(origin+'/short/new')
  await page.getByRole('button',{name:'开始建书',exact:true}).waitFor()
  assert.deepEqual(await assertFixedRail(page, viewport), settingsRail, 'Settings and short creation navigation dimensions match')
  await page.getByRole('button',{name:'开始建书',exact:true}).click()
  await page.getByRole('button',{name:'确认，开写',exact:true}).click()
  const chooser=page.getByRole('dialog',{name:'选择本书写作资源'})
  await chooser.getByRole('checkbox',{name:'选用 已选文风'}).waitFor()
  const scrollRegions=await chooser.evaluate(dialog=>[dialog,...dialog.querySelectorAll('*')].filter(el=>/auto|scroll/.test(getComputedStyle(el).overflowY)&&el.scrollHeight>el.clientHeight+2).length)
  assert.ok(scrollRegions<=1,`Resource chooser must have one content scroll region, found ${scrollRegions}`)
  const chooserBody=await chooser.locator('.creation-resource-body').boundingBox()
  const chooserHeader=await chooser.locator('header').first().boundingBox()
  const chooserFooter=await chooser.locator('.creation-resource-actions').boundingBox()
  assert.ok(chooserBody.y>=chooserHeader.y+chooserHeader.height-1&&chooserBody.y+chooserBody.height<=chooserFooter.y+1,'Dialog chrome must not overlap content')
  assert.ok(chooserFooter.y+chooserFooter.height<=viewport.height,'Confirmation remains on screen')
  await chooser.screenshot({path:path.join(output,`${name}-creation-resource-dialog.png`)})

  await page.evaluate(()=>document.documentElement.style.setProperty('--surface-1','#18252b'))
  assert.equal(await chooser.locator('footer.creation-resource-actions').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(24, 37, 43)')
  await page.evaluate(()=>document.documentElement.style.removeProperty('--surface-1'))
  await chooser.getByRole('checkbox',{name:'选用 已选文风'}).check()
  const ruleChoice=chooser.getByRole('checkbox',{name:'选用 创作规则',exact:true})
  assert.ok(await ruleChoice.isChecked());assert.ok(await ruleChoice.isEnabled())
  await ruleChoice.uncheck()
  assert.ok(await chooser.getByRole('checkbox',{name:'选用 表达规则',exact:true}).isChecked())
  assert.equal(receipt.requests.slice(shortStart).some(key=>key.includes('/commit')||key.includes('/short/generate')),false)
  const generated=page.waitForResponse(response=>response.url().endsWith('/short/generate'))
  await chooser.getByRole('button',{name:'确认资源并创建作品',exact:true}).click()
  await chooser.getByRole('status',{name:'正在创建作品并保存写作资源'}).waitFor()
  await page.waitForURL('**/projects/new-short')
  assert.equal(lastSelection.some(item=>item.resource_id==='writing'),false)
  assert.equal(lastSelection.some(item=>item.resource_id==='expression'),true)
  await generated
  // Finish the admitted task's initial read before a full-document navigation.
  // WebKit reports pending fetches aborted by page.goto as access-control errors.
  await page.waitForLoadState('networkidle')
  if(name==='mobile'){const rail=await page.getByRole('complementary').first().boundingBox();assert.ok(rail.height<85,'Mobile rail including resource action must remain a compact single row')}
  const shortRequests=receipt.requests.slice(shortStart)
  assert.ok(shortRequests.indexOf('PUT /api/v1/projects/new-short/writing-resources')<shortRequests.indexOf('POST /api/v1/projects/new-short/short/generate'))
  assert.equal(shortRequests.filter(key=>key==='POST /api/v1/projects/new-short/short/generate').length,1)
  receipt.checks.push(`${name}:short_dialog_selection_before_single_auto_generation`)

  const longStart=receipt.requests.length
  await page.goto(origin+'/long/new?draft=new-long')
  await page.getByRole('heading',{name:'③ 整书大纲',exact:true}).waitFor()
  assert.equal(await page.getByRole('heading',{name:'① 作品信息',exact:true}).isVisible(),false)
  await page.getByRole('button',{name:'上一步',exact:true}).click()
  await page.getByRole('heading',{name:'② 设定骨架草稿',exact:true}).waitFor()
  await page.getByRole('button',{name:'上一步',exact:true}).click()
  await page.getByRole('heading',{name:'① 作品信息',exact:true}).waitFor()
  await page.getByRole('button',{name:'下一步',exact:true}).click()
  await page.getByRole('button',{name:'确认设定，下一步',exact:true}).click()
  await page.getByRole('heading',{name:'③ 整书大纲',exact:true}).waitFor()
  assert.equal(await page.getByRole('main').locator('..').evaluate(el=>el.scrollTop),0)
  await page.screenshot({path:path.join(output,`${name}-long-outline-step.png`)})
  await page.getByRole('button',{name:'选择资源并完成建书',exact:true}).click()
  await page.evaluate(()=>document.documentElement.style.setProperty('--surface-1','#18252b'))
  assert.equal(await chooser.locator('footer.creation-resource-actions').evaluate(el=>getComputedStyle(el).backgroundColor),'rgb(24, 37, 43)')
  await page.evaluate(()=>document.documentElement.style.removeProperty('--surface-1'))
  await chooser.getByRole('checkbox',{name:'选用 已选文风'}).check()
  const longRuleChoice=chooser.getByRole('checkbox',{name:'选用 创作规则',exact:true})
  assert.ok(await longRuleChoice.isChecked());assert.ok(await longRuleChoice.isEnabled())
  await longRuleChoice.uncheck()
  assert.ok(await chooser.getByRole('checkbox',{name:'选用 表达规则',exact:true}).isChecked())
  assert.equal(receipt.requests.slice(longStart).includes('PUT /api/v1/projects/new-long/outline'),false)
  await chooser.getByRole('button',{name:'确认资源并创建作品',exact:true}).click()
  await page.waitForURL('**/projects/new-long')
  await page.waitForLoadState('networkidle')
  const longRequests=receipt.requests.slice(longStart)
  assert.ok(longRequests.indexOf('PUT /api/v1/projects/new-long/writing-resources')<longRequests.indexOf('PUT /api/v1/projects/new-long/outline'))
  assert.equal(longRequests.some(key=>key.includes('/generate')),false)
  receipt.checks.push(`${name}:long_steps_restore_and_resources_before_confirmation`)
  await page.close()
 }
 assert.deepEqual(receipt.unknownApi,[]);assert.deepEqual(receipt.pageErrors,[])
 assert.equal(receipt.requests.filter(key=>key==='POST /api/v1/projects/new-short/short/generate').length,2)
 receipt.passed=true
}catch(error){receipt.error=String(error);if(page){await page.screenshot({path:path.join(output,'failure.png')}).catch(()=>{});fs.writeFileSync(path.join(output,'failure.txt'),await page.locator('body').innerText().catch(()=>''))}throw error}
finally{releaseChat();await finalizeBrowserReceipt(receipt,output,[()=>browser?.close(),()=>{server.closeAllConnections();return new Promise((resolve,reject)=>server.close(error=>error?reject(error):resolve()))}]);if(!receipt.passed)process.exitCode=1;console.log(JSON.stringify({passed:receipt.passed,checks:receipt.checks,output}))}
