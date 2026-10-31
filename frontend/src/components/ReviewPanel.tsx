import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api, type Project, type Remark, type ReviewKind } from '../api'
import { errorText, useI18n, type MessageKey } from '../i18n'

interface Props {
  project: Project
  /** The chapter open in the book: ticked when a check dialog opens. */
  chapterId?: string
}

const KINDS: ReviewKind[] = ['grammar', 'editorial', 'contradictions']
/** What each check looks for, as listed in its dialog (the prompts on the server do the same). */
const RULES: Record<ReviewKind, MessageKey[]> = {
  grammar: ['review.rule.grammar.1', 'review.rule.grammar.2', 'review.rule.grammar.3', 'review.rule.grammar.4'],
  editorial: [
    'review.rule.editorial.1',
    'review.rule.editorial.2',
    'review.rule.editorial.3',
    'review.rule.editorial.4',
    'review.rule.editorial.5',
    'review.rule.editorial.6',
  ],
  contradictions: ['review.rule.contradictions.1', 'review.rule.contradictions.2'],
}

/** Manuscript checks for the writer: the book is never changed, only remarks are listed. */
export default function ReviewPanel({ project, chapterId }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [choosing, setChoosing] = useState<ReviewKind | null>(null)
  const [running, setRunning] = useState<ReviewKind | null>(null)
  const [done, setDone] = useState<ReviewKind | null>(null)
  const [remarks, setRemarks] = useState<Remark[]>([])
  const [error, setError] = useState('')

  const run = async (kind: ReviewKind, chapterIds: string[]) => {
    setChoosing(null)
    setRunning(kind)
    setError('')
    try {
      // The server checks one chapter at a time; contradictions look at the whole book.
      const found: Remark[] = []
      for (const id of kind === 'contradictions' ? [''] : chapterIds) {
        found.push(...(await api.review(project.id, kind, id)).remarks)
      }
      setRemarks(found)
      setDone(kind)
    } catch (e) {
      setError(errorText(t, e))
    }
    setRunning(null)
  }
  const category = (name: string) => {
    const key = `review.cat.${name}` as MessageKey
    const text = t(key)
    return text === key ? name : text
  }

  return (
    <div className="stack">
      <h4>{t('review.title')}</h4>
      <p className="muted small">{t('review.hint')}</p>
      {KINDS.map((kind) => (
        <button key={kind} className="btn" disabled={running !== null} onClick={() => setChoosing(kind)}>
          {t(`review.${kind}` as MessageKey)}
        </button>
      ))}
      {running && <p className="muted">{t('review.running')}</p>}
      {error && <p className="error">{error}</p>}
      {done && !running && (
        <>
          <b>{remarks.length ? t('review.count', { n: remarks.length }) : t('review.empty')}</b>
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
      {choosing && (
        <ReviewDialog
          project={project}
          kind={choosing}
          initial={chapterId}
          onClose={() => setChoosing(null)}
          onStart={(ids) => run(choosing, ids)}
        />
      )}
    </div>
  )
}

interface DialogProps {
  project: Project
  kind: ReviewKind
  initial?: string
  onClose: () => void
  onStart: (chapterIds: string[]) => void
}

/** Pick the chapters and read what the check looks for; nothing runs before "Check". */
function ReviewDialog({ project, kind, initial, onClose, onStart }: DialogProps) {
  const { t } = useI18n()
  const wholeBook = kind === 'contradictions'
  const [selected, setSelected] = useState(() => new Set(initial ? [initial] : []))
  const ids = project.chapters.filter((c) => selected.has(c.id)).map((c) => c.id)
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
        <div className="stack">
          <h4>{t('review.rules')}</h4>
          <ul className="rules">
            {RULES[kind].map((key) => (
              <li key={key}>{t(key)}</li>
            ))}
          </ul>
        </div>
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
            {ids.length > 1 && <p className="muted small">{t('review.many', { n: ids.length })}</p>}
          </>
        )}
        <div className="row">
          <span className="spacer" />
          <button className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={!wholeBook && ids.length === 0} onClick={() => onStart(ids)}>
            {t('review.start')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
