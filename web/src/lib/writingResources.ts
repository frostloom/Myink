import { formatErrorText } from './apiError'
import { authenticatedGet, authenticatedSend } from './api'
import { getToken } from './token'
import type { GenreFields } from './genrePacks'
export type ResourceKind =
  | 'role_prompt'
  | 'reference'
  | 'genre'
  | 'genre_rule'
  | 'style'
  | 'writing_rule'
  | 'expression_rule'
export type ResourceBody =
  | { role: string; templates: Record<string, string>; supplement?: string }
  | {
      catalog_id: string
      fields: GenreFields
      setup_caps?: Record<string, unknown>
    }
  | { profile: Record<string, unknown> }
  | {
      genre_ids?: string[]
      roles: Record<string, string>
      validation?: Record<string, unknown>
    }
  | { files: Array<{ path: string; content: string }> }
export interface WritingResource {
  id: string
  name: string
  kind: ResourceKind
  source: string
  status: 'draft' | 'published' | 'archived'
  generation: number
  current_version: number | null
  body: ResourceBody
}
export interface ResourceRevision {
  version: number
  name: string
  source: string
  body: ResourceBody
  created_at: string
  action: 'publish' | 'rollback' | 'initial'
  note: string
}
export interface ResourceSelection {
  resource_id: string
  origin: 'platform' | 'personal'
  name: string
  kind: ResourceKind
  version: number
  generation: number
  body: ResourceBody
  personal_override: boolean
}
export interface ResourceSnapshot {
  revision: number
  configured: boolean
  selections: ResourceSelection[]
}
export interface ResourceUpdate {
  resource_id: string
  name: string
  kind: ResourceKind
  current_version: number
  target_version: number
  target_generation: number
  action: 'publish' | 'rollback'
  note: string
  dismissed: boolean
}
export type ResourceInput = Pick<
  WritingResource,
  'name' | 'kind' | 'source' | 'body'
>
export type SelectionInput = Pick<
  ResourceSelection,
  'origin' | 'resource_id'
> & { personal_override?: boolean; body?: ResourceBody }
const get = async <T>(path: string) =>
  authenticatedGet<T>(path, getToken() ?? '')
const send = <T>(method: 'POST' | 'PUT', path: string, body: unknown) =>
  authenticatedSend<T>(method, path, getToken() ?? '', body)
const admin = '/admin/writing-resources'
const project = (id: string) =>
  `/projects/${encodeURIComponent(id)}/writing-resources`
export const resourceKinds: Record<ResourceKind, string> = {
  role_prompt: '角色提示词',
  reference: '写作知识库',
  genre: '题材包',
  genre_rule: '题材规则',
  style: '文风',
  writing_rule: '创作规则',
  expression_rule: '表达规则',
}
export const writingResources = {
  adminList: () => get<{ items: WritingResource[] }>(admin),
  create: (input: ResourceInput) => send<WritingResource>('POST', admin, input),
  save: (
    id: string,
    input: Omit<ResourceInput, 'kind'> & { expected_generation: number; status?: 'draft' | 'archived' },
  ) =>
    send<WritingResource>('PUT', `${admin}/${encodeURIComponent(id)}`, input),
  revisions: (id: string) =>
    get<{ items: ResourceRevision[] }>(
      `${admin}/${encodeURIComponent(id)}/revisions`,
    ),
  publish: (id: string, expected_generation: number, note: string) =>
    send<WritingResource>(
      'POST',
      `${admin}/${encodeURIComponent(id)}/publish`,
      { expected_generation, note },
    ),
  rollback: (
    id: string,
    expected_generation: number,
    version: number,
    note: string,
  ) =>
    send<WritingResource>(
      'POST',
      `${admin}/${encodeURIComponent(id)}/rollback`,
      { expected_generation, version, note },
    ),
  catalog: () => get<{ items: WritingResource[] }>('/writing-resources'),
  personal: () => get<{ items: WritingResource[] }>('/my-writing-resources'),
  createPersonal: (input: ResourceInput) =>
    send<WritingResource>('POST', '/my-writing-resources', input),
  savePersonal: (
    id: string,
    input: Omit<ResourceInput, 'kind'> & { expected_generation: number },
  ) =>
    send<WritingResource>(
      'PUT',
      `/my-writing-resources/${encodeURIComponent(id)}`,
      input,
    ),
  snapshot: (id: string) => get<ResourceSnapshot>(project(id)),
  select: (
    id: string,
    expected_revision: number,
    selections: SelectionInput[],
  ) =>
    send<ResourceSnapshot>('PUT', project(id), {
      expected_revision,
      selections,
    }),
  updates: (id: string) =>
    get<{ items: ResourceUpdate[] }>(`${project(id)}/updates`),
  dismiss: (
    id: string,
    updates: Array<{ resource_id: string; target_generation: number }>,
  ) => send<{ ok: boolean }>('POST', `${project(id)}/dismiss`, { updates }),
  adopt: (
    id: string,
    expected_revision: number,
    updates: Array<{ resource_id: string; target_generation: number }>,
  ) =>
    send<ResourceSnapshot>('POST', `${project(id)}/adopt`, {
      expected_revision,
      updates,
    }),
}
export function resourceError(error: unknown) {
  const status = error && typeof error === 'object' && 'status' in error && typeof error.status === 'number' ? error.status : undefined
  if (status === 409) return '资源已发生变化，草稿已保留。请重新加载后核对版本再操作。'
  return formatErrorText(error instanceof Error ? error.message : undefined, status, '操作未完成，请重新加载后重试。')
}

export function emptyResourceStyleProfile(): Record<string, unknown> {
  return {
    pov: '',
    narrative_voice: '',
    dialogue_style: '',
    scene_description: '',
    transitions: '',
    pacing: '',
    diction: '',
    emotional_expression: '',
    distinctive_habits: '',
    sentence_style: '',
    lexicon_tendency: '',
    dialogue: '',
    forbidden: [],
    reference_excerpts: [],
    frequent_words: [],
    sentence_len_dist: { avg: 0 },
    dialogue_ratio: 0,
  }
}
