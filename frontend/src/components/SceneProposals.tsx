import { useEffect, useRef, useState } from 'react'
import { api, type SceneProposal, type SceneProposals } from '../api'
import { errorText, useI18n } from '../i18n'
import { confirmSplit } from '../sceneSplit'

interface ListProps {
  chapterId: string
  /** Ask with the price before the first split; "Pick from the book" splits at once. */
  confirm: boolean
  onPick: (proposal: SceneProposal, stale: boolean) => void
}

/**
 * The scenes proposed for a chapter (owner's notes 27.11, item 25): one split, kept on the
 * server, shared by "Split into scenes" and "Pick from the book". A chapter not split yet is
 * split here; "Split again" asks the model anew.
 */
export function ProposalList({ chapterId, confirm, onPick }: ListProps) {
  const { t } = useI18n()
  const [data, setData] = useState<SceneProposals | null>(null)
  const [busy, setBusy] = useState(false)
  const [declined, setDeclined] = useState(false)
  const [error, setError] = useState('')
  const shown = useRef(chapterId) // a late answer for another chapter is not shown

  const split = async (again: boolean) => {
    const key = chapterId
    setError('')
    setDeclined(false)
    try {
      if ((confirm || again) && !(await confirmSplit(t, key, again))) {
        if (!again) setDeclined(true)
        return
      }
      setBusy(true)
      const found = await api.splitScenes(key, again)
      if (shown.current === key) setData(found)
    } catch (e) {
      if (shown.current === key) setError(errorText(t, e))
    } finally {
      if (shown.current === key) setBusy(false)
    }
  }

  useEffect(() => {
    shown.current = chapterId
    setData(null)
    setError('')
    setDeclined(false)
    api.sceneProposals(chapterId).then((found) => {
      if (shown.current !== chapterId) return
      if (found.exists) setData(found)
      else void split(false)
    }, (e) => shown.current === chapterId && setError(errorText(t, e)))
    // A new chapter only; `split` reads the current one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chapterId])

  if (busy) return <p className="muted">{t('scenes.split.busy')}</p>
  return (
    <div className="stack">
      {error && <p className="error small">{error}</p>}
      {declined && (
        <button className="btn primary" onClick={() => split(false)}>
          {t('scenes.split')}
        </button>
      )}
      {!data && !error && !declined && <p className="muted">{t('scenes.split.busy')}</p>}
      {data?.stale && <p className="error small">{t('scenes.proposals.stale')}</p>}
      {data && data.items.length === 0 && <p className="faint">{t('scenes.proposals.none')}</p>}
      {data?.items.map((p) => (
        <button
          key={p.number}
          className="btn ghost"
          style={{ justifyContent: 'flex-start', textAlign: 'left', whiteSpace: 'normal', height: 'auto' }}
          onClick={() => onPick(p, data.stale)}
        >
          <span>
            <b>
              {p.vivid && '★ '}
              {p.title}
            </b>
            {p.scene_id && <span className="small faint"> · {t('scenes.proposals.made')}</span>}
            <br />
            <span className="small muted">{p.summary}</span>
          </span>
        </button>
      ))}
      {data && (
        <div className="row">
          <span className="spacer" />
          <button className="btn ghost small" onClick={() => split(true)}>
            {t('scenes.split.again')}
          </button>
        </div>
      )}
    </div>
  )
}

interface DialogProps {
  chapterId: string
  title: string
  onClose: () => void
  /** The card of the picked scene, made now or before. */
  onPicked: (sceneId: string) => void
}

/** "Split into scenes": the chapter's proposed scenes; a pick makes one card. */
export default function SceneProposalsDialog({ chapterId, title, onClose, onPicked }: DialogProps) {
  const { t } = useI18n()
  const [error, setError] = useState('')
  const pick = async (p: SceneProposal) => {
    setError('')
    if (p.scene_id) return onPicked(p.scene_id)
    try {
      onPicked((await api.pickProposal(chapterId, p.number)).id)
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll">
        <div className="row">
          <h3 className="grow">{title || t('scenes.proposals.title')}</h3>
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="small faint">{t('scenes.proposals.hint')}</p>
        {error && <p className="error small">{error}</p>}
        <ProposalList chapterId={chapterId} confirm onPick={pick} />
      </div>
    </div>
  )
}
