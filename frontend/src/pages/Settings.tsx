import { useCallback, useEffect, useState, type FormEvent } from 'react'
import {
  api,
  type Connection,
  type ConnectionKind,
  type ModelInfo,
  type ModelSettings,
} from '../api'
import { errorText, useI18n } from '../i18n'

const PRESETS = [
  { name: 'OpenRouter', url: 'https://openrouter.ai/api/v1' },
  { name: 'OmniRoute', url: 'http://127.0.0.1:20128/v1' },
]

export default function Settings() {
  const { t } = useI18n()
  const [connections, setConnections] = useState<Connection[]>([])
  const [settings, setSettings] = useState<ModelSettings | null>(null)
  const [hasCli, setHasCli] = useState(false)
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadConnections = useCallback(() => api.connections().then(setConnections, fail), [fail])
  useEffect(() => {
    loadConnections()
    api.settings().then(setSettings, fail)
    api.system().then((info) => setHasCli(info.claude_cli), fail)
  }, [loadConnections, fail])

  const save = (patch: Partial<ModelSettings>) => {
    if (!settings) return
    const next = { ...settings, ...patch }
    setSettings(next)
    api.saveSettings(next).catch(fail)
  }
  const remove = async (connection: Connection) => {
    if (!confirm(t('settings.delete.confirm', { name: connection.name }))) return
    await api.deleteConnection(connection.id).catch(fail)
    loadConnections()
    api.settings().then(setSettings, fail)
  }

  return (
    <main className="page narrow stack">
      <h1>{t('settings.title')}</h1>
      {error && <p className="error">{error}</p>}

      <section className="panel pad stack">
        <div>
          <h2>{t('settings.connections')}</h2>
          <p className="muted">{t('settings.connections.hint')}</p>
        </div>
        {connections.length === 0 && <p className="faint">{t('settings.connections.empty')}</p>}
        {connections.map((connection) => (
          <div key={connection.id} className="row connection">
            <div className="grow">
              <b>{connection.name}</b>
              <div className="muted small">
                {connection.kind === 'claude_cli'
                  ? t('settings.kind.claude_cli')
                  : `${connection.base_url} · ${
                      connection.api_key_hint
                        ? t('settings.key.stored', { hint: connection.api_key_hint })
                        : t('settings.key.none')
                    }`}
              </div>
            </div>
            <button className="btn ghost small danger" onClick={() => remove(connection)}>
              {t('app.delete')}
            </button>
          </div>
        ))}
        <AddConnection hasCli={hasCli} onAdded={loadConnections} />
      </section>

      {settings && (
        <section className="panel pad stack">
          <div>
            <h2>{t('settings.models')}</h2>
            <p className="muted">{t('settings.models.hint')}</p>
          </div>
          <ModelPicker
            title={t('settings.models.text')}
            connections={connections}
            connectionId={settings.text_connection_id}
            model={settings.text_model}
            onChange={(connectionId, model) =>
              save({ text_connection_id: connectionId, text_model: model })
            }
          />
          <ModelPicker
            title={t('settings.models.image')}
            imagesOnly
            // The subscription connection is text-only.
            connections={connections.filter((c) => c.kind !== 'claude_cli')}
            connectionId={settings.image_connection_id}
            model={settings.image_model}
            onChange={(connectionId, model) =>
              save({ image_connection_id: connectionId, image_model: model })
            }
          />
        </section>
      )}
    </main>
  )
}

function AddConnection({ hasCli, onAdded }: { hasCli: boolean; onAdded: () => void }) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  const [kind, setKind] = useState<ConnectionKind>('openai')
  const [name, setName] = useState('')
  const [url, setUrl] = useState('')
  const [key, setKey] = useState('')
  const [error, setError] = useState('')

  if (!open) {
    return (
      <div>
        <button className="btn" onClick={() => setOpen(true)}>
          + {t('settings.add')}
        </button>
      </div>
    )
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setError('')
    try {
      await api.createConnection({
        kind,
        name: name || (kind === 'claude_cli' ? 'Claude' : ''),
        base_url: kind === 'openai' ? url : '',
        api_key: kind === 'openai' ? key : '',
      })
      setOpen(false)
      setName('')
      setUrl('')
      setKey('')
      onAdded()
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  return (
    <form className="stack subform" onSubmit={submit}>
      <label className="field">
        {t('settings.kind')}
        <select className="input" value={kind} onChange={(e) => setKind(e.target.value as ConnectionKind)}>
          <option value="openai">{t('settings.kind.openai')}</option>
          <option value="claude_cli">{t('settings.kind.claude_cli')}</option>
        </select>
      </label>
      {kind === 'claude_cli' ? (
        <p className={hasCli ? 'muted small' : 'error'}>
          {hasCli ? t('settings.kind.claude_cli.hint') : t('settings.kind.claude_cli.missing')}
        </p>
      ) : (
        <>
          <div className="row">
            {PRESETS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                className="btn small"
                onClick={() => {
                  setName(preset.name)
                  setUrl(preset.url)
                }}
              >
                {preset.name}
              </button>
            ))}
          </div>
          <label className="field">
            {t('settings.url')}
            <input
              className="input"
              value={url}
              required
              placeholder="https://…/v1"
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <label className="field">
            {t('settings.key')}
            <input
              className="input"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <span className="faint">{t('settings.key.hint')}</span>
          </label>
        </>
      )}
      <label className="field">
        {t('settings.name')}
        <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button className="btn primary" disabled={kind === 'claude_cli' && !hasCli}>
          {t('app.save')}
        </button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          {t('app.cancel')}
        </button>
      </div>
    </form>
  )
}

interface PickerProps {
  title: string
  imagesOnly?: boolean
  connections: Connection[]
  connectionId: string
  model: string
  onChange: (connectionId: string, model: string) => void
}

function ModelPicker({ title, imagesOnly, connections, connectionId, model, onChange }: PickerProps) {
  const { t } = useI18n()
  const [models, setModels] = useState<ModelInfo[] | null>(null)
  const [freeOnly, setFreeOnly] = useState(false)
  const [status, setStatus] = useState('')
  const [failed, setFailed] = useState(false)
  const known = connections.some((c) => c.id === connectionId)

  useEffect(() => {
    setModels(null)
    setStatus('')
    if (!known) return
    let stale = false
    api.models(connectionId).then(
      (list) => !stale && setModels(list),
      (e) => {
        if (stale) return
        setModels([])
        setFailed(true)
        setStatus(errorText(t, e))
      },
    )
    return () => {
      stale = true
    }
  }, [connectionId, known, t])

  const anyImageFlag = models?.some((m) => m.image) ?? false
  const anyPrice = models?.some((m) => m.free !== null) ?? false
  const visible = (models ?? []).filter(
    (m) => (!imagesOnly || !anyImageFlag || m.image) && (!freeOnly || m.free),
  )
  const test = async () => {
    setFailed(false)
    setStatus(t('settings.testing'))
    try {
      const result = await api.testModel(connectionId, model)
      setStatus(
        t('settings.test.ok', {
          reply: result.reply,
          input: result.input_tokens,
          output: result.output_tokens,
        }),
      )
    } catch (e) {
      setFailed(true)
      setStatus(errorText(t, e))
    }
  }

  return (
    <div className="stack subform">
      <h3>{title}</h3>
      <div className="row wrap">
        <label className="field grow">
          {t('settings.connection')}
          <select
            className="input"
            value={known ? connectionId : ''}
            onChange={(e) => onChange(e.target.value, '')}
          >
            <option value="">{t('settings.connection.none')}</option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field grow">
          {t('settings.model')}
          <select
            className="input"
            value={model}
            disabled={!known || !models}
            onChange={(e) => onChange(connectionId, e.target.value)}
          >
            <option value="">{models || !known ? t('settings.model.none') : t('settings.models.loading')}</option>
            {/* Keep the saved model selectable even when a filter hides it. */}
            {model && !visible.some((m) => m.id === model) && <option value={model}>{model}</option>}
            {visible.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name === m.id ? m.id : `${m.name} (${m.id})`}
                {m.free ? ` · ${t('settings.free')}` : ''}
              </option>
            ))}
          </select>
        </label>
      </div>
      {known && models && (
        <div className="row wrap small muted">
          <span>{t('settings.models.count', { n: visible.length })}</span>
          {anyPrice && (
            <label className="row">
              <input type="checkbox" checked={freeOnly} onChange={(e) => setFreeOnly(e.target.checked)} />
              {t('settings.free.only')}
            </label>
          )}
          {imagesOnly && models.length > 0 && !anyImageFlag && <span>{t('settings.image.unknown')}</span>}
          <span className="spacer" />
          {/* Image models are exercised when the first picture is generated. */}
          {!imagesOnly && (
            <button className="btn small" disabled={!model} onClick={test}>
              {t('settings.test')}
            </button>
          )}
        </div>
      )}
      {status && <p className={failed ? 'error' : 'ok'}>{status}</p>}
    </div>
  )
}
