// 扫榜源的纯展示映射（source → 中文标签 / 徽标色调 + 榜单字段格式化）。
// 抽成纯函数便于单测；字段键对齐 Python RankingsOut（rank/title/author/tags/hot）。
// source=remote（实时榜单）/ sample（降级样例：网络不可达 / RANKINGS_ENABLED=0）。
import type { BadgeTone } from '../components/StatusBadge'

export const SOURCE_LABELS: Record<string, string> = {
  remote: '实时榜单',
  sample: '样例数据',
}

export function sourceLabel(source: string): string {
  return SOURCE_LABELS[source] ?? source
}

/** remote 用 accent 徽标（真实外部源），sample 用 warning（降级，数据非实时） */
export function sourceTone(source: string): BadgeTone {
  return source === 'remote' ? 'accent' : 'warning'
}

/** tags 顿号连接展示（外部榜单标签可能缺失） */
export function tagsText(tags: string[] | undefined): string {
  return (tags ?? []).filter(Boolean).join('、')
}

/** hot 字段兜底（sanitize 后可能为空） */
export function hotText(hot: string | null | undefined): string {
  const s = (hot ?? '').trim()
  return s
}
