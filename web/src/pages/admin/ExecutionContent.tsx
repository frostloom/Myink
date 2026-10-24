import { Disclosure } from './Disclosure'
export { Disclosure } from './Disclosure'
import { ResourceContent } from './ResourceContent'
import type { CapturedData } from '../../lib/adminApi'
import { asRecord } from '../../lib/snapshotView'
import { resourceTitle } from '../../lib/resourceDisplay'
import { ReadableContent } from './ReadableContent'
import { parseContent } from '../../lib/readableContent'
import styles from './ExecutionDetail.module.css'

function records(value: unknown) { return Array.isArray(value) ? value.map(asRecord).filter(item => item !== null) : [] }
function text(value: unknown): string { return typeof value === 'string' ? value : '' }

export function CreationInput({ value, system }: { value: unknown; system: boolean }) {
  if (typeof value !== 'string') return <ReadableContent value={value} />
  const catalogue: string[] = []
  let content = value.replace(/【本任务可查阅的准确路径】[\s\S]*?(?=\n【|$)/g, block => {
    const start = block.indexOf('[')
    const paths = start < 0 ? null : parseContent(block.slice(start))
    if (!Array.isArray(paths) || !paths.every(path => typeof path === 'string')) {
      return '【可供查阅的写作资料】\n目录未完整留存，无法还原全部可用资料。'
    }
    catalogue.push(...paths)
    return `【可供查阅的写作资料】\n本次提供 ${paths.length} 项写作资料供 AI 按需查阅；提供目录不代表已经阅读。`
  })
  if (system) content = content.replace(/输出格式（硬要求[^\n]*\n(?:[^\n]+\n?)+/g,
    '【交付格式】\n系统已固定章节拆分和交付约定，用于将输出保存为独立章节。\n')
  if (system) content = content.replace(/输出严格 JSON：\s*\n\{[^\n]+\}\nverdict[^\n]*/g, '【审核结论的交付约定】\n仅在正文可直接发布时判为通过；存在必须修改的问题时，需要列出问题与可执行的修改建议。')
    .replace(/issues 与 suggestions/g, '问题与修改建议').replace(/写进 issues/g, '记入问题清单')
  content = content.replace(/\bread_genre_reference\b/g, '资料查阅工具')
    .replace(/^=+\s*CHAPTER\s+\d+(?:\s+(?:CONTENT|TITLE))?\s*=+\s*$/gim, '')
  return <>
    <ReadableContent value={content} />
    {catalogue.length > 0 && <Disclosure title="查看可用资料名称"><ul className={styles.items}>
      {catalogue.map((path, index) => <li key={index}>{resourceTitle({ kind: 'reference', name: path })}</li>)}
    </ul></Disclosure>}
  </>
}

export function ExecutionError({ value, label }: { value: CapturedData; label: string }) {
  return <section aria-label={label}><h4>{label}</h4>
    {value.truncated && <p className={styles.muted}>内容已截断</p>}
    {value.redacted && <p className={styles.muted}>敏感信息已脱敏</p>}
    <ReadableContent value={value.data} />
  </section>
}

export function ExecutionContent({ value }: { value: unknown }) {
  const data = asRecord(value)
  const response = asRecord(data?.response)
  const output = response?.content
  const review = asRecord(parseContent(output))
  const invalidOutput = typeof output === 'string' && typeof parseContent(output) === 'string' && /^\s*(?:```(?:json)?\s*)?[[{]\s*"/.test(output)
  const requests = records(response?.tool_calls)
  const reads = records(data?.tool_trace)
  const messages = records(data?.messages)
  return <div className={styles.content}>
    <section aria-label="实际资料与状态查阅"><h4>实际资料与状态查阅</h4>
      {reads.length === 0
        ? <p className={styles.muted}>本次调用没有保存查阅记录。已提供资料目录不代表实际读取过资料。</p>
        : <ul className={styles.reads}>{reads.map((read, index) => {
          const args = asRecord(read.arguments)
          const path = text(args?.path)
          const result = parseContent(read.result)
          const record = asRecord(result)
          const failed = Boolean(read.skipped) || Boolean(record?.error) || /^\s*\{\s*"error"\s*:/.test(text(read.result))
          const incomplete = !record && /^\s*\{/.test(text(read.result))
          const contentFragment = incomplete && /"content"\s*:/.test(text(read.result))
          const reference = read.tool === 'read_genre_reference'
          const label = reference
            ? (path ? resourceTitle({ kind: 'reference', name: path }) : '查询写作资料目录')
            : ({ inspect_character: '查询人物状态', inspect_foreshadows: '查询伏笔', inspect_plot_threads: '查询剧情线', inspect_facts: '查询世界观约束' }[text(read.tool)] ?? '其他只读查阅')
          const status = read.skipped ? '未执行：额度已用尽' : failed ? '读取失败'
            : contentFragment ? '已返回正文片段'
            : reference && typeof record?.content === 'string' && record.content.length > 0 ? '已读取正文'
            : reference && !path && Array.isArray(record?.files) ? '已返回目录'
            : read.result ? '已返回查阅结果' : '结果未留存'
          return <li key={index} className={styles.read} data-failed={failed}>
            <div className={styles.readHead}><strong>{label}</strong><span>{status}</span></div>
            {read.skipped ? <p className={styles.muted}>本次可查阅次数已用完，这项请求没有执行。</p>
              : failed ? <p className={styles.muted}>这次未能取得资料，不能算作已阅读。</p>
              : incomplete ? <p className={styles.muted}>查阅返回的内容未完整留存，无法还原全文；原始片段可在技术诊断中查看。</p>
              : record?.content ? <Disclosure title="查看读到的资料"><ResourceContent body={{files:[{path,content:text(record.content)}]}} /></Disclosure>
              : record?.files ? <p className={styles.muted}>取得了可查阅资料清单；取得目录不等于阅读了正文。</p>
              : read.result ? <Disclosure title="查看查阅结果"><ReadableContent value={result} /></Disclosure> : null}
          </li>
        })}</ul>}
    </section>
    {requests.length > 0 ? <section><h4>本次调用的进展</h4><p className={styles.text}>本次回复发起了 {requests.length} 项资料或状态查阅请求，尚不是最终成稿。</p><p className={styles.muted}>查阅是否执行成功，请以保存的查阅结果为准。</p></section>
      : output != null && output !== '' && <section aria-label="模型输出"><h4>模型输出</h4>
        {invalidOutput ? <p className={styles.muted}>模型回复的格式无法识别，或留存内容不完整，当前无法可靠展示结果。可展开技术诊断核对原始回复。</p> : review?.verdict ? <>
          <p><strong>{review.verdict === 'pass' ? '审核通过' : review.verdict === 'revise' ? '建议修改' : '审核结果待确认'}</strong></p>
          <ReadableContent value={Object.fromEntries(Object.entries(review).filter(([key]) => key !== 'verdict'))} />
        </> : <ReadableContent value={output} />}
      </section>}
    {messages.length > 0 && <Disclosure title={`查看创作依据（${messages.length} 条）`}>
      <p className={styles.muted}>以下是本次调用实际收到的要求和资料，按用途整理。完整协议和原始记录可在技术诊断中查看。</p>
      {messages.map((message, index) => <section className={styles.input} key={index}>
        <h4>{({ system: '角色职责与创作要求', user: '本次创作任务', assistant: '前轮回复', tool: '查阅返回的资料' }[text(message.role)] ?? '补充输入')} · {index + 1}</h4>
        <CreationInput value={message.content} system={message.role === 'system'} />
      </section>)}
    </Disclosure>}
  </div>
}
