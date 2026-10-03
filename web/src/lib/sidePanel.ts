// 工作台右栏的展开偏好（§3.7b）：默认收起，正文列才拿得到 720px 的阅读宽度。
// 记 localStorage 而不是 sessionStorage——这是「我习惯怎么看」，不是「我正在做哪件事」。

const STORAGE_KEY = 'myink.sidePanel'

export function readSidePanelOpen(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === 'open'
  } catch {
    return false
  }
}

export function writeSidePanelOpen(open: boolean): void {
  localStorage.setItem(STORAGE_KEY, open ? 'open' : 'closed')
}
