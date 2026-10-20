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
  enabled: boolean
  user_visible: boolean
}

export interface PlatformConnectionInput extends ModelConnectionInput {
  enabled: boolean
  user_visible: boolean
}

type GenreFieldsResponse = { [Key in keyof GenreFields]?: GenreFields[Key] | null }

export interface PlatformConfigurationData {
  version: number
  user_defaults?: UserDefaults
  model_connections: PlatformConnection[]
  model_routes: Record<string, string>
  prompts: Record<string, string>
  genre_packs: Record<string, GenreFieldsResponse>
}

export interface PlatformConfigurationInput extends Omit<PlatformConfigurationData, 'model_connections' | 'genre_packs'> {
  model_connections: PlatformConnectionInput[]
  genre_packs: Record<string, GenreFields>
}

export interface PlatformReadiness {
  ready: boolean
  checks: Array<{ role: string; ready: boolean; reason: string | null }>
}

const PATH = '/admin/configuration'

export const platformApi = {
  getReadiness: () =>
    authenticatedGet<PlatformReadiness>(`${PATH}/readiness`, getToken() ?? ''),
  getConfiguration: () =>
    authenticatedGet<PlatformConfigurationData>(PATH, getToken() ?? ''),
  updateConfiguration: (body: PlatformConfigurationInput) =>
    authenticatedSend<PlatformConfigurationData>('PUT', PATH, getToken() ?? '', body),
  listModels: (body: ModelProbeRequest) =>
    authenticatedSend<ModelListResult>('POST', `${PATH}/models`, getToken() ?? '', body),
  testConnection: (body: ModelProbeRequest) =>
    authenticatedSend<ConnectionTestResult>('POST', `${PATH}/test-connection`, getToken() ?? '', body),
}
