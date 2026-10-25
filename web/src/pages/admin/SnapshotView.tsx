import { ReadableContent } from './ReadableContent'
import { CreationInput, Disclosure } from './ExecutionContent'
import { CapturedView } from './shared'
import { useCallback, useMemo, useState } from 'react'
import { adminApi, type AdminSnapshot } from '../../lib/adminApi'
import {
  conflictTypeLabel,
  findingSourceLabel,
  nodeLabel,
  scopeLabel,
  severityLabel,
} from '../../lib/labels'
import {
  appliedSpans,
  availableSubViews,
  findings,
  HARD_RULE_SECTION,
  hardRuleFacts,
  hardRuleSection,
  promptSections,
  recallGroups,
  recallStats,
  severityClass,
  snapshotPayload,
  styleSection,
  SUB_VIEW_LABELS,
  type RecallGroup,
  type SnapshotSubView,
} from '../../lib/snapshotView'
import {
  formatCost,
  formatDate,
  formatDuration,
  LoadState,
  RefreshButton,
  useResource,
} from './shared'
import styles from './SnapshotView.module.css'

function ItemList({ group }: { group: RecallGroup }) {
  if (group.items.length === 0) return <p className={styles.muted}>本次没有使用这类前情资料</p>
  return (
    <ul className={styles.items}>
      {group.items.map((item, index) => (
        <li key={`${group.key}-${index}`}>
          <ReadableContent value={Object.fromEntries(Object.entries(item).filter(([key]) => !key.endsWith('_id') && key !== 'id' && key !== 'is_hard'))} />
          {item.is_hard === true && <span className="badge badge-warning">必须遵守的设定</span>}
        </li>
      ))}
    </ul>
  )
}

function PromptSections({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  const sections = promptSections(payload)
  return (
    <>
      <p className={styles.summary}>
        本次提供了 {sections.length} 部分创作依据
        {payload.prompt?.truncated === true && <span className="badge badge-warning">整体已截断</span>}
      </p>
      <ul className={styles.sections}>
        {sections.map((section, index) => (
          <li key={`${section.name ?? 'preamble'}-${index}`}>
            <div className={styles.itemHead}>
              <strong>{section.name ?? '模板前言'}</strong>
              <span className="badge">{({system:'角色职责与创作要求',user:'本次创作任务',assistant:'前轮回复',tool:'查阅资料'}[section.role ?? '']) ?? '补充依据'}</span>
              {section.policy === 'hash' && <span className="badge">未保存正文</span>}
              {section.truncated === true && <span className="badge badge-warning">已截断</span>}
              {section.omitted === 'budget' && <span className="badge badge-warning">超过留存上限，未保存正文</span>}
            </div>
            {typeof section.text === 'string' && section.text !== ''
              ? <CreationInput value={section.text} system={section.role === 'system'} />
              : <p className={styles.muted}>此部分未保存正文，无法还原当时的具体内容。</p>}
          </li>
        ))}
      </ul>
    </>
  )
}

function RecallView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  const groups = recallGroups(payload)
  const stats = recallStats(payload)
  return (
    <>
      <dl className={styles.pairs}>
        {groups.map((group) => <div key={group.key}><dt>{group.label}</dt><dd>{group.items.length}</dd></div>)}
      </dl>
      {Object.keys(stats).length > 0 && <Disclosure title="召回诊断"><ReadableContent value={stats} /></Disclosure>}
      {groups.map((group) => (
        <section key={group.key} className={styles.group} aria-label={group.label}>
          <h4>{group.label}（{group.items.length}）</h4>
          <ItemList group={group} />
        </section>
      ))}
    </>
  )
}

function HardRulesView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  const section = hardRuleSection(payload)
  const facts = hardRuleFacts(payload)
  return (
    <>
      <h4>本次必须遵守的设定</h4>
      {section
        ? <ReadableContent value={section.text ?? '此部分未保存正文，无法还原当时的具体内容。'} />
        : <p className={styles.muted}>本次没有单独留存【{HARD_RULE_SECTION}】要求</p>}
      <h4>作品中必须遵守的事实（{facts.length}）</h4>
      {facts.length === 0
        ? <p className={styles.muted}>作品中暂无标记为必须遵守的长期事实</p>
        : <ul className={styles.items}>{facts.map((fact, index) => <li key={index}>
          <ReadableContent value={Object.fromEntries(Object.entries(fact).filter(([key]) => !key.endsWith('_id') && key !== 'id' && key !== 'is_hard'))} />
        </li>)}</ul>}
    </>
  )
}

function FindingsView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  return <ol className={styles.items}>{findings(payload).map((finding, index) => <li key={finding.finding_id ?? index}>
    <div className={styles.itemHead}>
      <strong>{finding.conflict_type ? conflictTypeLabel(finding.conflict_type) : '创作问题'} · {index + 1}</strong>
      <span className={severityClass(finding.severity)}>{finding.severity ? severityLabel(finding.severity) : '未标明影响程度'}</span>
    </div>
    <p className={styles.summary}>{finding.scope ? scopeLabel(finding.scope) : '范围未记录'} · {finding.source ? findingSourceLabel(finding.source) : '来源未记录'}</p>
    <h5>处理建议</h5><ReadableContent value={finding.suggestion ?? '未提供处理建议'} />
    <h5>判断依据</h5>
    {(finding.evidence ?? []).length > 0 ? finding.evidence!.map((item, i) => <blockquote key={i}>第 {item.chapter} 章：{item.quote}</blockquote>) : <p className={styles.muted}>未保存具体证据</p>}
  </li>)}</ol>
}

function PatchView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  return <ol className={styles.items}>{appliedSpans(payload).map((span, index) => <li key={index}>
    <h4>修改 {index + 1}</h4><h5>修改前</h5><ReadableContent value={span.target} />
    <h5>修改后</h5><ReadableContent value={span.replacement} />
  </li>)}</ol>
}

function SubView({ view, payload }: {
  view: SnapshotSubView
  payload: ReturnType<typeof snapshotPayload>
}) {
  if (view === 'prompt') return <PromptSections payload={payload} />
  if (view === 'recall') return <RecallView payload={payload} />
  if (view === 'hardRules') return <HardRulesView payload={payload} />
  if (view === 'style') return <StyleView payload={payload} />
  if (view === 'findings') return <FindingsView payload={payload} />
  return <PatchView payload={payload} />
}

function StyleView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  const section = styleSection(payload)
  return (
    <>
      <h4>当时生效的文风要求</h4>
      {section?.text
        ? <CreationInput value={section.text} system={section.role === 'system'} />
        : <p className={styles.muted}>此部分未保存正文，无法还原当时的具体内容。</p>}
    </>
  )
}

export function SnapshotView({ token, snapshotId, onForbidden }: {
  token: string
  snapshotId: number
  onForbidden: () => void
}) {
  const load = useCallback(
    (signal: AbortSignal) => adminApi.getSnapshot(token, snapshotId, signal),
    [snapshotId, token],
  )
  const resource = useResource<AdminSnapshot>(load, onForbidden)
  const value = resource.data
  const payload = useMemo(() => snapshotPayload(value?.payload), [value])
  const views = useMemo(() => availableSubViews(payload), [payload])
  const [picked, setPicked] = useState<SnapshotSubView | null>(null)
  const active = picked !== null && views.includes(picked) ? picked : views[0] ?? null
  return (
    <LoadState {...resource} empty={!value}>
      {value && <article className={styles.snapshot} aria-label={`快照 ${value.id}`}>
        <div className={styles.head}>
          <div>
            <h3>{nodeLabel(value.stage)} · 第 {value.chapter_seq ?? '—'} 章 · 第 {value.attempt} 次</h3>
            <dl className={styles.pairs}>
              <div><dt>模型</dt><dd>{value.model_id ?? '未记录'}</dd></div>
              <div><dt>耗时</dt><dd>{formatDuration(value.duration_ms)}</dd></div>
              <div><dt>输入 token</dt><dd>{value.input_tokens.toLocaleString()}</dd></div>
              <div><dt>输出 token</dt><dd>{value.output_tokens.toLocaleString()}</dd></div>
              <div><dt>预估成本</dt><dd>{formatCost(value.cost_est)}</dd></div>
              <div><dt>缓存</dt><dd>{value.cache_hit ? '命中' : '未命中'}</dd></div>
              <div><dt>降级</dt><dd>{value.degraded ? '是' : '否'}</dd></div>
              <div><dt>重试</dt><dd>{value.retry_count}</dd></div>
              <div><dt>创建时间</dt><dd>{formatDate(value.created_at)}</dd></div>
            </dl>
          </div>
          <RefreshButton onClick={resource.retry} />
        </div>
        <div className={styles.flags}>
          <span className="badge">部分内容已留存</span>
          {value.payload.truncated && <span className="badge badge-warning">内容已截断</span>}
          {value.payload.redacted && <span className="badge badge-warning">敏感信息已脱敏</span>}
        </div>
        {value.snapshot_missing
          ? <p className="banner banner-warning">这条旧记录未保存创作依据和输出内容，只能查看调用时间与用量。</p>
          : <>
            <nav className={styles.subnav} aria-label="快照子视图">
              {views.map((view) => <button
                key={view}
                type="button"
                className={active === view ? styles.activeView : ''}
                aria-pressed={active === view}
                onClick={() => setPicked(view)}
              >{SUB_VIEW_LABELS[view]}</button>)}
            </nav>
            {active && <SubView view={active} payload={payload} />}
          </>}
        {payload.output && <section className={styles.group}>
          <h4>本次输出摘录</h4>
          <p className={styles.summary}>这里只展示留存的片段；完整正文请到作品章节中查看。</p>
          <ReadableContent value={payload.output.excerpt} />
        </section>}
        {payload.summary && <section className={styles.group}>
          <h4>问题检查小结</h4>
          <ReadableContent value={payload.summary} />
        </section>}
        {payload.error && <p className="banner banner-error">{payload.error}</p>}
        <Disclosure title="技术诊断"><CapturedView value={value.payload} raw label="原始章节快照" /></Disclosure>
      </article>}
    </LoadState>
  )
}
