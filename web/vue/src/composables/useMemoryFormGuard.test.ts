// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { cleanup, render } from '@testing-library/vue'
import { createMemoryHistory, createRouter, RouterView } from 'vue-router'
import { useMemoryFormGuard } from './useMemoryFormGuard'
vi.mock('../../../src/lib/pendingWrites', () => ({ hasPendingWrites: () => pending }))
let pending = false
afterEach(() => { cleanup(); pending = false; vi.restoreAllMocks() })
async function start() {
  const dirty = ref(false), status = ref('authenticated')
  let permit!: ReturnType<typeof useMemoryFormGuard>['permitNavigation']
  const page = defineComponent({ setup: function usePageGuard() { permit = useMemoryFormGuard(() => dirty.value, { recovering: () => status.value === 'anonymous' }).permitNavigation; return () => h('input') } })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/form/:id', component: page }, { path: '/other', component: { render: () => null } }] })
  await router.push('/form/a'); await router.isReady(); render(RouterView, { global: { plugins: [router] } })
  return { router, dirty, permit, status }
}
it('protects programmatic changes, same-component updates and unload', async () => {
  const { router, dirty } = await start(); dirty.value = true
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/form/b'); expect(router.currentRoute.value.path).toBe('/form/a'); expect(confirm).toHaveBeenCalledTimes(1)
  const event = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(event); expect(event.defaultPrevented).toBe(true)
  confirm.mockReturnValue(true); await router.push('/other'); expect(router.currentRoute.value.path).toBe('/other')
  const after = new Event('beforeunload', { cancelable: true }); window.dispatchEvent(after); expect(after.defaultPrevented).toBe(false)
})
it('blocks pending writes without a discard prompt even on a clean form', async () => {
  const { router } = await start(); pending = true
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  await router.push('/other'); expect(router.currentRoute.value.path).toBe('/form/a'); expect(confirm).not.toHaveBeenCalled()
})
it('allows successful explicit navigation and restores protection after rejected save', async () => {
  const { router, dirty, permit } = await start(); dirty.value = true
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await expect(permit(async () => { throw new Error('save failed') })).rejects.toThrow('save failed')
  await router.push('/other'); expect(router.currentRoute.value.path).toBe('/form/a')
  await permit(() => router.push('/other')); expect(router.currentRoute.value.path).toBe('/other'); expect(confirm).toHaveBeenCalledTimes(1)
})

it('combines nested dirty scopes into one confirmation', async () => {
  const nested = defineComponent({ setup: function useNestedGuard() { useMemoryFormGuard(() => true); useMemoryFormGuard(() => true); return () => h('div') } })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/nested', component: nested }, { path: '/other', component: { render: () => null } }] })
  await router.push('/nested'); await router.isReady(); render(RouterView, { global: { plugins: [router] } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true)
  await router.push('/other'); expect(confirm).toHaveBeenCalledTimes(1)
})
it('allows session recovery without trapping discarded credentials', async () => {
  const { router, dirty, status } = await start(); dirty.value = true; pending = true; status.value = 'anonymous'
  router.addRoute({ path: '/login', component: { render: () => null } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/login'); expect(router.currentRoute.value.path).toBe('/login'); expect(confirm).not.toHaveBeenCalled()
})

it('still protects an authenticated form when navigating manually to login', async () => {
  const { router, dirty } = await start(); dirty.value = true
  router.addRoute({ path: '/login', component: { render: () => null } })
  const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
  await router.push('/login'); expect(router.currentRoute.value.path).toBe('/form/a'); expect(confirm).toHaveBeenCalledTimes(1)
})
