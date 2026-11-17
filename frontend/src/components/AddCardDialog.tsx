import { useRef, useState, type FormEvent } from 'react'
import { api, type EntityBrief, type EntityKind } from '../api'
import { errorText, useI18n } from '../i18n'
import { UploadIcon } from './icons'

interface Props {
  projectId: string
  kind: EntityKind
  onClose: () => void
  onCreated: (card: EntityBrief) => void
}

/** A card made by hand in one step: its name and, if the user wants, a description.
 * Or a whole card from a file saved by the export in another project. */
export function AddCardDialog({ projectId, kind, onClose, onCreated }: Props) {
  const { t } = useI18n()
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const fileInput = useRef<HTMLInputElement>(null)

  const load = async (file: File | undefined) => {
    if (!file || busy) return
    setBusy(true)
    setError('')
    try {
      const created = await api.importEntity(projectId, kind, file)
      const card = await api.entity(created.id)
      onCreated({
        id: card.id,
        name: card.name,
        aliases: card.aliases,
        chapters: 0,
        facts: 0,
        stale: false,
        blurb: card.description,
      })
    } catch (err) {
      setError(errorText(t, err))
      setBusy(false)
    }
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim() || busy) return
    setBusy(true)
    try {
      const created = await api.createEntity(projectId, kind, name.trim())
      if (description.trim()) await api.saveEntityDescription(created.id, description.trim())
      onCreated({
        id: created.id,
        name: name.trim(),
        aliases: [],
        chapters: 0,
        facts: 0,
        stale: false,
        blurb: description.trim(),
      })
    } catch (err) {
      setError(errorText(t, err))
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="dialog stack" onSubmit={submit}>
        <h2>{t(`add.title.${kind}`)}</h2>
        <label className="field">
          {t('entities.add.prompt')}
          <input
            className="input"
            autoFocus
            required
            maxLength={200}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="field">
          {t('add.description')}
          <textarea
            className="input prompt"
            rows={6}
            maxLength={6000}
            placeholder={t(`description.${kind}.placeholder`)}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <div className="row">
          <input
            ref={fileInput}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e) => {
              load(e.target.files?.[0])
              e.target.value = ''
            }}
          />
          <button
            type="button"
            className="btn"
            title={t('add.fromFile.hint')}
            disabled={busy}
            onClick={() => fileInput.current?.click()}
          >
            <UploadIcon /> {t('add.fromFile')}
          </button>
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button type="submit" className="btn primary" disabled={!name.trim() || busy}>
            {t('add.create')}
          </button>
        </div>
      </form>
    </div>
  )
}
