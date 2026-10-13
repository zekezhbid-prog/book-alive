import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
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
import ProjectHeader from '../components/ProjectHeader'
import { errorText, useI18n } from '../i18n'

const POLL_MS = 2000

/** Characters or locations: cards built from the book, read-only. */
export default function Entities({ kind }: { kind: EntityKind }) {
  const { t } = useI18n()
  const { projectId = '', entityId } = useParams()
  const navigate = useNavigate()
  const section = kind === 'character' ? 'characters' : 'locations'
  const [project, setProject] = useState<Project | null>(null)
  const [list, setList] = useState<EntityBrief[] | null>(null)
  const [entity, setEntity] = useState<Entity | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [choosing, setChoosing] = useState(false)
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadList = useCallback(
    () => api.entities(projectId, kind).then(setList, fail),
    [projectId, kind, fail],
  )
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

  const activeId = list?.some((e) => e.id === entityId) ? entityId : undefined
  useEffect(() => {
    if (!activeId) return setEntity(null)
    api.entity(activeId).then(setEntity, fail)
    // Refetch when the list changes too: a run may have added facts to the open card.
  }, [activeId, list, fail])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const cancel = () => run && api.cancelRun(run.id).then(() => setRun({ ...run, status: 'running' }), fail)
  const runError = run?.error === 'interrupted' ? t('run.interrupted') : run?.error

  return (
    <>
      <ProjectHeader project={project} />
      <div className="workspace">
        <aside className="chapters">
          <button className="btn primary" disabled={running} onClick={() => setChoosing(true)}>
            {t(`entities.find.${kind}`)}
          </button>
          <nav>
            {list?.map((item) => (
              <button
                key={item.id}
                className={`chapter-link entity-link ${item.id === activeId ? 'active' : ''}`}
                onClick={() => navigate(`/projects/${projectId}/${section}/${item.id}`)}
              >
                <span>{item.name}</span>
                {item.stale && <span className="dot" title={t('entities.stale.hint')} />}
                <span className="faint small">{item.chapters}</span>
              </button>
            ))}
          </nav>
        </aside>

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
            {run?.status === 'failed' && (
              <p className="notice error">
                {t('run.failed', { done: run.done, total: run.total, error: runError ?? '' })}
              </p>
            )}
            {run?.status === 'cancelled' && (
              <p className="notice">{t('run.cancelled', { done: run.done, total: run.total })}</p>
            )}
            {list?.length === 0 && !running && <p className="muted">{t(`entities.empty.${kind}`)}</p>}
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
              />
            )}
          </div>
        </section>
      </div>
      {choosing && (
        <RunDialog
          project={project}
          kind={kind}
          onClose={() => setChoosing(false)}
          onStarted={(started) => {
            setChoosing(false)
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
}

/** Facts are read-only; who is who is the user's call, hence merge and split. */
function Card({ entity, projectId, others, onChanged, onError }: CardProps) {
  const { t } = useI18n()
  const merge = (otherId: string) => {
    const other = others.find((e) => e.id === otherId)
    if (!other || !confirm(t('entities.merge.confirm', { other: other.name, name: entity.name }))) return
    api.mergeEntities(entity.id, other.id).then(onChanged, onError)
  }
  const split = (alias: string) => {
    if (!confirm(t('entities.split.confirm', { alias }))) return
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
      <h4>{t('entities.permanent')}</h4>
      {entity.permanent.length === 0 && <p className="faint">{t('entities.permanent.none')}</p>}
      <ul className="facts">
        {entity.permanent.map((fact, i) => (
          <li key={i}>
            {fact.text} {fact.stale && stale}
            {source(fact)}
          </li>
        ))}
      </ul>
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
  project: Project
  kind: EntityKind
  onClose: () => void
  onStarted: (run: Run) => void
}

/** Pick chapters, see what it will cost, then start. Nothing is spent before "Start". */
function RunDialog({ project, kind, onClose, onStarted }: DialogProps) {
  const { t } = useI18n()
  const [selected, setSelected] = useState(() => new Set(project.chapters.map((c) => c.id)))
  const [estimate, setEstimate] = useState<Estimate | null>(null)
  const [error, setError] = useState('')
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
  const idsKey = ids.join(',')

  useEffect(() => {
    setEstimate(null)
    if (!idsKey) return
    let stale = false
    const timer = setTimeout(
      () =>
        api.estimate(project.id, kind, idsKey.split(',')).then(
          (result) => !stale && setEstimate(result),
          (e) => !stale && setError(errorText(t, e)),
        ),
      300,
    )
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [idsKey, project.id, kind, t])

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }
  const start = () =>
    api.startRun(project.id, kind, ids).then(onStarted, (e) => setError(errorText(t, e)))
  const number = (n: number) => n.toLocaleString()

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack">
        <h2>{t(`entities.find.${kind}`)}</h2>
        <div className="row">
          <h4>{t('run.title')}</h4>
          <span className="spacer" />
          <button className="btn ghost small" onClick={() => setSelected(new Set(project.chapters.map((c) => c.id)))}>
            {t('run.all')}
          </button>
          <button className="btn ghost small" onClick={() => setSelected(new Set())}>
            {t('run.none')}
          </button>
        </div>
        <div className="chapter-picker">
          {project.chapters.map((chapter) => (
            <label key={chapter.id} className="row">
              <input type="checkbox" checked={selected.has(chapter.id)} onChange={() => toggle(chapter.id)} />
              <span className="grow">{chapter.title || t('book.untitled')}</span>
              <span className="faint small">{number(chapter.chars)}</span>
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
        {error && <p className="error">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={!idsKey || !estimate} onClick={start}>
            {t('run.start')}
          </button>
        </div>
      </div>
    </div>
  )
}
