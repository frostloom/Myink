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
  fieldLabel,
  findings,
  HARD_RULE_SECTION,
  hardRuleFacts,
  hardRuleSection,
  promptSections,
  recallGroups,
  recallStats,
  scalarPairs,
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
  RecordFields,
  RefreshButton,
  useResource,
  ValueText,
} from './shared'
import styles from './SnapshotView.module.css'

function ItemList({ group }: { group: RecallGroup }) {
  if (group.items.length === 0) return <p className={styles.muted}>这一组召回为空</p>
  return (
    <ul className={styles.items}>
      {group.items.map((item, index) => (
        <li key={`${group.key}-${index}`}>
          <div className={styles.itemHead}>
            {typeof item.name === 'string' && <strong>{item.name}</strong>}
            {typeof item.kind === 'string' && <span className="badge">{item.kind}</span>}
            {item.is_hard === true && <span className="badge badge-warning">硬约束</span>}
          </div>
          <dl className={styles.pairs}>
            {scalarPairs(item).filter(([key]) => key !== 'name' && key !== 'kind').map(([key, value]) => (
              <div key={key}><dt>{fieldLabel(key)}</dt><dd>{value}</dd></div>
            ))}
          </dl>
          {typeof item.excerpt === 'string' && item.excerpt !== '' && <p className={styles.excerpt}>{item.excerpt}</p>}
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
        共 {sections.length} 节 · 留存预算 {payload.prompt?.bytes ?? 0} 字节
        {payload.prompt?.truncated === true && <span className="badge badge-warning">整体已截断</span>}
      </p>
      <ul className={styles.sections}>
        {sections.map((section, index) => (
          <li key={`${section.name ?? 'preamble'}-${index}`}>
            <div className={styles.itemHead}>
              <strong>{section.name ?? '模板前言'}</strong>
              <span className="badge">{section.role ?? '未记角色'}</span>
              {section.policy === 'hash' && <span className="badge">仅存哈希</span>}
              {section.truncated === true && <span className="badge badge-warning">已截断</span>}
              {section.omitted === 'budget' && <span className="badge badge-warning">预算外省略</span>}
              {typeof section.bytes === 'number' && <span className={styles.muted}>{section.bytes} 字节</span>}
            </div>
            {typeof section.text === 'string' && section.text !== ''
              ? <pre className={styles.pre}>{section.text}</pre>
              : <p className={styles.muted}>原文未留存，仅 {section.bytes ?? 0} 字节 / {section.sha256?.slice(0, 12) ?? '—'}</p>}
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
      {Object.keys(stats).length > 0 && <dl className={styles.pairs}>
        {Object.entries(stats).map(([key, value]) => (
          <div key={key}><dt>{fieldLabel(key)}</dt><dd><ValueText value={value} /></dd></div>
        ))}
      </dl>}
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
      <h4>当时注入的硬约束</h4>
      {section
        ? <pre className={styles.pre}>{section.text ?? `原文未留存（${section.bytes ?? 0} 字节）`}</pre>
        : <p className={styles.muted}>这次提示词没有【{HARD_RULE_SECTION}】节</p>}
      <h4>台账侧标了硬约束的事实（{facts.length}）</h4>
      {facts.length === 0
        ? <p className={styles.muted}>没有 is_hard 的长期事实</p>
        : <ul className={styles.items}>{facts.map((fact, index) => <li key={index}>
          <p className={styles.excerpt}>{String(fact.content ?? fact.fact_id ?? '')}</p>
          <dl className={styles.pairs}>
            {scalarPairs(fact).filter(([key]) => key !== 'content' && key !== 'excerpt').map(([key, value]) => (
              <div key={key}><dt>{fieldLabel(key)}</dt><dd>{value}</dd></div>
            ))}
          </dl>
        </li>)}</ul>}
    </>
  )
}

function FindingsView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  return (
    <div className={styles.tableWrap}><table>
      <thead><tr><th>严重度</th><th>类型</th><th>范围</th><th>来源</th><th>置信</th><th>建议</th><th>证据</th></tr></thead>
      <tbody>{findings(payload).map((finding, index) => <tr key={finding.finding_id ?? index}>
        <td><span className={severityClass(finding.severity)}>{finding.severity ? severityLabel(finding.severity) : '未标'}</span></td>
        <td>{finding.conflict_type ? conflictTypeLabel(finding.conflict_type) : '—'}</td>
        <td>{finding.scope ? scopeLabel(finding.scope) : '—'}</td>
        <td>{finding.source ? findingSourceLabel(finding.source) : '—'}</td>
        <td>{finding.confidence ?? '—'}</td>
        <td>{finding.suggestion ?? '—'}</td>
        <td>{(finding.evidence ?? []).map((item) => `第 ${item.chapter} 章：${item.quote}`).join('；') || '—'}</td>
      </tr>)}</tbody>
    </table></div>
  )
}

function PatchView({ payload }: { payload: ReturnType<typeof snapshotPayload> }) {
  const spans = appliedSpans(payload)
  return (
    <div className={styles.tableWrap}><table>
      <thead><tr><th>原文</th><th>改为</th></tr></thead>
      <tbody>{spans.map((span, index) => <tr key={index}>
        <td><pre className={styles.pre}>{span.target}</pre></td>
        <td><pre className={styles.pre}>{span.replacement}</pre></td>
      </tr>)}</tbody>
    </table></div>
  )
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
        ? <pre className={styles.pre}>{section.text}</pre>
        : <p className={styles.muted}>原文未留存（{section?.bytes ?? 0} 字节）</p>}
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
          <span className="badge">选择性留存</span>
          {value.payload.truncated && <span className="badge badge-warning">内容已截断</span>}
          {value.payload.redacted && <span className="badge badge-warning">敏感信息已脱敏</span>}
        </div>
        {value.snapshot_missing
          ? <p className="banner banner-warning">这条记录早于快照上线，只剩标量遥测。</p>
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
          <h4>模型输出（正文已落章节表，这里只留摘要）</h4>
          <p className={styles.summary}>{payload.output.bytes} 字节 · {payload.output.sha256.slice(0, 12)}</p>
          <pre className={styles.pre}>{payload.output.excerpt}</pre>
        </section>}
        {payload.summary && <section className={styles.group}>
          <h4>校验小结</h4>
          <RecordFields value={payload.summary} />
        </section>}
        {payload.error && <p className="banner banner-error">{payload.error}</p>}
      </article>}
    </LoadState>
  )
}
