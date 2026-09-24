import type { Project } from '../types'

export function isProjectDraft(project: Project): boolean {
  return project.creation_status === 'draft' || project.creation_status === 'setup_confirmed'
}

/** 草稿要回到自己形态的建书动线；正式作品进工作台（工作台自己按 form 分叉）。 */
export function projectHref(project: Project): string {
  return isProjectDraft(project)
    ? `/${project.form === 'short' ? 'short' : 'long'}/new?draft=${encodeURIComponent(project.id)}`
    : `/projects/${project.id}`
}
