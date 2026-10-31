import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Remark, type ReviewKind } from '../api'
import { errorText, useI18n, type MessageKey } from '../i18n'

interface Props {
  projectId: string
  chapterId?: string
}

const KINDS: ReviewKind[] = ['grammar', 'editorial', 'contradictions']

/** Manuscript checks for the writer: the book is never changed, only remarks are listed. */
export default function ReviewPanel({ projectId, chapterId }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [running, setRunning] = useState<ReviewKind | null>(null)
  const [done, setDone] = useState<ReviewKind | null>(null)
  const [remarks, setRemarks] = useState<Remark[]>([])
  const [error, setError] = useState('')

  const run = async (kind: ReviewKind) => {
    setRunning(kind)
    setError('')
    try {
      const result = await api.review(projectId, kind, chapterId ?? '')
      setRemarks(result.remarks)
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
        <button
          key={kind}
          className="btn"
          disabled={running !== null || (kind !== 'contradictions' && !chapterId)}
          onClick={() => run(kind)}
        >
          {t(`review.${kind}` as MessageKey)}
        </button>
      ))}
      <p className="muted small">{t('review.contradictions.hint')}</p>
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
                          `/projects/${projectId}/chapters/${place.chapter_id}` +
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
    </div>
  )
}
