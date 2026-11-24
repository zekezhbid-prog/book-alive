import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  api,
  peek,
  sectionOf,
  type Entity,
  type EntityBrief,
  type EntityKind,
  type Estimate,
  type Fact,
  type ImproveRequest,
  type Project,
  type Run,
} from '../api'
import { AddCardDialog } from '../components/AddCardDialog'
import CardGrid, { type Tile } from '../components/CardGrid'
import FoldHead from '../components/FoldHead'
import Gallery from '../components/Gallery'
import { MicButton } from '../components/MicButton'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import AiNotice, { useTextModelReady } from '../components/AiNotice'
import {
  DownloadIcon,
  GoldPlusSymbol,
  GoldSparklesSymbol,
  PencilIcon,
  SparklesIcon,
  TrashIcon,
  CheckIcon,
  QuestionIcon,
} from '../components/icons'
import { errorText, useI18n, type MessageKey, type Translate } from '../i18n'
import { useView } from '../view'
import { ask } from '../dialogs'
import SelectAll from '../components/SelectAll'

const POLL_MS = 2000

/** Characters, locations or items: cards built from the book, read-only. */
export default function Entities({ kind }: { kind: EntityKind }) {
  const { t } = useI18n()
  const { projectId = '', entityId } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const section = sectionOf(kind)
  // The last answers are shown at once (no blink when switching tabs), then refreshed.
  const [project, setProject] = useState<Project | null>(() => peek.project(projectId) ?? null)
  const [list, setList] = useState<EntityBrief[] | null>(() => peek.entities(projectId, kind) ?? null)
  const [entity, setEntity] = useState<Entity | null>(() => (entityId && peek.entity(entityId)) || null)
  const [run, setRun] = useState<Run | null>(null)
  // null: closed. Otherwise the chapters ticked when the dialog opens (empty = all).
  const [choosing, setChoosing] = useState<string[] | null>(null)
  const [staleChapters, setStaleChapters] = useState<string[]>([])
  const [adding, setAdding] = useState(false)
  // The open card's "rebuild" dialog.
  const [rebuilding, setRebuilding] = useState(false)
  // Tiles ticked for removing several at once; a new section starts with none.
  const [picked, setPicked] = useState<Set<string>>(new Set())
  useEffect(() => setPicked(new Set()), [projectId, section])
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
  // A run seen running on this page and then done: say so, until the reader closes it.
  const [finished, setFinished] = useState(false)
  const wasRunning = useRef(false)
  useEffect(() => {
    if (running) wasRunning.current = true
    else if (wasRunning.current && run?.status === 'done') {
      wasRunning.current = false
      setFinished(true)
      loadList() // the last words of the run (a rebuilt card's appearance) show at once
    }
  }, [running, run?.status, loadList])
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

  const activeId = list?.some((item) => item.id === entityId) ? entityId : undefined
  useEffect(() => {
    if (!activeId) return setEntity(null)
    // Another card's page must not show the previous one while it loads.
    setEntity((shown) => (shown?.id === activeId ? shown : (peek.entity(activeId) ?? null)))
    let current = true
    api.entity(activeId).then((next) => { if (current) setEntity(next) }, (e) => { if (current) fail(e) })
    return () => { current = false }
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
    corner: item.uncertain
      ? { icon: <CheckIcon />, label: t('entities.confirm'), onClick: () => setUncertain(item.id, false) }
      : { icon: <QuestionIcon />, label: t('entities.doubt'), onClick: () => setUncertain(item.id, true) },
  })
  const setUncertain = (id: string, uncertain: boolean) => {
    setList((had) => had && had.map((e) => (e.id === id ? { ...e, uncertain } : e)))
    api.setEntityUncertain(id, uncertain).catch((e) => {
      fail(e)
      loadList()
    })
  }

  const cancel = () =>
    run && api.cancelRun(run.id).then(() => setRun({ ...run, status: 'running' }), fail)
  const runError = run?.error === 'interrupted' ? t('run.interrupted') : run?.error
  const KINDS: EntityKind[] = ['character', 'location', 'item']
  const movePicked = (target: EntityKind) => {
    const ids = [...picked].filter((id) => list?.some((e) => e.id === id))
    // One after another: two picked cards with the same name join each other there.
    ids
      .reduce<Promise<unknown>>((done, id) => done.then(() => api.moveEntity(id, target)), Promise.resolve())
      .then(() => setPicked(new Set()), fail)
      .finally(loadList)
  }
  const deletePicked = async () => {
    const ids = [...picked].filter((id) => list?.some((e) => e.id === id))
    if (!ids.length || !(await ask(t('entities.delete.many.confirm', { n: ids.length })))) return
    Promise.all(ids.map((id) => api.deleteEntity(id))).then(
      () => setPicked(new Set()),
      fail,
    ).finally(loadList)
  }

  return (
    <>
      <ProjectHeader project={project} />
      <div className={entityId ? 'workspace' : 'workspace entity-index'}>
        <ProjectNav project={project} {...{ [section]: list }} />

        <section className="reading">
          <div className="chapter stack">
            {error && <p className="error">{error}</p>}
            {/* Stays on top while the cards below change: the run is never out of sight. */}
            {running && run && (
              <div className="notice stack run-progress">
                <div className="row">
                  <b className="run-progress-text">{runText(run, t)}</b>
                  <span className="spacer" />
                  <button className="btn small" onClick={cancel}>
                    {t('run.cancel')}
                  </button>
                </div>
                {/* A wave keeps running along the bar, so a long chapter does not look stuck. */}
                <div
                  className="live-progress"
                  role="progressbar"
                  aria-valuenow={Math.round(runPercent(run))}
                  aria-valuemax={100}
                >
                  <div className="live-progress-fill" style={{ width: `${Math.max(4, runPercent(run))}%` }} />
                </div>
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
            {finished && run && (
              <div className="notice row run-done">
                <div className="grow stack">
                  <span>
                    ✅{' '}
                    {run.entity_id
                      ? t('rebuild.done', { name: run.entity_name })
                      : t('run.done', { total: run.total, cards: list?.length ?? 0 })}
                    {run.seconds != null && ` ${t('run.took', { time: duration(run.seconds, t) })}`}
                  </span>
                  {/* What the reconciliation did, so a merge is never invisible. */}
                  {!run.entity_id && <span className="muted">
                    {t('run.report', { merged: run.merged.length, adopted: run.adopted.length })}
                  </span>}
                  {run.merged.length + run.adopted.length > 0 && (
                    <details>
                      <summary className="muted">{t('run.report.list')}</summary>
                      <ul className="facts">
                        {[...run.adopted, ...run.merged].map(([from, into], i) => (
                          <li key={i}>
                            {from} → <b>{into}</b>
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
                <button className="btn ghost small" aria-label={t('app.close')} onClick={() => setFinished(false)}>
                  ✕
                </button>
              </div>
            )}
            {run?.status === 'cancelled' && (
              <p className="notice">
                {run.entity_id
                  ? t('rebuild.cancelled', { name: run.entity_name })
                  : t('run.cancelled', { done: run.done, total: run.total })}
                {run.seconds != null && ` ${t('run.took', { time: duration(run.seconds, t) })}`}
              </p>
            )}
            <AiNotice ready={aiReady} />
            {/* Nothing open: every card as a tile, adding by hand and finding with AI first. */}
            {list && !entityId && (
              <CardGrid
                actions={[
                  {
                    icon: <GoldPlusSymbol />,
                    title: t(`nav.add.${section}`),
                    hint: t(`tiles.add.${kind}`),
                    onClick: () => setAdding(true),
                  },
                  {
                    icon: <GoldSparklesSymbol />,
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
                // While a search runs the cards are being rewritten: nothing is removed then.
                selection={
                  running
                    ? undefined
                    : {
                        selected: picked,
                        onChange: setPicked,
                        onDelete: deletePicked,
                        moveLabel: t('entities.picked.move'),
                        moveTo: KINDS.filter((k) => k !== kind).map((k) => ({
                          label: t(`tabs.${k}`),
                          onClick: () => movePicked(k),
                        })),
                        label: t('entities.pick'),
                        startLabel: t('entities.pick.start'),
                        allLabel: t('entities.pick.all'),
                        countLabel: t('entities.picked', { n: picked.size }),
                        deleteLabel: t('entities.picked.delete'),
                        doneLabel: t('entities.pick.done'),
                      }
                }
              />
            )}
            {!error && ((!entityId && !list) || (entityId && entity?.id !== entityId)) && (
              <p role="status" className="muted">{t('app.loading')}</p>
            )}
            {entity && entity.id === entityId && (
              <Card
                onClose={() => navigate(`/projects/${projectId}/${section}`)}
                entity={entity}
                projectId={projectId}
                onChanged={(next) => {
                  loadList()
                  navigate(`/projects/${projectId}/${section}/${next.id}`)
                }}
                onRebuild={running ? undefined : () => setRebuilding(true)}
                onDelete={async () => {
                  if (!(await ask(t('entities.delete.confirm', { name: entity.name })))) return
                  api.deleteEntity(entity.id).then(() => {
                    loadList()
                    navigate(`/projects/${projectId}/${section}`)
                  }, fail)
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
                    onChanged={loadList}
                  />
                  )
                }
              />
            )}
          </div>
        </section>
      </div>
      {rebuilding && entity && (
        <ImproveDialog
          entity={entity}
          others={list?.filter((e) => e.id !== entity.id) ?? []}
          onClose={() => setRebuilding(false)}
          onStart={(body) =>
            api.improveEntity(entity.id, body).then((started) => {
              setRebuilding(false)
              setError('')
              if (started.run) setRun(started.run)
              loadList()
              // After a merge the other card may be the one that stays.
              navigate(`/projects/${projectId}/${section}/${started.entity_id}`)
            }, fail)
          }
        />
      )}
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
  /** The bin beside "merge with": a card that is not needed. */
  onDelete: () => void
  /** Opens "Improve" (wishes, merge, the book read again); missing while a run is going. */
  onRebuild?: () => void
  entity: Entity
  projectId: string
  onChanged: (shown: Entity) => void
  onError: (error: unknown) => void
  /** The card's references, shown between the name and the description. */
  gallery: ReactNode
}

/** Facts are read-only; who is who is the user's call, hence merge and split.
 *  Top to bottom: name, references, description, mentions by chapter. */
function Card({ onClose, onDelete, onRebuild, entity, projectId, onChanged, onError, gallery }: CardProps) {
  const { t } = useI18n()
  // Only the description starts open; the rest is a click away.
  const [factsOpen, setFactsOpen] = useState(false)
  const [timelineOpen, setTimelineOpen] = useState(false)
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
        <div className="row card-head">
          <h1 className="entity-name grow">{entity.name}</h1>
          <button
            className="btn ghost icon"
            title={t(onRebuild ? 'improve.button' : 'improve.busy')}
            aria-label={t('improve.button')}
            disabled={!onRebuild}
            onClick={onRebuild}
          >
            <SparklesIcon />
          </button>
          <a
            className="btn ghost icon"
            href={api.exportEntityUrl(entity.id)}
            download
            title={t('entities.export')}
            aria-label={t('entities.export')}
          >
            <DownloadIcon />
          </a>
          <button
            className="btn ghost icon"
            title={t('entities.delete')}
            aria-label={t('entities.delete')}
            onClick={onDelete}
          >
            <TrashIcon />
          </button>
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
      {/* Their own keys: the gallery beside them is keyed by the card id too. */}
      <EditableText
        key={`description-${entity.id}`}
        title={t('entities.profile')}
        editLabel={t('entities.profile.edit')}
        own={entity.description}
        generated={entity.summary}
        placeholder={t(`description.${entity.kind}.placeholder`)}
        none={t('entities.profile.none')}
        startOpen
        save={(text) => api.saveEntityDescription(entity.id, text)}
      />
      {/* What pictures and scenes are drawn from: age, build, face, clothes; a place's look. */}
      <EditableText
        key={`appearance-${entity.id}`}
        title={t(`entities.appearance.${entity.kind}`)}
        editLabel={t('entities.appearance.edit')}
        own={entity.appearance_own}
        generated={entity.appearance}
        placeholder={t(`entities.appearance.${entity.kind}.placeholder`)}
        none={t('entities.appearance.none')}
        save={(text) => api.saveEntityAppearance(entity.id, text)}
      />
      <AuthorNotes key={`notes-${entity.id}`} entity={entity} onChanged={onChanged} onError={onError} />
      {entity.profile.length + entity.permanent.length > 0 && (
        <div className="stack">
          <FoldHead title={t('entities.facts')} open={factsOpen} onToggle={() => setFactsOpen(!factsOpen)} />
          {factsOpen && (
            <ul className="facts">
              {[...entity.profile, ...entity.permanent].map((fact, i) => (
                <li key={i}>
                  {fact.text} {fact.stale && stale}
                  {source(fact)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      {gallery}
      <FoldHead
        title={t(`entities.timeline.${entity.kind}`)}
        open={timelineOpen}
        onToggle={() => setTimelineOpen(!timelineOpen)}
      />
      {/* Chapters where the card only takes part go together in one line, so the list stays short. */}
      {timelineOpen && entity.timeline.some((entry) => entry.facts.length === 0) && (
        <div className="timeline-entry">
          <b>{t('entities.present')}</b>
          <p className="present-list">
            {entity.timeline
              .filter((entry) => entry.facts.length === 0)
              .map((entry, i) => (
                <span key={entry.chapter_id}>
                  {i > 0 && ', '}
                  <Link to={`/projects/${projectId}/chapters/${entry.chapter_id}`}>
                    {entry.chapter_title || t('book.untitled')}
                  </Link>
                  {entry.stale && <span title={t('entities.stale.hint')}> {stale}</span>}
                </span>
              ))}
          </p>
        </div>
      )}
      {timelineOpen &&
        entity.timeline
        .filter((entry) => entry.facts.length > 0)
        .map((entry) => (
          <div key={entry.chapter_id} className="timeline-entry">
            <div className="row">
              <Link to={`/projects/${projectId}/chapters/${entry.chapter_id}`}>
                <b>{entry.chapter_title || t('book.untitled')}</b>
              </Link>
              {entry.stale && <span title={t('entities.stale.hint')}>{stale}</span>}
            </div>
            <ul className="facts">
              {entry.facts.map((fact, i) => (
                <li key={i}>
                  {fact.text}
                  {source(fact)}
                </li>
              ))}
            </ul>
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
  // Cards found from nothing (nothing read yet, or from scratch) get the deep search,
  // as the server decides: over the chosen chapters, the whole book or a part for a trial.
  const deep = fresh || status?.read.size === 0
  const locked = (id: string) => !deep && !fresh && !!status?.read.has(id)
  // A chapter closed for AI is never sent to a model, so it is not offered at all.
  const open = project.chapters.filter((c) => !c.private)
  const ids = open.filter((c) => selected.has(c.id) || locked(c.id)).map((c) => c.id)
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
    api
      .startRun(project.id, kind, ids, fresh)
      .then(onStarted, (e) => setError(errorText(t, e)))
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
          {deep && (
            <p className="small">
              {t('run.deep')}
              <span className="faint"> — {t('run.deep.hint')}</span>
            </p>
          )}
        </div>
        <div className="row">
          <h4>{t('run.title')}</h4>
          <span className="spacer" />
          <SelectAll
            ids={open.filter((c) => !locked(c.id)).map((c) => c.id)}
            selected={selected}
            onChange={setSelected}
          />
        </div>
        <div className="chapter-picker">
          {open.map((chapter) => (
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

interface EditableProps {
  title: string
  editLabel: string
  /** The user's own text; empty means the model's is shown. */
  own: string
  generated: string
  placeholder: string
  none: string
  /** Shown unfolded when the card opens. */
  startOpen?: boolean
  save: (text: string) => Promise<unknown>
}

/** A text of the card the model writes at the end of a search (the general description, the
 *  appearance); the pencil lets the user write their own, which later searches never
 *  overwrite. Clearing the text brings the model's version back. */
function EditableText({
  title,
  editLabel,
  own: savedOwn,
  generated,
  placeholder,
  none,
  startOpen = false,
  save: send,
}: EditableProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState(startOpen)
  const [own, setOwn] = useState(savedOwn)
  const [draft, setDraft] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const shown = own.trim() || generated
  const save = async () => {
    if (draft === null) return
    setBusy(true)
    setError('')
    try {
      const text = draft.trim() === generated.trim() ? '' : draft.trim()
      await send(text)
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
      <FoldHead title={title} open={open || draft !== null} onToggle={() => setOpen(!open)}>
        {draft === null && (
          <button
            className="btn primary nav-action"
            title={editLabel}
            aria-label={editLabel}
            onClick={() => {
              setOpen(true)
              setDraft(shown)
            }}
          >
            <PencilIcon />
          </button>
        )}
      </FoldHead>
      {!open && draft === null ? null : draft !== null ? (
        <>
          <textarea
            className="input prompt"
            rows={7}
            maxLength={6000}
            autoFocus
            value={draft}
            placeholder={placeholder}
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
        <p className="faint">{none}</p>
      )}
    </div>
  )
}

/** "1 ч 5 мин", "12 мин 30 с", "40 с". */
function duration(seconds: number, t: Translate): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60
  if (h) return t('time.hm', { h, m })
  if (m) return t('time.ms', { m, s })
  return t('time.s', { s })
}

// After the chapters the run still has its final steps; the bar keeps a part for them,
// so it never sits at the end while work goes on.
const FINAL_STAGES = ['reconcile', 'cards', 'check', 'adopt', 'summarize', 'general', 'looks']
const READING_SHARE = 80

function runPercent(run: Run): number {
  const reading = run.total ? (run.done / run.total) * READING_SHARE : 0
  // Each card is written and then checked: both are one step of the bar.
  const index = FINAL_STAGES.indexOf(run.stage === 'check' ? 'cards' : run.stage)
  if (index < 0) return reading
  const step = (100 - READING_SHARE) / FINAL_STAGES.length
  const inside = run.stage_total ? run.stage_done / run.stage_total : 0
  return Math.min(99, READING_SHARE + step * (index + inside))
}

function runText(run: Run, t: Translate): string {
  if (run.entity_id) {
    // One card: its chapters first, then the description and the appearance.
    if (run.stage === 'summarize' || run.stage === 'general')
      return t('rebuild.stage.summary', { name: run.entity_name })
    if (run.stage === 'looks') return t('rebuild.stage.looks', { name: run.entity_name })
    return t('rebuild.progress', { name: run.entity_name, done: run.done, total: run.total })
  }
  if (FINAL_STAGES.includes(run.stage)) {
    return t(`run.stage.${run.stage}` as MessageKey, {
      done: run.stage_done,
      total: run.stage_total,
    })
  }
  return t('run.progress', { done: run.done, total: run.total })
}

/** One way to make a card better: the author's wishes (typed or spoken), a merge, and the
 *  book read again for what the card lacks. "From scratch" is there for the worst case. */
function ImproveDialog({
  entity,
  others,
  onClose,
  onStart,
}: {
  entity: Entity
  others: EntityBrief[]
  onClose: () => void
  onStart: (body: ImproveRequest) => void
}) {
  const { t } = useI18n()
  const [wishes, setWishes] = useState('')
  const [mergeWith, setMergeWith] = useState('')
  const [scratch, setScratch] = useState(false)
  const [voiceError, setVoiceError] = useState('')
  const body = (mergeOnly: boolean): ImproveRequest => ({
    wishes: mergeOnly ? '' : wishes,
    merge_with: mergeWith || null,
    scratch,
    merge_only: mergeOnly,
  })
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack improve-dialog">
        <h2>{t('improve.title', { name: entity.name })}</h2>
        <p className="muted">{t('improve.hint')}</p>
        <label className="stack">
          <b>{t('improve.wishes')}</b>
          <div className="row improve-wishes">
            <textarea
              className="input grow"
              rows={4}
              maxLength={4000}
              value={wishes}
              placeholder={t('improve.wishes.placeholder')}
              onChange={(e) => setWishes(e.target.value)}
            />
            <MicButton
              onText={(text) => {
                setVoiceError('')
                setWishes((now) => (now.trim() ? `${now.trim()} ${text}` : text))
              }}
              onError={setVoiceError}
            />
          </div>
          <span className="faint small">{t('improve.wishes.hint')}</span>
          {voiceError && <span className="error small">{voiceError}</span>}
        </label>
        {others.length > 0 && (
          <label className="stack">
            <b>{t('improve.merge')}</b>
            <select className="input" value={mergeWith} onChange={(e) => setMergeWith(e.target.value)}>
              <option value="">{t('improve.merge.none')}</option>
              {others.map((other) => (
                <option key={other.id} value={other.id}>
                  {other.name}
                </option>
              ))}
            </select>
            <span className="faint small">{t('improve.merge.hint')}</span>
          </label>
        )}
        <label className="row">
          <input type="checkbox" checked={scratch} onChange={(e) => setScratch(e.target.checked)} />
          <span className="grow">
            {t('improve.scratch')}
            <span className="faint small"> — {t('improve.scratch.hint')}</span>
          </span>
        </label>
        <div className="row">
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          {mergeWith && (
            <button className="btn" onClick={() => onStart(body(true))}>
              {t('improve.merge_only')}
            </button>
          )}
          <button className="btn primary" onClick={() => onStart(body(false))}>
            {t('improve.start')}
          </button>
        </div>
      </div>
    </div>
  )
}

/** The author's notes on a card: shown as a list, edited as lines of one text. */
function AuthorNotes({ entity, onChanged, onError }: {
  entity: Entity
  onChanged: (shown: Entity) => void
  onError: (error: unknown) => void
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [text, setText] = useState('')
  const notes = entity.author_notes ?? []
  if (!notes.length && !editing) return null
  const save = () =>
    api.saveEntityNotes(entity.id, text.split('\n')).then((next) => {
      setEditing(false)
      onChanged(next)
    }, onError)
  return (
    <div className="stack author-notes">
      <FoldHead
        title={t('notes.title')}
        open={open || editing}
        onToggle={() => setOpen(!open)}
        note={<span className="faint small">{notes.length}</span>}
      >
        {!editing && (
          <button
            className="btn primary nav-action"
            title={t('notes.edit')}
            aria-label={t('notes.edit')}
            onClick={() => {
              setText(notes.join('\n'))
              setOpen(true)
              setEditing(true)
            }}
          >
            <PencilIcon />
          </button>
        )}
      </FoldHead>
      {(open || editing) && <span className="faint small">{t('notes.hint')}</span>}
      {!open && !editing ? null : editing ? (
        <>
          <textarea
            className="input"
            rows={Math.max(3, notes.length + 1)}
            value={text}
            placeholder={t('notes.placeholder')}
            onChange={(e) => setText(e.target.value)}
          />
          <div className="row">
            <span className="spacer" />
            <button className="btn" onClick={() => setEditing(false)}>
              {t('app.cancel')}
            </button>
            <button className="btn primary" onClick={save}>
              {t('app.save')}
            </button>
          </div>
        </>
      ) : (
        <ul className="facts">
          {notes.map((note, i) => (
            <li key={i}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
