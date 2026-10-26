import { afterEach, expect, it, vi } from 'vitest'
import { api, ApiError } from '../../src/lib/api'
import { setSession } from '../../src/lib/token'
import { createSessionScope } from './session'
let scope: ReturnType<typeof createSessionScope> | undefined
afterEach(()=>{scope?.dispose();localStorage.clear();vi.restoreAllMocks()})
it('rechecks same-owner rotated credentials after a password change revokes them',async()=>{
 const stored={token:'old',userId:'a',username:'alice',tier:'normal' as const,role:'user' as const,roleVerified:true,expiresAt:Date.now()+3600000}
 let revoked=false
 vi.spyOn(api,'getSession').mockImplementation(async token=>{if(revoked)throw new ApiError(401,'revoked',null);return {token:token!,user_id:'a',username:'alice',tier:'normal',role:'user',expires_in:3600}})
 let finish!:()=>void
 vi.spyOn(api,'changePassword').mockImplementation(()=>new Promise(resolve=>{finish=()=>{revoked=true;resolve({ok:true})}}))
 setSession(stored);scope=createSessionScope();await scope.start()
 const pending=scope.changePassword('old-password','new-password1')
 setSession({...stored,token:'rotated'});await scope.revalidate()
 expect(scope.session.value?.token).toBe('rotated')
 finish();await pending
 expect(scope.status.value).toBe('anonymous')
})

it('finishes password-change logout after a same-token session verification',async()=>{
 const stored={token:'unchanged',userId:'a',username:'alice',tier:'normal' as const,role:'user' as const,roleVerified:true,expiresAt:Date.now()+3600000}
 vi.spyOn(api,'getSession').mockResolvedValue({token:'unchanged',user_id:'a',username:'alice',tier:'normal',role:'user',expires_in:3600})
 let finish!:()=>void;vi.spyOn(api,'changePassword').mockImplementation(()=>new Promise(resolve=>{finish=()=>resolve({ok:true})}))
 setSession(stored);scope=createSessionScope();await scope.start()
 const pending=scope.changePassword('old-password','new-password1')
 await scope.revalidate()
 expect(scope.session.value?.token).toBe('unchanged')
 finish();await pending
 expect(scope.status.value).toBe('anonymous')
 expect(scope.notice.value).toContain('密码已修改')
})

it.each(['a', 'b'])('preserves a later valid login for owner %s', async owner => {
 const stored={token:'old',userId:'a',username:'alice',tier:'normal' as const,role:'user' as const,roleVerified:true,expiresAt:Date.now()+3600000}
 vi.spyOn(api,'getSession').mockResolvedValue({token:'old',user_id:'a',username:'alice',tier:'normal',role:'user',expires_in:3600})
 let finish!:()=>void
 vi.spyOn(api,'changePassword').mockImplementation(()=>new Promise(resolve=>{finish=()=>resolve({ok:true})}))
 vi.spyOn(api,'login').mockResolvedValue({token:'new-login',user_id:owner,username:'new',tier:'normal',role:'user',expires_in:3600})
 setSession(stored);scope=createSessionScope();await scope.start()
 const pending=scope.changePassword('old-password','new-password1')
 await scope.login('new','new-password1');finish();await pending
 expect(scope.status.value).toBe('authenticated');expect(scope.session.value?.token).toBe('new-login')
})

it('preserves a valid same-owner credential from another tab after password success', async()=>{
 const stored={token:'old',userId:'a',username:'alice',tier:'normal' as const,role:'user' as const,roleVerified:true,expiresAt:Date.now()+3600000}
 const verify=vi.spyOn(api,'getSession').mockImplementation(async token=>({token:token!,user_id:'a',username:'alice',tier:'normal',role:'user',expires_in:3600}))
 let finish!:()=>void;vi.spyOn(api,'changePassword').mockImplementation(()=>new Promise(resolve=>{finish=()=>resolve({ok:true})}))
 setSession(stored);scope=createSessionScope();await scope.start()
 const pending=scope.changePassword('old-password','new-password1')
 setSession({...stored,token:'valid-new'});await scope.revalidate();verify.mockClear()
 finish();await pending
 expect(verify).toHaveBeenCalledWith('valid-new',expect.any(AbortSignal))
 expect(scope.session.value?.token).toBe('valid-new');expect(scope.status.value).toBe('authenticated')
})

it('rechecks a token renewed while password mutation was pending',async()=>{
 vi.useFakeTimers()
 try {
  const stored={token:'old',userId:'a',username:'alice',tier:'normal' as const,role:'user' as const,roleVerified:true,expiresAt:Date.now()+240000}
  let revoked=false
  vi.spyOn(api,'getSession').mockImplementation(async()=>{if(revoked)throw new ApiError(401,'revoked',null);return {token:'renewed',user_id:'a',username:'alice',tier:'normal',role:'user',expires_in:3600}})
  let finish!:()=>void;vi.spyOn(api,'changePassword').mockImplementation(()=>new Promise(resolve=>{finish=()=>{revoked=true;resolve({ok:true})}}))
  setSession(stored);scope=createSessionScope();await scope.start()
  const pending=scope.changePassword('old-password','new-password1')
  await vi.advanceTimersByTimeAsync(60000)
  expect(scope.session.value?.token).toBe('renewed')
  finish();await pending
  expect(scope.status.value).toBe('anonymous');expect(scope.notice.value).toContain('密码已修改')
 } finally { vi.useRealTimers() }
})
