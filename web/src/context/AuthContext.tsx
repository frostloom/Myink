// 登录态：原子 localStorage 会话 + 服务端校验。账号切换时终止旧 token 请求，
// 旧请求的 401/登录响应也不能清空或覆盖新账号。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { abortRequestsForToken, api } from '../lib/api'
import {
  clearSession,
  getSession as readStoredSession,
  SESSION_STORAGE_KEY,
  setSession as storeSession,
  UNAUTHORIZED_EVENT,
  type StoredSession,
} from '../lib/token'

export type AuthStatus = 'checking' | 'authenticated' | 'anonymous' | 'unavailable'

/** 令牌到期前多久去换新的：留出重试余量，写作中途掉线的代价远大于多签一张令牌 */
const RENEW_LEAD_MS = 5 * 60 * 1000
/** 续期检查周期，兼作失败后的重试间隔 */
const RENEW_POLL_MS = 60 * 1000

interface AuthState {
  session: StoredSession | null
  status: AuthStatus
  validationError: string | null
  notice: string | null
  login: (username: string, password: string) => Promise<boolean>
  register: (username: string, password: string, invitationCode: string) => Promise<boolean>
  logout: () => Promise<void>
  changePassword: (currentPassword: string, newPassword: string) => Promise<void>
  revalidate: () => void
}

const AuthContext = createContext<AuthState | null>(null)

function fromAuthResponse(resp: {
  token: string
  user_id: string
  username: string
  tier: string
  role: 'user' | 'admin'
  expires_in: number
}): StoredSession {
  return {
    token: resp.token,
    userId: resp.user_id,
    username: resp.username,
    tier: resp.tier,
    role: resp.role,
    roleVerified: true,
    expiresAt: Date.now() + Math.max(0, resp.expires_in) * 1000,
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const initial = useRef<StoredSession | null | undefined>(undefined)
  if (initial.current === undefined) initial.current = readStoredSession()

  const [session, setSessionState] = useState<StoredSession | null>(initial.current)
  const [status, setStatus] = useState<AuthStatus>(initial.current ? 'checking' : 'anonymous')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const sessionRef = useRef<StoredSession | null>(initial.current)
  const generationRef = useRef(0)
  const validationRef = useRef<AbortController | null>(null)
  const renewRef = useRef<AbortController | null>(null)
  const validateRunnerRef = useRef<(candidate: StoredSession) => void>(() => {})

  const applySession = useCallback((
    next: StoredSession | null,
    persist: boolean,
    nextStatus: AuthStatus,
  ) => {
    const previous = sessionRef.current
    // 换账号才终止旧 token 的在途请求。滑动续期也换 token 但不换账号：那些请求拿的
    // 旧令牌还没被吊销、本身完全有效，续期时打断它们等于把一次正常轮换变成报错。
    if (previous?.token && previous.token !== next?.token
      && previous.userId !== next?.userId) {
      abortRequestsForToken(previous.token)
    }
    sessionRef.current = next
    if (persist) {
      if (next) storeSession(next)
      else clearSession()
    }
    setSessionState(next)
    setStatus(nextStatus)
    setValidationError(null)
  }, [])

  const syncFromStorage = useCallback(() => {
    ++generationRef.current
    validationRef.current?.abort()
    const stored = readStoredSession()
    if (!stored) {
      applySession(null, false, 'anonymous')
      return
    }
    applySession(stored, false, 'checking')
    validateRunnerRef.current(stored)
  }, [applySession])

  const validate = useCallback((candidate: StoredSession) => {
    const generation = ++generationRef.current
    validationRef.current?.abort()
    const controller = new AbortController()
    validationRef.current = controller
    applySession(candidate, false, 'checking')

    void api.getSession(candidate.token, controller.signal).then((remote) => {
      if (controller.signal.aborted || generation !== generationRef.current) return
      if (sessionRef.current?.token !== candidate.token) return
      if (readStoredSession()?.token !== candidate.token) {
        syncFromStorage()
        return
      }
      applySession({
        ...candidate,
        userId: remote.user_id,
        username: remote.username,
        tier: remote.tier,
        role: remote.role,
        roleVerified: true,
      }, true, 'authenticated')
    }).catch((err: unknown) => {
      if (controller.signal.aborted || generation !== generationRef.current) return
      if (sessionRef.current?.token !== candidate.token) return
      if (readStoredSession()?.token !== candidate.token) {
        syncFromStorage()
        return
      }
      const code = typeof err === 'object' && err !== null && 'code' in err
        ? String((err as { code: unknown }).code)
        : ''
      if (code === 'request_aborted') return
      if (typeof err === 'object' && err !== null && 'status' in err
        && (err as { status: unknown }).status === 401) {
        applySession(null, true, 'anonymous')
        return
      }
      setStatus('unavailable')
      setValidationError('暂时无法验证登录状态，请确认网关已启动后重试。')
    })
  }, [applySession, syncFromStorage])
  validateRunnerRef.current = validate

  /**
   * 滑动续期：拿手上的令牌去 /auth/session 换一张新的。
   *
   * 刻意不走 validate()：那条路会把 status 打回 checking（整页闪成「正在验证登录
   * 状态…」），而且它的守卫按令牌比对，续期自己就会把自己判成过时。
   */
  const renewSession = useCallback(async () => {
    const current = sessionRef.current
    if (!current || renewRef.current) return
    const controller = new AbortController()
    renewRef.current = controller
    try {
      const remote = await api.getSession(current.token, controller.signal)
      if (controller.signal.aborted) return
      // 老版本后端只回身份、不回新令牌。宁可不续期也不能把会话写坏：缺 token 的会话会被
      // getSession() 判成无效，等于当场把人登出——比不做续期还糟。
      if (!remote.token || !(remote.expires_in > 0)) return
      if (sessionRef.current?.token !== current.token) return
      if (readStoredSession()?.token !== current.token) {
        syncFromStorage()
        return
      }
      applySession({
        ...current,
        token: remote.token,
        username: remote.username,
        tier: remote.tier,
        role: remote.role,
        roleVerified: true,
        expiresAt: Date.now() + Math.max(0, remote.expires_in) * 1000,
      }, true, 'authenticated')
    } catch {
      // 401 已由 api 层派发 unauthorized 统一登出；网络抖动不在这里处理——
      // 留给下一个周期重试，只要还没到硬到期就不该动登录态。
    } finally {
      if (renewRef.current === controller) renewRef.current = null
    }
  }, [applySession, syncFromStorage])

  useEffect(() => {
    const onUnauthorized = (event: Event) => {
      const token = event instanceof CustomEvent
        && typeof event.detail === 'object'
        && event.detail !== null
        && 'token' in event.detail
        ? (event.detail as { token: unknown }).token
        : null
      if (token && token !== sessionRef.current?.token) return
      const persistedToken = readStoredSession()?.token ?? null
      if (persistedToken !== sessionRef.current?.token) {
        syncFromStorage()
        return
      }
      ++generationRef.current
      validationRef.current?.abort()
      applySession(null, true, 'anonymous')
    }

    const onStorage = (event: StorageEvent) => {
      if (event.key !== SESSION_STORAGE_KEY) return
      const stored = readStoredSession()
      // 别的标签页刚续期（换了令牌、没换账号）：把新令牌同步过来即可，别走 validate——
      // 那会把 status 打回 checking，正在写作的页面整页闪成「正在验证登录状态…」。
      if (stored && stored.userId === sessionRef.current?.userId) {
        ++generationRef.current
        validationRef.current?.abort()
        applySession(
          { ...stored, roleVerified: sessionRef.current?.roleVerified ?? false },
          false,
          'authenticated',
        )
        return
      }
      syncFromStorage()
    }

    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    window.addEventListener('storage', onStorage)
    if (initial.current) validate(initial.current)
    return () => {
      validationRef.current?.abort()
      window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
      window.removeEventListener('storage', onStorage)
    }
  }, [applySession, syncFromStorage, validate])

  useEffect(() => {
    if (status !== 'authenticated' || !session?.expiresAt) return
    const token = session.token
    const expiresAt = session.expiresAt
    const stillCurrent = () => sessionRef.current?.token === token

    const expire = () => {
      if (!stillCurrent()) return
      if (readStoredSession()?.token !== token) {
        syncFromStorage()
        return
      }
      ++generationRef.current
      validationRef.current?.abort()
      applySession(null, true, 'anonymous')
    }

    // 轮询而不是一次性定时器：失败的那次一分钟后再试。写一篇两万字要好几分钟，
    // 一次网络抖动不该升级成写作掉线。真正到期还没换上才登出。
    const tick = () => {
      if (!stillCurrent()) return
      if (Date.now() >= expiresAt) {
        expire()
        return
      }
      if (Date.now() >= expiresAt - RENEW_LEAD_MS) void renewSession()
    }
    const timer = window.setInterval(tick, RENEW_POLL_MS)
    // 后台标签页的定时器会被节流到分钟级，电脑睡眠时根本不跑：回到前台立刻补一次
    const onVisible = () => {
      if (document.visibilityState === 'visible') tick()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [applySession, renewSession, session, status, syncFromStorage])

  const authenticate = useCallback(async (
    action: 'login' | 'register',
    username: string,
    password: string,
    invitationCode?: string,
  ): Promise<boolean> => {
    const generation = ++generationRef.current
    const storedTokenAtStart = readStoredSession()?.token ?? null
    const resp = action === 'login'
      ? await api.login(username, password)
      : await api.register(username, password, invitationCode ?? '')
    if (generation !== generationRef.current) return false
    if ((readStoredSession()?.token ?? null) !== storedTokenAtStart) {
      syncFromStorage()
      return false
    }
    setNotice(null)
    applySession(fromAuthResponse(resp), true, 'authenticated')
    return true
  }, [applySession, syncFromStorage])

  const login = useCallback(
    (username: string, password: string) => authenticate('login', username, password),
    [authenticate],
  )

  const register = useCallback(
    (username: string, password: string, invitationCode: string) => (
      authenticate('register', username, password, invitationCode)
    ),
    [authenticate],
  )

  const logout = useCallback(async () => {
    const current = sessionRef.current
    if (!current) return
    ++generationRef.current
    validationRef.current?.abort()
    abortRequestsForToken(current.token)
    setSessionState(null)
    setStatus('checking')
    const controller = new AbortController()
    const timer = window.setTimeout(() => controller.abort(), 5000)
    try {
      await api.logout(current.token, controller.signal)
    } catch {
      if (sessionRef.current?.token === current.token
        && readStoredSession()?.token === current.token) {
        setNotice('无法联系服务器，已仅从本机退出；该登录会在凭据过期后失效。')
      }
    } finally {
      window.clearTimeout(timer)
      if (sessionRef.current?.token === current.token) {
        if (readStoredSession()?.token === current.token) {
          applySession(null, true, 'anonymous')
        } else {
          syncFromStorage()
        }
      }
    }
  }, [applySession, syncFromStorage])

  const changePassword = useCallback(async (currentPassword: string, newPassword: string) => {
    const current = sessionRef.current
    if (!current) return
    await api.changePassword(currentPassword, newPassword, current.token)
    if (sessionRef.current?.token === current.token) {
      if (readStoredSession()?.token === current.token) {
        ++generationRef.current
        applySession(null, true, 'anonymous')
      } else {
        syncFromStorage()
      }
    }
  }, [applySession, syncFromStorage])

  const revalidate = useCallback(() => {
    const current = sessionRef.current
    if (current) validate(current)
  }, [validate])

  const value = useMemo<AuthState>(() => ({
    session,
    status,
    validationError,
    notice,
    login,
    register,
    logout,
    changePassword,
    revalidate,
  }), [session, status, validationError, notice, login, register, logout, changePassword, revalidate])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
