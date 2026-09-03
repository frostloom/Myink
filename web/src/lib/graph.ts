// 关系图谱纯函数（§9 世界拓扑：4 类节点 + 人物关系/地点层级边 → ECharts 力导向配置）。
// 关系中文标签 / 配色 / 图例元数据集中在此，便于单测；组件只负责挂载渲染。

import type { GraphEdge, GraphNode, WorldGraphResponse } from '../types'

/** 人物关系类型 → 中文标签（§7.8 九类关系） */
export const RELATION_LABELS: Record<string, string> = {
  hostile: '敌对',
  ally: '盟友',
  master_student: '师徒',
  located_in: '位于',
  owns: '拥有',
  defeated_by: '败于',
  knows: '相识',
  promises: '承诺',
  happened_at: '发生于',
}

/** 关系类型 → 边配色（同类一色；活跃/失效由线型区分，不另设色） */
export const RELATION_TONE: Record<string, string> = {
  hostile: '#d64541',
  ally: '#3aa675',
  master_student: '#8e6cc8',
  located_in: '#5b9bd5',
  owns: '#d9a03c',
  defeated_by: '#c0392b',
  knows: '#7f8c8d',
  promises: '#b26a00',
  happened_at: '#4d6bd9',
}

/** 地点层级边配色（与 located_in 区分开，层级是结构关系不是人物关系） */
export const HIERARCHY_TONE = '#8a95a6'

export function relationLabel(edgeType: string): string {
  if (edgeType === 'hierarchy') return '位于'
  return RELATION_LABELS[edgeType] ?? edgeType
}

export function relationTone(edgeType: string): string {
  if (edgeType === 'hierarchy') return HIERARCHY_TONE
  return RELATION_TONE[edgeType] ?? HIERARCHY_TONE
}

/** 4 类节点图例元数据（图例名 + 节点配色） */
export const CATEGORY_META: Record<string, { label: string; color: string }> = {
  character: { label: '人物', color: '#5b9bd5' },
  faction: { label: '势力', color: '#8e6cc8' },
  location: { label: '地点', color: '#3aa675' },
  entity: { label: '设定实体', color: '#d9a03c' },
}

/** 类别键顺序（与下方 categories 数组索引对齐；ECharts 节点 category 需命中索引或 name，
 *  内部类型字符串（如 'character'）不匹配中文图例名会导致整图静默不渲染） */
const CATEGORY_KEYS = Object.keys(CATEGORY_META)

export function categoryLabel(type: string): string {
  return CATEGORY_META[type]?.label ?? type
}

export function categoryColor(type: string): string {
  return CATEGORY_META[type]?.color ?? '#7f8c8d'
}

/** 节点数上限（力导向性能：超大书只渲染最核心设定，超限由组件提示截断数） */
export const MAX_GRAPH_NODES = 200

interface EchartsNode {
  id: string
  name: string
  category: number
  symbolSize: number
  itemStyle: { color: string }
  _node: GraphNode
}

interface EchartsLink {
  source: string
  target: string
  label: { show: boolean; formatter: string; fontSize: number; color: string }
  lineStyle: {
    color: string
    width: number
    type: 'solid' | 'dashed'
    curveness: number
  }
  _edge: GraphEdge
}

/**
 * API 拓扑 → ECharts graph series 配置。
 * 节点裁剪到 MAX_GRAPH_NODES（超限截断）；边端点不在裁剪后节点集 → 丢弃（父地点
 * 可能被截断或被删）。tooltip 边：A —(关系)→ B · 置信度 · 第 N 章 · 活跃/已失效。
 */
export function toEchartsOption(graph: WorldGraphResponse) {
  const nodes = graph.nodes.slice(0, MAX_GRAPH_NODES).map<EchartsNode>((n) => ({
    id: n.id,
    name: n.name,
    category: CATEGORY_KEYS.indexOf(n.type in CATEGORY_META ? n.type : 'entity'),
    symbolSize: n.type === 'character' ? 34 : n.type === 'faction' ? 28 : n.type === 'location' ? 24 : 20,
    itemStyle: { color: categoryColor(n.type) },
    _node: n,
  }))
  const nodeIds = new Set(nodes.map((n) => n.id))
  const links = graph.edges
    .filter((e) => nodeIds.has(e.source_id) && nodeIds.has(e.target_id))
    .map<EchartsLink>((e) => ({
      source: e.source_id,
      target: e.target_id,
      label: {
        show: true,
        formatter: relationLabel(e.edge_type),
        fontSize: 10,
        color: '#8a95a6',
      },
      lineStyle: {
        color: relationTone(e.edge_type),
        width: e.edge_type === 'hierarchy' ? 1.5 : 2,
        type: e.expired ? 'dashed' : 'solid',
        curveness: 0.15,
      },
      _edge: e,
    }))

  const nameById = new Map(graph.nodes.map((n) => [n.id, n.name]))
  const edgeTip = (e: GraphEdge): string => {
    const parts = [
      `${nameById.get(e.source_id) ?? e.source_id} —(${relationLabel(e.edge_type)})→ ${nameById.get(e.target_id) ?? e.target_id}`,
    ]
    if (e.confidence != null) parts.push(`置信度 ${Math.round(e.confidence * 100)}%`)
    if (e.source_chapter != null) parts.push(`第 ${e.source_chapter} 章`)
    parts.push(e.expired ? '已失效' : '活跃')
    return parts.join(' · ')
  }
  const nodeTip = (n: GraphNode): string => {
    const parts = [n.name, categoryLabel(n.type)]
    if (n.type === 'character' && n.realm_cap) parts.push(n.realm_cap)
    if (n.type === 'faction' && n.stance) parts.push(n.stance)
    if (n.type === 'entity' && n.entity_type) parts.push(n.entity_type)
    return parts.join(' · ')
  }

  return {
    tooltip: {
      trigger: 'item',
      formatter: (params: { dataType?: string; data?: EchartsNode & EchartsLink }) => {
        if (params.dataType === 'edge' && params.data?._edge) return edgeTip(params.data._edge)
        if (params.data?._node) return nodeTip(params.data._node)
        return String(params.data?.name ?? '')
      },
    },
    legend: {
      data: Object.values(CATEGORY_META).map((c) => c.label),
      top: 0,
    },
    series: [
      {
        type: 'graph',
        layout: 'force',
        roam: true,
        draggable: true,
        data: nodes,
        links,
        categories: Object.values(CATEGORY_META).map((c) => ({ name: c.label })),
        force: { repulsion: 140, edgeLength: [60, 180], gravity: 0.1 },
        label: { show: true, position: 'right', fontSize: 11 },
        emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
      },
    ],
  }
}
