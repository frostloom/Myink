// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { beginWrite, hasPendingWrites, hasNavigationBlockingWrites } from './pendingWrites'

it('lets a retained conversation run behind routes but still protects unload and other writes', () => {
  const conversation = beginWrite(true)
  const otherWrite = beginWrite()
  try {
    expect(hasNavigationBlockingWrites()).toBe(true)
    otherWrite()
    expect(hasNavigationBlockingWrites()).toBe(false)
    expect(hasPendingWrites()).toBe(true)
    const unload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unload)
    expect(unload.defaultPrevented).toBe(true)
  } finally { otherWrite(); conversation() }
  expect(hasPendingWrites()).toBe(false)
  expect(hasNavigationBlockingWrites()).toBe(false)
})
