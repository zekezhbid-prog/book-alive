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

/** The two halves one under the other, English first. */
export function TwoLangPrompt({ english, onEnglish, local, onLocal, both, busy, disabled, placeholder }: Props) {
  const { t } = useI18n()
  return (
    <div className="two-lang">
      <label className="two-lang-half">
        {both && <span className="faint small">English</span>}
        <textarea
          className="input prompt"
          value={english}
          maxLength={4000}
          disabled={disabled}
          placeholder={placeholder}
          onChange={(e) => onEnglish(e.target.value)}
        />
      </label>
      {both && (
        <label className="two-lang-half">
          <span className="faint small">
            {t('generate.prompt.local')}
            {busy && ` · ${t('generate.prompt.translating')}`}
          </span>
          <textarea
            className="input prompt"
            value={local}
            maxLength={4000}
            disabled={disabled}
            onChange={(e) => onLocal(e.target.value)}
          />
        </label>
      )}
    </div>
  )
}
