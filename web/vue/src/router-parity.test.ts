// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import type { RouteObject } from 'react-router-dom'

// 测试期加载真实React路由，避免把React TSX拉入Vue模板的类型编译范围。
const loaded = import.meta.glob('../../src/router.tsx', { eager: true })
const { router: reactRouter } = loaded['../../src/router.tsx'] as { router: { routes: RouteObject[] } }
import { createCandidateRouter } from './router'

// 比较两套路由的实际注册，不解析源码。新增React路由而未在Vue登记会阻断CI。
it('accounts for every existing React route in the Vue candidate', () => {
  function paths(routes: typeof reactRouter.routes, parent = ''): string[] {
    return routes.flatMap(route => {
      const full = route.path?.startsWith('/') ? route.path : route.path ? `${parent}/${route.path}` : parent
      return [...(route.path ? [full] : []), ...paths(route.children ?? [], full)]
    })
  }
  const candidate = new Set(createCandidateRouter(createMemoryHistory()).getRoutes().map(route => route.path))
  for (const path of paths(reactRouter.routes).filter(path => path !== '/*')) {
    expect(candidate.has(path), `React route missing from Vue inventory: ${path}`).toBe(true)
  }
})

it.each([
  ['/projects', '/long'], ['/appearance', '/theme'], ['/admin/configuration', '/admin/models'], ['/unknown-page', '/'],
])('preserves redirect %s to %s', async (from, to) => {
  const router = createCandidateRouter(createMemoryHistory())
  await router.push(from)
  expect(router.currentRoute.value.path).toBe(to)
})

it('connects every product route to a real Vue implementation', () => {
  const router = createCandidateRouter(createMemoryHistory())
  for (const route of router.getRoutes()) {
    if (route.redirect) continue
    expect(route.components?.default, `${route.path} must have a page`).toBeTruthy()
    const component = route.components?.default as { __file?: string }
    expect(component.__file ?? '', `${route.path} still uses a migration placeholder`).not.toContain('MigrationPendingPage')
  }
})
