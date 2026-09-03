// 建书题材（§7.11 建书向导）：自由输入 + 常用题材标签组合。
// 题材后端本就是自由字符串（models/project.py String(64)，无枚举校验），
// GENRE_SUGGESTIONS 只是建议集非限定——用户可输入任意题材/组合（如「都市修仙」）。
// 点选标签在逗号分隔串上追加/移除，支持多题材叠加。
export const GENRE_SUGGESTIONS: string[] = [
  '仙侠', '玄幻', '都市', '科幻', '历史', '悬疑', '灵异',
  '无限流', '末世', '星际', '系统流', '武侠', '西幻', '轻小说',
]

/** 当前题材串 → 去重标签列表（按全角/半角逗号切，trim，过滤空段） */
export function parseGenres(text: string): string[] {
  return [...new Set(text.split(/[,，]/).map((s) => s.trim()).filter(Boolean))]
}

/** 点选标签：已存在则移除，否则追加（逗号拼接）。返回新题材串。 */
export function toggleGenre(current: string, tag: string): string {
  const list = parseGenres(current)
  const i = list.indexOf(tag)
  if (i >= 0) list.splice(i, 1)
  else list.push(tag)
  return list.join('，')
}
