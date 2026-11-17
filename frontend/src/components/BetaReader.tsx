import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type BetaReview, type Project } from '../api'
import { ask } from '../dialogs'
import { errorText, useI18n, type MessageKey } from '../i18n'
import CheckWindow, { CheckProgress, useWhen } from './CheckWindow'
import { AiMark, TrashIcon } from './icons'
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
  /** The chapter open in the book: ticked when the window opens. */
  chapterId?: string
  /** Another check is running: the button waits. */
  busy: boolean
  /** Tells the checklist that a review is being written, so other checks wait. */
  onBusy: (busy: boolean) => void
}

interface Job {
  done: number
  total: number
}

/** A living review of chapters, as from a reader the author knows. The button opens a
 * window: the choice, the progress and the reviews stay in it; reviews are kept. */
export default function BetaReader({ project, chapterId, busy, onBusy }: Props) {
  const { t } = useI18n()
  const [reviews, setReviews] = useState<BetaReview[]>([])
  const [open, setOpen] = useState(false)
  const [job, setJob] = useState<Job | null>(null)
  // The reviews the window shows; none means the window offers a new review.
  const [shown, setShown] = useState<BetaReview[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api.betaReviews(project.id).then(setReviews, (e) => setError(errorText(t, e)))
  }, [project.id, t])

  const run = async (chapterIds: string[], choice: Choice) => {
    setError('')
    onBusy(true)
    const made: BetaReview[] = []
    try {
      for (const [n, id] of chapterIds.entries()) {
        setJob({ done: n, total: chapterIds.length })
        const review = await api.betaReview(project.id, id, choice)
        made.push(review)
        setReviews((list) => [review, ...list])
      }
    } catch (e) {
      setError(errorText(t, e))
    }
    setShown(made.length ? made : null)
    setJob(null)
    onBusy(false)
  }
  const remove = async (review: BetaReview) => {
    if (!(await ask(t('beta.delete.confirm')))) return
    try {
      await api.deleteBetaReview(project.id, review.id)
      setReviews((list) => list.filter((r) => r.id !== review.id))
      setShown((list) => (list ? list.filter((r) => r.id !== review.id) : list))
    } catch (e) {
      setError(errorText(t, e))
    }
  }

  return (
    <>
      <button className="btn badge-btn" disabled={busy} onClick={() => setOpen(true)}>
        <span className="grow">{t('beta.title')}</span>
        {job && <span className="faint small">{Math.round((100 * job.done) / job.total)}%</span>}
        <AiMark title={t('review.engine.ai')} />
      </button>
      {open && (
        <CheckWindow title={t('beta.title')} onClose={() => setOpen(false)}>
          {job ? (
            <CheckProgress
              text={t('beta.reading', { done: job.done + 1, n: job.total })}
              done={job.done}
              total={job.total}
            />
          ) : (
            <>
              {error && <p className="error">{error}</p>}
              {shown && shown.length > 0 ? (
                <>
                  <div className="row">
                    <span className="spacer" />
                    <button className="btn small" onClick={() => setShown(null)}>
                      {t('beta.again')}
                    </button>
                  </div>
                  <ReviewList project={project} reviews={shown} full onRemove={remove} onLeave={() => setOpen(false)} />
                </>
              ) : (
                <>
                  <BetaSetup project={project} initial={chapterId} onStart={run} />
                  {reviews.length > 0 && (
                    <>
                      <h4>{t('beta.history')}</h4>
                      <ReviewList project={project} reviews={reviews} onOpen={(r) => setShown([r])} onRemove={remove} />
                    </>
                  )}
                </>
              )}
            </>
          )}
        </CheckWindow>
      )}
    </>
  )
}

interface ListProps {
  project: Project
  reviews: BetaReview[]
  /** Show the text of each review; otherwise only its line, which opens it. */
  full?: boolean
  onOpen?: (review: BetaReview) => void
  onRemove: (review: BetaReview) => void
  /** The chapter was opened in the book: the window steps aside. */
  onLeave?: () => void
}

function ReviewList({ project, reviews, full, onOpen, onRemove, onLeave }: ListProps) {
  const { t } = useI18n()
  const whenText = useWhen()
  const navigate = useNavigate()
  const title = (id: string) => project.chapters.find((c) => c.id === id)?.title || t('book.untitled')
  return (
    <ul className="history">
      {reviews.map((review) => (
        <li key={review.id}>
          <div className="stack grow">
            <div className="row">
              <button
                className="hit grow"
                title={onOpen ? undefined : t('review.open')}
                onClick={() => {
                  if (onOpen) return onOpen(review)
                  onLeave?.()
                  navigate(`/projects/${project.id}/chapters/${review.chapter_id}`)
                }}
              >
                <span className="small">{title(review.chapter_id)}</span>
                <span className="faint small">
                  {t(`beta.reader.${review.reader}` as MessageKey)} · {t(`beta.tone.${review.tone}` as MessageKey)} ·{' '}
                  {whenText(review.created_at)}
                </span>
              </button>
              <button
                className="btn ghost small icon danger"
                title={t('app.delete')}
                aria-label={t('app.delete')}
                onClick={() => onRemove(review)}
              >
                <TrashIcon />
              </button>
            </div>
            {review.outdated && <span className="faint small">{t('beta.outdated')}</span>}
            {full && (
              <div className="beta-text small">
                {blocks(review.text).map((block, i) => (
                  <p key={i}>
                    {block.heading && <b>{block.heading}</b>}
                    {block.body}
                  </p>
                ))}
              </div>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}

interface SetupProps {
  project: Project
  initial?: string
  onStart: (chapterIds: string[], choice: Choice) => void
}

/** What the reader is asked, who reads and how frankly, and which chapters. */
function BetaSetup({ project, initial, onStart }: SetupProps) {
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
  return (
    <>
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
        <button
          className="btn primary"
          disabled={ids.length === 0 || choice.asks.length === 0}
          onClick={() => onStart(ids, choice)}
        >
          {t('beta.start')}
        </button>
      </div>
    </>
  )
}
