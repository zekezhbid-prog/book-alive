import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { api, type Chapter, type Project, type SearchHit } from '../api'
import ChapterEditor from '../components/ChapterEditor'
import ChapterReader from '../components/ChapterReader'
import VersionsPanel from '../components/VersionsPanel'
import { errorText, useI18n } from '../i18n'

type View = 'writer' | 'illustrator'

export default function Book() {
  const { t } = useI18n()
  const { projectId = '', chapterId } = useParams()
  const [searchParams] = useSearchParams()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [chapter, setChapter] = useState<Chapter | null>(null)
  const [error, setError] = useState('')
  const [view, setViewState] = useState<View>(
    () => (localStorage.getItem(`view:${projectId}`) as View) || 'writer',
  )
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const reloadProject = useCallback(
    () => api.project(projectId).then(setProject).catch(fail),
    [projectId, fail],
  )
  useEffect(() => {
    reloadProject()
  }, [reloadProject])

  const activeId = chapterId ?? project?.chapters[0]?.id
  const reloadChapter = useCallback(() => {
    if (!activeId) return setChapter(null)
    api.chapter(activeId).then(setChapter).catch(fail)
  }, [activeId, fail])
  useEffect(reloadChapter, [reloadChapter])

  useEffect(() => {
    if (query.trim().length < 2) return setHits(null)
    const timer = setTimeout(() => api.search(projectId, query).then(setHits).catch(fail), 250)
    return () => clearTimeout(timer)
  }, [query, projectId, fail])

  if (error && !project) return <main className="page error">{error}</main>
  if (!project) return <main className="page muted">{t('app.loading')}</main>

  const writing = project.mode === 'writer' && view === 'writer'
  const open = (id: string, paragraph?: number) =>
    navigate(`/projects/${projectId}/chapters/${id}${paragraph === undefined ? '' : `?p=${paragraph}`}`)
  const setView = (next: View) => {
    localStorage.setItem(`view:${projectId}`, next)
    setViewState(next)
  }
  const changed = async () => {
    setError('')
    await reloadProject()
    reloadChapter()
  }
  // After a chapter disappears (delete, merge, rollback) the URL may point nowhere.
  const afterStructureChange = async (goTo?: string) => {
    await reloadProject()
    if (goTo) open(goTo)
    else navigate(`/projects/${projectId}`)
    reloadChapter()
  }
  const addChapter = async () => {
    try {
      const created = await api.createChapter(projectId, '', activeId)
      await reloadProject()
      open(created.id)
    } catch (e) {
      fail(e)
    }
  }

  const slot = document.getElementById('topbar-slot')
  const highlighted = searchParams.has('p') ? Number(searchParams.get('p')) : undefined

  return (
    <>
      {slot &&
        createPortal(
          <>
            <span className="crumb">
              <Link to="/">{t('app.projects')}</Link> / <b>{project.title}</b>
            </span>
            <span className={`badge ${project.mode}`}>{t(`mode.${project.mode}`)}</span>
            <span className="spacer" />
            {project.mode === 'writer' && (
              <div className="segmented">
                {(['writer', 'illustrator'] as const).map((option) => (
                  <button
                    key={option}
                    className={view === option ? 'active' : ''}
                    onClick={() => setView(option)}
                  >
                    {t(`book.view.${option}`)}
                  </button>
                ))}
              </div>
            )}
          </>,
          slot,
        )}
      <div className={`workspace ${project.mode === 'writer' ? 'with-side' : ''}`}>
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
                  <button key={i} className="hit" onClick={() => open(hit.chapter_id, hit.paragraph)}>
                    <span className="faint small">{hit.chapter_title || t('book.untitled')}</span>
                    <span>…{hit.snippet}…</span>
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
                {project.chapters.map((item) => (
                  <button
                    key={item.id}
                    className={`chapter-link ${item.id === activeId ? 'active' : ''}`}
                    onClick={() => open(item.id)}
                  >
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
          {!chapter && (
            <p className="muted">{t(writing ? 'book.empty.writer' : 'book.empty.reader')}</p>
          )}
          {chapter && writing && (
            <ChapterEditor
              key={`${chapter.id}:${chapter.content_hash}`}
              project={project}
              chapter={chapter}
              onSaved={reloadProject}
              onStructureChange={afterStructureChange}
              onError={fail}
            />
          )}
          {chapter && !writing && (
            <ChapterReader
              key={`${chapter.id}:${chapter.content_hash}`}
              project={project}
              chapter={chapter}
              highlighted={highlighted}
              onChanged={changed}
              onStructureChange={afterStructureChange}
              onError={fail}
            />
          )}
        </section>

        {project.mode === 'writer' && (
          <aside className="side">
            <VersionsPanel project={project} onChanged={() => afterStructureChange(activeId)} onError={fail} />
          </aside>
        )}
      </div>
    </>
  )
}
