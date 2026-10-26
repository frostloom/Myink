/* eslint-disable vue/one-component-per-file -- Tests mount local router harness components. */
import { flushPromises,mount } from '@vue/test-utils'
import { afterEach,describe,expect,it,vi } from 'vitest'
import { defineComponent,h,ref } from 'vue'
import { createMemoryHistory,createRouter,RouterView,useRoute } from 'vue-router'
import type { StoredSession } from '../../../../src/lib/token'
import { authKey } from '../../authContext'
import type { SessionScope } from '../../session'
import AdminPage from '../AdminPage.vue'
import { useAdminContext } from './context'
const wrappers: ReturnType<typeof mount>[] = []
afterEach(() => { wrappers.forEach(w => w.unmount()); wrappers.length = 0 })
async function setup(verified = true, path = '/admin') {
  const session = ref<StoredSession | null>({ token: 'token', userId: 'admin', username: 'a', tier: 'normal', role: 'admin', roleVerified: verified, expiresAt: null })
  const revalidate = vi.fn()
  let forbidden: (() => void) | undefined
  const child = defineComponent({ setup: function AdminDetailFixture() { forbidden = useAdminContext().onForbidden; const id=useRoute().params.id; return () => h('p', '机密用户列表'+(id??'')) } })
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/admin', component: AdminPage, children: [{ path: '', component: child },{path:'users/:id',component:child}] }] })
  await router.push(path); await router.isReady()
  const wrapper = mount(defineComponent({ render: () => h(RouterView) }), { global: { plugins: [router], provide: { [authKey as symbol]: { session, status: ref('authenticated'), revalidate, logout: vi.fn() } as unknown as SessionScope }, stubs: { AdminRail: true } } })
  wrappers.push(wrapper); await flushPromises()
  return { wrapper, session, revalidate, router, forbid: () => forbidden?.() }
}
describe('administrator gate', () => {
  it('retains the subtree on renewal and replaces it on account change',async()=>{const {wrapper,session}=await setup();const before=wrapper.find('p').element;session.value={...session.value!,token:'renewed'};await flushPromises();expect(wrapper.find('p').element).toBe(before);session.value={...session.value!,userId:'other'};await flushPromises();expect(wrapper.find('p').element).not.toBe(before)})
  it('does not clear a forbidden decision merely because the token renews',async()=>{const {wrapper,session,forbid}=await setup();forbid();await flushPromises();session.value={...session.value!,token:'renewed'};await flushPromises();expect(wrapper.text()).toContain('管理员权限已变化');expect(wrapper.text()).not.toContain('机密用户列表')})
  it('clears the protected subtree when the verified role is revoked',async()=>{const {wrapper,session}=await setup();session.value={...session.value!,role:'user'};await flushPromises();expect(wrapper.text()).not.toContain('机密用户列表');expect(wrapper.text()).toContain('只有管理员可以打开控制台')})
  it('clears the previous detail subtree when moving between identifiers',async()=>{const {wrapper,router}=await setup(true,'/admin/users/first');expect(wrapper.text()).toContain('机密用户列表first');await router.push('/admin/users/second');await flushPromises();expect(wrapper.text()).toContain('机密用户列表second');expect(wrapper.text()).not.toContain('机密用户列表first')})
  it('denies cached administrator roles without server verification', async () => {
    const { wrapper } = await setup(false)
    expect(wrapper.text()).toContain('只有管理员可以打开控制台')
    expect(wrapper.text()).not.toContain('机密用户列表')
  })
  it('unmounts protected descendants and revalidates after 403', async () => {
    const { wrapper, forbid, revalidate } = await setup()
    expect(wrapper.text()).toContain('机密用户列表')
    forbid(); await flushPromises()
    expect(wrapper.text()).not.toContain('机密用户列表')
    expect(wrapper.text()).toContain('管理员权限已变化')
    expect(revalidate).toHaveBeenCalledOnce()
  })
})
