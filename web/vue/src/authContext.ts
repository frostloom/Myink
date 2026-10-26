import { inject, type InjectionKey } from 'vue'
import type { SessionScope } from './session'

export const authKey: InjectionKey<SessionScope> = Symbol('authentication')
export function useAuth(): SessionScope {
  const auth = inject(authKey)
  if (!auth) throw new Error('Authentication scope is missing')
  return auth
}
