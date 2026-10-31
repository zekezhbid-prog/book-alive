export type Mode = 'reader' | 'writer'

export type ReviewKind = 'grammar' | 'editorial' | 'contradictions'

export interface RemarkPlace {
  chapter_id: string
  chapter_title: string
  paragraph: number | null
  quote: string
}

export interface Remark {
  category: string
  problem: string
  suggestion: string
  places: RemarkPlace[]
}

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
  style_id: string
  style_text: string
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

export type EntityKind = 'character' | 'location'

export interface Estimate {
  chapters: number
  cached: number
  requests: number
  input_tokens: number
  output_tokens: number
}

export interface Run {
  id: string
  kind: EntityKind
  status: 'running' | 'done' | 'failed' | 'cancelled'
  total: number
  done: number
  error: string
  created_at: string
}

export interface EntityBrief {
  id: string
  name: string
  aliases: string[]
  chapters: number
  facts: number
  stale: boolean
}

export interface Fact {
  text: string
  quote: string
  chapter_id: string
  paragraph: number | null
  stale: boolean
}

export interface ChapterFacts {
  chapter_id: string
  chapter_title: string
  position: number
  stale: boolean
  facts: Fact[]
}

export interface Entity {
  id: string
  kind: EntityKind
  name: string
  aliases: string[]
  permanent: Fact[]
  timeline: ChapterFacts[]
}

export interface Usage {
  rows: {
    operation: string
    connection_name: string
    model: string
    calls: number
    input_tokens: number
    output_tokens: number
  }[]
  input_tokens: number
  output_tokens: number
}

export interface Citation {
  n: number
  chapter_id: string
  chapter_title: string
  paragraph: number
  quote: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations: Citation[]
  created_at: string
}

/** A step the chat agent has started: shown while the user waits for the answer. */
export interface ChatStatus {
  code: 'index' | 'search' | 'read' | 'think'
  detail: string
}

type ChatStreamLine =
  | ({ type: 'status' } & ChatStatus)
  | { type: 'done'; messages: ChatMessage[] }
  | { type: 'error'; detail: string }

/** Asks a question and reports the agent's steps as they come; resolves with the
 * question and the answer as stored. */
async function askStream(
  projectId: string,
  question: string,
  chapterId: string,
  onStatus: (status: ChatStatus) => void,
): Promise<ChatMessage[]> {
  const response = await fetch(`/api/projects/${projectId}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, chapter_id: chapterId }),
  })
  if (response.status === 401) window.dispatchEvent(new Event('login-required'))
  if (!response.ok || !response.body) {
    const payload = await response.json().catch(() => null)
    throw new ApiError(response.status, typeof payload?.detail === 'string' ? payload.detail : '')
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const text of lines) {
      if (!text.trim()) continue
      const line = JSON.parse(text) as ChatStreamLine
      if (line.type === 'status') onStatus({ code: line.code, detail: line.detail })
      else if (line.type === 'done') return line.messages
      else throw new ApiError(502, line.detail)
    }
  }
  throw new ApiError(502, 'provider_error: the answer was cut off')
}

export interface StylePreset {
  id: string
  prompt: string
}

export interface ImageInfo {
  id: string
  entity_id: string | null
  origin: 'upload' | 'generated'
  style_key: string
  current_style: boolean
  is_main: boolean
  /** The view a main picture shows; empty when not set. */
  angle: Angle | ''
  look_label: string
  chapter_from_id: string
  chapter_to_id: string
  prompt: string
  url: string
  created_at: string
}

/** Views of a character's main pictures, most useful first (as on the server). */
export const ANGLES = [
  'face_front',
  'full_front',
  'face_profile',
  'face_three_quarter',
  'full_side',
  'full_back',
] as const
export type Angle = (typeof ANGLES)[number]

/** Picture shapes the server knows (`SIZES` there); empty leaves it to the model. */
export const IMAGE_SIZES = ['1:1', '2:3', '3:2', '9:16', '16:9'] as const
export type ImageSize = (typeof IMAGE_SIZES)[number]

/** Empty label and chapters: a main picture in `angle` (empty: the server picks one). */
export interface LookRequest {
  angle: Angle | ''
  look_label: string
  chapter_from_id: string
  chapter_to_id: string
}

export interface SceneBrief {
  id: string
  chapter_id: string
  chapter_title: string
  chapter_position: number
  paragraph_from: number
  paragraph_to: number
  title: string
  summary: string
  vivid: boolean
  origin: 'auto' | 'manual'
  stale: boolean
  has_prompt: boolean
}

export interface Scene extends SceneBrief {
  text: string
  prompt: string
  frame_prompt: string
  participants: { id: string; kind: EntityKind; name: string; images: ImageInfo[] }[]
  references: {
    number: number
    entity_id: string
    entity_name: string
    role: 'main' | 'look'
    angle: Angle | ''
    look_label: string
    url: string
  }[]
  frames: ImageInfo[]
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
  if (response.status === 401 && path !== '/login') {
    // The session ended (or never started): the app shows the login screen.
    window.dispatchEvent(new Event('login-required'))
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    const detail = typeof payload?.detail === 'string' ? payload.detail : ''
    throw new ApiError(response.status, detail)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export interface SessionInfo {
  password_required: boolean
  authenticated: boolean
}

export const api = {
  session: () => request<SessionInfo>('GET', '/session'),
  login: (password: string) => request<SessionInfo>('POST', '/login', { password }),
  logout: () => request<SessionInfo>('POST', '/logout'),
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

  review: (projectId: string, kind: ReviewKind, chapterId: string) =>
    request<{ kind: ReviewKind; remarks: Remark[] }>('POST', `/projects/${projectId}/review`, {
      kind,
      chapter_id: chapterId,
    }),

  estimate: (projectId: string, kind: EntityKind, chapterIds: string[]) =>
    request<Estimate>('POST', `/projects/${projectId}/analysis/estimate`, {
      kind,
      chapter_ids: chapterIds,
    }),
  startRun: (projectId: string, kind: EntityKind, chapterIds: string[]) =>
    request<Run>('POST', `/projects/${projectId}/analysis`, { kind, chapter_ids: chapterIds }),
  latestRun: (projectId: string, kind: EntityKind) =>
    request<Run | null>('GET', `/projects/${projectId}/analysis?kind=${kind}`),
  cancelRun: (runId: string) => request<Run>('POST', `/analysis/${runId}/cancel`),
  stale: (projectId: string, kind: EntityKind) =>
    request<{ chapter_ids: string[]; orphaned_facts: number }>(
      'GET',
      `/projects/${projectId}/stale?kind=${kind}`,
    ),
  entities: (projectId: string, kind: EntityKind) =>
    request<EntityBrief[]>('GET', `/projects/${projectId}/entities?kind=${kind}`),
  entity: (id: string) => request<Entity>('GET', `/entities/${id}`),
  mergeEntities: (id: string, otherId: string) =>
    request<Entity>('POST', `/entities/${id}/merge`, { other_id: otherId }),
  splitEntity: (id: string, name: string) =>
    request<Entity>('POST', `/entities/${id}/split`, { name }),
  chat: (projectId: string) => request<ChatMessage[]>('GET', `/projects/${projectId}/chat`),
  ask: (
    projectId: string,
    question: string,
    chapterId: string | undefined,
    onStatus: (status: ChatStatus) => void,
  ) => askStream(projectId, question, chapterId ?? '', onStatus),
  suggest: (projectId: string, label: string, chapterId?: string) =>
    request<ChatMessage[]>('POST', `/projects/${projectId}/chat/suggest`, {
      question: label,
      chapter_id: chapterId ?? '',
    }),
  clearChat: (projectId: string) => request<void>('DELETE', `/projects/${projectId}/chat`),
  styles: () => request<StylePreset[]>('GET', '/styles'),
  setStyle: (projectId: string, styleId: string, styleText: string) =>
    request<{ style_id: string; style_text: string }>('PUT', `/projects/${projectId}/style`, {
      style_id: styleId,
      style_text: styleText,
    }),
  images: (projectId: string, entityId?: string) =>
    request<ImageInfo[]>('GET', `/projects/${projectId}/images?entity_id=${entityId ?? ''}`),
  uploadImages: (projectId: string, files: File[], entityId?: string) => {
    const form = new FormData()
    for (const file of files) form.append('files', file)
    form.set('entity_id', entityId ?? '')
    return request<ImageInfo[]>('POST', `/projects/${projectId}/images`, form)
  },
  updateImage: (
    id: string,
    patch: Partial<
      Pick<ImageInfo, 'is_main' | 'angle' | 'look_label' | 'chapter_from_id' | 'chapter_to_id'>
    >,
  ) => request<ImageInfo>('PATCH', `/images/${id}`, patch),
  deleteImage: (id: string) => request<void>('DELETE', `/images/${id}`),
  imagePrompt: (entityId: string, look: LookRequest & { view_free?: boolean }) =>
    request<{ prompt: string; angle: Angle | '' }>(
      'POST',
      `/entities/${entityId}/image-prompt`,
      look,
    ),
  generateImage: (
    entityId: string,
    body: LookRequest & { prompt: string; size: ImageSize | ''; add_view?: boolean },
  ) =>
    request<ImageInfo>('POST', `/entities/${entityId}/images/generate`, body),
  createEntity: (projectId: string, kind: EntityKind, name: string) =>
    request<{ id: string }>('POST', `/projects/${projectId}/entities`, { kind, name }),
  scenes: (projectId: string) => request<SceneBrief[]>('GET', `/projects/${projectId}/scenes`),
  scene: (id: string) => request<Scene>('GET', `/scenes/${id}`),
  deleteScene: (id: string) => request<void>('DELETE', `/scenes/${id}`),
  splitEstimate: (chapterId: string) =>
    request<{ input_tokens: number; output_tokens: number; existing: number }>(
      'GET',
      `/chapters/${chapterId}/scenes/estimate`,
    ),
  splitScenes: (chapterId: string) =>
    request<SceneBrief[]>('POST', `/chapters/${chapterId}/scenes/split`),
  markScene: (chapterId: string, from: number, to: number) =>
    request<SceneBrief>('POST', `/chapters/${chapterId}/scenes`, {
      paragraph_from: from,
      paragraph_to: to,
    }),
  buildScenePrompt: (id: string, note: string) =>
    request<Scene>('POST', `/scenes/${id}/prompt`, { note }),
  refineScenePrompt: (id: string, change: string) =>
    request<Scene>('POST', `/scenes/${id}/prompt/refine`, { change }),
  saveScenePrompt: (id: string, prompt: string) =>
    request<Scene>('PUT', `/scenes/${id}/prompt`, { prompt }),
  generateSceneFrame: (id: string, prompt: string) =>
    request<Scene>('POST', `/scenes/${id}/frame`, { prompt }),
  uploadSceneFrame: (id: string, file: File) => {
    const form = new FormData()
    form.set('file', file)
    return request<Scene>('POST', `/scenes/${id}/frame/upload`, form)
  },
  sceneArchiveUrl: (id: string) => `/api/scenes/${id}/archive`,
  usage: (projectId: string) => request<Usage>('GET', `/projects/${projectId}/usage`),

  system: () => request<{ claude_cli: boolean }>('GET', '/system'),
  connections: () => request<Connection[]>('GET', '/connections'),
  createConnection: (body: {
    name: string
    kind: ConnectionKind
    base_url: string
    api_key: string
  }) => request<Connection>('POST', '/connections', body),
  deleteConnection: (id: string) => request<void>('DELETE', `/connections/${id}`),
  models: (connectionId: string) =>
    request<ModelInfo[]>('GET', `/connections/${connectionId}/models`),
  testModel: (connectionId: string, model: string) =>
    request<TestResult>('POST', `/connections/${connectionId}/test`, { model }),
  settings: () => request<ModelSettings>('GET', '/settings'),
  saveSettings: (body: ModelSettings) => request<ModelSettings>('PUT', '/settings', body),
}
