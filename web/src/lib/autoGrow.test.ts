// @vitest-environment jsdom
import { expect, it } from 'vitest'
import { autoGrow } from './autoGrow'

function box(scrollHeight: number) {
  const el = document.createElement('textarea')
  Object.defineProperty(el, 'scrollHeight', { value: scrollHeight })
  return el
}

it('把框撑到装下全部内容，让框自己不再滚', () => {
  const el = box(160)
  autoGrow(el)
  expect(el.style.height).toBe('160px')
})

it('给了上限就停在上限，多出来的内容由外层那个滚动容器接', () => {
  const el = box(900)
  autoGrow(el, 200)
  expect(el.style.height).toBe('200px')
})

it('量不到高度时（jsdom / 尚未布局）不动内联高，交回 CSS', () => {
  // 写死成 0px 会把框压没，用户看不到输入过的字。
  const el = box(0)
  autoGrow(el)
  expect(el.style.height).toBe('')
})
