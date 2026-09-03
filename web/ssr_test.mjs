import * as echarts from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { TooltipComponent, LegendComponent } from 'echarts/components'
import { SVGRenderer } from 'echarts/renderers'
echarts.use([GraphChart, TooltipComponent, LegendComponent, SVGRenderer])

const PID = '09456ebc-6694-4bd9-a561-8b179634ebb5'
// 登录拿数据（同 toEchartsOption 的输入）
async function getGraph() {
  const r0 = await fetch('http://localhost:8080/api/v1/auth/token', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username:'demo', password:'demo123'}),
  })
  const { token } = await r0.json()
  const r = await fetch(`http://localhost:8080/api/v1/projects/${PID}/graph`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  return r.json()
}

// —— 复制 lib/graph.ts 的 CATEGORY_META 与 toEchartsOption ——
const CATEGORY_META = {
  character: { label: '人物', color: '#5b9bd5' },
  faction: { label: '势力', color: '#8e6cc8' },
  location: { label: '地点', color: '#3aa675' },
  entity: { label: '设定实体', color: '#d9a03c' },
}
function categoryColor(t){ return CATEGORY_META[t]?.color ?? '#7f8c8d' }
function toEchartsOption(graph) {
  const nodes = graph.nodes.slice(0, 200).map((n) => ({
    id: n.id, name: n.name, category: n.type in CATEGORY_META ? n.type : 'entity',
    symbolSize: n.type==='character'?34:n.type==='faction'?28:n.type==='location'?24:20,
    itemStyle: { color: categoryColor(n.type) },
  }))
  const nodeIds = new Set(nodes.map(n=>n.id))
  const links = graph.edges.filter(e=>nodeIds.has(e.source_id)&&nodeIds.has(e.target_id)).map(e=>({
    source: e.source_id, target: e.target_id,
    lineStyle: { color:'#8a95a6', width: 2, type: e.expired?'dashed':'solid', curveness: 0.15 },
  }))
  return {
    tooltip: { trigger: 'item', formatter: (p)=>{ try { return String(p.data?.name ?? '') } catch(e){ return '' } } },
    legend: { data: Object.values(CATEGORY_META).map(c=>c.label), top: 0 },
    series: [{
      type: 'graph', layout: 'force', roam: true, draggable: true,
      data: nodes, links,
      categories: Object.values(CATEGORY_META).map(c=>({name:c.label})),
      force: { repulsion: 140, edgeLength: [60,180], gravity: 0.1 },
      label: { show: true, position: 'right', fontSize: 11 },
      emphasis: { focus: 'adjacency', lineStyle: { width: 3 } },
    }],
  }
}

const graph = await getGraph()
console.log('API nodes:', graph.nodes.length, 'edges:', graph.edges.length)
const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: 800, height: 460 })
chart.setOption(toEchartsOption(graph))
const svg = chart.renderToSVGString()
// 统计节点符号（ECharts 节点 symbol 会渲染为 path 或 circle）
const nodeSym = (svg.match(/<circle/g)||[]).length
const pathCount = (svg.match(/<path/g)||[]).length
const textCount = (svg.match(/<text/g)||[]).length
const hasNames = graph.nodes.slice(0,5).some(n=>svg.includes(n.name))
console.log('SSR svg: circles=', nodeSym, 'paths=', pathCount, 'texts=', textCount, 'hasNodeName=', hasNames)
