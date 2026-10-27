// Track all mutations for reload protection. Retained conversations may finish
// behind another route; other writes still block navigation until they settle.
let pending = 0
let navigationBlocking = 0
const listeners = new Set<() => void>()
export function hasPendingWrites(): boolean { return pending > 0 }
export function hasNavigationBlockingWrites(): boolean { return navigationBlocking > 0 }
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
export function beginWrite(background = false): () => void {
  if (!background) navigationBlocking++
  if (pending++ === 0 && typeof window !== 'undefined') window.addEventListener('beforeunload', warn)
  notify()
  let finished = false
  return () => {
    if (finished) return
    finished = true
    pending--
    if (!background) navigationBlocking--
    if (pending === 0 && typeof window !== 'undefined') window.removeEventListener('beforeunload', warn)
    notify()
  }
}
