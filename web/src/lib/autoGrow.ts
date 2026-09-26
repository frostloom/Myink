/** 让 textarea 高到装下全部内容：框内不该再长出第二条滚动条。
 *
 * 整页/整块只留一个滚动容器；框自己滚就成了「能滚的页面里嵌一个能滚的小页面」。
 * jsdom 里 scrollHeight 恒为 0，这时交回 CSS 的默认高度，别写死成 0px。
 */
export function autoGrow(el: HTMLTextAreaElement, maxHeight = Infinity): void {
  el.style.height = 'auto'
  const next = Math.min(el.scrollHeight, maxHeight)
  el.style.height = next > 0 ? `${next}px` : ''
}
