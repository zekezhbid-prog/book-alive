import { useState } from 'react'
import { useI18n } from '../i18n'

interface Props {
  english: string
  onEnglish: (text: string) => void
  local: string
  onLocal: (text: string) => void
  /** False: one English field, the interface is in English. */
  both: boolean
  busy: boolean
  disabled?: boolean
  placeholder?: string
}

/**
 * One prompt field with a switch above it: English (what the image model gets) or the
 * interface language. Both halves stay in memory and follow each other as before; only one
 * is shown (owner's notes 27.11).
 */
export function TwoLangPrompt({ english, onEnglish, local, onLocal, both, busy, disabled, placeholder }: Props) {
  const { t } = useI18n()
  const [half, setHalf] = useState<'english' | 'local'>('local')
  const showLocal = both && half === 'local'
  return (
    <div className="two-lang">
      {both && (
        <div className="row two-lang-switch">
          <div className="segmented small" role="group" aria-label={t('generate.prompt.lang')}>
            <button className={showLocal ? '' : 'active'} aria-pressed={!showLocal} onClick={() => setHalf('english')}>
              English
            </button>
            <button className={showLocal ? 'active' : ''} aria-pressed={showLocal} onClick={() => setHalf('local')}>
              {t('generate.prompt.lang.local')}
            </button>
          </div>
          {busy && <span className="faint small">{t('generate.prompt.translating')}</span>}
        </div>
      )}
      <textarea
        className="input prompt"
        value={showLocal ? local : english}
        maxLength={4000}
        disabled={disabled}
        placeholder={placeholder}
        aria-label={showLocal ? t('generate.prompt.lang.local') : 'English'}
        onChange={(e) => (showLocal ? onLocal(e.target.value) : onEnglish(e.target.value))}
      />
    </div>
  )
}
