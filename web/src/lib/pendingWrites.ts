// One counter for API mutations shared by both frontends. Read requests and
// long-lived SSE streams do not prevent an intentional navigation/update.
let pending = 0
const listeners = new Set<() => void>()
export function hasPendingWrites(): boolean { return pending > 0 }
export function subscribePendingWrites(listener: () => void): () => void {
  listeners.add(listener)
  return () => { listeners.delete(listener) }
}
function warn(event: BeforeUnloadEvent) {
  if (!hasPendingWrites()) return
  event.preventDefault()
  event.returnValue = ''
}
function notify() { for (const listener of listeners) listener() }
export function beginWrite(): () => void {
  if (pending++ === 0 && typeof window !== 'undefined') window.addEventListener('beforeunload', warn)
  notify()
  let finished = false
  return () => {
    if (finished) return
    finished = true
    pending--
    if (pending === 0 && typeof window !== 'undefined') window.removeEventListener('beforeunload', warn)
    notify()
  }
}
