// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { ConnectionNotices } from './ConnectionNotices'

afterEach(cleanup)

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
