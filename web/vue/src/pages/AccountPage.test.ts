import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/vue'
import { ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { api } from '../../../src/lib/api'
import AccountPage from './AccountPage.vue'
const auth = vi.hoisted(() => ({value:{} as Record<string,unknown>}))
vi.mock('../authContext',()=>({useAuth:()=>auth.value}))
async function page(role='admin',verified=true) {
 auth.value={session:ref({token:'old',userId:'a',username:'alice',tier:'normal',role,roleVerified:verified}),status:ref('authenticated'),logout:vi.fn(),changePassword:vi.fn().mockResolvedValue(undefined),endSession:vi.fn()}
 vi.spyOn(api,'listProjects').mockResolvedValue([]); vi.spyOn(api,'mfaStatus').mockResolvedValue({enabled:false})
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/:pathMatch(.*)*',component:{template:'<div/>'}}]}); await router.push('/account')
 const view=render(AccountPage,{global:{plugins:[router]}}); return {...view,router}
}
afterEach(()=>{cleanup();vi.restoreAllMocks()})
it('validates passwords and changes them without persisting sensitive fields',async()=>{
 await page('user'); await fireEvent.update(screen.getByLabelText('当前密码'),'old'); await fireEvent.update(screen.getByLabelText('新密码'),'abcdefgh'); await fireEvent.update(screen.getByLabelText('确认新密码'),'abcdefgh')
 await fireEvent.submit(screen.getByLabelText('新密码').closest('form')!); expect(screen.getByRole('alert')).toBeTruthy(); expect(auth.value.changePassword).not.toHaveBeenCalled()
 await fireEvent.update(screen.getByLabelText('新密码'),'abcdefg1'); await fireEvent.update(screen.getByLabelText('确认新密码'),'abcdefg1'); await fireEvent.submit(screen.getByLabelText('新密码').closest('form')!); expect(auth.value.changePassword).toHaveBeenCalledWith('old','abcdefg1'); expect(localStorage.length).toBe(0)
})
it('only exposes admin security for a verified administrator',async()=>{const v=await page('admin',false);expect(screen.queryByText('两步验证')).toBeNull();v.unmount();await page();expect(await screen.findByLabelText('账号密码')).toBeTruthy();expect(screen.getByRole('navigation',{name:'平台管理导航'})).toBeTruthy()})
it('enrolls using account password and confirms then revokes and navigates to login',async()=>{
 const {router}=await page();vi.spyOn(api,'mfaEnroll').mockResolvedValue({secret:'MEMORY-SECRET',otpauth_uri:'otpauth://memory'});vi.spyOn(api,'mfaConfirm').mockResolvedValue({ok:true})
 await fireEvent.update(await screen.findByLabelText('账号密码'),'old');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!);expect(await screen.findByText('MEMORY-SECRET')).toBeTruthy();expect(localStorage.length).toBe(0)
 await fireEvent.update(screen.getByLabelText('验证码'),'123456');await fireEvent.submit(screen.getByLabelText('验证码').closest('form')!);await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/login'));expect(auth.value.endSession).toHaveBeenCalledOnce()
})
it('ignores enrollment responses after an account switch',async()=>{
 await page();let finish!:(value:{secret:string;otpauth_uri:string})=>void;vi.spyOn(api,'mfaEnroll').mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
 await fireEvent.update(await screen.findByLabelText('账号密码'),'old');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!);
 (auth.value.session as ReturnType<typeof ref>).value={token:'new',userId:'b',username:'bob',tier:'normal',role:'user',roleVerified:true};finish({secret:'STALE-SECRET',otpauth_uri:'otpauth://stale'})
 await vi.waitFor(()=>expect(within(screen.getByRole('main')).getByText('bob')).toBeTruthy());expect(screen.queryByText('STALE-SECRET')).toBeNull();expect(auth.value.endSession).not.toHaveBeenCalled()
})
it('keeps sessions on rejected confirmation codes and permits retry',async()=>{
 await page();vi.spyOn(api,'mfaEnroll').mockResolvedValue({secret:'MEMORY',otpauth_uri:'otpauth://memory'});vi.spyOn(api,'mfaConfirm').mockRejectedValue(new Error('验证码无效'))
 await fireEvent.update(await screen.findByLabelText('账号密码'),'old');await fireEvent.submit(screen.getByLabelText('账号密码').closest('form')!)
 await fireEvent.update(await screen.findByLabelText('验证码'),'123');await fireEvent.submit(screen.getByLabelText('验证码').closest('form')!);expect(await screen.findByRole('alert')).toHaveProperty('textContent','请输入 6 位验证码')
 await fireEvent.update(screen.getByLabelText('验证码'),'123456');await fireEvent.submit(screen.getByLabelText('验证码').closest('form')!);expect((await screen.findByRole('alert')).textContent).toContain('开启两步验证失败');expect(auth.value.endSession).not.toHaveBeenCalled();expect((screen.getByRole('button',{name:'确认开启'}) as HTMLButtonElement).disabled).toBe(false)
})
it('disables an enabled second factor and re-enters login',async()=>{
 const{router}=await page();vi.mocked(api.mfaStatus).mockResolvedValue({enabled:true});(auth.value.session as ReturnType<typeof ref>).value={token:'admin-new',userId:'a',username:'alice',tier:'normal',role:'admin',roleVerified:true};vi.spyOn(api,'mfaDisable').mockResolvedValue({ok:true})
 await fireEvent.update(await screen.findByLabelText('验证码'),'123456');await fireEvent.submit(screen.getByLabelText('验证码').closest('form')!);await vi.waitFor(()=>expect(router.currentRoute.value.path).toBe('/login'));expect(auth.value.endSession).toHaveBeenCalledWith('两步验证已关闭，本次登录已失效，请重新登录。')
})
