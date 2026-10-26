import { afterEach, expect, it, vi } from 'vitest'
import { createSessionScope } from './session'
import { api } from '../../src/lib/api'
import { getSession, setSession } from '../../src/lib/token'
const stored = { token: 'old', userId: 'a', username: 'alice', tier: 'normal' as const, role: 'user' as const, roleVerified: true, expiresAt: Date.now()+3600000 }
let scope: ReturnType<typeof createSessionScope>
async function start() { setSession(stored); vi.spyOn(api, 'getSession').mockResolvedValue({user_id:'a',username:'alice',tier:'normal',role:'user',token:'old',expires_in:3600}); scope = createSessionScope(); await scope.start() }
afterEach(() => { scope?.dispose(); localStorage.clear(); vi.restoreAllMocks() })
it('revokes password-changed credentials and exposes the re-login notice', async () => {
 await start(); vi.spyOn(api,'changePassword').mockResolvedValue({ok:true}); await scope.changePassword('old','new123456')
 expect(getSession()).toBeNull(); expect(scope.status.value).toBe('anonymous'); expect(scope.notice.value).toContain('密码已修改')
})
it('does not clear a new account when the previous password request finishes late', async () => {
 await start(); let finish!: () => void; vi.spyOn(api,'changePassword').mockImplementation(() => new Promise(resolve => { finish=()=>resolve({ok:true}) }))
 const pending = scope.changePassword('old','new123456'); setSession({...stored,token:'new',userId:'b',username:'bob'}); finish(); await pending
 expect(getSession()?.token).toBe('new')
})
it('ends a session locally with a caller notice', async () => { await start(); scope.endSession('重新登录'); expect(getSession()).toBeNull(); expect(scope.notice.value).toBe('重新登录') })
