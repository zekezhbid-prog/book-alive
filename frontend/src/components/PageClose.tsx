import { useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'

/** ✕ in the corner of a page opened from the menu: back to where the user came from. */
export default function PageClose({ fallback }: { fallback: string }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  // A page opened by a pasted link has nowhere to go back to: then the book itself.
  const canGoBack = (window.history.state?.idx ?? 0) > 0
  return (
    <button
      className="btn ghost"
      title={t('app.close')}
      aria-label={t('app.close')}
      onClick={() => (canGoBack ? navigate(-1) : navigate(fallback))}
    >
      ✕
    </button>
  )
}
