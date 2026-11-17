import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  api,
  type Project,
  type Remark,
  type ReviewCheck,
  type ReviewChecks,
  type ReviewKind,
  type ReviewRun,
  type ReviewRunBrief,
} from '../api'
import { ask } from '../dialogs'
import { errorText, useI18n, type MessageKey } from '../i18n'
import { savesSettled } from '../saveQueue'
import BetaReader from './BetaReader'
import ChapterStats from './ChapterStats'
import CheckWindow, { CheckProgress, useWhen } from './CheckWindow'
import SelectAll from './SelectAll'
import { AiMark, TrashIcon } from './icons'

interface Props {
  project: Project
  /** The chapter open in the book: ticked when a check window opens. */
  chapterId?: string
  /** Called after "Fix all" changed chapter text on the server. */
  onChanged?: () => void
}

const KINDS: ReviewKind[] = ['grammar', 'editorial', 'contradictions']
/** A note under the ticks: what the section never does. */
const NOTES: Record<ReviewKind, MessageKey> = {
  grammar: 'review.rule.grammar.4',
  editorial: 'review.rule.editorial.6',
  contradictions: 'review.rule.contradictions.2',
}

const storageKey = (projectId: string, kind: ReviewKind) => `review:${projectId}:${kind}`

/** The ticks last used for this section of this book, or the defaults. */
function savedTicks(projectId: string, kind: ReviewKind, offered: ReviewCheck[]): Set<string> {
  const ids = offered.filter((c) => c.kind === kind).map((c) => c.id)
  try {
    const raw = localStorage.getItem(storageKey(projectId, kind))
    if (raw) {
      const saved = JSON.parse(raw) as string[]
      return new Set(saved.filter((id) => ids.includes(id)))
    }
  } catch {
    /* unreadable or blocked storage: fall back to the defaults */
  }
  return new Set(offered.filter((c) => c.kind === kind && c.default).map((c) => c.id))
}

function saveTicks(projectId: string, kind: ReviewKind, ticks: Set<string>) {
  try {
    localStorage.setItem(storageKey(projectId, kind), JSON.stringify([...ticks]))
  } catch {
    /* private mode: the choice lasts until the page is reloaded only */
  }
}

/** A check under way: it goes on when its window is closed, and the window shows it again. */
interface Job {
  kind: ReviewKind
  text: string
  done: number
  total: number
}

/** Manuscript checks for the writer: a column of buttons, each opening its own window.
 * Only "Fix all" changes the book, and only typesetting. */
export default function ReviewPanel({ project, chapterId, onChanged }: Props) {
  const { t } = useI18n()
  const [offer, setOffer] = useState<ReviewChecks | null>(null)
  const [open, setOpen] = useState<ReviewKind | null>(null)
  const [job, setJob] = useState<Job | null>(null)
  // The result each window shows; none means the window offers a new check.
  const [shown, setShown] = useState<Partial<Record<ReviewKind, ReviewRun>>>({})
  const [errors, setErrors] = useState<Partial<Record<ReviewKind, string>>>({})
  const [betaBusy, setBetaBusy] = useState(false)
  const [loadError, setLoadError] = useState('')

  useEffect(() => {
    api.reviewChecks(project.id).then(setOffer, (e) => setLoadError(errorText(t, e)))
  }, [project.id, t])

  const show = (kind: ReviewKind, run: ReviewRun | null) =>
    setShown((all) => {
      const next = { ...all }
      if (run) next[kind] = run
      else delete next[kind]
      return next
    })

  const run = async (kind: ReviewKind, chapterIds: string[], ticks: string[]) => {
    setErrors((all) => ({ ...all, [kind]: '' }))
    try {
      // The server checks one chapter at a time; contradictions look at the whole book.
      const found: Remark[] = []
      if (kind === 'contradictions') {
        // Text items first take notes from every chapter, one request each (unchanged
        // chapters answer at once from what was read before), then the book is compared.
        const all = offer?.checks.some((c) => c.reads_text && ticks.includes(c.id)) ? project.chapters.map((c) => c.id) : []
        for (const [n, id] of all.entries()) {
          setJob({ kind, text: t('review.reading', { done: n, n: all.length }), done: n, total: all.length + 1 })
          await api.review(project.id, kind, id, ticks)
        }
        setJob({ kind, text: t('review.comparing'), done: all.length, total: all.length + 1 })
        found.push(...(await api.review(project.id, kind, '', ticks)).remarks)
      } else {
        for (const [n, id] of chapterIds.entries()) {
          const title = project.chapters.find((c) => c.id === id)?.title || t('book.untitled')
          setJob({ kind, text: t('review.running.chapter', { done: n + 1, n: chapterIds.length, title }), done: n, total: chapterIds.length })
          found.push(...(await api.review(project.id, kind, id, ticks)).remarks)
        }
      }
      const kept = await api.keepReviewRun(project.id, {
        kind,
        chapter_ids: kind === 'contradictions' ? [] : chapterIds,
        checks: ticks,
        remarks: found,
      })
      show(kind, kept)
    } catch (e) {
      setErrors((all) => ({ ...all, [kind]: errorText(t, e) }))
    }
    setJob(null)
  }

  const busy = job !== null || betaBusy
  return (
    <div className="stack">
      <h4>{t('review.title')}</h4>
      {loadError && <p className="error">{loadError}</p>}
      {KINDS.map((kind) => (
        <button
          key={kind}
          className="btn badge-btn"
          disabled={offer === null || (busy && job?.kind !== kind)}
          onClick={() => setOpen(kind)}
        >
          <span className="grow">{t(`review.${kind}` as MessageKey)}</span>
          {job?.kind === kind && <span className="faint small">{Math.round((100 * job.done) / job.total)}%</span>}
          {offer?.checks.some((c) => c.kind === kind && c.engine === 'ai') && <AiMark title={t('review.engine.ai')} />}
        </button>
      ))}
      <ChapterStats project={project} busy={busy} />
      <BetaReader project={project} chapterId={chapterId} busy={job !== null} onBusy={setBetaBusy} />
      {open && offer && (
        <CheckWindow title={t(`review.${open}` as MessageKey)} onClose={() => setOpen(null)}>
          {job?.kind === open ? (
            <CheckProgress text={job.text} done={job.done} total={job.total} />
          ) : (
            <>
              {errors[open] && <p className="error">{errors[open]}</p>}
              {shown[open] ? (
                <RunResult
                  key={shown[open].id}
                  project={project}
                  run={shown[open]}
                  onRun={(next) => show(open, next)}
                  onAgain={() => show(open, null)}
                  onLeave={() => setOpen(null)}
                  onChanged={onChanged}
                />
              ) : (
                <CheckSetup
                  project={project}
                  kind={open}
                  offer={offer}
                  initial={chapterId}
                  onStart={(ids, ticks) => run(open, ids, ticks)}
                  onOpen={(kept) => show(open, kept)}
                />
              )}
            </>
          )}
        </CheckWindow>
      )}
    </div>
  )
}

/** Chapter titles of a kept check, or "the whole book". */
function chaptersText(project: Project, ids: string[], t: ReturnType<typeof useI18n>['t']) {
  if (ids.length === 0) return t('review.run.book')
  const list = ids.map((id) => project.chapters.find((c) => c.id === id)?.title || t('book.untitled')).join(', ')
  return t('review.run.chapters', { list })
}

/** One line of a kept check: when, which chapters, how many items, how many remarks. */
function RunLine({ project, run }: { project: Project; run: ReviewRunBrief }) {
  const { t } = useI18n()
  const whenText = useWhen()
  return (
    <>
      <span className="small">{t('review.run.when', { date: whenText(run.created_at) })}</span>
      <span className="faint small">
        {chaptersText(project, run.chapter_ids, t)} · {t('review.run.items', { n: run.checks.length })} ·{' '}
        {run.count ? t('review.count', { n: run.count }) : t('review.empty')}
      </span>
    </>
  )
}

interface ResultProps {
  project: Project
  run: ReviewRun
  onRun: (run: ReviewRun) => void
  onAgain: () => void
  /** A remark's place was opened in the book: the window steps aside. */
  onLeave: () => void
  onChanged?: () => void
}

/** The remarks of one check, new or kept, with "Fix all" for typesetting. */
function RunResult({ project, run, onRun, onAgain, onLeave, onChanged }: ResultProps) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [fixing, setFixing] = useState(false)
  const [fixed, setFixed] = useState('')
  const [error, setError] = useState('')
  const fixable = run.remarks.filter((r) => r.fixable).length
  const category = (name: string) => {
    const key = `review.cat.${name}` as MessageKey
    const text = t(key)
    return text === key ? name : text
  }
  const fixAll = async () => {
    setFixing(true)
    setError('')
    try {
      // The editor may still hold unsaved keystrokes: they go into the saved version first.
      await savesSettled()
      const result = await api.fixTypography(project.id, run.chapter_ids)
      onRun(await api.updateReviewRun(project.id, run.id, run.remarks.filter((r) => !r.fixable)))
      setFixed(
        result.changed.length
          ? t('review.fixed', { n: result.changed.length }) +
              (result.version ? ' ' + t('review.fixed.version', { n: result.version }) : '')
          : t('review.fixed.none'),
      )
      if (result.changed.length) onChanged?.()
    } catch (e) {
      setError(errorText(t, e))
    }
    setFixing(false)
  }
  return (
    <>
      <div className="row">
        <div className="stack grow">
          <RunLine project={project} run={run} />
        </div>
        <button className="btn small" onClick={onAgain}>
          {t('review.again')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {fixed && <p className="notice">{fixed}</p>}
      <b>{run.remarks.length ? t('review.count', { n: run.remarks.length }) : t('review.empty')}</b>
      {fixable > 0 && (
        <div className="stack">
          <button className="btn primary" disabled={fixing} onClick={fixAll}>
            {t('review.fix', { n: fixable })}
          </button>
          <span className="faint small">{t('review.fix.hint')}</span>
        </div>
      )}
      <ul className="history">
        {run.remarks.map((remark, index) => (
          <li key={index}>
            <div className="stack">
              <span className="faint small">{category(remark.category)}</span>
              <span>{remark.problem}</span>
              {remark.suggestion && (
                <span className="small">
                  {t('review.suggestion')} {remark.suggestion}
                </span>
              )}
              {remark.places.map((place, i) => (
                <button
                  key={i}
                  className="hit"
                  title={t('review.open')}
                  onClick={() => {
                    onLeave()
                    navigate(
                      `/projects/${project.id}/chapters/${place.chapter_id}` +
                        (place.paragraph === null ? '' : `?p=${place.paragraph}`),
                    )
                  }}
                >
                  <span className="small">{place.chapter_title}</span>
                  <span className="faint small">«{place.quote}»</span>
                </button>
              ))}
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}

interface SetupProps {
  project: Project
  kind: ReviewKind
  offer: ReviewChecks
  initial?: string
  onStart: (chapterIds: string[], ticks: string[]) => void
  onOpen: (run: ReviewRun) => void
}

/** Tick what to look for and pick the chapters; nothing runs before "Check". Below, the
 * kept checks of this kind, to open again. */
function CheckSetup({ project, kind, offer, initial, onStart, onOpen }: SetupProps) {
  const { t } = useI18n()
  const wholeBook = kind === 'contradictions'
  const items = offer.checks.filter((c) => c.kind === kind)
  const [ticks, setTicks] = useState(() => savedTicks(project.id, kind, offer.checks))
  const [selected, setSelected] = useState(() => new Set(initial ? [initial] : []))
  const [kept, setKept] = useState<ReviewRunBrief[]>([])
  const [error, setError] = useState('')
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
  const chosen = items.filter((c) => ticks.has(c.id))
  const usesModel = chosen.some((c) => c.engine === 'ai')

  const load = useCallback(() => {
    api.reviewRuns(project.id, kind).then(setKept, (e) => setError(errorText(t, e)))
  }, [project.id, kind, t])
  useEffect(load, [load])

  // A short example after the editorial name, in brackets.
  const example = (id: string) => {
    const key = `review.check.${id}.ex` as MessageKey
    const text = t(key)
    return text === key ? undefined : text
  }
  const tick = (next: Set<string>) => {
    setTicks(next)
    saveTicks(project.id, kind, next)
  }
  const toggleTick = (id: string) => {
    const next = new Set(ticks)
    if (!next.delete(id)) next.add(id)
    tick(next)
  }
  const toggle = (id: string) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }
  const reopen = async (brief: ReviewRunBrief) => {
    try {
      onOpen(await api.reviewRun(project.id, brief.id))
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  const remove = async (brief: ReviewRunBrief) => {
    if (!(await ask(t('review.delete.confirm')))) return
    try {
      await api.deleteReviewRun(project.id, brief.id)
      setKept((list) => list.filter((r) => r.id !== brief.id))
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  return (
    <>
      <p className="muted small">{t('review.hint')}</p>
      <div className="row">
        <h4>{t('review.rules')}</h4>
        <span className="spacer" />
        <SelectAll ids={items.map((c) => c.id)} selected={ticks} onChange={tick} />
        <button className="btn ghost small" onClick={() => tick(new Set(items.filter((c) => c.default).map((c) => c.id)))}>
          {t('review.defaults')}
        </button>
      </div>
      <div className="chapter-picker">
        {items.map((item) => (
          <label key={item.id} className="row">
            <input type="checkbox" checked={ticks.has(item.id)} onChange={() => toggleTick(item.id)} />
            <span className="grow">
              {t(`review.check.${item.id}` as MessageKey)}
              {example(item.id) && <span className="faint small"> ({example(item.id)})</span>}
            </span>
            {item.engine === 'ai' && <AiMark title={t('review.engine.ai')} />}
          </label>
        ))}
      </div>
      <p className="muted small">{t(NOTES[kind])}</p>
      {offer.language !== 'ru' && <p className="notice">{t(`review.lang.${offer.language}` as MessageKey)}</p>}
      {wholeBook ? (
        <>
          <p className="notice">{t('review.contradictions.hint')}</p>
          {chosen.some((c) => c.reads_text) && (
            <p className="muted small">{t('review.reads', { n: project.chapters.length })}</p>
          )}
        </>
      ) : (
        <>
          <div className="row">
            <h4>{t('run.title')}</h4>
            <span className="spacer" />
            <SelectAll ids={project.chapters.map((c) => c.id)} selected={selected} onChange={setSelected} />
          </div>
          <div className="chapter-picker">
            {project.chapters.map((chapter) => (
              <label key={chapter.id} className="row">
                <input type="checkbox" checked={selected.has(chapter.id)} onChange={() => toggle(chapter.id)} />
                <span className="grow">{chapter.title || t('book.untitled')}</span>
                <span className="faint small">{chapter.chars.toLocaleString()}</span>
              </label>
            ))}
          </div>
          {ids.length > 1 && usesModel && <p className="muted small">{t('review.many', { n: ids.length })}</p>}
        </>
      )}
      {!usesModel && chosen.length > 0 && <p className="muted small">{t('review.free')}</p>}
      <div className="row">
        <span className="spacer" />
        <button
          className="btn primary"
          disabled={chosen.length === 0 || (!wholeBook && ids.length === 0)}
          onClick={() => onStart(ids, chosen.map((c) => c.id))}
        >
          {t('review.start')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {kept.length > 0 && (
        <>
          <h4>{t('review.history')}</h4>
          <ul className="history">
            {kept.map((brief) => (
              <li key={brief.id}>
                <button className="hit grow" title={t('review.open')} onClick={() => reopen(brief)}>
                  <RunLine project={project} run={brief} />
                </button>
                <button
                  className="btn ghost small icon danger"
                  title={t('app.delete')}
                  aria-label={t('app.delete')}
                  onClick={() => remove(brief)}
                >
                  <TrashIcon />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  )
}
