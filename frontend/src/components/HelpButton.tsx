import { useState } from 'react'
import { useI18n } from '../i18n'
import { QuestionIcon } from './icons'

interface Props {
  title: string
  /** Each paragraph of the help; empty ones are skipped. */
  paragraphs: string[]
}

/**
 * The "?" beside a window's cross: every explanation of the window opens in a small window of
 * its own, so the working window keeps only what is needed to work (owner's notes 27.11).
 */
export function HelpButton({ title, paragraphs }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        className="btn ghost small icon"
        title={t('help.open')}
        aria-label={t('help.open')}
        onClick={() => setOpen(true)}
      >
        <QuestionIcon />
      </button>
      {open && (
        <div
          className="overlay help-overlay"
          onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}
        >
          <div className="dialog help-dialog" role="dialog" aria-label={title}>
            <div className="row">
              <h3 className="grow">{title}</h3>
              <button
                className="btn ghost small icon"
                title={t('app.close')}
                aria-label={t('app.close')}
                onClick={() => setOpen(false)}
              >
                ✕
              </button>
            </div>
            <div className="stack help-body">
              {paragraphs.filter(Boolean).map((text) => (
                <p key={text}>{text}</p>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
