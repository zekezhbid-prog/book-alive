import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api, type BetaReview, type Project } from '../api'
import { ask } from '../dialogs'
import { errorText, useI18n, type MessageKey } from '../i18n'
import { TrashIcon } from './icons'
import SelectAll from './SelectAll'

const ASKS = ['liked', 'boring', 'disbelief', 'unclear', 'expect']
const READERS = ['fan', 'casual', 'critic']
const TONES = ['soft', 'honest']

interface Choice {
  asks: string[]
  reader: string
  tone: string
}
const DEFAULT: Choice = { asks: ASKS, reader: 'casual', tone: 'soft' }
const storageKey = (projectId: string) => `beta:${projectId}`

function savedChoice(projectId: string): Choice {
  try {
    const raw = localStorage.getItem(storageKey(projectId))
    if (raw) return { ...DEFAULT, ...(JSON.parse(raw) as Partial<Choice>) }
  } catch {
    /* unreadable or blocked storage: the defaults */
  }
  return DEFAULT
}

function saveChoice(projectId: string, choice: Choice) {
  try {
    localStorage.setItem(storageKey(projectId), JSON.stringify(choice))
  } catch {
    /* private mode: the choice lasts until the page is reloaded only */
  }
}

/** The review split into paragraphs; a short first line without a full stop is the
 * heading of its point ("What I liked"). */
function blocks(text: string): { heading: string; body: string }[] {
  return text
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const [first, ...rest] = part.split('\n')
      const heading = rest.length > 0 && first.length <= 80 && !/[.!?…»"]$/.test(first) ? first : ''
      return { heading, body: heading ? rest.join('\n') : part }
    })
}

interface Props {
  project: Project
  /** The chapter open in the book: ticked when the dialog opens. */
  chapterId?: string
  /** Another check is running: the button waits. */
  busy: boolean
}

/** A living review of chapters, as from a reader the author knows. Reviews are kept. */
export default function BetaReader({ project, chapterId, busy }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [reviews, setReviews] = useState<BetaReview[]>([])
  const [choosing, setChoosing] = useState(false)
  const [progress, setProgress] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    api.betaReviews(project.id).then(setReviews, (e) => setError(errorText(t, e)))
  }, [project.id, t])

  const run = async (chapterIds: string[], choice: Choice) => {
    setChoosing(false)
    setError('')
    try {
      for (const [n, id] of chapterIds.entries()) {
        setProgress(t('beta.reading', { done: n + 1, n: chapterIds.length }))
        const review = await api.betaReview(project.id, id, choice)
        setReviews((list) => [review, ...list])
      }
    } catch (e) {
      setError(errorText(t, e))
    }
    setProgress('')
  }
  const remove = async (review: BetaReview) => {
    if (!(await ask(t('beta.delete.confirm')))) return
    try {
      await api.deleteBetaReview(project.id, review.id)
      setReviews((list) => list.filter((r) => r.id !== review.id))
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  const title = (id: string) => project.chapters.find((c) => c.id === id)?.title || t('book.untitled')

  return (
    <div className="stack">
      <button className="btn" disabled={busy || progress !== ''} onClick={() => setChoosing(true)}>
        {t('beta.title')}
      </button>
      {progress && <p className="muted">{progress}</p>}
      {error && <p className="error">{error}</p>}
      {reviews.length > 0 && (
        <>
          <b>{t('beta.saved', { n: reviews.length })}</b>
          <ul className="history">
            {reviews.map((review) => (
              <li key={review.id}>
                <div className="stack">
                  <div className="row">
                    <button
                      className="hit grow"
                      title={t('review.open')}
                      onClick={() => navigate(`/projects/${project.id}/chapters/${review.chapter_id}`)}
                    >
                      <span className="small">{title(review.chapter_id)}</span>
                      <span className="faint small">
                        {t(`beta.reader.${review.reader}` as MessageKey)} · {t(`beta.tone.${review.tone}` as MessageKey)}{' '}
                        · {new Date(review.created_at).toLocaleDateString()}
                      </span>
                    </button>
                    <button
                      className="btn ghost small icon danger"
                      title={t('app.delete')}
                      aria-label={t('app.delete')}
                      onClick={() => remove(review)}
                    >
                      <TrashIcon />
                    </button>
                  </div>
                  {review.outdated && <span className="faint small">{t('beta.outdated')}</span>}
                  <div className="beta-text small">
                    {blocks(review.text).map((block, i) => (
                      <p key={i}>
                        {block.heading && <b>{block.heading}</b>}
                        {block.body}
                      </p>
                    ))}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </>
      )}
      {choosing && (
        <BetaDialog
          project={project}
          initial={chapterId}
          onClose={() => setChoosing(false)}
          onStart={run}
        />
      )}
    </div>
  )
}

interface DialogProps {
  project: Project
  initial?: string
  onClose: () => void
  onStart: (chapterIds: string[], choice: Choice) => void
}

function BetaDialog({ project, initial, onClose, onStart }: DialogProps) {
  const { t } = useI18n()
  const [choice, setChoice] = useState(() => savedChoice(project.id))
  const [selected, setSelected] = useState(() => new Set(initial ? [initial] : []))
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
  const update = (next: Choice) => {
    setChoice(next)
    saveChoice(project.id, next)
  }
  const toggleAsk = (id: string) =>
    update({ ...choice, asks: choice.asks.includes(id) ? choice.asks.filter((a) => a !== id) : [...choice.asks, id] })
  const toggle = (id: string) => {
    const next = new Set(selected)
    if (!next.delete(id)) next.add(id)
    setSelected(next)
  }
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll">
        <h2>{t('beta.title')}</h2>
        <p className="muted small">{t('beta.hint')}</p>
        <div className="row">
          <h4>{t('beta.asks')}</h4>
          <span className="spacer" />
          <SelectAll
            ids={ASKS}
            selected={new Set(choice.asks)}
            onChange={(next) => update({ ...choice, asks: ASKS.filter((a) => next.has(a)) })}
          />
        </div>
        <div className="chapter-picker">
          {ASKS.map((id) => (
            <label key={id} className="row">
              <input type="checkbox" checked={choice.asks.includes(id)} onChange={() => toggleAsk(id)} />
              <span className="grow">{t(`beta.ask.${id}` as MessageKey)}</span>
            </label>
          ))}
        </div>
        <h4>{t('beta.who')}</h4>
        <div className="stack">
          {READERS.map((id) => (
            <label key={id} className="row">
              <input type="radio" name="beta-reader" checked={choice.reader === id} onChange={() => update({ ...choice, reader: id })} />
              <span className="grow">
                {t(`beta.reader.${id}` as MessageKey)}
                <span className="faint small"> ({t(`beta.reader.${id}.ex` as MessageKey)})</span>
              </span>
            </label>
          ))}
        </div>
        <h4>{t('beta.tone')}</h4>
        <div className="row">
          {TONES.map((id) => (
            <label key={id} className="row">
              <input type="radio" name="beta-tone" checked={choice.tone === id} onChange={() => update({ ...choice, tone: id })} />
              <span>{t(`beta.tone.${id}` as MessageKey)}</span>
            </label>
          ))}
        </div>
        <div className="row">
          <h4>{t('run.title')}</h4>
          <span className="spacer" />
          <SelectAll ids={project.chapters.map((c) => c.id)} selected={selected} onChange={setSelected} />
        </div>
        <div className="chapter-picker short">
          {project.chapters.map((chapter) => (
            <label key={chapter.id} className="row">
              <input type="checkbox" checked={selected.has(chapter.id)} onChange={() => toggle(chapter.id)} />
              <span className="grow">{chapter.title || t('book.untitled')}</span>
              <span className="faint small">{chapter.chars.toLocaleString()}</span>
            </label>
          ))}
        </div>
        {ids.length > 1 && <p className="muted small">{t('beta.many', { n: ids.length })}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button
            className="btn primary"
            disabled={ids.length === 0 || choice.asks.length === 0}
            onClick={() => onStart(ids, choice)}
          >
            {t('beta.start')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
