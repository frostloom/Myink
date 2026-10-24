import { resourceFieldLabels } from '../../lib/resourceFieldLabels'
import { parseContent } from '../../lib/readableContent'
import { asRecord, fieldLabel, isInternalKey } from '../../lib/snapshotView'
import styles from './ExecutionDetail.module.css'

const labels: Record<string, string> = {
  chapters: '章节安排', chapter_plans: '章节安排', chapter_count: '计划章数',
  chars_per_chapter: '每章目标字数', goal: '本章目标', beats: '情节推进',
  cast: '出场人物', characters: '人物设定', relations: '人物关系', relationships: '人物关系',
  ending: '故事结局', opening: '开场', conflict: '核心冲突', stakes: '风险与代价',
  payoff: '兑现与回报', twist: '转折', theme: '主题', logline: '故事梗概',
  hooks_to_plant: '拟埋设的伏笔', hooks_to_resolve: '拟回收的伏笔',
  issues: '发现的问题', suggestions: '修改建议', reason: '原因说明',
  severity: '影响程度', location: '发生位置', evidence: '判断依据',
  message: '情况说明', error: '问题说明', detail: '具体情况',
  genre: '题材', premise: '故事构想', brief: '创作方案', plan: '创作计划',
  draft: '草稿', body: '内容', instructions: '创作要求', world: '世界设定',
  must_include: '必须包含', must_avoid: '需要避免',
}
const enumFields = new Set(['verdict', 'status', 'severity', 'mode', 'role', 'lesson_type'])
const enums: Record<string, string> = {
  pass: '通过', revise: '需要修改', fail: '未通过', critical: '严重', major: '较大', minor: '较小',
  pending: '待处理', active: '进行中', resolved: '已解决', confirmed: '已确认', planted: '已埋设', developing: '推进中', dropped: '已放弃', expired: '已失效', must_handle: '必须处理', hint: '提示', rewrite: '需要重写', replan: '需要重新规划', system: '角色职责与创作要求', user: '本次创作任务', assistant: '模型回复', tool: '查阅资料',
  planning: '规划时使用', writing: '写作时使用', both: '规划和写作时使用',
}

// Find the end of a leading JSON object without treating braces inside strings as delimiters.
function leadingStructure(source: string): { value: unknown; tail: string } | null {
  const trimmed = source.trim()
  if (!/^[{[]/.test(trimmed)) return null
  let depth = 0
  let quoted = false
  let escaped = false
  for (let i = 0; i < trimmed.length; i++) {
    const char = trimmed[i]
    if (quoted) {
      if (escaped) escaped = false
      else if (char === '\\') escaped = true
      else if (char === '"') quoted = false
    } else if (char === '"') quoted = true
    else if (char === '{' || char === '[') depth++
    else if (char === '}' || char === ']') {
      depth--
      if (depth === 0) {
        const value = parseContent(trimmed.slice(0, i + 1))
        return typeof value === 'string' ? null : { value, tail: trimmed.slice(i + 1).trim() }
      }
    }
  }
  return null
}

/** Kept deterministic: show the saved facts, never invent a summary of missing data. */
export function ReadableContent({ value, field }: { value: unknown; field?: string }) {
  const parsed = parseContent(value)
  if (parsed === null || parsed === undefined || parsed === '') return <p className={styles.muted}>未记录</p>
  if (Array.isArray(parsed)) return parsed.length === 0
    ? <p className={styles.muted}>无</p>
    : <ol className={styles.items}>{parsed.map((item, index) => <li key={index}><ReadableContent value={item} /></li>)}</ol>
  const record = asRecord(parsed)
  if (record) {
    const entries = Object.entries(record).filter(([key, item]) => !isInternalKey(key) && item !== null && item !== undefined && item !== '')
    return <div className={styles.explanation}>{entries.map(([key, item]) => {
      const label = labels[key] ?? resourceFieldLabels[key] ?? fieldLabel(key)
      return <section className={styles.fact} key={key}>
        <h5>{label === key && /^[a-z][a-z0-9_]*$/i.test(key) ? '补充内容' : label}</h5>
        <ReadableContent value={item} field={key} />
      </section>
    })}{entries.length === 0 && <p className={styles.muted}>暂无内容</p>}</div>
  }
  if (typeof parsed === 'boolean') return <p className={styles.text}>{parsed ? '是' : '否'}</p>
  if (typeof parsed !== 'string') return <p className={styles.text}>{String(parsed)}</p>
  if (field && enumFields.has(field) && enums[parsed]) return <p className={styles.text}>{enums[parsed]}</p>

  const leading = leadingStructure(parsed)
  if (leading) return <div className={styles.explanation}><ReadableContent value={leading.value} />{leading.tail && <ReadableContent value={leading.tail} />}</div>
  if (/^\s*[[{]\s*"/.test(parsed)) return <p className={styles.muted}>这段结构化内容未完整留存或格式无法识别，无法可靠整理。原始片段可在技术诊断中查看。</p>

  // The writer's machine delimiters are display headings, not part of the story.
  const prose = parsed.replace(/^=+\s*CHAPTER\s+(\d+)(?:\s+(?:CONTENT|TITLE))?\s*=+\s*$/gim, '【第 $1 章】')
  const sections = [...prose.matchAll(/(?:^|\n)(?:【([^\n】]+)】|#{1,6}\s+([^\n]+))\s*\n?/g)]
  if (sections.length) return <div className={styles.explanation}>
    {sections[0].index! > 0 && <ReadableContent value={prose.slice(0, sections[0].index)} />}
    {sections.map((match, index) => {
      const title = match[1] ?? match[2]
      const body = prose.slice(match.index! + match[0].length, sections[index + 1]?.index).trim()
      return <section className={styles.fact} key={index}><h5>{title}</h5>
        {title === '章标记'
          ? <p className={styles.muted}>系统要求按章节分别输出，便于保存为独立章节。</p>
          : <ReadableContent value={body} />}
      </section>
    })}
  </div>
  // JSON embedded in otherwise readable prose (e.g. a plan followed by an instruction).
  const fenced = [...prose.matchAll(/```(?:json)?\s*\n([\s\S]*?)\n```/g)]
  if (fenced.length) {
    let start = 0
    const parts = fenced.flatMap((match) => {
      const before = prose.slice(start, match.index)
      start = match.index! + match[0].length
      const data = parseContent(match[1])
      return [before, data]
    })
    parts.push(prose.slice(start))
    return <div className={styles.explanation}>{parts.filter(part => part !== '').map((part, index) => <ReadableContent key={index} value={part} />)}</div>
  }
  return <p className={styles.text}>{prose}</p>
}
