// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { createMemoryHistory } from 'vue-router'
import { createCandidateRouter } from './router'

// Public URLs are a product contract independent of any retired implementation.
it.each([
  '/', '/login', '/projects', '/appearance', '/long', '/short', '/long/new',
  '/short/new', '/projects/new', '/account', '/environment', '/theme', '/styles',
  '/projects/:projectId', '/projects/:projectId/settings', '/projects/:projectId/audit',
  '/projects/:projectId/lore', '/admin', '/admin/configuration', '/admin/models',
  '/admin/model-routes', '/admin/defaults', '/admin/prompts', '/admin/genres',
  '/admin/writing-resources', '/admin/projects/:projectId', '/admin/tasks/:taskId',
  '/admin/runs/:runId', '/admin/users/:userId',
])('keeps the public route %s registered', path => {
  const routes = createCandidateRouter(createMemoryHistory()).getRoutes()
  expect(routes.some(route => route.path === path)).toBe(true)
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
