import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '../../src/lib/api'
import AccountPage from './pages/AccountPage.vue'
import { setSession } from '../../src/lib/token'
const auth = vi.hoisted(() => ({ value: {} as Record<string, unknown> }))
vi.mock('./authContext', () => ({ useAuth: () => auth.value }))
afterEach(() => { cleanup(); localStorage.clear(); vi.restoreAllMocks() })
it('retains in-progress password fields across same-owner renewal', async () => {
 const identity = { token: 'before', userId: 'a', username: 'alice', role: 'user', tier: 'normal', roleVerified: true }
 const session = ref(identity)
 auth.value = { session, status: ref('authenticated'), changePassword: vi.fn(), endSession: vi.fn() }
 vi.spyOn(api, 'listProjects').mockResolvedValue([])
 const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/account', component: AccountPage }] })
 await router.push('/account'); await router.isReady()
 render(AccountPage, { global: { plugins: [router] } })
 await flushPromises()
 await fireEvent.update(screen.getByLabelText('当前密码'), 'current-password')
 await fireEvent.update(screen.getByLabelText('新密码'), 'next-password1')
 session.value = { ...identity, token: 'after' }
 await flushPromises()
 expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('current-password')
 expect((screen.getByLabelText('新密码') as HTMLInputElement).value).toBe('next-password1')
})

it('retains unsaved environment preferences across same-owner renewal', async () => {
 const { default: EnvironmentPage } = await import('./pages/EnvironmentPage.vue')
 const identity = { token: 'before', userId: 'a', username: 'alice', role: 'user', tier: 'normal', roleVerified: true }
 const session = ref(identity)
 auth.value = { session, status: ref('authenticated'), logout: vi.fn() }
 vi.spyOn(api, 'listProjects').mockResolvedValue([])
 vi.spyOn(api, 'getEnvironment').mockResolvedValue({ model_routes: {}, model_connections: [], thinking_enabled: false, rankings: { enabled: true, timeout: 10, limit: 10 } })
 const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/environment', component: EnvironmentPage }] })
 await router.push('/environment'); await router.isReady()
 render(EnvironmentPage, { global: { plugins: [router] } })
 await flushPromises()
 await fireEvent.click(screen.getByRole('button', { name: '展开高级设置' }))
 await fireEvent.update(screen.getByLabelText('扫榜超时'), '8')
 session.value = { ...identity, token: 'after' }
 await flushPromises()
 expect((screen.getByLabelText('扫榜超时') as HTMLInputElement).value).toBe('8')
})

async function securityPage() {
 const session = ref<import('../../src/lib/token').StoredSession | null>({ token:'before',userId:'a',username:'alice',role:'admin',tier:'normal',roleVerified:true,expiresAt:Date.now()+3600000 })
 const status = ref('authenticated')
 auth.value = { session,status,logout:vi.fn(),changePassword:vi.fn(),endSession:vi.fn() }
 vi.spyOn(api,'mfaStatus').mockResolvedValue({enabled:false})
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]})
 await router.push('/account');await router.isReady()
 render(AccountPage,{global:{plugins:[router]}});await flushPromises()
 return {session,status}
}
it('retains MFA pairing and code through renewal and confirms using the current token',async()=>{
 const {session}=await securityPage()
 vi.spyOn(api,'mfaEnroll').mockResolvedValue({secret:'PAIRING',otpauth_uri:'otpauth://pairing'})
 vi.spyOn(api,'mfaConfirm').mockResolvedValue({ok:true})
 await fireEvent.update(screen.getByLabelText('账号密码'),'password');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 await fireEvent.update(await screen.findByLabelText('验证码'),'123456')
 session.value={...session.value!,token:'after'};await flushPromises()
 expect(screen.getByText('PAIRING')).toBeTruthy();expect((screen.getByLabelText('验证码') as HTMLInputElement).value).toBe('123456')
 await fireEvent.submit(screen.getByLabelText('验证码').closest('form')!)
 expect(api.mfaConfirm).toHaveBeenCalledWith('123456','after');expect(auth.value.endSession).toHaveBeenCalledOnce()
})
it('accepts an in-flight same-owner enrollment after renewal without allowing duplicate submissions',async()=>{
 const {session}=await securityPage();let finish!:(value:{secret:string;otpauth_uri:string})=>void
 vi.spyOn(api,'mfaEnroll').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 await fireEvent.update(screen.getByLabelText('账号密码'),'password');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 session.value={...session.value!,token:'after'};await flushPromises()
 expect((screen.getByRole('button',{name:'生成中…'}) as HTMLButtonElement).disabled).toBe(true)
 finish({secret:'LATE-SAME-OWNER',otpauth_uri:'otpauth://pairing'});await flushPromises()
 expect(screen.getByText('LATE-SAME-OWNER')).toBeTruthy()
})
it('clears security secrets on permission revocation and ignores the old enrollment',async()=>{
 const {session}=await securityPage();let finish!:(value:{secret:string;otpauth_uri:string})=>void
 vi.spyOn(api,'mfaEnroll').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 await fireEvent.update(screen.getByLabelText('当前密码'),'private');await fireEvent.update(screen.getByLabelText('账号密码'),'password');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 session.value={...session.value!,role:'user'};await flushPromises();finish({secret:'REVOKED',otpauth_uri:'otpauth://revoked'});await flushPromises()
 expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('');expect(screen.queryByText('REVOKED')).toBeNull();expect(screen.queryByText('两步验证')).toBeNull()
})
it('clears secrets on logout and on a different owner while rejecting the previous MFA response',async()=>{
 const {session,status}=await securityPage();let finish!:(value:{secret:string;otpauth_uri:string})=>void
 vi.spyOn(api,'mfaEnroll').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 await fireEvent.update(screen.getByLabelText('当前密码'),'private');await fireEvent.update(screen.getByLabelText('账号密码'),'password');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 session.value={...session.value!,userId:'b',token:'other'};await flushPromises();finish({secret:'OTHER-OWNER',otpauth_uri:'otpauth://old'});await flushPromises()
 expect(screen.queryByText('OTHER-OWNER')).toBeNull();expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('')
 await fireEvent.update(screen.getByLabelText('当前密码'),'new-private');session.value=null;status.value='anonymous';await flushPromises()
 expect((screen.getByLabelText('当前密码') as HTMLInputElement).value).toBe('')
})
it('keeps environment save busy through renewal and applies its successful response',async()=>{
 const {default:EnvironmentPage}=await import('./pages/EnvironmentPage.vue')
 const session=ref({token:'before',userId:'a'});auth.value={session,status:ref('authenticated'),logout:vi.fn()}
 const env={model_routes:{},model_connections:[],thinking_enabled:false,rankings:{enabled:true,timeout:10,limit:10}}
 vi.spyOn(api,'listProjects').mockResolvedValue([]);vi.spyOn(api,'getEnvironment').mockResolvedValue(env)
 let finish!:(value:typeof env)=>void;vi.spyOn(api,'updateEnvironment').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div />'}}]});await router.push('/environment')
 render(EnvironmentPage,{global:{plugins:[router]}});await flushPromises();await fireEvent.click(screen.getByRole('button',{name:'展开高级设置'}));await fireEvent.update(screen.getByLabelText('扫榜超时'),'8');await fireEvent.click(screen.getByRole('button',{name:'保存扫榜配置'}))
 session.value={...session.value,token:'after'};await flushPromises()
 expect(api.getEnvironment).toHaveBeenCalledTimes(1);expect((screen.getByRole('button',{name:'保存中…'}) as HTMLButtonElement).disabled).toBe(true)
 finish({...env,rankings:{...env.rankings,timeout:8}});await flushPromises();expect((screen.getByLabelText('扫榜超时') as HTMLInputElement).value).toBe('8');expect((screen.getByRole('button',{name:'保存扫榜配置'}) as HTMLButtonElement).disabled).toBe(false)
})

it('rejects an old enrollment when stored access was revoked before the storage event arrives',async()=>{
 const {session}=await securityPage();let finish!:(value:{secret:string;otpauth_uri:string})=>void
 vi.spyOn(api,'mfaEnroll').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 await fireEvent.update(screen.getByLabelText('账号密码'),'password');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 setSession({...session.value!,token:'revoked',role:'user',roleVerified:true})
 finish({secret:'QUEUED-REVOKED',otpauth_uri:'otpauth://revoked'});await flushPromises()
 expect(screen.queryByText('QUEUED-REVOKED')).toBeNull();expect(auth.value.endSession).not.toHaveBeenCalled()
})
