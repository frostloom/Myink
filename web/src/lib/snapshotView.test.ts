import { expect, it } from 'vitest'
import type { CapturedData } from './adminApi'
import {
  appliedSpans,
  availableSubViews,
  fieldLabel,
  findings,
  hardRuleFacts,
  promptSections,
  recallGroups,
  scalarPairs,
  severityClass,
  snapshotPayload,
  styleSection,
} from './snapshotView'

function captured(data: unknown): CapturedData {
  return {
    data, truncated: false, redacted: false,
    limits: { max_depth: 10, max_items: 80, max_text: 16000, max_bytes: 65536 },
  }
}

const writePayload = {
  _capture: { scope: 'snapshot', selective: true, truncated: false, redacted: false },
  prompt: {
    bytes: 4096,
    truncated: false,
    sections: [
      { role: 'system', name: '句式禁令', policy: 'hash', bytes: 900, sha256: 'a'.repeat(64) },
      { role: 'system', name: '题材参考文档', policy: 'hash', bytes: 3000, sha256: 'b'.repeat(64) },
      { role: 'system', name: '世界观硬约束', policy: 'full', text: '【世界观硬约束】\n- 灵气不可外放' },
      { role: 'user', name: '文风要求 v3', policy: 'full', text: '【文风要求 v3】\n克制冷峻' },
      { role: 'user', name: '章节计划', policy: 'full', text: '【章节计划】\n主角进山' },
    ],
  },
  recall: {
    counts: { long_term_facts: 2 },
    stats: { share: 0.5, vector_hits: 3 },
    groups: {
      long_term_facts: [
        { fact_id: 'f1', content: '灵气不可外放', is_hard: true, source: 'book_setup' },
        { fact_id: 'f2', content: '主角怕水', is_hard: false, chapter: 4 },
      ],
      open_foreshadows: [{ foreshadow_id: 's1', excerpt: '铜镜里的第二个人影' }],
    },
  },
  output: { bytes: 5200, sha256: 'c'.repeat(64), excerpt: '他踏进山门。' },
}

it('drops the retention marker and survives a missing payload', () => {
  expect(snapshotPayload(captured(writePayload))).not.toHaveProperty('_capture')
  expect(snapshotPayload(captured(null))).toEqual({})
  expect(snapshotPayload(undefined)).toEqual({})
  expect(snapshotPayload(captured('不是对象'))).toEqual({})
})

it('separates full sections from hash-only ones', () => {
  const payload = snapshotPayload(captured(writePayload))
  const sections = promptSections(payload)

  expect(sections).toHaveLength(5)
  expect(sections.filter((section) => section.text === undefined).map((section) => section.name))
    .toEqual(['句式禁令', '题材参考文档'])
  expect(styleSection(payload)?.name).toBe('文风要求 v3')
  expect(styleSection(payload)?.text).toContain('克制冷峻')
})

it('labels recall groups in Chinese and keeps unknown keys verbatim', () => {
  const groups = recallGroups(snapshotPayload(captured(writePayload)))

  expect(groups.map((group) => group.label)).toEqual(['长期事实与硬约束', '开放伏笔'])
  const unknown = recallGroups(snapshotPayload(captured({ recall: { groups: { 新腿: [] } } })))
  expect(unknown[0]?.label).toBe('新腿')
})

it('keeps only the hard-labelled facts as hard-rule sources', () => {
  const payload = snapshotPayload(captured(writePayload))

  expect(hardRuleFacts(payload).map((fact) => fact.fact_id)).toEqual(['f1'])
})

it('only offers sub-views that actually carry content', () => {
  const payload = snapshotPayload(captured(writePayload))

  expect(availableSubViews(payload)).toEqual(['prompt', 'recall', 'hardRules', 'style'])
  expect(availableSubViews({})).toEqual([])
  expect(availableSubViews(snapshotPayload(captured({ findings: [{ severity: 'major' }] }))))
    .toEqual(['findings'])
})

it('reads findings, applied spans and scalar pairs defensively', () => {
  const payload = snapshotPayload(captured({
    findings: [{ severity: 'major', suggestion: '把铜镜改成铜铃' }],
    applied_spans: [
      { target: '灵气外放', replacement: '灵气内敛' },
      { target: '只给了目标没给替换' },
      '不是对象',
    ],
  }))

  expect(findings(payload)).toHaveLength(1)
  expect(appliedSpans(payload)).toEqual([{ target: '灵气外放', replacement: '灵气内敛' }])
  expect(scalarPairs({ chapter: 4, is_hard: true, nested: {}, excerpt: '不该成对显示' }))
    .toEqual([['chapter', '4'], ['is_hard', 'true']])
})

it('maps severity to a badge class and falls back for unknown fields', () => {
  expect(severityClass('critical')).toBe('badge badge-error')
  expect(severityClass('major')).toBe('badge badge-warning')
  expect(severityClass('minor')).toBe('badge')
  expect(severityClass(null)).toBe('badge')
  expect(fieldLabel('fact_id')).toBe('事实')
  expect(fieldLabel('没登记过的键')).toBe('没登记过的键')
})
