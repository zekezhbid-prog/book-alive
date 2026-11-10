import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  type Entity,
  type EntityBrief,
  type EntityKind,
  type Estimate,
  type Fact,
  type Project,
  type Run,
} from '../api'
import Gallery from '../components/Gallery'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import DescriptionEditor from '../components/DescriptionEditor'
import AiNotice, { useTextModelReady } from '../components/AiNotice'
import { SparklesIcon } from '../components/icons'
import { errorText, useI18n } from '../i18n'
import { useView } from '../view'
import { ask } from '../dialogs'

const POLL_MS = 2000

/** Characters or locations: cards built from the book, read-only. */
export default function Entities({ kind }: { kind: EntityKind }) {
  const { t } = useI18n()
  const { projectId = '', entityId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const section = kind === 'character' ? 'characters' : 'locations'
  const [project, setProject] = useState<Project | null>(null)
  const [list, setList] = useState<EntityBrief[] | null>(null)
  const [entity, setEntity] = useState<Entity | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  // null: closed. Otherwise the chapters ticked when the dialog opens (empty = all).
  const [choosing, setChoosing] = useState<string[] | null>(null)
  const [staleChapters, setStaleChapters] = useState<string[]>([])
  const view = useView({ id: projectId, mode: project?.mode ?? 'reader' })
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadList = useCallback(() => {
    api.stale(projectId, kind).then((report) => setStaleChapters(report.chapter_ids), fail)
    return api.entities(projectId, kind).then(setList, fail)
  }, [projectId, kind, fail])
  useEffect(() => {
    setList(null)
    setRun(null)
    api.project(projectId).then(setProject, fail)
    api.latestRun(projectId, kind).then(setRun, fail)
    loadList()
  }, [projectId, kind, loadList, fail])

  // While a run is going, cards appear chapter by chapter.
  const running = run?.status === 'running'
  useEffect(() => {
    if (!running) return
    const timer = setInterval(() => {
      api.latestRun(projectId, kind).then(setRun, fail)
      loadList()
    }, POLL_MS)
    return () => clearInterval(timer)
  }, [running, projectId, kind, loadList, fail])

  // A card just added in the left menu is not in this page's list yet.
  const missing = Boolean(list && entityId && !list.some((e) => e.id === entityId))
  useEffect(() => {
    if (missing) loadList()
  }, [missing, loadList])

  // "Find characters / locations" at the bottom of the left menu opens the run dialog here.
  const find = searchParams.has('find')
  const loaded = list !== null
  const openFind = useCallback(() => {
    if (running) return
    let last: string | null = null
    try {
      last = localStorage.getItem(`lastChapter:${projectId}`)
    } catch {
      /* the dialog falls back to the first chapter */
    }
    setChoosing(project?.chapters.some((c) => c.id === last) && last ? [last] : [])
  }, [running, project, projectId])
  useEffect(() => {
    if (!find || !loaded) return
    setSearchParams({}, { replace: true })
    openFind()
  }, [find, loaded, setSearchParams, openFind])
  const aiReady = useTextModelReady()

  const activeId = list?.some((e) => e.id === entityId) ? entityId : undefined
  useEffect(() => {
    if (!activeId) return setEntity(null)
    api.entity(activeId).then(setEntity, fail)
    // Refetch when the list changes too: a run may have added facts to the open card.
  }, [activeId, list, fail])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const cancel = () =>
    run && api.cancelRun(run.id).then(() => setRun({ ...run, status: 'running' }), fail)
  const runError = run?.error === 'interrupted' ? t('run.interrupted') : run?.error

  return (
    <>
      <ProjectHeader project={project} />
      <div className="workspace">
        <ProjectNav project={project} {...{ [section]: list }} />

        <section className="reading">
          <div className="chapter stack">
            {error && <p className="error">{error}</p>}
            {running && run && (
              <div className="notice stack">
                <div className="row">
                  <span>{t('run.progress', { done: run.done, total: run.total })}</span>
                  <span className="spacer" />
                  <button className="btn small" onClick={cancel}>
                    {t('run.cancel')}
                  </button>
                </div>
                <progress value={run.done} max={run.total} />
              </div>
            )}
            {staleChapters.length > 0 && !running && (
              <div className="notice row">
                <span className="grow">{t('entities.refresh', { n: staleChapters.length })}</span>
                <button className="btn small" onClick={() => setChoosing(staleChapters)}>
                  {t('entities.refresh.button')}
                </button>
              </div>
            )}
            {run?.status === 'failed' && (
              <p className="notice error">
                {t('run.failed', { done: run.done, total: run.total, error: runError ?? '' })}
              </p>
            )}
            {run?.status === 'cancelled' && (
              <p className="notice">{t('run.cancelled', { done: run.done, total: run.total })}</p>
            )}
            <AiNotice ready={aiReady} />
            {list?.length === 0 && !running && (
              <div className="empty-state stack">
                <p className="muted">{t(`entities.empty.${kind}`)}</p>
                <button className="btn primary" onClick={openFind}>
                  <SparklesIcon /> {t(`nav.find.${section}`)}
                </button>
              </div>
            )}
            {list && list.length > 0 && !entity && <p className="muted">{t('entities.select')}</p>}
            {entity && (
              <Card
                entity={entity}
                projectId={projectId}
                others={list?.filter((e) => e.id !== entity.id) ?? []}
                onChanged={(next) => {
                  loadList()
                  navigate(`/projects/${projectId}/${section}/${next.id}`)
                }}
                onError={fail}
                gallery={
                  view === 'writer' ? null : (
                  <Gallery
                    key={entity.id}
                    projectId={projectId}
                    entityId={entity.id}
                    kind={entity.kind}
                    chapters={project.chapters}
                    hasStyle={Boolean(project.style_id)}
                  />
                  )
                }
                writing={view === 'writer'}
              />
            )}
          </div>
        </section>
      </div>
      {choosing && (
        <RunDialog
          aiReady={aiReady}
          project={project}
          kind={kind}
          initial={choosing}
          onClose={() => setChoosing(null)}
          onStarted={(started) => {
            setChoosing(null)
            setError('')
            setRun(started)
          }}
        />
      )}
    </>
  )
}

interface CardProps {
  entity: Entity
  projectId: string
  others: EntityBrief[]
  onChanged: (shown: Entity) => void
  onError: (error: unknown) => void
  /** The card's references, shown between the name and the description. */
  gallery: ReactNode
  /** A writer describes the card in words; pictures belong to the illustrator. */
  writing: boolean
}

/** Facts are read-only; who is who is the user's call, hence merge and split.
 *  Top to bottom: name, references, description, mentions by chapter. */
function Card({ entity, projectId, others, onChanged, onError, gallery, writing }: CardProps) {
  const { t } = useI18n()
  const merge = async (otherId: string) => {
    const other = others.find((e) => e.id === otherId)
    if (!other || !(await ask(t('entities.merge.confirm', { other: other.name, name: entity.name }))))
      return
    api.mergeEntities(entity.id, other.id).then(onChanged, onError)
  }
  const split = async (alias: string) => {
    if (!(await ask(t('entities.split.confirm', { alias })))) return
    api.splitEntity(entity.id, alias).then(onChanged, onError)
  }
  const source = (fact: Fact) =>
    fact.quote && (
      <Link
        className="quote"
        title={t('entities.source')}
        to={`/projects/${projectId}/chapters/${fact.chapter_id}?p=${fact.paragraph}`}
      >
        «{fact.quote}»
      </Link>
    )
  const stale = <span className="badge stale">{t('entities.stale')}</span>
  return (
    <>
      <div className="stack">
        <div className="row">
          <h1 className="entity-name grow">{entity.name}</h1>
          {others.length > 0 && (
            <select className="input merge-select" value="" onChange={(e) => merge(e.target.value)}>
              <option value="">{t('entities.merge')}</option>
              {others.map((other) => (
                <option key={other.id} value={other.id}>
                  {other.name}
                </option>
              ))}
            </select>
          )}
        </div>
        {entity.aliases.length > 0 && (
          <div className="row wrap muted">
            {t('entities.aliases')}:
            {entity.aliases.map((alias) => (
              <span key={alias} className="chip">
                {alias}
                <button title={t('entities.split')} onClick={() => split(alias)}>
                  ⤴
                </button>
              </span>
            ))}
          </div>
        )}
      </div>
      {writing && (
        <DescriptionEditor
          key={entity.id}
          value={entity.description}
          label={t('description.title')}
          placeholder={t(`description.${entity.kind}.placeholder`)}
          onSave={(text) => api.saveEntityDescription(entity.id, text)}
        />
      )}
      <h4>{t('entities.profile')}</h4>
      {/* A connected text written by the model when a search ends or is stopped. */}
      {entity.summary ? (
        <p className="summary">{entity.summary}</p>
      ) : (
        <p className="faint">{t('entities.profile.none')}</p>
      )}
      {entity.profile.length + entity.permanent.length > 0 && (
        <details>
          <summary className="muted">{t('entities.facts')}</summary>
          <ul className="facts">
            {[...entity.profile, ...entity.permanent].map((fact, i) => (
              <li key={i}>
                {fact.text} {fact.stale && stale}
                {source(fact)}
              </li>
            ))}
          </ul>
        </details>
      )}
      {gallery}
      <h4>{t('entities.timeline')}</h4>
      {entity.timeline.map((entry) => (
        <div key={entry.chapter_id} className="timeline-entry">
          <div className="row">
            <Link to={`/projects/${projectId}/chapters/${entry.chapter_id}`}>
              <b>{entry.chapter_title || t('book.untitled')}</b>
            </Link>
            {entry.stale && <span title={t('entities.stale.hint')}>{stale}</span>}
          </div>
          {entry.facts.length === 0 ? (
            <p className="faint small">{t('entities.present')}</p>
          ) : (
            <ul className="facts">
              {entry.facts.map((fact, i) => (
                <li key={i}>
                  {fact.text}
                  {source(fact)}
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </>
  )
}

interface DialogProps {
  /** False when no text model is chosen: the dialog says so and "Start" stays off. */
  aiReady: boolean | null
  project: Project
  kind: EntityKind
  /** Chapters ticked at the start; empty means the whole book. */
  initial: string[]
  onClose: () => void
  onStarted: (run: Run) => void
}

/** Pick chapters, see what it will cost, then start. Nothing is spent before "Start". */
function RunDialog({ aiReady, project, kind, initial, onClose, onStarted }: DialogProps) {
  const { t } = useI18n()
  const [selected, setSelected] = useState(
    () => new Set(initial.length ? initial : project.chapters.slice(0, 1).map((c) => c.id)),
  )
  const [estimate, setEstimate] = useState<Estimate | null>(null)
  const [fresh, setFresh] = useState(false)
  const [error, setError] = useState('')
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
  const idsKey = ids.join(',')

  useEffect(() => {
    setEstimate(null)
    if (!idsKey) return
    let stale = false
    const timer = setTimeout(
      () =>
        api.estimate(project.id, kind, idsKey.split(','), fresh).then(
          (result) => !stale && setEstimate(result),
          (e) => !stale && setError(errorText(t, e)),
        ),
      300,
    )
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [idsKey, project.id, kind, fresh, t])

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }
  const start = () =>
    api.startRun(project.id, kind, ids, fresh).then(onStarted, (e) => setError(errorText(t, e)))
  const number = (n: number) => n.toLocaleString()

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack">
        <h2>{t(`entities.find.${kind}`)}</h2>
        <div className="row">
          <h4>{t('run.title')}</h4>
          <span className="spacer" />
          <button
            className="btn ghost small"
            onClick={() => setSelected(new Set(project.chapters.map((c) => c.id)))}
          >
            {t('run.all')}
          </button>
          <button className="btn ghost small" onClick={() => setSelected(new Set())}>
            {t('run.none')}
          </button>
        </div>
        <div className="chapter-picker">
          {project.chapters.map((chapter) => (
            <label key={chapter.id} className="row">
              <input
                type="checkbox"
                checked={selected.has(chapter.id)}
                onChange={() => toggle(chapter.id)}
              />
              <span className="grow">{chapter.title || t('book.untitled')}</span>
              <span className="faint small">{number(chapter.chars)}</span>
            </label>
          ))}
        </div>
        <div className="stack">
          {[false, true].map((value) => (
            <label key={String(value)} className="row">
              <input type="radio" name="run-mode" checked={fresh === value} onChange={() => setFresh(value)} />
              <span className="grow">
                {t(value ? 'run.fresh' : 'run.add')}
                <span className="faint small"> — {t(value ? 'run.fresh.hint' : 'run.add.hint')}</span>
              </span>
            </label>
          ))}
        </div>
        <div className="notice">
          <b>{t('run.estimate')}</b>
          {!idsKey ? (
            <div>{t('error.no_chapters_selected')}</div>
          ) : !estimate ? (
            <div>{t('run.estimate.loading')}</div>
          ) : (
            <>
              <div>
                {estimate.requests === 0
                  ? t('run.estimate.free')
                  : t('run.estimate.body', {
                      requests: estimate.requests,
                      input: number(estimate.input_tokens),
                      output: number(estimate.output_tokens),
                    })}
              </div>
              {estimate.cached > 0 && estimate.requests > 0 && (
                <div>{t('run.estimate.cached', { n: estimate.cached })}</div>
              )}
              {estimate.requests > 0 && <div className="muted small">{t('run.estimate.note')}</div>}
            </>
          )}
        </div>
        <AiNotice ready={aiReady} />
        {error && <p className="error">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={!idsKey || !estimate || aiReady === false} onClick={start}>
            {t('run.start')}
          </button>
        </div>
      </div>
    </div>
  )
}
