import { useEffect, useMemo, useState } from 'react'
import type { ArtifactState } from '../hooks/useTaskEvents'
import { api, ApiError } from '../lib/api'
import type {
  AgentRun,
  ChapterPlan,
  ChapterPlanCharacter,
  ChapterPlanScene,
  TaskStatus,
} from '../types'
import styles from './ChapterPlanPanel.module.css'

interface Props {
  taskId: string | null
  chapterSeq: number
  status: TaskStatus | null
  runs: AgentRun[]
  artifact: ArtifactState | null
  onConfirmed: (taskId: string, chapterSeq: number) => void
  onCancelled: (taskId: string, chapterSeq: number) => void
}

const JSON_KEYS = new Set([
  'project_id', 'chapter_seq', 'goals', 'scenes', 'characters', 'hooks_to_plant',
  'hooks_to_resolve', 'expected_events', 'hard_constraints', 'transition', 'mode',
  'anchor_quote', 'pending_action', 'opening_beat', 'bridge', 'location_id',
  'participants', 'goal', 'time', 'character_id', 'expected_state',
])

function isPlan(value: unknown): value is ChapterPlan {
  if (!value || typeof value !== 'object') return false
  const plan = value as Partial<ChapterPlan>
  return Array.isArray(plan.goals) && Array.isArray(plan.expected_events)
}

function clonePlan(plan: ChapterPlan): ChapterPlan {
  return JSON.parse(JSON.stringify(plan)) as ChapterPlan
}

function streamPreview(raw: string): string {
  const values: string[] = []
  for (const match of raw.matchAll(/"((?:\\.|[^"\\])*)"/g)) {
    try {
      const value = JSON.parse(`"${match[1]}"`) as string
      if (value && !JSON_KEYS.has(value) && !/^[0-9a-f-]{30,}$/i.test(value)) values.push(value)
    } catch { /* 不完整转义留给后续片段 */ }
  }
  return values.join(' · ')
}

function listText(items: string[]): string { return items.join('\n') }
function textList(value: string): string[] {
  return value.split('\n').map((item) => item.trim()).filter(Boolean)
}

function stateText(state: Record<string, unknown>): string {
  return Object.entries(state).map(([key, value]) => `${key}：${String(value)}`).join('\n')
}

function textState(value: string): Record<string, string> {
  const state: Record<string, string> = {}
  for (const line of value.split('\n')) {
    const [key, ...rest] = line.split(/[：:]/)
    if (key?.trim() && rest.join(':').trim()) state[key.trim()] = rest.join(':').trim()
  }
  return state
}

function PlanReadOnly({ plan }: { plan: ChapterPlan }) {
  return <div className={styles.readonly}>
    <section><h4>本章目标</h4><ul>{plan.goals.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
    {plan.transition && <section>
      <h4>章节衔接</h4>
      <p><b>{plan.transition.mode}</b> · {plan.transition.opening_beat}</p>
      {plan.transition.pending_action && <p>承接：{plan.transition.pending_action}</p>}
      {plan.transition.bridge && <p>过渡：{plan.transition.bridge}</p>}
    </section>}
    <section><h4>场景安排</h4><ol>{plan.scenes.map((scene, i) => <li key={i}>
      <b>{scene.location_id}</b>{scene.time ? ` · ${scene.time}` : ''}：{scene.goal}
      {scene.participants.length > 0 && <small>{scene.participants.join('、')}</small>}
    </li>)}</ol></section>
    <section><h4>预期事件</h4><ul>{plan.expected_events.map((item, i) => <li key={i}>{item}</li>)}</ul></section>
    {(plan.hooks_to_plant.length > 0 || plan.hooks_to_resolve.length > 0) && <section>
      <h4>伏笔</h4>
      {plan.hooks_to_plant.map((item, i) => <p key={`p${i}`}>埋设：{item}</p>)}
      {plan.hooks_to_resolve.map((item, i) => <p key={`r${i}`}>回收：{item}</p>)}
    </section>}
    {plan.hard_constraints.length > 0 && <section><h4>硬约束</h4><ul>
      {plan.hard_constraints.map((item, i) => <li key={i}>{item}</li>)}
    </ul></section>}
  </div>
}

function ListField({ label, value, onChange }: { label: string; value: string[]; onChange: (next: string[]) => void }) {
  return <label className={styles.field}><span>{label}<small>每行一条</small></span>
    <textarea rows={Math.max(2, Math.min(5, value.length + 1))} value={listText(value)} onChange={(e) => onChange(textList(e.target.value))} />
  </label>
}

function PlanEditor({ plan, onChange }: { plan: ChapterPlan; onChange: (next: ChapterPlan) => void }) {
  const update = <K extends keyof ChapterPlan>(key: K, value: ChapterPlan[K]) => onChange({ ...plan, [key]: value })
  const transition = plan.transition ?? { mode: 'continue' as const, anchor_quote: '', pending_action: '', opening_beat: '', bridge: '' }
  const updateScene = (index: number, patch: Partial<ChapterPlanScene>) => {
    const scenes = plan.scenes.map((scene, i) => i === index ? { ...scene, ...patch } : scene)
    update('scenes', scenes)
  }
  const updateCharacter = (index: number, patch: Partial<ChapterPlanCharacter>) => {
    const characters = plan.characters.map((character, i) => i === index ? { ...character, ...patch } : character)
    update('characters', characters)
  }
  return <div className={styles.editor}>
    <ListField label="本章目标" value={plan.goals} onChange={(value) => update('goals', value)} />
    <fieldset className={styles.transition}><legend>与上一章的衔接</legend>
      <label><span>方式</span><select value={transition.mode} onChange={(e) => update('transition', { ...transition, mode: e.target.value as typeof transition.mode })}>
        <option value="continue">直接接续</option><option value="time_jump">时间跳转</option>
        <option value="scene_cut">场景切换</option><option value="opening">首章开场</option>
      </select></label>
      <label><span>上一章锚点</span><input value={transition.anchor_quote} onChange={(e) => update('transition', { ...transition, anchor_quote: e.target.value })} /></label>
      <label><span>未完成动作</span><input value={transition.pending_action} onChange={(e) => update('transition', { ...transition, pending_action: e.target.value })} /></label>
      <label><span>本章第一拍</span><textarea rows={2} value={transition.opening_beat} onChange={(e) => update('transition', { ...transition, opening_beat: e.target.value })} /></label>
      <label><span>过渡桥</span><textarea rows={2} value={transition.bridge} onChange={(e) => update('transition', { ...transition, bridge: e.target.value })} /></label>
    </fieldset>
    <fieldset className={styles.collection}><legend>场景安排</legend>
      {plan.scenes.map((scene, index) => <div className={styles.item} key={index}>
        <input aria-label={`场景 ${index + 1} 地点`} placeholder="地点" value={scene.location_id} onChange={(e) => updateScene(index, { location_id: e.target.value })} />
        <input aria-label={`场景 ${index + 1} 时间`} placeholder="时间（可选）" value={scene.time ?? ''} onChange={(e) => updateScene(index, { time: e.target.value || null })} />
        <input aria-label={`场景 ${index + 1} 人物`} className={styles.wide} placeholder="人物，用顿号或逗号分隔" value={scene.participants.join('、')} onChange={(e) => updateScene(index, { participants: e.target.value.split(/[、,，]/).map((v) => v.trim()).filter(Boolean) })} />
        <textarea aria-label={`场景 ${index + 1} 目标`} className={styles.wide} rows={2} placeholder="场景目标" value={scene.goal} onChange={(e) => updateScene(index, { goal: e.target.value })} />
        <button type="button" onClick={() => update('scenes', plan.scenes.filter((_, i) => i !== index))}>移除场景</button>
      </div>)}
      <button type="button" onClick={() => update('scenes', [...plan.scenes, { location_id: '', participants: [], goal: '', time: null }])}>＋ 添加场景</button>
    </fieldset>
    {plan.characters.length > 0 && <fieldset className={styles.collection}><legend>人物预期状态</legend>
      {plan.characters.map((character, index) => <div className={styles.item} key={index}>
        <input aria-label={`人物 ${index + 1} 名称`} value={character.character_id} onChange={(e) => updateCharacter(index, { character_id: e.target.value })} />
        <textarea aria-label={`人物 ${index + 1} 状态`} className={styles.wide} rows={2} value={stateText(character.expected_state)} onChange={(e) => updateCharacter(index, { expected_state: textState(e.target.value) })} />
      </div>)}
    </fieldset>}
    <ListField label="预期事件" value={plan.expected_events} onChange={(value) => update('expected_events', value)} />
    <ListField label="埋设伏笔" value={plan.hooks_to_plant} onChange={(value) => update('hooks_to_plant', value)} />
    <ListField label="回收伏笔" value={plan.hooks_to_resolve} onChange={(value) => update('hooks_to_resolve', value)} />
    <ListField label="硬约束" value={plan.hard_constraints} onChange={(value) => update('hard_constraints', value)} />
  </div>
}

export function ChapterPlanPanel({ taskId, chapterSeq, status, runs, artifact, onConfirmed, onCancelled }: Props) {
  const [draft, setDraft] = useState<ChapterPlan | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const plans = useMemo(() => {
    const reviews = new Map<number, ChapterPlan>()
    for (const run of runs) {
      const attempt = run.detail?.plan_attempt ?? 1
      if (run.node === 'plan_review' && isPlan(run.detail?.approved_plan)) reviews.set(attempt, run.detail.approved_plan)
    }
    return runs.filter((run) => run.node === 'plan_chapter' && isPlan(run.detail?.plan)).map((run) => {
      const attempt = run.detail?.plan_attempt ?? 1
      return { attempt, plan: reviews.get(attempt) ?? run.detail!.plan! }
    })
  }, [runs])

  const streamedPlan = isPlan(artifact?.artifact) ? artifact.artifact : null
  const latestPersistedAttempt = plans.at(-1)?.attempt ?? 0
  const streamingNewPlan = Boolean(
    artifact && !artifact.complete && artifact.attempt > latestPersistedAttempt,
  )
  const current = streamingNewPlan
    ? null
    : streamedPlan
      ? { attempt: artifact?.attempt || latestPersistedAttempt || 1, plan: streamedPlan }
      : plans.at(-1) ?? null
  const previous = current
    ? plans.filter((item) => item.attempt < current.attempt)
    : plans
  // 直接显示模型经 SSE 送达的完整语义片段，避免再排入前端打字队列而落后于真实生成。
  const preview = streamPreview(artifact?.content ?? '')
  const editable = status === 'awaiting_plan' && current !== null

  useEffect(() => {
    if (current && editable) setDraft(clonePlan(current.plan))
    else setDraft(null)
    setError(null)
  }, [current?.attempt, editable]) // eslint-disable-line react-hooks/exhaustive-deps

  async function confirm() {
    if (!taskId || !current || !draft || busy) return
    if (draft.goals.length === 0 || draft.expected_events.length === 0) {
      setError('本章目标和预期事件至少各保留一条。')
      return
    }
    if (!draft.transition?.opening_beat.trim()) {
      setError('请填写“本章第一拍”，它决定正文如何承接上一章。')
      return
    }
    if (draft.scenes.some((scene) => !scene.location_id.trim() || !scene.goal.trim())) {
      setError('每个场景都需要填写地点和场景目标。')
      return
    }
    if (['time_jump', 'scene_cut'].includes(draft.transition.mode) && !draft.transition.bridge.trim()) {
      setError('时间跳转或场景切换需要填写“过渡桥”。')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await api.confirmTaskPlan(taskId, draft, current.attempt)
      onConfirmed(taskId, chapterSeq)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PLAN_VERSION_CONFLICT') {
        setError('计划已在其他页面更新，请刷新后再编辑。')
      } else if (err instanceof ApiError && err.status === 422) {
        setError(err.code || '计划内容不符合约束，请修改后重试。')
      } else {
        setError('计划确认失败，请重试。')
      }
    } finally { setBusy(false) }
  }

  async function cancel() {
    if (!taskId || busy) return
    setBusy(true)
    setError(null)
    try {
      await api.cancelTask(taskId)
      onCancelled(taskId, chapterSeq)
    } catch {
      setError('取消失败，请重试。')
    } finally { setBusy(false) }
  }

  return <section className={styles.panel}>
    <header className={styles.head}>
      <span><b>第 {chapterSeq} 章 Plan</b><small>{!current ? '生成中' : editable ? '等待确认' : '已生成'}</small></span>
      <span>独立 Plan 页面</span>
    </header>
    <div className={styles.body}>
      {!current ? <>
        <div className={styles.streaming}><span>AI 正在规划</span><p>{preview || '正在读取前情、伏笔和人物状态…'}<i /></p></div>
        {previous.length > 0 && <details className={styles.history}><summary>历史计划（{previous.length}）</summary>
          {previous.map((item) => <details key={item.attempt}><summary>第 {item.attempt} 版计划</summary><PlanReadOnly plan={item.plan} /></details>)}
        </details>}
      </> : <>
        {editable && draft ? <PlanEditor plan={draft} onChange={setDraft} /> : <PlanReadOnly plan={current.plan} />}
        {previous.length > 0 && <details className={styles.history}><summary>历史计划（{previous.length}）</summary>
          {previous.map((item) => <details key={item.attempt}><summary>第 {item.attempt} 版计划</summary><PlanReadOnly plan={item.plan} /></details>)}
        </details>}
        {error && <div className="banner banner-error" role="alert">{error}</div>}
        {editable && <div className={styles.confirmBar}>
          <span>确认后才会产生正文写作费用并进入 Write。</span>
          <div className={styles.confirmActions}>
            <button type="button" className="btn btn-quiet" disabled={busy} onClick={() => void cancel()}>取消本次写作</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={() => void confirm()}>{busy ? '提交中…' : '确认计划并开始写作'}</button>
          </div>
        </div>}
      </>}
    </div>
  </section>
}
