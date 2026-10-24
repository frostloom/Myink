import { referenceCsv } from './referenceCsv'
import type { ResourceBody, WritingResource } from './writingResources'
export function isSourceNotice(item: Pick<WritingResource, 'name' | 'kind'>) {
  return (
    item.kind === 'reference' &&
    /^(license|notice|copying)(\.|$)/i.test(
      item.name.split(/[\\/]/).pop() ?? '',
    )
  )
}
export function parseReferenceFile(file: {
  path: string
  content: string
}): unknown {
  if (/\.json$/i.test(file.path)) {
    try {
      return JSON.parse(file.content)
    } catch {
      /* Preserve invalid files as text for repair. */
    }
  }
  if (/\.csv$/i.test(file.path)) return referenceCsv(file.content) ?? file.content
  return file.content
}
function fileSummary(file: { path: string; content: string }): string {
  const parsed = parseReferenceFile(file)
  if (typeof parsed === 'string') return parsed.replace(/[#*`>]/g, '').trim()
  if (Array.isArray(parsed)) return `共 ${parsed.length} 条素材条目`
  if (parsed && typeof parsed === 'object') {
    const record = parsed as Record<string, unknown>
    const description = [record.description, record.title, record.summary].find(
      (v) => typeof v === 'string' && v,
    )
    if (typeof description === 'string') return description
    const errors = record.errors
    if (Array.isArray(errors))
      return `共 ${errors.length} 条错误条目，包含问题原因、影响与处理建议。`
    const entries = Object.values(record).find(Array.isArray)
    return entries
      ? `共 ${entries.length} 条素材条目`
      : `结构化参考资料，包含 ${Object.keys(record).length} 项内容`
  }
  return '结构化参考资料'
}
const referenceNames: Record<string, string> = {
  '人设与关系': '人物设计与关系写法', '写作技法': '叙事与写作技巧',
  '命名规则': '人物与事物命名', '场景写法': '场景组织与描写',
  '桥段套路': '桥段设计参考', '爽点与节奏': '爽点与阅读节奏',
  '裁决规则': '创作问题判断原则', '金手指与设定': '金手指与世界机制',
  '题材与调性推理': '题材方向与氛围判断',
  'genre-profiles': '各类题材的写法与节奏', 'genre-canonical': '题材名称与分类参考',
  'plot-signal-vs-spoiler': '剧情铺垫与剧透的区别',
  'reading-power-taxonomy': '追读动力与情绪回报',
  'blocking-override-guidelines': '重大创作问题的审核原则',
  'cool-points-guide': '爽点设计与兑现', 'core-constraints': '故事创作的基本约束',
  'naming-and-voice-gaps': '人物命名与说话风格',
  'strand-weave-pattern': '多条剧情线交织写法', 'genre-index': '题材分类索引',
  'golden-finger-templates': '金手指设计参考',
  '复合题材-融合逻辑': '复合题材融合写法', '大纲-卷时间线': '卷内时间线规划',
  '大纲-卷节拍表': '卷内情节节奏设计', '大纲-总纲': '整书大纲写法',
  '设定集-世界观': '世界观设定写法', '设定集-主角卡': '主角设计参考',
  '设定集-主角组': '多主角与团队设计', '设定集-力量体系': '力量体系设定参考',
  '设定集-反派设计': '反派塑造参考', '设定集-女主卡': '女主角设计参考',
  '设定集-金手指': '金手指设定写法',
}
export function referencePurpose(item: Pick<WritingResource, 'name' | 'kind'>) {
  const title = resourceTitle(item)
  if (title === '人物设计与关系写法') return '提供人物动机、行为逻辑和关系互动的写法；本书实际人物与关系仍由作品维护。'
  if (/题材/.test(title)) return '帮助规划、写作与审核理解不同题材的惯例；无需作者逐份勾选。'
  if (/大纲|时间线|节奏|剧情线/.test(title)) return '供规划与写作按需参考，组织情节、推进节奏和故事结构。'
  if (/审核|判断|约束/.test(title)) return '供创作与审核按需参考，识别故事问题并提出修改依据。'
  return `提供“${title}”的方法和示例，AI在创作需要时查阅，不会整份反复加入提示词。`
}
export function resourceTitle(item: Pick<WritingResource, 'name' | 'kind'>) {
  if (item.kind === 'role_prompt') {
    const knownNames: Record<string, string> = {'角色创作要求（写作与修订）': '写作提示词', '角色创作要求（故事规划）': '规划提示词', '角色创作要求（内容审核）': '审核提示词', '角色创作要求（记忆与文风提炼）': '记忆整理提示词', '角色创作要求（章节摘要）': '章节摘要提示词', '角色创作要求（台账语义校验）': '设定一致性检查提示词'}
    if (knownNames[item.name]) return knownNames[item.name]
    const role = /^角色创作要求[（(]([a-z0-9_]+)[）)]$/.exec(item.name)?.[1]
    if (role && writingRoles[role]) return writingRoles[role].name + '提示词'
  }
  if (isSourceNotice(item))
    return `来源说明 · ${item.name.split(/[\\/]/).pop()}`
  if (item.kind !== 'reference') return item.name
  const basename = item.name.split(/[\\/]/).pop()!.replace(/\.[a-z0-9]+$/i, '')
  return referenceNames[basename] ?? (/templates[/\\]genres[/\\]/.test(item.name) ? `${basename}写法参考` : basename)
}
export function resourceSummary(body: ResourceBody): string {
  if ('templates' in body)
    return Object.values(body.templates).filter(Boolean).join(' ') || '管理此角色在各写作阶段的创作要求'
  if ('files' in body)
    return (
      body.files
        .map(fileSummary)
        .join(' ')
        .replace(/[#*`>]/g, '')
        .trim() || '尚未添加参考正文'
    )
  if ('fields' in body)
    return body.fields.selling_point || body.fields.pacing || '尚未填写题材内容'
  if ('roles' in body)
    return (
      Object.values(body.roles)
        .filter(Boolean)
        .join(' ')
        .replace(/[#*`>]/g, '') || '尚未填写环节规则'
    )
  return (
    Object.values(body.profile)
      .filter((v) => typeof v === 'string' && v)
      .join(' ') || '尚未填写文风维度'
  )
}


export const writingRoles: Record<string, {name: string; when: string; purpose: string}> = {
  writer: {name: '写作', when: '长篇正文、短篇整篇、修订与补写时', purpose: '组织场景、人物动作、对话与叙事表达'},
  planner: {name: '规划', when: '建书讨论、设定、大纲、章节方案与审纲时', purpose: '明确故事方向、角色出场与情节推进'},
  audit: {name: '审核', when: '正文完成后审核、跨章复盘与卷级审查时', purpose: '发现创作问题并提出可执行的修改建议'},
  extract: {name: '记忆整理', when: '章节完成后整理记忆，或作者提炼文风时', purpose: '记录人物、事件与状态变化，分析作者文风'},
  summarize: {name: '章节摘要', when: '章节落库后整理后续创作所需的前情时', purpose: '保留关键事件、人物状态与未完成的问题'},
  validator_l2: {name: '设定一致性检查', when: '正文与已有台账进行语义比对时', purpose: '检查人物、关系与设定是否前后矛盾'},
}

export function resourceUsage(item: Pick<WritingResource, 'kind' | 'body'>) {
  if (item.kind === 'role_prompt' && 'role' in item.body)
    return {activation: '自动生效', when: writingRoles[item.body.role]?.when ?? '对应角色执行时'}
  if (item.kind === 'reference') return {activation: 'AI按需查阅 · 无需作者选择', when: '规划、写作与审核可通过工具查阅；本书人物与关系由作品自行维护'}
  const when: Record<string, string> = {
    reference: '供规划、写作与审核按需查阅，不会整份反复加载',
    genre: '用于故事设定、规划、正文写作与审核',
    genre_rule: '选用后，还需与作品题材匹配，才会加入规划、写作与审核',
    style: '用于规划、写作与审核；作品自己的文风与样本优先',
    writing_rule: '在内容填写的写作环节使用，空白环节不追加要求',
    expression_rule: '在指定环节改善表达，并执行已开启的写作检查',
  }
  const roles = 'roles' in item.body ? Object.entries(item.body.roles).filter(([, text]) => text.trim()).map(([role]) => writingRoles[role]?.name ?? role) : []
  return {activation: '作品选用后生效', when: roles.length
    ? `用于${roles.join('、')}。${item.kind === 'genre_rule' ? '还需与作品选择的题材匹配。' : ''}`
    : when[item.kind] ?? '根据作品设置使用'}
}

export function isSupportingReference(item: Pick<WritingResource, 'kind' | 'name'>) {
  return item.kind === 'reference' && (
    isSourceNotice(item) || /(?:^|[/\\])README\.md$/i.test(item.name) ||
    /(?:author_(?:error_catalog|glossary)|(?:index|state|review)-schema|reference-loading-map|reference-gap-register)/i.test(item.name)
  )
}


export function isLegacyRoleSupplement(item: Pick<WritingResource, 'id'>) {
  return item.id.startsWith('writing-rule:platform:')
}
