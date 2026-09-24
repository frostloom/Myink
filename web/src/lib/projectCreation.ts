import type { Project } from '../types'

export function isProjectDraft(project: Project): boolean {
  return project.creation_status === 'draft' || project.creation_status === 'setup_confirmed'
}

export function projectHref(project: Project): string {
  // 短篇一律进工作台（含草稿）：/short/new 现在是对话页，回不去一篇聊到一半的会话。
  if (project.form === 'short') return `/projects/${project.id}`
  return isProjectDraft(project)
    ? `/long/new?draft=${encodeURIComponent(project.id)}`
    : `/projects/${project.id}`
}
