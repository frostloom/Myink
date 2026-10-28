import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { createMemoryHistory } from 'vue-router'
import App from './App.vue'
import { createCandidateRouter } from './router'
import { createSessionScope } from './session'
import { setSession } from '../../src/lib/token'
import { api } from '../../src/lib/api'
const guest = { user_id: 'g', username: 'guest-g', token: 'guest-token', tier: 'normal', role: 'user', is_guest: true, expires_in: 3600 }
const member = { ...guest, username: 'alice', token: 'member-token', is_guest: false }
const quota = { short: { limit: 2, used: 1, remaining: 1 }, long: { limit: 10, used: 3, remaining: 7 } }
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })
function stored(expiresAt = Date.now() + 3600000) { setSession({ token: 'guest-token', userId: 'g', username: 'guest-g', tier: 'normal', role: 'user', roleVerified: true, expiresAt, isGuest: true }) }
const scopes: ReturnType<typeof createSessionScope>[] = []
async function app(path = '/short/new') {
 const router = createCandidateRouter(createMemoryHistory()); await router.push(path); await router.isReady()
 render(App, {global: {plugins: [router]}}); return router
}
function fixtures(options: {failedUpgrade?: boolean; quotaError?: boolean} = {}) {
 return vi.fn(async (path: string, init: RequestInit) => {
  if(path.endsWith('/auth/session') || path.endsWith('/auth/guest')) return response(guest)
  if(path.endsWith('/auth/guest/quota')) return options.quotaError ? response({error:'GUEST_QUOTA_UNAVAILABLE'},503) : response(quota)
  if(path.endsWith('/auth/register')) {
   expect((init.headers as Record<string,string>).Authorization).toBe('Bearer guest-token')
   return options.failedUpgrade ? response({error:'INVITATION_INVALID'},400) : response(member)
  }
  if(path.endsWith('/short/creation')) return response({session:{id:'s',status:'active',card:{}},messages:[],sessions:[],ready:false})
  if(path.includes('style')) return response({items:[]})
  if(path.endsWith('/graph')) return response({nodes:[],edges:[]})
  return response([])
 })
}
afterEach(() => { cleanup(); scopes.splice(0).forEach(s=>s.dispose()); localStorage.clear(); vi.unstubAllGlobals(); vi.restoreAllMocks() })
it('offers guest entry in unauthenticated prompt and disables repeated entry while pending', async () => {
 let finish!: (value:Response)=>void
 const fetcher = vi.fn(()=>new Promise<Response>(resolve=>{finish=resolve})); vi.stubGlobal('fetch',fetcher)
 await app('/long'); await fireEvent.click(await screen.findByRole('link',{name:'新建长篇'}))
 const dialog = await screen.findByRole('dialog')
 await fireEvent.click(within(dialog).getByRole('button',{name:'游客体验'}))
 expect((within(dialog).getByRole('button',{name:'正在进入…'}) as HTMLButtonElement).disabled).toBe(true)
 expect(fetcher).toHaveBeenCalledTimes(1)
 finish(response(guest)); await flushPromises()
 expect(screen.queryByRole('dialog')).toBeNull()
 expect(await screen.findByText('游客')).toBeTruthy()
})
it('offers guest entry without persistent quota hints', async()=>{
 vi.stubGlobal('fetch',fixtures()); const router = await app('/login')
 expect(screen.queryByText(/同一 IP/)).toBeNull()
 await fireEvent.click(screen.getByRole('button',{name:'游客体验'}))
 await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/long'))
 expect(screen.queryByText(/短篇剩余|长篇剩余/)).toBeNull()
})
it('restores expired guests only, preserving the same identity without an anonymous creation request',async()=>{
 stored(Date.now()-1000)
 const fetcher=vi.fn(async (_:string,init:RequestInit)=>{expect(JSON.parse(init.body as string)).toEqual({restore_only:true});expect(init.credentials).toBe('same-origin');return response(guest)})
 vi.stubGlobal('fetch',fetcher); const s=createSessionScope();scopes.push(s);await s.start()
 expect(s.status.value).toBe('authenticated');expect(s.session.value?.userId).toBe('g');expect(s.session.value?.isGuest).toBe(true)
 expect(fetcher).toHaveBeenCalledTimes(1)
})
it('never falls back to guest creation when an ordinary account expires',async()=>{
 setSession({token:'old',userId:'u',username:'alice',tier:'normal',role:'user',roleVerified:true,expiresAt:Date.now()-1000})
 const fetcher=vi.fn();vi.stubGlobal('fetch',fetcher);const s=createSessionScope();scopes.push(s);await s.start()
 expect(s.status.value).toBe('anonymous');expect(fetcher).not.toHaveBeenCalled()
})
it.each([false,true])('keeps the workspace and draft mounted after guest upgrade (failure=%s)',async failedUpgrade=>{
 stored();vi.stubGlobal('fetch',fixtures({failedUpgrade}));const router=await app()
 const draft=await screen.findByLabelText('对助手说');await fireEvent.update(draft,'保留我的草稿')
 window.dispatchEvent(new Event('myink:guest-upgrade'))
 const dialog=await screen.findByRole('dialog',{name:'注册保留作品'})
 await fireEvent.update(within(dialog).getByLabelText('用户名'),'Alice')
 await fireEvent.update(within(dialog).getByLabelText('密码'),'abcd1234')
 await fireEvent.update(within(dialog).getByLabelText('确认密码'),'abcd1234')
 await fireEvent.update(within(dialog).getByLabelText('邀请码'),'invite')
 await fireEvent.click(within(dialog).getByRole('button',{name:'创建账号'}));await flushPromises()
 expect(router.currentRoute.value.path).toBe('/short/new');expect(screen.getByLabelText('对助手说')).toBe(draft)
 expect((draft as HTMLTextAreaElement).value).toBe('保留我的草稿')
 if(failedUpgrade){expect(within(dialog).getByRole('alert').textContent).toContain('邀请码无效');expect(localStorage.getItem('myink.session')).toContain('guest-token')}
 else{expect(screen.queryByRole('dialog')).toBeNull();expect(localStorage.getItem('myink.session')).toContain('member-token');expect(screen.queryByText('短篇剩余 1 次')).toBeNull()}
})
it('does not show quota hints or open registration after quota fetch or focus',async()=>{
 stored();vi.stubGlobal('fetch',fixtures({quotaError:true}));await app('/long');await flushPromises()
 window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));await flushPromises()
 expect(screen.queryByRole('region',{name:'游客体验额度'})).toBeNull()
 expect(screen.queryByRole('dialog')).toBeNull()
})
it('keeps an exhausted draft and opens registration from the quota warning',async()=>{
 stored();const fetcher=fixtures();let depleted=false
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/short/generate')){depleted=true;return response({error:'GUEST_QUOTA_EXHAUSTED'},429)}
  if(depleted&&path.endsWith('/auth/guest/quota'))return response({...quota,short:{limit:2,used:2,remaining:0}})
  return fetcher(path,init)
 })
 await app();const draft=await screen.findByLabelText('对助手说');await fireEvent.update(draft,'仍可编辑')
 await expect(api.generateShort('book')).rejects.toThrow('GUEST_QUOTA_EXHAUSTED')
 expect(await screen.findByText(/短篇体验额度已用完/)).toBeTruthy()
 expect(await screen.findByRole('dialog')).toBeTruthy();expect((draft as HTMLTextAreaElement).value).toBe('仍可编辑')
 await fireEvent.click(screen.getByRole('button',{name:'关闭注册'}))
 window.dispatchEvent(new Event('focus'));document.dispatchEvent(new Event('visibilitychange'));await flushPromises()
 expect(screen.queryByRole('dialog')).toBeNull()
})
it('clears an unrecoverable expired guest without silently creating another identity',async()=>{
 stored(Date.now()-1000);const requests:unknown[]=[]
 vi.stubGlobal('fetch',async(_:string,init:RequestInit)=>{requests.push(JSON.parse(init.body as string));return response({error:'GUEST_RECOVERY_INVALID'},401)})
 const s=createSessionScope();scopes.push(s);await s.start()
 expect(s.status.value).toBe('anonymous');expect(s.session.value).toBeNull();expect(requests).toEqual([{restore_only:true}])
})
it('renews a near-expiry guest with restore-only while retaining its workspace',async()=>{
 stored(Date.now()+60000);const requests:unknown[]=[]
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/guest')){requests.push(JSON.parse(init.body as string));return response({...guest,token:'rotated-guest'})}
  return response(guest)
 })
 const s=createSessionScope();scopes.push(s);await s.start()
 document.dispatchEvent(new Event('visibilitychange'));await flushPromises()
 expect(s.session.value?.token).toBe('rotated-guest');expect(s.session.value?.userId).toBe('g');expect(requests).toEqual([{restore_only:true}])
})
it('keeps a different account chosen while guest restoration is pending',async()=>{
 stored(Date.now()-1000);let finish!:(value:Response)=>void
 vi.stubGlobal('fetch',async(path:string)=>path.endsWith('/auth/guest')?new Promise<Response>(resolve=>{finish=resolve}):response({...member,user_id:'b'}))
 const s=createSessionScope();scopes.push(s);const pending=s.start()
 setSession({token:'b-token',userId:'b',username:'bob',tier:'normal',role:'user',roleVerified:false,expiresAt:Date.now()+3600000})
 await s.revalidate();finish(response(guest));await pending
 expect(s.session.value?.userId).toBe('b');expect(s.session.value?.isGuest).toBe(false)
})
it('cleans guest workspace and quota when logging into a different account',async()=>{
 stored();const base=fixtures();vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>path.endsWith('/auth/token')?response({...member,user_id:'b'}):base(path,init))
 const router=await app();await fireEvent.update(await screen.findByLabelText('对助手说'),'前一位游客的草稿')
 const confirm=vi.spyOn(window,'confirm').mockReturnValue(false)
 await router.push('/login');expect(router.currentRoute.value.path).toBe('/short/new')
 confirm.mockReturnValue(true);await router.push('/login')
 await fireEvent.update(await screen.findByLabelText('用户名'),'alice');await fireEvent.update(screen.getByLabelText('密码'),'password1')
 await fireEvent.click(screen.getByRole('button',{name:'登录'}));await flushPromises()
 expect(router.currentRoute.value.path).toBe('/long');expect(screen.queryByText('短篇剩余 1 次')).toBeNull()
 await router.push('/short/new');expect((await screen.findByLabelText('对助手说') as HTMLTextAreaElement).value).toBe('')
})
it('offers guest entry when a protected project cannot open anonymously',async()=>{
 vi.stubGlobal('fetch',fixtures());await app('/projects/unknown')
 expect(await screen.findByText('未登录，无法打开作品。')).toBeTruthy()
 await fireEvent.click(screen.getByRole('button',{name:'游客体验'}))
 await screen.findByText('游客')
})
it('offers account registration and existing-account login without a guest password form',async()=>{
 stored();vi.stubGlobal('fetch',fixtures());await app('/account')
 expect(await screen.findByRole('link',{name:'登录已有账号'})).toBeTruthy()
 expect(screen.queryByLabelText('当前密码')).toBeNull()
 expect(screen.queryByText('忘记密码')).toBeNull()
 expect(screen.queryByText('当前账号')).toBeNull()
 expect(screen.getByLabelText('确认密码')).toBeTruthy()
 await fireEvent.click(screen.getByRole('link',{name:'登录已有账号'}))
 expect(await screen.findByLabelText('用户名')).toBeTruthy()
})
it('restarts an aborted guest restoration when storage changes to another expired guest',async()=>{
 stored(Date.now()-1000);const finishes:Array<(value:Response)=>void>=[]
 vi.stubGlobal('fetch',()=>new Promise<Response>(resolve=>{finishes.push(resolve)}))
 const s=createSessionScope();scopes.push(s);const first=s.start()
 setSession({token:'g2-expired',userId:'g2',username:'guest-2',tier:'normal',role:'user',roleVerified:false,isGuest:true,expiresAt:Date.now()-1000})
 const second=s.revalidate()
 expect(finishes).toHaveLength(2)
 finishes[1]!(response({...guest,user_id:'g2',token:'g2-new'}));await second
 finishes[0]!(response(guest));await first
 expect(s.session.value?.userId).toBe('g2');expect(s.status.value).toBe('authenticated')
})
it('does not clear a different stored account when an old guest restore is rejected',async()=>{
 stored(Date.now()-1000);let finish!:(value:Response)=>void
 vi.stubGlobal('fetch',async(path:string)=>path.endsWith('/auth/guest')?new Promise<Response>(resolve=>{finish=resolve}):response({...member,user_id:'b'}))
 const s=createSessionScope();scopes.push(s);const first=s.start()
 setSession({token:'b-token',userId:'b',username:'bob',tier:'normal',role:'user',roleVerified:false,expiresAt:Date.now()+3600000})
 finish(response({error:'INVALID_CREDENTIALS'},401));await first
 expect(s.session.value?.userId).toBe('b');expect(localStorage.getItem('myink.session')).toContain('b-token')
})
async function submitUpgrade() {
 window.dispatchEvent(new Event('myink:guest-upgrade'))
 const dialog=await screen.findByRole('dialog',{name:'注册保留作品'})
 await fireEvent.update(within(dialog).getByLabelText('用户名'),'alice')
 await fireEvent.update(within(dialog).getByLabelText('密码'),'password1')
 await fireEvent.update(within(dialog).getByLabelText('确认密码'),'password1')
 await fireEvent.update(within(dialog).getByLabelText('邀请码'),'invite')
 await fireEvent.click(within(dialog).getByRole('button',{name:'创建账号'}))
}
it.each(['renewal','expiry'] as const)('preserves the member response and mounted draft across pending guest upgrade %s',async boundary=>{
 let now=Date.now();vi.spyOn(Date,'now').mockImplementation(()=>now)
 stored(now+60000);let finish!:(value:Response)=>void
 const base=fixtures();let renewals=0
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/register'))return new Promise<Response>(resolve=>{finish=resolve})
  if(path.endsWith('/auth/guest')){renewals++;if(boundary==='expiry')return new Promise<Response>(()=>{});return response({...guest,token:'guest-rotated'})}
  return base(path,init)
 })
 await app();const editor=await screen.findByLabelText('对助手说');await fireEvent.update(editor,'注册等待期间的草稿')
 await submitUpgrade()
 if(boundary==='expiry')now+=120000
 document.dispatchEvent(new Event('visibilitychange'));await flushPromises()
 if(boundary==='renewal'){
  // Another tab may rotate this same identity even while local renewal is paused.
  setSession({token:'guest-rotated',userId:'g',username:'guest-g',tier:'normal',role:'user',roleVerified:false,isGuest:true,expiresAt:now+3600000})
  window.dispatchEvent(new StorageEvent('storage',{key:'myink.session'}));await flushPromises()
 }
 finish(response(member));await flushPromises()
 expect(localStorage.getItem('myink.session')).toContain('member-token')
 expect(screen.queryByRole('dialog')).toBeNull();expect(screen.getByLabelText('对助手说')).toBe(editor)
 expect((editor as HTMLTextAreaElement).value).toBe('注册等待期间的草稿')
 expect(renewals).toBe(0)
})
it('rejects pending guest upgrade success after actual account replacement',async()=>{
 stored();let finish!:(value:Response)=>void;const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/register'))return new Promise<Response>(resolve=>{finish=resolve})
  if(path.endsWith('/auth/session')&&(init.headers as Record<string,string>).Authorization==='Bearer b-token')return response({...member,user_id:'b',username:'bob',token:'b-token'})
  return base(path,init)
 })
 await app();const editor=await screen.findByLabelText('对助手说');await fireEvent.update(editor,'上一位游客的草稿')
 await submitUpgrade()
 setSession({token:'b-token',userId:'b',username:'bob',tier:'normal',role:'user',roleVerified:false,expiresAt:Date.now()+3600000})
 window.dispatchEvent(new StorageEvent('storage',{key:'myink.session'}));await flushPromises()
 finish(response(member));await flushPromises()
 expect(localStorage.getItem('myink.session')).toContain('b-token');expect(localStorage.getItem('myink.session')).not.toContain('member-token')
 const next=await screen.findByLabelText('对助手说');expect(next).not.toBe(editor);expect((next as HTMLTextAreaElement).value).toBe('')
})
it('uses positive balances after an oversized batch refusal and refreshes them after smaller admission',async()=>{
 stored();let remaining=3;let refuse=true;const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/guest/quota'))return response({...quota,long:{limit:10,used:10-remaining,remaining}})
  if(path.endsWith('/batches/generate')){
   if(refuse)return response({error:'GUEST_QUOTA_EXHAUSTED'},429)
   remaining=1;return response({task_id:'batch-small',trace_id:'trace',status:'queued'})
  }
  return base(path,init)
 })
 await app();await screen.findByLabelText('对助手说')
 await expect(api.generateBatch('book',{size:5,start:1})).rejects.toThrow('GUEST_QUOTA_EXHAUSTED');await flushPromises()
 const dialog=await screen.findByRole('dialog')
 expect(dialog.textContent).toContain('减少批次章数');expect(dialog.textContent).not.toContain('已用完')
 await fireEvent.click(within(dialog).getByRole('button',{name:'关闭注册'}))
 refuse=false;await api.generateBatch('book',{size:2,start:1});await flushPromises()
 expect(screen.queryByRole('dialog')).toBeNull()
 expect((await api.guestQuota('guest-token')).long.remaining).toBe(1)
})
it('identifies only the exhausted category while the other still has quota',async()=>{
 stored();const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/guest/quota'))return response({...quota,short:{limit:2,used:2,remaining:0}})
  if(path.endsWith('/short/generate'))return response({error:'GUEST_QUOTA_EXHAUSTED'},429)
  return base(path,init)
 })
 await app();await screen.findByLabelText('对助手说');expect(screen.queryByRole('dialog')).toBeNull()
 await expect(api.generateShort('book')).rejects.toThrow('GUEST_QUOTA_EXHAUSTED');await flushPromises()
 const region=screen.getByRole('dialog')
 expect(region.textContent).toContain('短篇体验额度已用完');expect(region.textContent).toContain('长篇仍可继续')
 expect(region.textContent).not.toContain('游客体验额度已用完');expect(region.textContent).not.toContain('长篇体验额度已用完')
})
it('reconciles deferred same-owner member credentials after a rejected pending upgrade without replacing the editor',async()=>{
 stored();let finish!:(value:Response)=>void;const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/auth/register'))return new Promise<Response>(resolve=>{finish=resolve})
  if(path.endsWith('/auth/session')&&(init.headers as Record<string,string>).Authorization==='Bearer member-other-tab')return response({...member,token:'member-other-tab'})
  return base(path,init)
 })
 await app();const editor=await screen.findByLabelText('对助手说');await fireEvent.update(editor,'另一个标签页升级后仍保留的草稿')
 await submitUpgrade()
 setSession({token:'member-other-tab',userId:'g',username:'alice',tier:'normal',role:'user',roleVerified:false,isGuest:false,expiresAt:Date.now()+3600000})
 window.dispatchEvent(new StorageEvent('storage',{key:'myink.session'}));await flushPromises()
 finish(response({error:'INVALID_CREDENTIALS'},401));await flushPromises()
 expect(localStorage.getItem('myink.session')).toContain('member-other-tab')
 expect(screen.queryByRole('dialog')).toBeNull();expect(screen.queryByRole('region',{name:'游客体验额度'})).toBeNull()
 expect(screen.getByLabelText('对助手说')).toBe(editor);expect((editor as HTMLTextAreaElement).value).toBe('另一个标签页升级后仍保留的草稿')
})

it('offers anonymous account registration without password-management cards or a second guest prompt',async()=>{
 vi.stubGlobal('fetch',fixtures());const router=await app('/account')
 expect(screen.queryByLabelText('当前密码')).toBeNull()
 expect(screen.queryByText('忘记密码')).toBeNull()
 await fireEvent.click(screen.getByRole('link',{name:'注册账号'}));await flushPromises()
 expect(router.currentRoute.value.query.mode).toBe('register')
 expect(screen.queryByRole('dialog')).toBeNull()
})
it('upgrades directly from the guest account page preserving identity',async()=>{
 stored();vi.stubGlobal('fetch',fixtures());const router=await app('/account')
 await fireEvent.update(await screen.findByLabelText('用户名'),'alice')
 await fireEvent.update(screen.getByLabelText('密码'),'password1')
 await fireEvent.update(screen.getByLabelText('确认密码'),'password1')
 await fireEvent.update(screen.getByLabelText('邀请码'),'invite')
 await fireEvent.click(screen.getByRole('button',{name:'创建账号'}));await flushPromises()
 expect(JSON.parse(localStorage.getItem('myink.session')!).userId).toBe('g')
 expect(router.currentRoute.value.path).toBe('/account')
 expect(screen.getByLabelText('当前密码')).toBeTruthy()
})
it.each([false,true])('delivers quota rejection across same-owner renewal but suppresses another owner (replace=%s)',async replaceOwner=>{
 stored();let finish!:(value:Response)=>void;const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/short/generate'))return new Promise<Response>(resolve=>{finish=resolve})
  if(path.endsWith('/auth/session')&&(init.headers as Record<string,string>).Authorization==='Bearer guest-renewed')return response({...guest,user_id:replaceOwner?'other':'g',token:'guest-renewed'})
  if(path.endsWith('/auth/guest/quota'))return response({...quota,short:{limit:2,used:2,remaining:0}})
  return base(path,init)
 })
 await app();const draft=await screen.findByLabelText('对助手说');await fireEvent.update(draft,'续期中的草稿')
 const pending=api.generateShort('book').catch(error=>error)
 setSession({token:'guest-renewed',userId:replaceOwner?'other':'g',username:'guest-renewed',tier:'normal',role:'user',roleVerified:false,isGuest:true,expiresAt:Date.now()+3600000})
 window.dispatchEvent(new StorageEvent('storage',{key:'myink.session'}));await flushPromises()
 finish(response({error:'GUEST_QUOTA_EXHAUSTED'},429));await pending;await flushPromises()
 if(replaceOwner){
  expect(screen.queryByRole('dialog')).toBeNull()
 }else{
  expect(await screen.findByRole('dialog')).toBeTruthy()
  expect(screen.getByLabelText('对助手说')).toBe(draft)
  expect((draft as HTMLTextAreaElement).value).toBe('续期中的草稿')
 }
})
it.each([10,0])('uses truthful generic quota advice for a short task resumed through generic task endpoint (long remaining=%s)',async remaining=>{
 stored();const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>{
  if(path.endsWith('/tasks/short-task/resume'))return response({error:'GUEST_QUOTA_EXHAUSTED'},429)
  if(path.endsWith('/auth/guest/quota'))return response({short:{limit:2,used:2,remaining:0},long:{limit:10,used:10-remaining,remaining}})
  return base(path,init)
 })
 await app();await screen.findByLabelText('对助手说')
 await expect(api.resumeTask('short-task')).rejects.toThrow('GUEST_QUOTA_EXHAUSTED');await flushPromises()
 const dialog=await screen.findByRole('dialog')
 expect(dialog.textContent).toContain('注册账号获取更多写作额度')
 expect(dialog.textContent).not.toContain('长篇体验额度已用完')
 expect(dialog.textContent).not.toContain('减少批次')
})
it('does not suggest reducing batch size for short generation with a newly replenished balance',async()=>{
 stored();const base=fixtures()
 vi.stubGlobal('fetch',async(path:string,init:RequestInit)=>path.endsWith('/short/generate')?response({error:'GUEST_QUOTA_EXHAUSTED'},429):base(path,init))
 await app();await screen.findByLabelText('对助手说')
 await expect(api.generateShort('book')).rejects.toThrow('GUEST_QUOTA_EXHAUSTED');await flushPromises()
 expect((await screen.findByRole('dialog')).textContent).not.toContain('减少批次')
})
