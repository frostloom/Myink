export interface ReleaseIdentity { schema: number; client: string; id: string; entry: string }
function identity(value: unknown): ReleaseIdentity | null {
  if (!value || typeof value !== 'object') return null
  const item = value as ReleaseIdentity
  return item.schema === 1 && (item.client === 'vue' || item.client === 'react') &&
    typeof item.id === 'string' && new RegExp(`^${item.client}-[a-f0-9]+$`).test(item.id) &&
    typeof item.entry === 'string' && /^\/assets\/[\w./-]+\.js$/.test(item.entry) && !item.entry.includes('..') ? item : null
}
export function releaseFromHtml(html: string): ReleaseIdentity | null {
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    const item = identity(JSON.parse(doc.querySelector('meta[name="myink-release"]')?.getAttribute('content') ?? 'null'))
    return item && Array.from(doc.querySelectorAll('script[type="module"][src]')).some(script => script.getAttribute('src') === item.entry) ? item : null
  } catch { return null }
}
export function activeRelease(): ReleaseIdentity | null { return releaseFromHtml(document.documentElement.outerHTML) }
export async function probeRelease(current: ReleaseIdentity, signal: AbortSignal, fetcher: typeof fetch = fetch): Promise<ReleaseIdentity | null> {
  const options: RequestInit = { cache: 'no-store', credentials: 'same-origin', signal }
  const manifest = await fetcher(`/release.json?_myink_version=${Date.now()}`, options)
  if (!manifest.ok || signal.aborted) return null
  const candidate = identity(await manifest.json())
  if (!candidate || candidate.id === current.id) return null
  const response = await fetcher(`/?_myink_version=${Date.now()}`, options)
  if (!response.ok || signal.aborted) return null
  const html = releaseFromHtml(await response.text())
  return !signal.aborted && html && html.id === candidate.id && html.client === candidate.client && html.entry === candidate.entry ? candidate : null
}
export const RELEASE_WARNING = '刷新会离开当前页面，未保存的章节、新建书籍、短篇、管理员表单、反馈正文与附件、主题预览及其他输入可能丢失。若草稿存储失败，请先导出内容备份。确认已保存或导出后刷新？'
export function requestReleaseRefresh(pending: () => boolean, confirm: (message: string) => boolean, reload: () => void): boolean {
  if (pending() || !confirm(RELEASE_WARNING) || pending()) return false
  reload(); return true
}
/** Each mounted guard owns and aborts its probe, including focus-triggered requests. */
export function watchRelease(onAvailable: (release: ReleaseIdentity) => void): () => void {
  const current = activeRelease()
  if (!current) return () => {}
  let checking = false; let stopped = false; let controller: AbortController | undefined
  const check = async () => {
    if (stopped || checking) return
    checking = true; controller = new AbortController()
    try { const next = await probeRelease(current, controller.signal); if (next && !stopped) onAvailable(next) }
    catch { /* Retain the active page during network/deploy failures. */ }
    finally { checking = false }
  }
  const focus = () => { void check() }
  const visibility = () => { if (document.visibilityState === 'visible') focus() }
  const timer = window.setInterval(focus, 30_000)
  window.addEventListener('focus', focus); document.addEventListener('visibilitychange', visibility); focus()
  return () => { stopped = true; controller?.abort(); window.clearInterval(timer); window.removeEventListener('focus', focus); document.removeEventListener('visibilitychange', visibility) }
}
