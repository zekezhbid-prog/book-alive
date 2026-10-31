import { useState } from 'react'
import { errorText, useI18n } from '../i18n'

interface Props {
  value: string
  label: string
  placeholder: string
  /** Called when the text is left with a change; it returns once the text is saved. */
  onSave: (text: string) => Promise<unknown>
}

/** The author's own description in words, saved when the field loses focus. */
export default function DescriptionEditor({ value, label, placeholder, onSave }: Props) {
  const { t } = useI18n()
  const [text, setText] = useState(value)
  const [state, setState] = useState<'' | 'saving' | 'saved'>('')
  const [error, setError] = useState('')
  const save = async () => {
    if (text.trim() === value.trim()) return
    setState('saving')
    setError('')
    try {
      await onSave(text)
      setState('saved')
    } catch (e) {
      setState('')
      setError(errorText(t, e))
    }
  }
  return (
    <div className="stack">
      <div className="row">
        <h4 className="grow">{label}</h4>
        {state && <span className="faint small">{state === 'saving' ? t('app.saving') : t('app.saved')}</span>}
      </div>
      <textarea
        className="input prompt"
        rows={8}
        maxLength={6000}
        value={text}
        placeholder={placeholder}
        onChange={(e) => {
          setText(e.target.value)
          setState('')
        }}
        onBlur={save}
      />
      {error && <p className="error">{error}</p>}
    </div>
  )
}
