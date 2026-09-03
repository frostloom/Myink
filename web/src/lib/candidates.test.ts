// 候选池展示映射纯函数单测：kind 标签/色调 + payload 字段渲染（curated 优先/未知键
// 兜底/冗余键跳过/UUID 截断/值格式化）。
import { describe, expect, it } from 'vitest'
import {
  candidateFields,
  candidateLabel,
  candidateTone,
  formatCandidateValue,
} from './candidates'

describe('candidateLabel / candidateTone', () => {
  it('候选有中文标签', () => {
    expect(candidateLabel('event')).toBe('事件')
    expect(candidateLabel('fact')).toBe('事实')
    expect(candidateLabel('character_state')).toBe('角色状态')
    expect(candidateLabel('relation_change')).toBe('关系变更')
    expect(candidateLabel('foreshadow')).toBe('伏笔')
    expect(candidateLabel('foreshadow_touch')).toBe('伏笔回收')
    expect(candidateLabel('chapter_summary')).toBe('章节摘要')
    expect(candidateLabel('memory_removal')).toBe('记忆删除')
  })

  it('未知 kind 回退原始字符串', () => {
    expect(candidateLabel('plotline')).toBe('plotline')
  })

  it('memory_removal 用 error 色调（破坏性动作警示）', () => {
    expect(candidateTone('memory_removal')).toBe('error')
    expect(candidateTone('event')).toBe('accent')
  })

  it('foreshadow_touch 与伏笔同用 warning 色调', () => {
    expect(candidateTone('foreshadow_touch')).toBe('warning')
  })
})

describe('formatCandidateValue', () => {
  it('空值跳过、布尔转是/否、数组顿号连接、对象 JSON', () => {
    expect(formatCandidateValue('k', null)).toBe('')
    expect(formatCandidateValue('k', undefined)).toBe('')
    expect(formatCandidateValue('is_hard', true)).toBe('是')
    expect(formatCandidateValue('participants', ['甲', '乙'])).toBe('甲、乙')
    expect(formatCandidateValue('trigger', { who: '甲' })).toBe('{"who":"甲"}')
  })

  it('UUID 型 id 截断前 8 位', () => {
    const id = '12345678-abcd-efgh-ijkl-987654321012'
    expect(formatCandidateValue('character_id', id)).toBe('12345678…')
    expect(formatCandidateValue('memory_id', id)).toBe('12345678…')
    // 非 id 键不截断
    expect(formatCandidateValue('summary', id)).toBe(id)
  })
})

describe('candidateFields', () => {
  it('character_state 按 curated 顺序展示字段并跳过冗余键', () => {
    const rows = candidateFields('character_state', {
      character_id: '12345678-abcd-efgh-ijkl-987654321012',
      field: 'realm',
      old_value: '筑基',
      new_value: '金丹',
      confidence: 0.9,
    })
    expect(rows).toEqual([
      ['角色', '12345678…'],
      ['字段', 'realm'],
      ['旧值', '筑基'],
      ['新值', '金丹'],
    ])
  })

  it('relation_change 双端角色 id 展示', () => {
    const rows = candidateFields('relation_change', {
      relation_type: 'hostile',
      source_id: 'aaaaaaaa-0000-0000-0000-000000000001',
      target_id: 'bbbbbbbb-0000-0000-0000-000000000002',
    })
    expect(rows[0]).toEqual(['关系', 'hostile'])
    expect(rows).toContainEqual(['源角色', 'aaaaaaaa…'])
    expect(rows).toContainEqual(['目标角色', 'bbbbbbbb…'])
  })

  it('未知键兜底为原键名', () => {
    const rows = candidateFields('foreshadow', { description: '埋个钩子', mystery_key: 'x' })
    expect(rows).toContainEqual(['描述', '埋个钩子'])
    expect(rows).toContainEqual(['mystery_key', 'x'])
  })

  it('空 payload 返回空数组', () => {
    expect(candidateFields('event', {})).toEqual([])
  })

  it('foreshadow_touch 展示伏笔 id/回收结果/说明', () => {
    const rows = candidateFields('foreshadow_touch', {
      foreshadow_id: 'aaaaaaaa-0000-0000-0000-000000000001',
      outcome: 'resolved',
      note: '灯谜在拍卖会上揭晓',
    })
    expect(rows).toEqual([
      ['伏笔', 'aaaaaaaa…'],
      ['回收结果', 'resolved'],
      ['说明', '灯谜在拍卖会上揭晓'],
    ])
  })
})
