// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ResourceBodyFields } from './ResourceBodyFields'
import { ResourceContent } from '../pages/admin/ResourceContent'
import { AutoTextarea } from './AutoTextarea'
import { AdminDialog } from '../pages/admin/AdminDialog'

afterEach(cleanup)
describe('resource usability', () => {
  it('preserves hidden settings on creative edits', () => {
    const onChange = vi.fn()
    const value = { roles: { writer: '原文' }, validation: { not_is: true }, genre_ids: ['fantasy'] }
    render(<ResourceBodyFields kind="writing_rule" value={value} onChange={onChange} />)
    expect(screen.queryByText('校验配置')).toBeNull()
    expect(screen.queryByDisplayValue('fantasy')).toBeNull()
    fireEvent.change(screen.getByLabelText('写作'), { target: { value: '新文' } })
    expect(onChange).toHaveBeenCalledWith({ ...value, roles: { writer: '新文' } })
  })
  it('generates a hidden path for new references', () => {
    const onChange = vi.fn()
    render(<ResourceBodyFields kind="reference" value={{ files: [] }} onChange={onChange} />)
    fireEvent.click(screen.getByRole('button', { name: /添加/ }))
    expect(onChange.mock.calls[0][0].files[0].path).toMatch(/^reference-.+\.md$/)
  })
  it('conceals technical identifiers in previews', () => {
    render(<ResourceContent body={{ catalog_id: 'secret-id', fields: { selling_point: '故事卖点' } } as never} />)
    expect(screen.queryByText('secret-id')).toBeNull()
    expect(screen.getByText('故事卖点')).not.toBeNull()
  })
  it('restores background scrolling on close', () => {
    const host = document.createElement('main')
    host.style.overflowY = 'auto'
    document.body.append(host)
    const { unmount } = render(<AdminDialog title="编辑" busy={false} onClose={() => {}}>正文</AdminDialog>, { container: host })
    expect(host.style.overflowY).toBe('hidden')
    unmount()
    expect(host.style.overflowY).toBe('auto')
    host.remove()
  })
})

it('selects genres by name and retains expression checks', () => {
  const onChange = vi.fn()
  const value = { genre_ids: ['fantasy'], roles: { writer: '正文' }, validation: { parallel: true } }
  render(<ResourceBodyFields kind="genre_rule" value={value} genres={[{ id: 'fantasy', name: '奇幻冒险' }]} onChange={onChange} />)
  fireEvent.click(screen.getByLabelText('奇幻冒险'))
  expect(onChange).toHaveBeenCalledWith({ ...value, genre_ids: [] })
  fireEvent.click(screen.getByLabelText('检查重复排比句式'))
  expect(onChange).toHaveBeenCalledWith({ ...value, validation: { parallel: false } })
})


it('expands long text again when its controlled value changes', () => {
  const height = vi.spyOn(HTMLTextAreaElement.prototype, 'scrollHeight', 'get').mockReturnValue(360)
  try {
    const { rerender } = render(<AutoTextarea aria-label="正文" value="长正文" readOnly />)
    const input = screen.getByLabelText('正文') as HTMLTextAreaElement
    expect(input.style.height).toBe('360px')
    expect(input.style.overflowY).toBe('hidden')
    height.mockReturnValue(720)
    rerender(<AutoTextarea aria-label="正文" value="更长的正文" readOnly />)
    expect(input.style.height).toBe('720px')
  } finally { height.mockRestore() }
})
