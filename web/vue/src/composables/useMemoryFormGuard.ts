import { hasInjectionContext, inject, onScopeDispose } from 'vue'
import { routerKey, type Router, type RouteLocationNormalized } from 'vue-router'
import { hasPendingWrites, hasNavigationBlockingWrites } from '../../../src/lib/pendingWrites'

type Scope = { dirty: (to?: RouteLocationNormalized) => boolean; permitted: boolean; recovering: () => boolean }
const scopesByRouter = new WeakMap<Router, Set<Scope>>()
/** Explicit reactive form state, including click/programmatic edits. No DOM input tracking. */
export function useMemoryFormGuard(dirty: (to?: RouteLocationNormalized) => boolean, options: { router?: Router; unloadDirty?: () => boolean; recovering?: () => boolean } = {}) {
  const router = options.router ?? (hasInjectionContext() ? inject(routerKey, null) : null)
  const scope: Scope = { dirty, permitted: false, recovering: options.recovering ?? (() => false) }
  let scopes: Set<Scope> | undefined
  if (router) {
    scopes = scopesByRouter.get(router)
    if (!scopes) {
      scopes = new Set()
      scopesByRouter.set(router, scopes)
      const activeScopes = scopes
      // One confirmation even when several nested memory forms are open.
      router.beforeEach((to, from) => {
        // Session recovery must always remain reachable after credentials expire.
        if (to.path === '/login' && from.path !== '/login' && (activeScopes.size === 0 || [...activeScopes].some(item => item.recovering()))) return true
        if (to.path === from.path && [...activeScopes].some(item => item.permitted) && [...activeScopes].every(item => item.permitted || !item.dirty(to))) return true
        if (hasNavigationBlockingWrites()) return false
        return ![...activeScopes].some(item => !item.permitted && item.dirty(to)) || window.confirm('有尚未保存的输入，离开会丢失这些修改。确定离开？')
      })
    }
    scopes.add(scope)
  }
  const beforeUnload = (event: BeforeUnloadEvent) => {
    if ((options.unloadDirty ?? dirty)() || hasPendingWrites()) { event.preventDefault(); event.returnValue = '' }
  }
  window.addEventListener('beforeunload', beforeUnload)
  onScopeDispose(() => { scopes?.delete(scope); window.removeEventListener('beforeunload', beforeUnload) })
  // Call only after a successful save, and only around its intended navigation.
  async function permitNavigation<T>(navigate: () => T): Promise<Awaited<T>> {
    scope.permitted = true
    try { return await navigate() } finally { scope.permitted = false }
  }
  return { permitNavigation }
}
