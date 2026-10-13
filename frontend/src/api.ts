export type Mode = 'reader' | 'writer'

export interface ChapterBrief {
  id: string
  position: number
  title: string
  chars: number
  content_hash: string
}

export interface Chapter extends ChapterBrief {
  text: string
}

export interface Version {
  id: string
  number: number
  label: string
  created_at: string
  chapters: number
}

export interface Changes {
  added: string[]
  removed: string[]
  edited: string[]
  renamed: string[]
  reordered: boolean
  dirty: boolean
}

export interface ProjectBrief {
  id: string
  title: string
  author: string
  mode: Mode
  created_at: string
  chapters: number
  chars: number
}

export interface Project {
  id: string
  title: string
  author: string
  mode: Mode
  source_filename: string
  split_method: 'headings' | 'pattern' | 'titles' | 'sections' | 'manual'
  created_at: string
  chapters: ChapterBrief[]
  version: Version | null
  changes: Changes | null
}

export interface SearchHit {
  chapter_id: string
  chapter_title: string
  paragraph: number
  snippet: string
}

export type ConnectionKind = 'openai' | 'claude_cli'

export interface Connection {
  id: string
  name: string
  kind: ConnectionKind
  base_url: string
  api_key_hint: string
}

export interface ModelInfo {
  id: string
  name: string
  free: boolean | null
  image: boolean
}

export interface ModelSettings {
  text_connection_id: string
  text_model: string
  image_connection_id: string
  image_model: string
}

export interface TestResult {
  reply: string
  input_tokens: number
  output_tokens: number
}

/** `code` is the machine-readable part of the server's error, e.g. `reader_mode_readonly`. */
export class ApiError extends Error {
  code: string
  detail: string

  constructor(status: number, detail: string) {
    super(detail || `HTTP ${status}`)
    const [code, ...rest] = (detail || `http_${status}`).split(': ')
    this.code = code
    this.detail = rest.join(': ')
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method }
  if (body instanceof FormData) {
    init.body = body
  } else if (body !== undefined) {
    init.body = JSON.stringify(body)
    init.headers = { 'Content-Type': 'application/json' }
  }
  const response = await fetch(`/api${path}`, init)
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    throw new ApiError(response.status, detail)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export const api = {
  projects: () => request<ProjectBrief[]>('GET', '/projects'),
  createProject: (mode: Mode, title: string, file: File | null) => {
    const form = new FormData()
    form.set('mode', mode)
    form.set('title', title)
    if (file) form.set('file', file)
    return request<Project>('POST', '/projects', form)
  },
  project: (id: string) => request<Project>('GET', `/projects/${id}`),
  updateProject: (id: string, patch: { title?: string; author?: string }) =>
    request<Project>('PATCH', `/projects/${id}`, patch),
  deleteProject: (id: string) => request<void>('DELETE', `/projects/${id}`),
  search: (id: string, q: string) =>
    request<SearchHit[]>('GET', `/projects/${id}/search?q=${encodeURIComponent(q)}`),

  chapter: (id: string) => request<Chapter>('GET', `/chapters/${id}`),
  updateChapter: (id: string, patch: { title?: string; text?: string }) =>
    request<Chapter>('PATCH', `/chapters/${id}`, patch),
  createChapter: (projectId: string, title: string, afterId?: string) =>
    request<Chapter>('POST', `/projects/${projectId}/chapters`, { title, after_id: afterId }),
  deleteChapter: (id: string) => request<void>('DELETE', `/chapters/${id}`),
  mergeNext: (id: string) => request<Chapter>('POST', `/chapters/${id}/merge-next`),
  split: (id: string, paragraph: number, title: string, dropHeading: boolean) =>
    request<Chapter[]>('POST', `/chapters/${id}/split`, {
      paragraph,
      title,
      drop_heading: dropHeading,
    }),
  reorder: (projectId: string, chapterIds: string[]) =>
    request<Project>('POST', `/projects/${projectId}/reorder`, { chapter_ids: chapterIds }),

  versions: (projectId: string) => request<Version[]>('GET', `/projects/${projectId}/versions`),
  commit: (projectId: string, label: string) =>
    request<Project>('POST', `/projects/${projectId}/versions`, { label }),
  rollback: (projectId: string, versionId: string) =>
    request<Project>('POST', `/projects/${projectId}/versions/${versionId}/rollback`),

  system: () => request<{ claude_cli: boolean }>('GET', '/system'),
  connections: () => request<Connection[]>('GET', '/connections'),
  createConnection: (body: {
    name: string
    kind: ConnectionKind
    base_url: string
    api_key: string
  }) => request<Connection>('POST', '/connections', body),
  deleteConnection: (id: string) => request<void>('DELETE', `/connections/${id}`),
  models: (connectionId: string) => request<ModelInfo[]>('GET', `/connections/${connectionId}/models`),
  testModel: (connectionId: string, model: string) =>
    request<TestResult>('POST', `/connections/${connectionId}/test`, { model }),
  settings: () => request<ModelSettings>('GET', '/settings'),
  saveSettings: (body: ModelSettings) => request<ModelSettings>('PUT', '/settings', body),
}
