import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api'
import { useI18n } from '../i18n'

/**
 * Whether a text model is chosen in Settings: true / false, null while it is not known yet.
 * Asked on every mount, so coming back from Settings shows the new choice.
 */
export function useTextModelReady(): boolean | null {
  const [ready, setReady] = useState<boolean | null>(null)
  useEffect(() => {
    let alive = true
    api.settings().then(
      (s) => alive && setReady(Boolean(s.text_connection_id && s.text_model)),
      // Settings that cannot be read are not a reason to block anything: the server still answers.
      () => alive && setReady(true),
    )
    return () => {
      alive = false
    }
  }, [])
  return ready
}

/** Says up front that the AI buttons will not work until a text model is chosen, with the way there. */
export default function AiNotice({ ready }: { ready: boolean | null }) {
  const { t } = useI18n()
  if (ready !== false) return null
  return (
    <div className="notice row ai-notice">
      <span className="grow">{t('ai.missing')}</span>
      <Link className="btn small" to="/settings">
        {t('ai.missing.open')}
      </Link>
    </div>
  )
}
