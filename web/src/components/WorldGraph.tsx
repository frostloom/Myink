// 关系图谱（§9 世界拓扑：ECharts 力导向分组图谱）。全量数据 → 4 类分组节点 + 人物关系/
// 地点层级边；活跃实线 / 失效虚线；拖拽 / 缩放 / 图例过滤开箱即用。
// tree-shaking：只从 echarts/core 按需注册 GraphChart + Tooltip + Legend + SVGRenderer。
import { useEffect, useRef, useState } from 'react'
import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
import { api } from '../lib/api'
import { formatApiError } from '../lib/apiError'
import { MAX_GRAPH_NODES, toEchartsOption } from '../lib/graph'
import type { WorldGraphResponse } from '../types'
import styles from './WorldGraph.module.css'

echarts.use([GraphChart, TooltipComponent, LegendComponent, SVGRenderer])

export function WorldGraph({ projectId }: { projectId: string }) {
  const ref = useRef<HTMLDivElement>(null)
  const chartRef = useRef<ReturnType<typeof echarts.init> | null>(null)
  const [graph, setGraph] = useState<WorldGraphResponse | null>(null)
  const [clipped, setClipped] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    // 切书/重试时清旧错误与截断数（同项目内不会重跑；projectId 变才重置）
    setError(null)
    setClipped(0)
    const el = ref.current
    if (!el) return
    const chart = echarts.init(el)
    chartRef.current = chart
    const onResize = () => chart.resize()
    const ro = new ResizeObserver(onResize)
    ro.observe(el)
    void api
      .listGraph(projectId)
      .then((g) => {
        if (!alive) return
        setGraph(g)
        setClipped(Math.max(0, g.nodes.length - MAX_GRAPH_NODES))
        if (g.nodes.length > 0) chart.setOption(toEchartsOption(g))
      })
      .catch((err: unknown) => {
        if (alive) setError(formatApiError(err, '关系图谱加载失败'))
      })
    return () => {
      alive = false
      ro.disconnect()
      chart.dispose()
      chartRef.current = null
    }
  }, [projectId])

  const empty = graph !== null && graph.nodes.length === 0

  return (
    <div className={styles.wrap}>
      {error && <div className="banner banner-error">{error}</div>}
      {empty && (
        <div className="empty">
          暂无关系与设定数据。写作中出现人物关系 / 地点层级 / 设定实体后自动生成世界拓扑。
        </div>
      )}
      <div ref={ref} className={empty || error ? styles.hidden : styles.canvas} />
      {clipped > 0 && (
        <p className={styles.hint}>
          节点超过 {MAX_GRAPH_NODES} 个，已截断 {clipped} 个（仅展示最核心设定）。
        </p>
      )}
    </div>
  )
}
