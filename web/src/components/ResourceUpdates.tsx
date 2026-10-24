import {
  useEffect,
  useState,
  useRef,
  useImperativeHandle,
  type Ref,
} from 'react'
import {
  writingResources as api,
  resourceError,
  type ResourceUpdate,
  type ResourceSnapshot,
} from '../lib/writingResources'
import { AdminDialog } from '../pages/admin/AdminDialog'
export interface ResourceUpdateGate {
  beforeGenerate: () => Promise<boolean>
}
export function ResourceUpdates({
  projectId,
  autoOpen = true,
  onAdopt,
  gateRef,
}: {
  projectId: string
  autoOpen?: boolean
  gateRef?: Ref<ResourceUpdateGate>
  onAdopt?: (s: ResourceSnapshot) => void
}) {
  const [updates, setUpdates] = useState<ResourceUpdate[]>([]),
    [revision, setRevision] = useState(0),
    [selected, setSelected] = useState<string[]>([]),
    [open, setOpen] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('')
  const pending = useRef<((proceed: boolean) => void) | null>(null)
  const requestSerial = useRef(0)
  const active = useRef(true)
  const [waiting, setWaiting] = useState(false)
  function finish(proceed: boolean) {
    const resolve = pending.current
    pending.current = null
    setWaiting(false)
    resolve?.(proceed)
  }
  useImperativeHandle(gateRef, () => ({
    async beforeGenerate() {
      if (pending.current) return false
      ++requestSerial.current
      setBusy(true)
      setError('')
      try {
        const [u, snapshot] = await Promise.all([
          api.updates(projectId),
          api.snapshot(projectId),
        ])
        if (!active.current) return false
        const eligible = u.items.filter(
          (update) =>
            !snapshot.selections.some(
              (selection) =>
                selection.resource_id === update.resource_id &&
                selection.personal_override,
            ),
        )
        setUpdates(eligible)
        setRevision(snapshot.revision)
        setSelected(eligible.map((update) => update.resource_id))
        if (!eligible.some((update) => !update.dismissed)) return true
      } catch (error) {
        setError(resourceError(error))
      } finally {
        setBusy(false)
      }
      if (!active.current) return false
      setOpen(true)
      setWaiting(true)
      return new Promise<boolean>((resolve) => {
        pending.current = resolve
      })
    },
  }))
  useEffect(() => {
    active.current = true
    return () => {
      active.current = false
      pending.current?.(false)
      pending.current = null
    }
  }, [])
  useEffect(() => {
    let live = true
    const request = ++requestSerial.current
    Promise.all([api.updates(projectId), api.snapshot(projectId)])
      .then(([u, s]) => {
        if (!live || request !== requestSerial.current) return
        const eligible = u.items.filter(
          (i) =>
            !s.selections.some(
              (v) => v.resource_id === i.resource_id && v.personal_override,
            ),
        )
        setUpdates(eligible)
        setRevision(s.revision)
        setSelected(eligible.map((i) => i.resource_id))
        setOpen(autoOpen && eligible.some((i) => !i.dismissed))
      })
      .catch((e) => {
        if (live) setError(resourceError(e))
      })
    return () => {
      live = false
    }
  }, [projectId, autoOpen])
  async function close() {
    setBusy(true)
    try {
      await api.dismiss(
        projectId,
        updates
          .filter((i) => !i.dismissed)
          .map((i) => ({
            resource_id: i.resource_id,
            target_generation: i.target_generation,
          })),
      )
      setUpdates((old) => old.map((i) => ({ ...i, dismissed: true })))
      setOpen(false)
      setError('')
      finish(true)
    } catch (e) {
      setError(resourceError(e))
    } finally {
      setBusy(false)
    }
  }
  async function adopt() {
    setBusy(true)
    try {
      const s = await api.adopt(
        projectId,
        revision,
        updates
          .filter((i) => selected.includes(i.resource_id))
          .map((i) => ({
            resource_id: i.resource_id,
            target_generation: i.target_generation,
          })),
      )
      onAdopt?.(s)
      setRevision(s.revision)
      setUpdates((old) => old.filter((i) => !selected.includes(i.resource_id)))
      setOpen(false)
      setError('')
      finish(true)
    } catch (e) {
      setError(resourceError(e))
    } finally {
      setBusy(false)
    }
  }
  async function review() {
    setBusy(true)
    try {
      const [u, s] = await Promise.all([
        api.updates(projectId),
        api.snapshot(projectId),
      ])
      const eligible = u.items.filter(
        (i) =>
          !s.selections.some(
            (v) => v.resource_id === i.resource_id && v.personal_override,
          ),
      )
      setUpdates(eligible)
      setRevision(s.revision)
      setSelected(eligible.map((i) => i.resource_id))
      setOpen(true)
      setError('')
    } catch (e) {
      setError(resourceError(e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <>
      <button
        className="btn btn-quiet"
        disabled={busy}
        onClick={() => void review()}
      >
        查看资源更新{updates.length ? `（${updates.length}）` : ''}
      </button>
      {error && !open && <p>{error}</p>}
      {open && (
        <AdminDialog
          title="写作资源更新"
          busy={busy}
          onClose={() => void close()}
        >
          <p>
            只更新勾选项；本书个人覆盖保持不变，当前运行任务继续使用原快照。
          </p>
          {updates.length === 0 && <p>暂无可采用更新。</p>}
          {updates.map((i) => (
            <label
              key={i.resource_id}
              style={{ display: 'block', margin: '1rem 0' }}
            >
              <input
                type="checkbox"
                checked={selected.includes(i.resource_id)}
                onChange={(e) =>
                  setSelected((old) =>
                    e.target.checked
                      ? [...old, i.resource_id]
                      : old.filter((id) => id !== i.resource_id),
                  )
                }
              />
              {i.name} · v{i.current_version} → v{i.target_version} ·{' '}
              {i.action === 'rollback' ? '管理员回退' : '新发布'} · 发布标识{' '}
              {i.target_generation}
              <br />
              {i.note}
              {i.dismissed ? ' · 已忽略（仍可采用）' : ''}
            </label>
          ))}
          {error && <p role="alert">{error}</p>}
          {waiting && error && (
            <button
              className="btn"
              disabled={busy}
              onClick={() => {
                setOpen(false)
                finish(true)
              }}
            >
              检查失败，仍使用当前快照
            </button>
          )}
          {waiting && (
            <button
              className="btn"
              disabled={busy}
              onClick={() => {
                setOpen(false)
                finish(false)
              }}
            >
              取消本次生成
            </button>
          )}
          <button className="btn" disabled={busy} onClick={() => void close()}>
            {waiting ? '继续使用当前快照' : '暂不更新'}
          </button>
          <button
            className="btn btn-primary"
            disabled={busy || !selected.length}
            onClick={() => void adopt()}
          >
            采用勾选更新
          </button>
          <button className="btn" disabled={busy} onClick={() => void review()}>
            重新检查版本
          </button>
        </AdminDialog>
      )}
    </>
  )
}
