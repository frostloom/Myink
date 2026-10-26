import { h, shallowRef, nextTick, type VNode } from 'vue'
import { RouterProvider } from './workspaceRouterTestUtils'
import { render as vueRender } from '@testing-library/vue'
export { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/vue'
export async function act(fn: () => unknown) { await fn(); await nextTick() }
export function render(node: VNode) {
  const current = shallowRef(node)
  const result = vueRender({ setup: () => () => h(current.value) }, { global: { plugins: node.type === RouterProvider ? [node.props!.router] : [] } })
  return { ...result, rerender: async (next: VNode) => { current.value = next; await nextTick() } }
}
