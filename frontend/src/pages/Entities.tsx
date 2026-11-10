import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  peek,
  type Entity,
  type EntityBrief,
  type EntityKind,
  type Estimate,
  type Fact,
  type Project,
  type Run,
} from '../api'
import { AddCardDialog } from '../components/AddCardDialog'
import CardGrid, { type Tile } from '../components/CardGrid'
import Gallery from '../components/Gallery'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import AiNotice, { useTextModelReady } from '../components/AiNotice'
import { PencilIcon } from '../components/icons'
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
  // The last answers are shown at once (no blink when switching tabs), then refreshed.
  const [project, setProject] = useState<Project | null>(() => peek.project(projectId) ?? null)
  const [list, setList] = useState<EntityBrief[] | null>(() => peek.entities(projectId, kind) ?? null)
  const [entity, setEntity] = useState<Entity | null>(() => (entityId && peek.entity(entityId)) || null)
  const [run, setRun] = useState<Run | null>(null)
  // null: closed. Otherwise the chapters ticked when the dialog opens (empty = all).
  const [choosing, setChoosing] = useState<string[] | null>(null)
  const [staleChapters, setStaleChapters] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  const view = useView({ id: projectId, mode: project?.mode ?? 'reader' })
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadList = useCallback(() => {
    api.stale(projectId, kind).then((report) => setStaleChapters(report.chapter_ids), fail)
    return api.entities(projectId, kind).then(setList, fail)
  }, [projectId, kind, fail])
  useEffect(() => {
    setList(peek.entities(projectId, kind) ?? null)
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
    // Another card's page must not show the previous one while it loads.
    setEntity((shown) => (shown?.id === activeId ? shown : (peek.entity(activeId) ?? null)))
    api.entity(activeId).then(setEntity, fail)
    // Refetch when the list changes too: a run may have added facts to the open card.
  }, [activeId, list, fail])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const tile = (item: EntityBrief): Tile => ({
    id: item.id,
    title: item.name,
    text: item.blurb,
    meta: [
      item.chapters ? t('tiles.chapters', { n: item.chapters }) : '',
      item.first_chapter ? t('tiles.first', { title: item.first_chapter }) : '',
    ]
      .filter(Boolean)
      .join(' · '),
    cover: item.cover,
    mark: item.uncertain ? <span className="uncertain-mark">? </span> : undefined,
    extra: item.stale ? <span className="dot" title={t('entities.stale.hint')} /> : undefined,
    faded: item.uncertain,
  })

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
            {/* Stays on top while the cards below change: the run is never out of sight. */}
            {running && run && (
              <div className="notice stack run-progress">
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
            {/* Nothing open: every card as a tile, adding by hand and finding with AI first. */}
            {list && !entityId && (
              <CardGrid
                actions={[
                  {
                    title: t(`nav.add.${section}`),
                    hint: t(`tiles.add.${kind}`),
                    onClick: () => setAdding(true),
                  },
                  {
                    title: t(`nav.find.${section}`),
                    hint: t(running ? 'tiles.find.running' : `tiles.find.${kind}`),
                    onClick: openFind,
                    disabled: running,
                  },
                ]}
                tiles={list.filter((e) => !e.uncertain).map(tile)}
                more={{
                  title: t('entities.uncertain'),
                  hint: t('entities.uncertain.hint'),
                  tiles: list.filter((e) => e.uncertain).map(tile),
                }}
                onOpen={(id) => navigate(`/projects/${projectId}/${section}/${id}`)}
              />
            )}
            {entity && entityId && (
              <Card
                onClose={() => navigate(`/projects/${projectId}/${section}`)}
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
              />
            )}
          </div>
        </section>
      </div>
      {adding && (
        <AddCardDialog
          projectId={projectId}
          kind={kind}
          onClose={() => setAdding(false)}
          onCreated={(created) => {
            setAdding(false)
            loadList()
            navigate(`/projects/${projectId}/${section}/${created.id}`)
          }}
        />
      )}
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
  /** The ✕ in the corner: back to the tiles of the section. */
  onClose: () => void
  entity: Entity
  projectId: string
  others: EntityBrief[]
  onChanged: (shown: Entity) => void
  onError: (error: unknown) => void
  /** The card's references, shown between the name and the description. */
  gallery: ReactNode
}

/** Facts are read-only; who is who is the user's call, hence merge and split.
 *  Top to bottom: name, references, description, mentions by chapter. */
function Card({ onClose, entity, projectId, others, onChanged, onError, gallery }: CardProps) {
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
          <button className="btn ghost card-close" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
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
      {/* Its own key: the gallery beside it is keyed by the card id too. */}
      <GeneralDescription key={`description-${entity.id}`} entity={entity} />
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
  const [selected, setSelected] = useState(() => new Set(initial))
  const [estimate, setEstimate] = useState<Estimate | null>(null)
  const [fresh, setFresh] = useState(false)
  const [error, setError] = useState('')
  // Chapters already read stay ticked when adding: their answers are reused for free and the
  // book does not change under the illustrator. Starting from scratch frees every box.
  const [status, setStatus] = useState<{ read: Set<string>; changed: Set<string> } | null>(null)
  useEffect(() => {
    api.chapterStatus(project.id, kind).then(
      (s) => {
        setStatus({ read: new Set(s.read), changed: new Set(s.changed) })
        // Nothing read yet and nothing asked for: offer the first chapter, as a start.
        if (!s.read.length && !initial.length) setSelected(new Set(project.chapters.slice(0, 1).map((c) => c.id)))
      },
      (e) => setError(errorText(t, e)),
    )
    // Once, when the dialog opens: later changes to the props must not reset the ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const locked = (id: string) => !fresh && !!status?.read.has(id)
  const ids = project.chapters.filter((c) => selected.has(c.id) || locked(c.id)).map((c) => c.id)
  const idsKey = ids.join(',')

  // The old estimate stays on screen while the new one is counted (by the server, from the
  // text length, no model involved), so the dialog keeps its size under the mouse.
  const [counting, setCounting] = useState(false)
  useEffect(() => {
    if (!idsKey) return
    let stale = false
    setCounting(true)
    const timer = setTimeout(
      () =>
        api.estimate(project.id, kind, idsKey.split(','), fresh).then(
          (result) => {
            if (stale) return
            setEstimate(result)
            setCounting(false)
          },
          (e) => !stale && setError(errorText(t, e)),
        ),
      300,
    )
    return () => {
      stale = true
      clearTimeout(timer)
    }
  }, [idsKey, project.id, kind, fresh, t])

  // Going from scratch keeps the read chapters ticked: they are what gets read again.
  const chooseMode = (value: boolean) => {
    if (value && status) setSelected(new Set([...selected, ...status.read]))
    setFresh(value)
  }
  const toggle = (id: string) => {
    if (locked(id)) return
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
        <div className="stack">
          {[false, true].map((value) => (
            <label key={String(value)} className="row">
              <input type="radio" name="run-mode" checked={fresh === value} onChange={() => chooseMode(value)} />
              <span className="grow">
                {t(value ? 'run.fresh' : 'run.add')}
                <span className="faint small"> — {t(value ? 'run.fresh.hint' : 'run.add.hint')}</span>
              </span>
            </label>
          ))}
        </div>
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
                checked={selected.has(chapter.id) || locked(chapter.id)}
                disabled={locked(chapter.id)}
                onChange={() => toggle(chapter.id)}
              />
              <span className="grow">
                {chapter.title || t('book.untitled')}
                {locked(chapter.id) && <span className="faint small"> · {t('run.chapter.read')}</span>}
                {status?.changed.has(chapter.id) && (
                  <span className="warn small"> · {t('run.chapter.changed')}</span>
                )}
              </span>
              <span className="faint small">{number(chapter.chars)}</span>
            </label>
          ))}
        </div>
        <div className={`notice estimate ${counting ? 'counting' : ''}`}>
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
          <button className="btn primary" disabled={!idsKey || !estimate || counting || aiReady === false} onClick={start}>
            {t('run.start')}
          </button>
        </div>
      </div>
    </div>
  )
}

/** One general description for every card. The model writes it at the end of a search; the
 *  pencil lets the user write their own, which later searches never overwrite. Clearing the
 *  text brings the model's version back. */
function GeneralDescription({ entity }: { entity: Entity }) {
  const { t } = useI18n()
  const [own, setOwn] = useState(entity.description)
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const shown = own.trim() || entity.summary
  const save = async () => {
    if (draft === null) return
    setBusy(true)
    setError('')
    try {
      const text = draft.trim() === entity.summary.trim() ? '' : draft.trim()
      await api.saveEntityDescription(entity.id, text)
      setOwn(text)
      setDraft(null)
    } catch (e) {
      setError(errorText(t, e))
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="stack">
      <div className="row profile-head">
        <h4 className="grow">{t('entities.profile')}</h4>
        {draft === null && (
          <button
            className="btn primary nav-action"
            title={t('entities.profile.edit')}
            aria-label={t('entities.profile.edit')}
            onClick={() => setDraft(shown)}
          >
            <PencilIcon />
          </button>
        )}
      </div>
      {draft !== null ? (
        <>
          <textarea
            className="input prompt"
            rows={7}
            maxLength={6000}
            autoFocus
            value={draft}
            placeholder={t(`description.${entity.kind}.placeholder`)}
            onChange={(e) => setDraft(e.target.value)}
          />
          {error && <p className="error">{error}</p>}
          <div className="row">
            <span className="faint small grow">{t('entities.profile.edit.hint')}</span>
            <button className="btn" onClick={() => setDraft(null)}>
              {t('app.cancel')}
            </button>
            <button className="btn primary" disabled={busy} onClick={save}>
              {t('app.save')}
            </button>
          </div>
        </>
      ) : shown ? (
        <p className="summary">{shown}</p>
      ) : (
        <p className="faint">{t('entities.profile.none')}</p>
      )}
    </div>
  )
}
