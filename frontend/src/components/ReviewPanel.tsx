import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api, type Project, type Remark, type ReviewCheck, type ReviewChecks, type ReviewKind } from '../api'
import { errorText, useI18n, type MessageKey } from '../i18n'
import { savesSettled } from '../saveQueue'

interface Props {
  project: Project
  /** The chapter open in the book: ticked when a check dialog opens. */
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

/** Manuscript checks for the writer. Only "Fix all" changes the book, and only typesetting. */
export default function ReviewPanel({ project, chapterId, onChanged }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [offer, setOffer] = useState<ReviewChecks | null>(null)
  const [choosing, setChoosing] = useState<ReviewKind | null>(null)
  const [running, setRunning] = useState<ReviewKind | null>(null)
  const [done, setDone] = useState<ReviewKind | null>(null)
  const [remarks, setRemarks] = useState<Remark[]>([])
  const [checked, setChecked] = useState<string[]>([])
  const [fixing, setFixing] = useState(false)
  const [fixed, setFixed] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api.reviewChecks(project.id).then(setOffer, (e) => setError(errorText(t, e)))
  }, [project.id, t])

  const run = async (kind: ReviewKind, chapterIds: string[], ticks: string[]) => {
    setChoosing(null)
    setRunning(kind)
    setError('')
    setFixed('')
    try {
      // The server checks one chapter at a time; contradictions look at the whole book.
      const found: Remark[] = []
      for (const id of kind === 'contradictions' ? [''] : chapterIds) {
        found.push(...(await api.review(project.id, kind, id, ticks)).remarks)
      }
      setRemarks(found)
      setChecked(chapterIds)
      setDone(kind)
    } catch (e) {
      setError(errorText(t, e))
    }
    setRunning(null)
  }
  const fixAll = async () => {
    setFixing(true)
    setError('')
    try {
      // The editor may still hold unsaved keystrokes: they go into the saved version first.
      await savesSettled()
      const result = await api.fixTypography(project.id, checked)
      setRemarks(remarks.filter((r) => !r.fixable))
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
  const category = (name: string) => {
    const key = `review.cat.${name}` as MessageKey
    const text = t(key)
    return text === key ? name : text
  }
  const fixable = remarks.filter((r) => r.fixable).length

  return (
    <div className="stack">
      <h4>{t('review.title')}</h4>
      <p className="muted small">{t('review.hint')}</p>
      {KINDS.map((kind) => (
        <button
          key={kind}
          className="btn"
          disabled={running !== null || fixing || offer === null}
          onClick={() => setChoosing(kind)}
        >
          {t(`review.${kind}` as MessageKey)}
        </button>
      ))}
      {running && <p className="muted">{t('review.running')}</p>}
      {error && <p className="error">{error}</p>}
      {fixed && <p className="notice">{fixed}</p>}
      {done && !running && (
        <>
          <b>{remarks.length ? t('review.count', { n: remarks.length }) : t('review.empty')}</b>
          {fixable > 0 && (
            <div className="stack">
              <button className="btn primary" disabled={fixing} onClick={fixAll}>
                {t('review.fix', { n: fixable })}
              </button>
              <span className="faint small">{t('review.fix.hint')}</span>
            </div>
          )}
          <ul className="history">
            {remarks.map((remark, index) => (
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
                      onClick={() =>
                        navigate(
                          `/projects/${project.id}/chapters/${place.chapter_id}` +
                            (place.paragraph === null ? '' : `?p=${place.paragraph}`),
                        )
                      }
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
      )}
      {choosing && offer && (
        <ReviewDialog
          project={project}
          kind={choosing}
          offer={offer}
          initial={chapterId}
          onClose={() => setChoosing(null)}
          onStart={(ids, ticks) => run(choosing, ids, ticks)}
        />
      )}
    </div>
  )
}

interface DialogProps {
  project: Project
  kind: ReviewKind
  offer: ReviewChecks
  initial?: string
  onClose: () => void
  onStart: (chapterIds: string[], ticks: string[]) => void
}

/** Tick what to look for and pick the chapters; nothing runs before "Check". */
function ReviewDialog({ project, kind, offer, initial, onClose, onStart }: DialogProps) {
  const { t } = useI18n()
  const wholeBook = kind === 'contradictions'
  const items = offer.checks.filter((c) => c.kind === kind)
  const [ticks, setTicks] = useState(() => savedTicks(project.id, kind, offer.checks))
  const [selected, setSelected] = useState(() => new Set(initial ? [initial] : []))
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
  const chosen = items.filter((c) => ticks.has(c.id))
  const usesModel = chosen.some((c) => c.engine === 'ai')
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
  // The side column blurs its background, which would trap a fixed overlay inside it.
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack">
        <h2>{t(`review.${kind}` as MessageKey)}</h2>
        <div className="row">
          <h4>{t('review.rules')}</h4>
          <span className="spacer" />
          <button className="btn ghost small" onClick={() => tick(new Set(items.map((c) => c.id)))}>
            {t('review.ticks.all')}
          </button>
          <button className="btn ghost small" onClick={() => tick(new Set())}>
            {t('review.ticks.none')}
          </button>
          <button
            className="btn ghost small"
            onClick={() => tick(new Set(items.filter((c) => c.default).map((c) => c.id)))}
          >
            {t('review.defaults')}
          </button>
        </div>
        <div className="chapter-picker">
          {items.map((item) => (
            <label key={item.id} className="row">
              <input type="checkbox" checked={ticks.has(item.id)} onChange={() => toggleTick(item.id)} />
              <span className="grow">{t(`review.check.${item.id}` as MessageKey)}</span>
              {item.engine === 'code' && <span className="faint small">{t('review.engine.code')}</span>}
            </label>
          ))}
        </div>
        <p className="muted small">{t(NOTES[kind])}</p>
        {offer.language !== 'ru' && (
          <p className="notice">{t(`review.lang.${offer.language}` as MessageKey)}</p>
        )}
        {wholeBook ? (
          <p className="notice">{t('review.contradictions.hint')}</p>
        ) : (
          <>
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
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button
            className="btn primary"
            disabled={chosen.length === 0 || (!wholeBook && ids.length === 0)}
            onClick={() => onStart(ids, chosen.map((c) => c.id))}
          >
            {t('review.start')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
