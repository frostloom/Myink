import { readonly, ref, shallowRef } from 'vue'
import { abortRequestsForToken, api, ApiError } from '../../src/lib/api'
import { clearSession, getSession, setSession, SESSION_STORAGE_KEY, UNAUTHORIZED_EVENT, type StoredSession } from '../../src/lib/token'
import type { AuthResponse } from '../../src/types'

export type LoginResult = { status: 'authenticated' } | { status: 'mfa'; mfaToken: string }
export type SessionScope = ReturnType<typeof createSessionScope>

export function createSessionScope() {
  const session = shallowRef<StoredSession | null>(null)
  const status = ref<'checking' | 'authenticated' | 'anonymous' | 'unavailable'>('checking')
  const error = ref<string | null>(null)
  const notice = ref<string | null>(null)
  let generation = 0
  let loginVersion = 0
  let controller: AbortController | null = null
  let guestPending: AbortController | null = null
  let pendingUpgrade: { userId: string } | null = null
  let renewal: AbortController | null = null
  let active = false
  let timer: number | undefined
  let logoutTimer: number | undefined
  // A rotated token can still have valid business requests in flight. Keep all
  // tokens for this account until an actual account change or disposal.
  const accountTokens = new Set<string>()

  function abortAccount() {
    for (const token of accountTokens) abortRequestsForToken(token)
    accountTokens.clear()
  }
  function apply(next: StoredSession | null, nextStatus: typeof status.value, persist = false) {
    if (session.value?.userId !== next?.userId) abortAccount()
    if (persist) { if (next) setSession(next); else clearSession() }
    if (next) accountTokens.add(next.token)
    session.value = next
    status.value = nextStatus
    error.value = null
  }
  function invalidate() {
    generation++
    controller?.abort()
    renewal?.abort()
    renewal = null
  }
  function reset() { invalidate(); apply(null, 'anonymous') }
  function failClosedStorage() {
    invalidate()
    apply(null, 'unavailable')
    error.value = '无法清理登录存储，请检查浏览器存储权限后重试。'
    notice.value = '当前页面已停止使用登录凭据，但无法确认浏览器中的凭据已清除，请恢复存储权限后重新检查登录状态。'
  }
  function fromAuth(resp: AuthResponse): StoredSession {
    return { token: resp.token, userId: resp.user_id, username: resp.username, tier: resp.tier, role: resp.role, roleVerified: true, isGuest: resp.is_guest === true, expiresAt: Date.now() + Math.max(0, resp.expires_in) * 1000 }
  }
  async function revalidate() {
    if (!active) return
    invalidate()
    const id = generation
    let candidate: StoredSession | null
    try { candidate = getSession(true) } catch {
      apply(null, 'unavailable')
      error.value = '无法读取登录状态，请检查浏览器存储权限。'
      return
    }
    if (!candidate) { apply(null, 'anonymous'); return }
    if (candidate.isGuest && candidate.expiresAt !== null && candidate.expiresAt <= Date.now()) {
      await restoreGuest()
      return
    }
    const previous = session.value
    const background = status.value === 'authenticated' && previous?.userId === candidate.userId
    // Same-account cache writes may supply a new token, but never a new verified
    // role. Keep the last server identity while validating in the background.
    apply(background ? { ...candidate, role: previous.role, roleVerified: previous.roleVerified, username: previous.username, tier: previous.tier, isGuest: previous.isGuest } : candidate, background ? 'authenticated' : 'checking')
    const request = new AbortController()
    controller = request
    try {
      const remote = await api.getSession(candidate.token, request.signal, false)
      if (!active || id !== generation || request.signal.aborted) return
      if (getSession()?.token !== candidate.token) { await revalidate(); return }
      apply({ ...candidate, userId: remote.user_id, username: remote.username, tier: remote.tier, role: remote.role, roleVerified: true, isGuest: remote.is_guest === true }, 'authenticated', true)
    } catch (err) {
      if (!active || id !== generation || request.signal.aborted) return
      try {
        if (getSession()?.token !== candidate.token) { await revalidate(); return }
      } catch {
        status.value = 'unavailable'
        error.value = '无法读取登录状态，请检查浏览器存储权限。'
        return
      }
      if (err instanceof ApiError && err.status === 401) {
        if (candidate.isGuest) {
          await restoreGuest()
        } else { try { clearSession(); reset() } catch { failClosedStorage() } }
        return
      }
      if (background) return
      status.value = 'unavailable'
      error.value = err instanceof ApiError && err.code === 'request_aborted' ? '登录状态校验已中断，请重试。' : '暂时无法验证登录状态，请确认网关已启动后重试。'
    }
  }
  function upgradingCurrentGuest() {
    return pendingUpgrade !== null && session.value?.userId === pendingUpgrade.userId && getSession(true)?.userId === pendingUpgrade.userId
  }
  async function renew() {
    const current = session.value
    if (!current || renewal || upgradingCurrentGuest()) return
    const request = new AbortController()
    renewal = request
    const id = generation
    try {
      const remote = current.isGuest ? await api.startGuest(true, request.signal) : await api.getSession(current.token, request.signal)
      if (!active || request.signal.aborted || id !== generation) return
      if (getSession(true)?.token !== current.token) { await revalidate(); return }
      if (!remote.token || !(remote.expires_in > 0)) return
      apply({ ...current, userId: remote.user_id, token: remote.token, username: remote.username, tier: remote.tier, role: remote.role, roleVerified: true, isGuest: remote.is_guest === true, expiresAt: Date.now() + remote.expires_in * 1000 }, 'authenticated', true)
    } catch {
      if (active && id === generation) {
        try { if (getSession()?.token !== current.token) await revalidate() } catch {
          status.value = 'unavailable'
          error.value = '无法读取登录状态，请检查浏览器存储权限。'
        }
      }
      // Network failures leave the verified session usable until hard expiry.
    } finally { if (renewal === request) renewal = null }
  }
  function tick() {
    const current = session.value
    if (!active || status.value !== 'authenticated' || !current?.expiresAt) return
    try {
      if (upgradingCurrentGuest()) return
      if (Date.now() >= current.expiresAt) {
        if (getSession()?.token && getSession()?.token !== current.token) { void revalidate(); return }
        if (current.isGuest) { void renew(); return }
        clearSession(); reset(); return
      }
      if (Date.now() >= current.expiresAt - 300000) void renew()
    } catch {
      status.value = 'unavailable'
      error.value = '无法读取登录状态，请检查浏览器存储权限。'
    }
  }
  function onVisible() { if (document.visibilityState === 'visible') tick() }
  function onStorage(event: StorageEvent) {
    if (event.key === null || event.key === SESSION_STORAGE_KEY || event.key === 'myink.token') {
      try { if (upgradingCurrentGuest()) return } catch { /* revalidate reports inaccessible storage. */ }
      void revalidate()
    }
  }
  function onUnauthorized(event: Event) {
    const token = (event as CustomEvent<{ token: string | null }>).detail?.token
    if (!session.value || token !== session.value.token) return
    try {
      if (upgradingCurrentGuest()) return
      if (getSession()?.token !== token) { void revalidate(); return }
      if (session.value.isGuest) { void restoreGuest(); return }
      clearSession(); reset()
    } catch { failClosedStorage() }
  }
  async function start() {
    if (active) return
    active = true
    window.addEventListener('storage', onStorage)
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    document.addEventListener('visibilitychange', onVisible)
    timer = window.setInterval(tick, 60000)
    await revalidate()
  }
  function dispose() {
    active = false
    invalidate(); abortAccount()
    window.clearInterval(timer)
    window.clearTimeout(logoutTimer)
    window.removeEventListener('storage', onStorage)
    window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    document.removeEventListener('visibilitychange', onVisible)
  }
  async function restoreGuest() {
    try { await startGuest({ restoreOnly: true }) } catch { /* Only the current request may update recovery state. */ }
  }
  async function startGuest(options: { restoreOnly?: boolean } = {}): Promise<LoginResult | null> {
    if (guestPending && !guestPending.signal.aborted) return null
    invalidate()
    const id = generation
    const request = new AbortController()
    controller = guestPending = request
    let storedToken: string | null = null
    try {
      storedToken = getSession(true)?.token ?? null
      const resp = await api.startGuest(options.restoreOnly === true, request.signal)
      if (!active || id !== generation || request.signal.aborted) return null
      if ((getSession(true)?.token ?? null) !== storedToken) { await revalidate(); return null }
      loginVersion++
      apply(fromAuth(resp), 'authenticated', true)
      notice.value = null
      return { status: 'authenticated' }
    } catch (err) {
      if (active && id === generation && !request.signal.aborted && options.restoreOnly) {
        try {
          if ((getSession(true)?.token ?? null) !== storedToken) { await revalidate(); return null }
          if (err instanceof ApiError && err.status === 401) {
            apply(null, 'anonymous', true)
            notice.value = '游客身份已失效，请重新选择游客体验或登录。'
          } else {
            status.value = 'unavailable'
            error.value = '游客身份暂时无法恢复，请重试。'
          }
        } catch { failClosedStorage() }
      }
      throw err
    } finally { if (guestPending === request) guestPending = null }
  }
  async function authenticate(action: 'login' | 'register', username: string, password: string, invitationCode = ''): Promise<LoginResult | null> {
    invalidate()
    const id = generation
    const upgrade = action === 'register' && session.value?.isGuest ? { userId: session.value.userId } : null
    if (upgrade) pendingUpgrade = upgrade
    try {
      const storedToken = getSession(Boolean(upgrade))?.token ?? null
      const resp = action === 'login' ? await api.login(username, password) : await api.register(username, password, invitationCode, upgrade ? session.value!.token : null)
      if (!active || id !== generation) return null
      const stored = getSession(Boolean(upgrade))
      // A guest upgrade retains ownership across expiry or another tab's token
      // rotation. A different account must still invalidate the response.
      if (upgrade ? stored?.userId !== upgrade.userId : (stored?.token ?? null) !== storedToken) { await revalidate(); return null }
      if ('mfa_required' in resp) return { status: 'mfa', mfaToken: resp.mfa_token }
      loginVersion++
      apply(fromAuth(resp), 'authenticated', true); notice.value = null
      return { status: 'authenticated' }
    } finally {
      if (pendingUpgrade === upgrade) {
        pendingUpgrade = null
        if (upgrade && active && id === generation) {
          try {
            const stored = getSession(true)
            // Reconcile a same-owner storage event deferred during registration.
            // Unchanged invitation failures retain the form and its error.
            if (stored?.userId === upgrade.userId && stored.token !== session.value?.token) await revalidate()
          } catch { await revalidate() }
        }
      }
    }
  }
  const login = (username: string, password: string) => authenticate('login', username, password)
  const register = (username: string, password: string, invitationCode: string) => authenticate('register', username, password, invitationCode)
  async function completeMfa(ticket: string, code: string): Promise<boolean> {
    invalidate()
    const id = generation
    const storedToken = getSession()?.token ?? null
    const resp = await api.verifyMfa(ticket, code)
    if (!active || id !== generation) return false
    if ((getSession()?.token ?? null) !== storedToken) { await revalidate(); return false }
    loginVersion++
    apply(fromAuth(resp), 'authenticated', true); notice.value = null
    return true
  }
  async function logout() {
    const current = session.value
    if (!current) return
    invalidate()
    const id = generation
    abortAccount()
    status.value = 'checking'
    const request = new AbortController()
    controller = request
    let timeout: number | undefined
    let remoteFailed = false
    try {
      await Promise.race([api.logout(current.token, request.signal), new Promise<never>((_, reject) => {
        timeout = logoutTimer = window.setTimeout(() => { request.abort(); reject(new Error('logout_timeout')) }, 5000)
      })])
    } catch {
      remoteFailed = true
    } finally {
      window.clearTimeout(timeout)
      request.abort()
      if (active && id === generation) {
        try {
          // Check identity before deleting anything: inaccessible storage may
          // already contain another tab's account, so never guess its owner.
          if (getSession()?.token !== current.token) await revalidate()
          else {
            clearSession()
            reset()
            if (remoteFailed) notice.value = '无法联系服务器，已仅从本机退出；该登录会在凭据过期后失效。'
          }
        } catch {
          failClosedStorage()
        }
      }
    }
  }

  function endSession(message: string): void {
    invalidate()
    abortAccount()
    try { apply(null, 'anonymous', true); notice.value = message } catch { failClosedStorage() }
  }
  async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const current = session.value
    if (!current) return
    const loginId = loginVersion
    await api.changePassword(currentPassword, newPassword, current.token)
    if (!active || loginId !== loginVersion || session.value?.userId !== current.userId) return
    try {
      const stored = getSession()
      if (stored?.token !== current.token) {
        // Renewal and other tabs may supply credentials issued before revocation,
        // or a valid login issued afterwards. Let the server decide their validity.
        await revalidate()
        if (active && loginId === loginVersion && status.value === 'anonymous' && stored?.userId === current.userId) notice.value = '密码已修改，请重新登录。'
        return
      }
      endSession('密码已修改，请重新登录。')
    } catch { failClosedStorage() }
  }

  return { session: readonly(session), status: readonly(status), error: readonly(error), notice: readonly(notice), start, revalidate, dispose, logout, login, register, startGuest, completeMfa, endSession, changePassword }
}
