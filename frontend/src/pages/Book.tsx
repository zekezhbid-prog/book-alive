import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Chapter, type EntityBrief, type Project, type SearchHit } from '../api'
import ChapterEditor from '../components/ChapterEditor'
import ChatPanel from '../components/ChatPanel'
import ChapterReader, { type NamedEntity } from '../components/ChapterReader'
import ProjectHeader from '../components/ProjectHeader'
import VersionsPanel from '../components/VersionsPanel'
import { errorText, useI18n } from '../i18n'
import { markMatches } from '../markMatches'
import { savesSettled } from '../saveQueue'

type View = 'writer' | 'illustrator'

export default function Book() {
  const { t } = useI18n()
  const { projectId = '', chapterId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [chapter, setChapter] = useState<Chapter | null>(null)
  // Bumped whenever chapter text may have changed on the server behind the editor's back
  // (rollback, merge, split): the open chapter is refetched and its component remounted.
  const [epoch, setEpoch] = useState(0)
  const [names, setNames] = useState<NamedEntity[]>([])
  const [error, setError] = useState('')
  const [view, setViewState] = useState<View>(
    () => (localStorage.getItem(`view:${projectId}`) as View) || 'writer',
  )
  const [side, setSide] = useState<'chat' | 'versions'>('chat')
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const reloadProject = useCallback(
    () => api.project(projectId).then(setProject).catch(fail),
    [projectId, fail],
  )
  useEffect(() => {
    reloadProject()
    const named = (kind: 'character' | 'location') => (list: EntityBrief[]) =>
      list.map((e) => ({ id: e.id, kind, names: [e.name, ...e.aliases] }))
    Promise.all([
      api.entities(projectId, 'character').then(named('character')),
      api.entities(projectId, 'location').then(named('location')),
    ]).then((lists) => setNames(lists.flat()), fail)
  }, [reloadProject, projectId, fail])

  // The URL may name a chapter that no longer exists (deleted, merged, rolled back).
  const activeId = project?.chapters.some((c) => c.id === chapterId)
    ? chapterId
    : project?.chapters[0]?.id
  useEffect(() => {
    if (!project) return
    if (!activeId) return setChapter(null)
    let stale = false
    api.chapter(activeId).then(
      (loaded) => !stale && setChapter(loaded),
      (e) => {
        if (stale) return
        if (e instanceof ApiError && e.code === 'chapter_not_found') reloadProject()
        else fail(e)
      },
    )
    return () => {
      stale = true
    }
    // `project` itself is left out on purpose: autosave refreshes it on every pause in typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, epoch, project === null, fail, reloadProject])

  useEffect(() => {
    if (query.trim().length < 2) return setHits(null)
    const timer = setTimeout(() => api.search(projectId, query).then(setHits).catch(fail), 250)
    return () => clearTimeout(timer)
  }, [query, projectId, fail])

  if (error && !project) return <main className="page error">{error}</main>
  if (!project) return <main className="page muted">{t('app.loading')}</main>

  // A link to a paragraph (a quote on a card, a citation in the chat, a search hit) is
  // shown in the reading view even in a writer project: the editor cannot highlight.
  const highlighted = searchParams.has('p') ? Number(searchParams.get('p')) : undefined
  const writing = project.mode === 'writer' && view === 'writer' && highlighted === undefined
  const shown = chapter?.id === activeId ? chapter : null
  const open = (id: string, paragraph?: number, found?: string) => {
    const params = new URLSearchParams()
    if (paragraph !== undefined) params.set('p', String(paragraph))
    if (found) params.set('q', found)
    navigate(`/projects/${projectId}/chapters/${id}${params.size ? `?${params}` : ''}`)
  }
  const setView = async (next: View) => {
    // The other view is drawn from what the server has, so the draft must be there first.
    await savesSettled()
    localStorage.setItem(`view:${projectId}`, next)
    setViewState(next)
    // Choosing a view by hand leaves the paragraph link behind.
    if (highlighted !== undefined && activeId) open(activeId)
  }
  const afterStructureChange = async (goTo?: string) => {
    setError('')
    await reloadProject()
    if (goTo) open(goTo)
    setEpoch((n) => n + 1)
  }
  const addChapter = async () => {
    try {
      const created = await api.createChapter(projectId, '', activeId)
      await afterStructureChange(created.id)
    } catch (e) {
      fail(e)
    }
  }

  return (
    <>
      <ProjectHeader project={project}>
        {project.mode === 'writer' && (
          <div className="segmented">
            {(['writer', 'illustrator'] as const).map((option) => (
              <button key={option} className={(writing ? 'writer' : 'illustrator') === option ? 'active' : ''}
                onClick={() => setView(option)}
              >
                {t(`book.view.${option}`)}
              </button>
            ))}
          </div>
        )}
      </ProjectHeader>
      <div className="workspace with-side">
        <aside className="chapters">
          <input
            className="input"
            type="search"
            placeholder={t('book.search')}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          {hits ? (
            <>
              <h4>{hits.length ? t('book.search.results', { n: hits.length }) : t('book.search.none')}</h4>
              <nav>
                {hits.map((hit, i) => (
                  <button key={i} className="hit" onClick={() => open(hit.chapter_id, hit.paragraph, query.trim())}>
                    <span className="faint small">{hit.chapter_title || t('book.untitled')}</span>
                    <span>…{markMatches(hit.snippet, query, (text) => [text])}…</span>
                  </button>
                ))}
              </nav>
            </>
          ) : (
            <>
              <h4>
                {t('book.chapters')} · {project.chapters.length}
              </h4>
              <nav>
                {project.chapters.map((item, index) => (
                  <button
                    key={item.id}
                    className={`chapter-link ${item.id === activeId ? 'active' : ''}`}
                    onClick={() => open(item.id)}
                  >
                    {/* A title like "Глава 3" or "III" already carries its number. */}
                    {!/\d|^[IVXLC]+\b/.test(item.title) && <span className="chapter-num">{index + 1}</span>}
                    <span className={item.title ? '' : 'faint'}>{item.title || t('book.untitled')}</span>
                    {project.changes?.edited.includes(item.id) ||
                    project.changes?.added.includes(item.id) ? (
                      <span className="dot" title={t('versions.dirty')} />
                    ) : null}
                  </button>
                ))}
              </nav>
              {writing && (
                <button className="btn small" onClick={addChapter}>
                  + {t('chapter.add')}
                </button>
              )}
            </>
          )}
        </aside>

        <section className="reading">
          {error && <p className="error">{error}</p>}
          {project.split_method === 'sections' && !writing && (
            <p className="notice">{t('book.split.sections')}</p>
          )}
          {!activeId && <p className="muted">{t(writing ? 'book.empty.writer' : 'book.empty.reader')}</p>}
          {shown && writing && (
            <ChapterEditor
              key={`${shown.id}:${epoch}`}
              project={project}
              chapter={shown}
              // Keeps this page's copy current, so a later remount starts from the saved text.
              onSaved={(saved) => {
                setChapter(saved)
                reloadProject()
              }}
              onStructureChange={afterStructureChange}
              onError={fail}
            />
          )}
          {shown && !writing && (
            <ChapterReader
              key={`${shown.id}:${epoch}`}
              project={project}
              chapter={shown}
              names={names}
              highlighted={highlighted}
              found={searchParams.get('q') ?? undefined}
              onStructureChange={afterStructureChange}
              onError={fail}
            />
          )}
        </section>

        <aside className="side">
          {project.mode === 'writer' && (
            <div className="segmented side-tabs">
              {(['chat', 'versions'] as const).map((option) => (
                <button key={option} className={side === option ? 'active' : ''} onClick={() => setSide(option)}>
                  {t(`side.${option}`)}
                  {option === 'versions' && project.changes?.dirty && <span className="dot" />}
                </button>
              ))}
            </div>
          )}
          {project.mode === 'writer' && side === 'versions' ? (
            <VersionsPanel project={project} onChanged={() => afterStructureChange()} onError={fail} />
          ) : (
            <ChatPanel projectId={project.id} chapterId={activeId} canSuggest={writing} />
          )}
        </aside>
      </div>
    </>
  )
}
