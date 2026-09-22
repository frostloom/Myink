// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ConnectionNotices, type ConnectionNotice } from './ConnectionNotices'

afterEach(cleanup)

it('reveals new and updated messages after the notice region has been scrolled', () => {
  const old: ConnectionNotice = { id: 'old', tone: 'error', text: '旧错误', returnFocus: null }
  const view = render(<ConnectionNotices items={[old]} onDismiss={vi.fn()} />)
  const region = screen.getByRole('region', { name: '模型连接通知' })
  region.scrollTop = 200
  const next: ConnectionNotice = { id: 'new', tone: 'error', text: '新错误', returnFocus: null }
  view.rerender(<ConnectionNotices items={[next, old]} onDismiss={vi.fn()} />)
  expect(region.scrollTop).toBe(0)
  region.scrollTop = 200
  view.rerender(<ConnectionNotices items={[{ ...next, text: '重试错误' }, old]} onDismiss={vi.fn()} />)
  expect(region.scrollTop).toBe(0)
  expect(screen.getAllByRole('alert')).toHaveLength(2)
})

it('keeps errors from separate connections without taking focus', () => {
  const trigger = document.createElement('button')
  document.body.append(trigger)
  trigger.focus()
  const dismiss = vi.fn()
  render(<ConnectionNotices items={[
    { id: 'a', tone: 'error', text: '连接 A：请求超时', returnFocus: trigger },
    { id: 'b', tone: 'error', text: '连接 B：额度不足', returnFocus: trigger },
  ]} onDismiss={dismiss} />)
  expect(screen.getAllByRole('alert')).toHaveLength(2)
  expect(document.activeElement).toBe(trigger)
  const close = screen.getAllByRole('button', { name: '关闭通知' })[0]
  close.focus()
  fireEvent.keyDown(close, { key: 'Escape' })
  expect(dismiss).toHaveBeenCalledExactlyOnceWith('a')
  expect(document.activeElement).toBe(trigger)
  trigger.remove()
})
