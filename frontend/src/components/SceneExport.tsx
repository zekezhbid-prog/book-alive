import { useEffect, useState } from 'react'
import { api, type Scene, type SceneExportOptions } from '../api'
import { errorText, useI18n } from '../i18n'
import { DownloadIcon } from './icons'
import { MicButton } from './MicButton'
import { AutoTextarea } from './AutoTextarea'

const ASPECTS: SceneExportOptions['aspect'][] = ['16:9', '9:16', '1:1']
const DURATIONS = [5, 10, 15, 20, 30, 45, 60]

/**
 * The questions a video prompt needs that the cards cannot answer (format, length, sound,
 * effects, palette), then one archive: the shot plan, a prompt per generation, the
 * pictures and the lines to voice (owner's notes, 24.11.2026).
 */
export default function SceneExport({ scene, onClose }: { scene: Scene; onClose: () => void }) {
  const { t } = useI18n()
  const [options, setOptions] = useState<SceneExportOptions>({
    aspect: '16:9',
    duration: 15,
    dialogue: true,
    narration: false,
    effects: '',
    palette: '',
    note: '',
    images_per_clip: 5,
  })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const set = <K extends keyof SceneExportOptions>(key: K, value: SceneExportOptions[K]) =>
    setOptions((had) => ({ ...had, [key]: value }))

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [busy, onClose])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const blob = await api.exportScene(scene.id, options)
      const link = document.createElement('a')
      link.href = URL.createObjectURL(blob)
      link.download = `${scene.title || 'scene'} - video.zip`
      link.click()
      setTimeout(() => URL.revokeObjectURL(link.href), 10_000)
      onClose()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy(false)
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="dialog scene-export stack">
        <div className="row">
          <h2 className="grow">{t('export.title')}</h2>
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} disabled={busy} onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="muted small">{t('export.hint')}</p>

        <div className="stack field">
          <span className="small muted">{t('export.aspect')}</span>
          <div className="segmented" role="radiogroup">
            {ASPECTS.map((aspect) => (
              <button
                key={aspect}
                role="radio"
                aria-checked={options.aspect === aspect}
                className={options.aspect === aspect ? 'active' : ''}
                disabled={busy}
                onClick={() => set('aspect', aspect)}
              >
                {t(`export.aspect.${aspect}`)}
              </button>
            ))}
          </div>
        </div>

        <div className="row wrap export-pair">
          <label className="stack field grow">
            <span className="small muted">{t('export.duration')}</span>
            <select
              className="input small"
              value={options.duration}
              disabled={busy}
              onChange={(e) => set('duration', Number(e.target.value))}
            >
              {DURATIONS.map((seconds) => (
                <option key={seconds} value={seconds}>
                  {t('export.seconds', { n: seconds })}
                </option>
              ))}
            </select>
          </label>
          <label className="stack field grow" title={t('export.images.hint')}>
            <span className="small muted">{t('export.images')}</span>
            <select
              className="input small"
              value={options.images_per_clip}
              disabled={busy}
              onChange={(e) => set('images_per_clip', Number(e.target.value))}
            >
              {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="stack field">
          <span className="small muted">{t('export.sound')}</span>
          <label className="row small">
            <input type="checkbox" checked={options.dialogue} disabled={busy} onChange={(e) => set('dialogue', e.target.checked)} />
            {t('export.dialogue')}
          </label>
          <label className="row small">
            <input type="checkbox" checked={options.narration} disabled={busy} onChange={(e) => set('narration', e.target.checked)} />
            {t('export.narration')}
          </label>
        </div>

        <label className="stack field">
          <span className="small muted">{t('export.effects')}</span>
          <input
            className="input small"
            value={options.effects}
            maxLength={300}
            disabled={busy}
            placeholder={t('export.effects.placeholder')}
            onChange={(e) => set('effects', e.target.value)}
          />
        </label>
        <label className="stack field">
          <span className="small muted">{t('export.palette')}</span>
          <input
            className="input small"
            value={options.palette}
            maxLength={300}
            disabled={busy}
            placeholder={t('export.palette.placeholder')}
            onChange={(e) => set('palette', e.target.value)}
          />
        </label>
        <label className="stack field">
          <span className="small muted">{t('export.note')}</span>
          <div className="row">
            <AutoTextarea
              className="input small grow"
              value={options.note}
              maxLength={1000}
              disabled={busy}
              placeholder={t('export.note.placeholder')}
              onChange={(e) => set('note', e.target.value)}
            />
            <MicButton
              disabled={busy}
              onText={(text) => set('note', options.note.trim() ? `${options.note.trim()} ${text}` : text)}
              onError={setError}
            />
          </div>
        </label>

        {error && <p className="error small">{error}</p>}
        <div className="row wrap">
          <span className="spacer" />
          <button className="btn ghost" disabled={busy} onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={busy} onClick={start}>
            <DownloadIcon />
            {busy ? t('export.busy') : t('export.start')}
          </button>
        </div>
      </div>
    </div>
  )
}
