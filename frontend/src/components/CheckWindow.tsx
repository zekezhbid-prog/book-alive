import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import { CloseIcon } from './icons'

interface Props {
  title: string
  onClose: () => void
  children: ReactNode
}

/** The window of a checklist button: the choice, the progress and the result all stay in
 * it, and it closes with its cross. Rendered into the body: the side column blurs its
 * background, which would trap a fixed overlay inside it. */
export default function CheckWindow({ title, onClose, children }: Props) {
  const { t } = useI18n()
  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll check-window">
        <div className="row">
          <h2 className="grow">{title}</h2>
          <button className="btn ghost small icon" onClick={onClose} title={t('app.close')} aria-label={t('app.close')}>
            <CloseIcon />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** What is being checked now, with a bar that keeps moving on a long step. */
export function CheckProgress({ text, done, total }: { text: string; done: number; total: number }) {
  const percent = total > 0 ? (100 * done) / total : 0
  return (
    <div className="notice stack">
      <b className="run-progress-text">{text}</b>
      <div className="live-progress" role="progressbar" aria-valuenow={Math.round(percent)} aria-valuemax={100}>
        <div className="live-progress-fill" style={{ width: `${Math.max(4, percent)}%` }} />
      </div>
    </div>
  )
}

/** Day and time of a kept check, in the language of the interface. */
export function useWhen() {
  const { lang } = useI18n()
  const locale = lang === 'by' ? 'be' : lang
  return (iso: string) =>
    new Date(iso).toLocaleString(locale, { day: 'numeric', month: 'long', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}
