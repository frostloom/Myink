import { authenticatedGet, authenticatedSend } from './api'
import { getToken } from './token'
import type {
  ConnectionTestResult,
  ModelConnection,
  ModelConnectionInput,
  ModelListResult,
  ModelProbeRequest,
  UserDefaults,
} from '../types'
import type { GenreFields } from './genrePacks'

export interface PlatformConnection extends ModelConnection {
  minimum_tier?: 'normal' | 'vip'
  origin?: 'builtin' | 'custom'
  enabled: boolean
  user_visible: boolean
}

export interface PlatformConnectionInput extends ModelConnectionInput {
  minimum_tier?: 'normal' | 'vip'
  enabled: boolean
  user_visible: boolean
}

type GenreFieldsResponse = { [Key in keyof GenreFields]?: GenreFields[Key] | null }

export interface PlatformConfigurationData {
  vip_model_routes?: Record<string, string>
  queue_weights?: { vip: number; normal: number }
  version: number
  user_defaults?: UserDefaults
  model_connections: PlatformConnection[]
  model_routes: Record<string, string>
  prompts: Record<string, string>
  genre_packs: Record<string, GenreFieldsResponse>
}

export interface PlatformConfigurationInput
  extends Omit<PlatformConfigurationData, 'model_connections' | 'genre_packs'> {
  model_connections: PlatformConnectionInput[]
  genre_packs: Record<string, GenreFields>
}

export interface PlatformReadiness {
  ready: boolean
  checks: Array<{ role: string; ready: boolean; reason: string | null }>
}

export interface PromptRoleTemplates {
  role: string
  templates: Array<{ id: string; title: string; content: string; source: string;
    editable_content?: string; fixed_content?: string; description?: string; when?: string }>
}

const PATH = '/admin/configuration'

export const platformApi = {
  getPromptTemplates: () =>
    authenticatedGet<PromptRoleTemplates[]>(`${PATH}/prompt-templates`, getToken() ?? ''),
  getReadiness: () => authenticatedGet<PlatformReadiness>(`${PATH}/readiness`, getToken() ?? ''),
  getConfiguration: () => authenticatedGet<PlatformConfigurationData>(PATH, getToken() ?? ''),
  updateConfiguration: (body: PlatformConfigurationInput) =>
    authenticatedSend<PlatformConfigurationData>('PUT', PATH, getToken() ?? '', body),
  listModels: (body: ModelProbeRequest) =>
    authenticatedSend<ModelListResult>('POST', `${PATH}/models`, getToken() ?? '', body),
  testConnection: (body: ModelProbeRequest) =>
    authenticatedSend<ConnectionTestResult>('POST', `${PATH}/test-connection`, getToken() ?? '', body),
}
