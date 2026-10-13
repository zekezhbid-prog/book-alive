import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type ChapterBrief, type ImageInfo } from '../api'
import { errorText, useI18n } from '../i18n'

interface Props {
  projectId: string
  /** A card's pictures; without it, the project's general references. */
  entityId?: string
  chapters: ChapterBrief[]
  /** Whether a project style is chosen: pictures cannot be generated without one. */
  hasStyle: boolean
}

/** Reference pictures: uploaded by the user or generated here, labelled with their style. */
export default function Gallery({ projectId, entityId, chapters, hasStyle }: Props) {
  const { t } = useI18n()
  const [images, setImages] = useState<ImageInfo[] | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const picker = useRef<HTMLInputElement>(null)

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const load = useCallback(
    () => api.images(projectId, entityId).then(setImages, fail),
    [projectId, entityId, fail],
  )
  useEffect(() => {
    setImages(null)
    load()
  }, [load])

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    setError('')
    await api.uploadImages(projectId, [...files], entityId).then(load, fail)
    setBusy(false)
    if (picker.current) picker.current.value = ''
  }
  const patch = (image: ImageInfo, change: Parameters<typeof api.updateImage>[1]) =>
    api.updateImage(image.id, change).then(load, fail)
  const remove = (image: ImageInfo) => {
    if (confirm(t('gallery.delete.confirm'))) api.deleteImage(image.id).then(load, fail)
  }
  const title = (id: string) => chapters.find((c) => c.id === id)?.title || t('book.untitled')

  return (
    <div className="stack">
      <div className="row">
        <h4>{t(entityId ? 'gallery.title' : 'gallery.general')}</h4>
        <span className="spacer" />
        <input
          ref={picker}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          onChange={(e) => upload(e.target.files)}
        />
        <button className="btn small" disabled={busy} onClick={() => picker.current?.click()}>
          {busy ? t('gallery.uploading') : t('gallery.upload')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {images?.length === 0 && (
        <p className="faint small">{t(entityId ? 'gallery.empty' : 'gallery.general.empty')}</p>
      )}
      <div className="gallery">
        {images?.map((image) => (
          <figure key={image.id} className={`shot ${image.current_style ? '' : 'other-style'}`}>
            <a href={image.url} target="_blank" rel="noreferrer">
              <img src={image.url} alt="" loading="lazy" />
            </a>
            <figcaption className="stack">
              <div className="row wrap">
                {image.is_main && <span className="badge writer">{t('gallery.main')}</span>}
                <span className="badge">{t(`gallery.origin.${image.origin}`)}</span>
                {!image.current_style && (
                  <span className="badge stale" title={t('gallery.other_style.hint')}>
                    {t('gallery.other_style')}
                  </span>
                )}
              </div>
              {entityId && !image.is_main && (
                <>
                  <input
                    className="input small"
                    defaultValue={image.look_label}
                    maxLength={200}
                    placeholder={t('gallery.look.placeholder')}
                    onBlur={(e) =>
                      e.target.value.trim() !== image.look_label &&
                      patch(image, { look_label: e.target.value })
                    }
                  />
                  <div className="row small muted">
                    <ChapterSelect
                      value={image.chapter_from_id}
                      chapters={chapters}
                      empty={t('gallery.from.start')}
                      onChange={(id) => patch(image, { chapter_from_id: id })}
                    />
                    —
                    <ChapterSelect
                      value={image.chapter_to_id}
                      chapters={chapters}
                      empty={t('gallery.to.end')}
                      onChange={(id) => patch(image, { chapter_to_id: id })}
                    />
                  </div>
                </>
              )}
              <div className="row">
                {entityId && !image.is_main && (
                  <button className="btn ghost small" onClick={() => patch(image, { is_main: true })}>
                    {t('gallery.make_main')}
                  </button>
                )}
                <span className="spacer" />
                <button className="btn ghost small danger" onClick={() => remove(image)}>
                  {t('app.delete')}
                </button>
              </div>
            </figcaption>
          </figure>
        ))}
      </div>
      {entityId && (
        <Generator
          entityId={entityId}
          chapters={chapters}
          hasStyle={hasStyle}
          hasMain={images?.some((i) => i.is_main && i.current_style) ?? false}
          chapterTitle={title}
          onCreated={load}
        />
      )}
    </div>
  )
}

interface SelectProps {
  value: string
  chapters: ChapterBrief[]
  empty: string
  onChange: (id: string) => void
}

function ChapterSelect({ value, chapters, empty, onChange }: SelectProps) {
  const { t } = useI18n()
  return (
    <select className="input small" value={value} onChange={(e) => onChange(e.target.value)}>
      <option value="">{empty}</option>
      {chapters.map((chapter) => (
        <option key={chapter.id} value={chapter.id}>
          {chapter.title || t('book.untitled')}
        </option>
      ))}
    </select>
  )
}

interface GeneratorProps {
  entityId: string
  chapters: ChapterBrief[]
  hasStyle: boolean
  hasMain: boolean
  chapterTitle: (id: string) => string
  onCreated: () => void
}

/** Two separate steps, each started by the user: the text model writes the prompt,
 *  then the image model draws it. The prompt can be edited, or copied to draw elsewhere. */
function Generator({ entityId, chapters, hasStyle, hasMain, onCreated }: GeneratorProps) {
  const { t } = useI18n()
  const [look, setLook] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image'>('')
  const [error, setError] = useState('')
  const request = { look_label: look, chapter_from_id: from, chapter_to_id: to }
  const isLook = Boolean(look || from || to)

  const run = async (step: 'prompt' | 'image') => {
    setBusy(step)
    setError('')
    try {
      if (step === 'prompt') setPrompt((await api.imagePrompt(entityId, request)).prompt)
      else {
        await api.generateImage(entityId, { ...request, prompt })
        onCreated()
      }
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }

  return (
    <div className="stack subform">
      <h4>{t('generate.title')}</h4>
      <p className="muted small">{t(hasMain ? 'generate.hint.look' : 'generate.hint.main')}</p>
      {hasMain && (
        <div className="row wrap">
          <input
            className="input grow"
            value={look}
            maxLength={200}
            placeholder={t('gallery.look.placeholder')}
            onChange={(e) => setLook(e.target.value)}
          />
          <ChapterSelect value={from} chapters={chapters} empty={t('gallery.from.start')} onChange={setFrom} />
          —
          <ChapterSelect value={to} chapters={chapters} empty={t('gallery.to.end')} onChange={setTo} />
        </div>
      )}
      <div className="row">
        <button className="btn" disabled={busy !== ''} onClick={() => run('prompt')}>
          {busy === 'prompt' ? t('generate.prompt.busy') : t('generate.prompt')}
        </button>
        {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
      </div>
      {prompt && (
        <>
          <textarea
            className="input prompt"
            rows={5}
            value={prompt}
            maxLength={4000}
            onChange={(e) => setPrompt(e.target.value)}
          />
          <div className="row">
            <button
              className="btn primary"
              disabled={busy !== '' || !hasStyle}
              onClick={() => run('image')}
            >
              {busy === 'image' ? t('generate.image.busy') : t(isLook ? 'generate.look' : 'generate.image')}
            </button>
            <button className="btn" onClick={() => navigator.clipboard.writeText(prompt)}>
              {t('generate.copy')}
            </button>
          </div>
        </>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}
