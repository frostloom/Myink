import { useEffect, useState, useSyncExternalStore } from 'react'
import { hasPendingWrites, subscribePendingWrites } from '../lib/pendingWrites'
import { requestReleaseRefresh, watchRelease } from '../lib/release'

export function AppVersionGuard() {
  const [available, setAvailable] = useState(false)
  const pending = useSyncExternalStore(subscribePendingWrites, hasPendingWrites, () => false)
  useEffect(() => watchRelease(() => setAvailable(true)), [])
  if (!available) return null
  return <div className="banner" role="status" data-guest-exempt>
    新版本已就绪。请先保存当前内容，再刷新页面。
    <button type="button" className="btn btn-quiet" disabled={pending} onClick={() => requestReleaseRefresh(hasPendingWrites, message => window.confirm(message), () => window.location.reload())}>刷新到新版本</button>
    {pending && <span>正在保存，请等待完成。</span>}
  </div>
}
