// @vitest-environment jsdom
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import type { Project } from '../types'
import { ProjectRail } from './ProjectRail'

vi.mock('../context/AuthContext', () => ({
  useAuth: () => ({ session: { username: 'demo' } }),
}))

afterEach(() => {
  cleanup()
})

it('shows environment config on the library, not inside a book', () => {
  const projects: Project[] = [{ id: 'p1', title: '第一本书', genre: '都市', current_chapter: 1, target_words: 3000 }]

  const { unmount } = render(
    <MemoryRouter initialEntries={['/projects']}>
      <Routes>
        <Route path="/projects" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: '环境配置' })).toBeTruthy()
  unmount()

  render(
    <MemoryRouter initialEntries={['/projects/p1']}>
      <Routes>
        <Route path="/projects/:projectId" element={<ProjectRail projects={projects} onLogout={vi.fn()} />} />
      </Routes>
    </MemoryRouter>,
  )
  expect(screen.queryByRole('link', { name: '环境配置' })).toBeNull()
  expect(screen.getByRole('link', { name: '创作设置' })).toBeTruthy()
})
