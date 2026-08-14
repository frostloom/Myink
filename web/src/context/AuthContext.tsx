// 登录态：localStorage 单源 + 401 事件自动登出（token.ts 解耦，避免循环依赖）。
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api } from '../lib/api'
import {
  clearSession,
  getSession,
  setSession,
  UNAUTHORIZED_EVENT,
  type StoredSession,
} from '../lib/token'

interface AuthState {
  session: StoredSession | null
  login: (username: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<StoredSession | null>(() => getSession())

  // 任一 API 调用收到 401（token 过期/失效）→ 全局登出，路由守卫自动重定向登录页
  useEffect(() => {
    const onUnauthorized = () => {
      clearSession()
      setSessionState(null)
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  const login = useCallback(async (username: string) => {
    const resp = await api.login(username)
    const next = { token: resp.token, userId: resp.user_id, username }
    setSession(next)
    setSessionState(next)
  }, [])

  const logout = useCallback(() => {
    clearSession()
    setSessionState(null)
  }, [])

  const value = useMemo(
    () => ({ session, login, logout }),
    [session, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth 必须在 AuthProvider 内使用')
  return ctx
}
