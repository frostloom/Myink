// 关系图谱纯函数单测（§9 世界拓扑：中文标签 / 配色 / 失效虚线 / 端点裁剪 / 节点上限）。
import { describe, expect, it } from 'vitest'
import {
  CATEGORY_META,
  MAX_GRAPH_NODES,
  relationLabel,
  relationTone,
  toEchartsOption,
} from './graph'
import type { WorldGraphResponse } from '../types'

const graph: WorldGraphResponse = {
  nodes: [
    { id: 'a', name: '林晚', type: 'character', realm_cap: '金丹' },
    { id: 'b', name: '沈岳', type: 'character', realm_cap: '元婴' },
    { id: 'c', name: '青云宗', type: 'faction', stance: '正道' },
    { id: 'd', name: '青云山', type: 'location', parent_id: 'e' },
    { id: 'e', name: '青云州', type: 'location' },
    { id: 'f', name: '焚天剑', type: 'entity', entity_type: 'item' },
  ],
  edges: [
    { source_id: 'a', target_id: 'b', edge_type: 'hostile', confidence: 0.9, expired: false, source_chapter: 3 },
    { source_id: 'b', target_id: 'a', edge_type: 'knows', confidence: 0.7, expired: true, source_chapter: 8 },
    { source_id: 'd', target_id: 'e', edge_type: 'hierarchy', expired: false },
  ],
}

describe('relationLabel', () => {
  it('maps the nine relation types to Chinese labels', () => {
    expect(relationLabel('hostile')).toBe('敌对')
    expect(relationLabel('ally')).toBe('盟友')
    expect(relationLabel('master_student')).toBe('师徒')
    expect(relationLabel('located_in')).toBe('位于')
    expect(relationLabel('owns')).toBe('拥有')
    expect(relationLabel('defeated_by')).toBe('败于')
    expect(relationLabel('knows')).toBe('相识')
    expect(relationLabel('promises')).toBe('承诺')
    expect(relationLabel('happened_at')).toBe('发生于')
  })
  it('labels hierarchy as 位于 and falls back to raw type', () => {
    expect(relationLabel('hierarchy')).toBe('位于')
    expect(relationLabel('unknown')).toBe('unknown')
  })
})

describe('relationTone', () => {
  it('returns a distinct hex color per known type and a fallback', () => {
    expect(relationTone('hostile')).toMatch(/^#[0-9a-f]{6}$/i)
    expect(relationTone('hostile')).not.toBe(relationTone('ally'))
    expect(relationTone('nope')).toBe(relationTone('hierarchy'))
  })
})

describe('CATEGORY_META', () => {
  it('defines the four node categories', () => {
    expect(Object.keys(CATEGORY_META)).toEqual(['character', 'faction', 'location', 'entity'])
    for (const { label, color } of Object.values(CATEGORY_META)) {
      expect(label).toBeTruthy()
      expect(color).toMatch(/^#[0-9a-f]{6}$/i)
    }
  })
})

describe('toEchartsOption', () => {
  it('maps nodes/edges to a force-layout graph series', () => {
    const option = toEchartsOption(graph)
    const series = option.series[0]
    expect(series.type).toBe('graph')
    expect(series.layout).toBe('force')
    expect(series.data).toHaveLength(6)
    expect(series.links).toHaveLength(3)
    expect(series.categories).toHaveLength(4)
  })

  it('maps node category to the categories-array index (string type keys mismatch Chinese legend names)', () => {
    const option = toEchartsOption(graph)
    const node = (id: string) => option.series[0].data.find((n) => n.id === id)!
    expect(node('a').category).toBe(0) // character → 人物
    expect(node('c').category).toBe(1) // faction → 势力
    expect(node('d').category).toBe(2) // location → 地点
    expect(node('f').category).toBe(3) // entity → 设定实体
    expect(option.series[0].categories[node('a').category].name).toBe(CATEGORY_META.character.label)
  })

  it('renders active relations solid and expired relations dashed', () => {
    const option = toEchartsOption(graph)
    const link = (edgeType: string) => option.series[0].links.find((l) => l._edge.edge_type === edgeType)
    expect(link('hostile')!.lineStyle.type).toBe('solid')
    expect(link('knows')!.lineStyle.type).toBe('dashed')
  })

  it('maps relation edge to its tone and hierarchy to the hierarchy tone', () => {
    const option = toEchartsOption(graph)
    const link = (edgeType: string) => option.series[0].links.find((l) => l._edge.edge_type === edgeType)
    expect(link('hostile')!.lineStyle.color).toBe(relationTone('hostile'))
    expect(link('hierarchy')!.lineStyle.color).toBe(relationTone('hierarchy'))
  })

  it('drops edges whose endpoints are not in the node set', () => {
    const g: WorldGraphResponse = {
      nodes: [{ id: 'a', name: '林晚', type: 'character', realm_cap: '金丹' }],
      edges: [{ source_id: 'a', target_id: 'ghost', edge_type: 'ally', expired: false }],
    }
    const option = toEchartsOption(g)
    expect(option.series[0].links).toHaveLength(0)
  })

  it('clips nodes beyond the cap', () => {
    const many = Array.from({ length: MAX_GRAPH_NODES + 10 }, (_, i) => ({
      id: `n${i}`,
      name: `角色${i}`,
      type: 'character' as const,
      realm_cap: '金丹',
    }))
    const option = toEchartsOption({ nodes: many, edges: [] })
    expect(option.series[0].data).toHaveLength(MAX_GRAPH_NODES)
  })
})
