import { useCallback, useEffect, useRef, useState } from 'react'
import {
  ANGLES,
  api,
  IMAGE_SIZES,
  type Angle,
  type ChapterBrief,
  type EntityKind,
  type ImageInfo,
  type ImageSize,
} from '../api'
import { errorText, useI18n } from '../i18n'
import { CopyIcon, GearIcon, SparklesIcon, StarIcon, TrashIcon, UploadIcon } from './icons'

interface Props {
  projectId: string
  /** A card's pictures; without it, the project's general references. */
  entityId?: string
  /** Main pictures of a character are marked with a view (face, full length). */
  kind?: EntityKind
  chapters: ChapterBrief[]
  /** Whether a project style is chosen: pictures cannot be generated without one. */
  hasStyle: boolean
}

/** Reference pictures: uploaded by the user or generated here, labelled with their style. */
export default function Gallery({ projectId, entityId, kind, chapters, hasStyle }: Props) {
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
    setOpen(true) // show what was just added
    if (picker.current) picker.current.value = ''
  }
  const patch = (image: ImageInfo, change: Parameters<typeof api.updateImage>[1]) =>
    api.updateImage(image.id, change).then(load, fail)
  const remove = (image: ImageInfo) => {
    if (confirm(t('gallery.delete.confirm'))) api.deleteImage(image.id).then(load, fail)
  }
  // A card's references start folded so the description is in view; the project's
  // general gallery is the whole point of its page and stays open.
  const [open, setOpen] = useState(!entityId)
  // The picture window: empty for a new picture, or open on an existing one.
  const [dialog, setDialog] = useState<ImageInfo | 'new' | null>(null)
  const closeDialog = useCallback(() => setDialog(null), [])

  return (
    <div className="stack">
      <div className="row">
        {entityId ? (
          <button className="fold" aria-expanded={open} onClick={() => setOpen(!open)}>
            <span className="fold-mark">{open ? '▾' : '▸'}</span>
            <h4>{t('gallery.title')}</h4>
            {images && <span className="faint small">{images.length}</span>}
          </button>
        ) : (
          <h4>{t('gallery.general')}</h4>
        )}
        <span className="spacer" />
        <input
          ref={picker}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          multiple
          hidden
          onChange={(e) => upload(e.target.files)}
        />
        {entityId && (
          <button className="btn small" onClick={() => setDialog('new')}>
            {t('generate.title')}
          </button>
        )}
        <button className="btn small" disabled={busy} onClick={() => picker.current?.click()}>
          {busy ? t('gallery.uploading') : t('gallery.upload')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {entityId && dialog && (
        <ImageDialog
          entityId={entityId}
          image={dialog === 'new' ? null : dialog}
          withAngles={kind === 'character'}
          chapters={chapters}
          hasStyle={hasStyle}
          onChanged={() => {
            load()
            setOpen(true) // a new picture is in view once the window closes
          }}
          onClose={closeDialog}
        />
      )}
      {open && images?.length === 0 && (
        <p className="faint small">{t(entityId ? 'gallery.empty' : 'gallery.general.empty')}</p>
      )}
      {open && entityId && !!images?.length && (
        <p className="muted small">{t('gallery.main.hint')}</p>
      )}
      {/* Rendered only when open: `hidden` would lose to the grid's own `display`. */}
      {open && (
        <div className="gallery">
          {images?.map((image) => (
            <figure key={image.id} className={`shot ${image.current_style ? '' : 'other-style'}`}>
              <a href={image.url} target="_blank" rel="noreferrer">
                <img src={image.url} alt="" loading="lazy" />
              </a>
              <figcaption>
                <div className="row">
                  {entityId && (
                    <button
                      className={`btn ghost small icon ${image.is_main ? 'on' : ''}`}
                      aria-pressed={image.is_main}
                      title={t(image.is_main ? 'gallery.unmake_main' : 'gallery.make_main')}
                      aria-label={t(image.is_main ? 'gallery.unmake_main' : 'gallery.make_main')}
                      onClick={() => patch(image, { is_main: !image.is_main })}
                    >
                      <StarIcon on={image.is_main} />
                    </button>
                  )}
                  {image.origin === 'upload' && (
                    <span className="mark-icon" title={t('gallery.uploaded')}>
                      <UploadIcon />
                    </span>
                  )}
                  {!image.current_style && (
                    <span className="badge stale" title={t('gallery.other_style.hint')}>
                      {t('gallery.other_style')}
                    </span>
                  )}
                  <span className="spacer" />
                  {entityId && (
                    <button
                      className="btn ghost small icon"
                      title={t('gallery.settings')}
                      aria-label={t('gallery.settings')}
                      onClick={() => setDialog(image)}
                    >
                      <GearIcon />
                    </button>
                  )}
                  <button
                    className="btn ghost small icon danger"
                    title={t('app.delete')}
                    aria-label={t('app.delete')}
                    onClick={() => remove(image)}
                  >
                    <TrashIcon />
                  </button>
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
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

function AngleSelect({
  value,
  empty,
  onChange,
}: {
  value: Angle | ''
  empty: string
  onChange: (angle: Angle | '') => void
}) {
  const { t } = useI18n()
  return (
    <select
      className="input small"
      value={value}
      onChange={(e) => onChange(e.target.value as Angle | '')}
    >
      <option value="">{empty}</option>
      {ANGLES.map((angle) => (
        <option key={angle} value={angle}>
          {t(`angle.${angle}`)}
        </option>
      ))}
    </select>
  )
}

interface DialogProps {
  entityId: string
  /** The picture whose settings are open; without it, the window starts empty for a new one. */
  image: ImageInfo | null
  withAngles: boolean
  chapters: ChapterBrief[]
  hasStyle: boolean
  /** A picture was drawn or its settings were saved: the gallery reloads. */
  onChanged: () => void
  onClose: () => void
}

type Change = Parameters<typeof api.updateImage>[1]

/**
 * One window for a picture: drawing a new one and changing an existing one's settings.
 * Two separate steps, each started by the user: the text model writes the prompt, then the
 * image model draws it. A drawn picture is stored at once as a new reference (an earlier one
 * stays); the settings are a draft until "Apply".
 */
function ImageDialog({
  entityId,
  image,
  withAngles,
  chapters,
  hasStyle,
  onChanged,
  onClose,
}: DialogProps) {
  const { t } = useI18n()
  const [current, setCurrent] = useState(image)
  const [isMain, setIsMain] = useState(image?.is_main ?? true)
  const [angle, setAngle] = useState<Angle | ''>(image?.angle ?? '')
  const [look, setLook] = useState(image?.look_label ?? '')
  const [chapter, setChapter] = useState(image ? image.chapter_from_id || image.chapter_to_id : '')
  const [prompt, setPrompt] = useState(image?.prompt ?? '')
  const [size, setSize] = useState<ImageSize | ''>('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image' | 'save'>('')
  const [error, setError] = useState('')
  // A look belongs to one chapter: the range is stored with both ends on it.
  const request = isMain
    ? { angle: withAngles ? angle : ('' as const), look_label: '', chapter_from_id: '', chapter_to_id: '' }
    : { angle: '' as const, look_label: look.trim(), chapter_from_id: chapter, chapter_to_id: chapter }
  // The server tells a look by its label or chapter: without them it would draw a main picture.
  const ready = isMain || Boolean(look.trim() || chapter)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = async (step: 'prompt' | 'image') => {
    setBusy(step)
    setError('')
    try {
      if (step === 'prompt') {
        const written = await api.imagePrompt(entityId, request)
        setPrompt(written.prompt)
        // The view the service picked stays chosen, so the picture is drawn as written.
        if (isMain) setAngle(written.angle)
      } else {
        const made = await api.generateImage(entityId, { ...request, prompt, size })
        setCurrent(made)
        setAngle(made.angle)
        onChanged()
      }
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }

  const apply = async () => {
    if (!current) return onClose()
    const change: Change = {}
    if (isMain !== current.is_main) change.is_main = isMain
    if (isMain && request.angle !== current.angle) change.angle = request.angle
    if (!isMain && request.look_label !== current.look_label) change.look_label = request.look_label
    if (!isMain && (chapter !== current.chapter_from_id || chapter !== current.chapter_to_id)) {
      change.chapter_from_id = chapter
      change.chapter_to_id = chapter
    }
    if (!Object.keys(change).length) return onClose()
    setBusy('save')
    try {
      await api.updateImage(current.id, change)
      onChanged()
      onClose()
    } catch (e) {
      setError(errorText(t, e))
      setBusy('')
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog generator image-dialog">
        <div className="row">
          <h2>{t(image ? 'gallery.settings' : 'generate.title')}</h2>
          <span className="spacer" />
          <button className="btn ghost small" aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="dialog-body">
          <div className="picture-slot">
            {current ? (
              <div className="stack slot-picture">
                <a href={current.url} target="_blank" rel="noreferrer">
                  <img src={current.url} alt="" />
                </a>
                {current.origin === 'upload' && (
                  <span className="muted small slot-note">
                    <UploadIcon />
                    {t('gallery.uploaded')}
                  </span>
                )}
              </div>
            ) : (
              <span className="faint small">
                {busy === 'image' ? t('generate.image.busy') : t('generate.slot')}
              </span>
            )}
          </div>
          <div className="stack">
            <button
              className={`btn small toggle ${isMain ? 'on' : ''}`}
              aria-pressed={isMain}
              onClick={() => setIsMain(!isMain)}
            >
              <StarIcon on={isMain} />
              {t(isMain ? 'gallery.is_main' : 'gallery.is_look')}
            </button>
            {/* Both sets of fields sit in one grid cell, the hidden one keeping its space:
                switching never changes the window's size or moves the buttons. */}
            <div className="mode-fields">
              <div className="stack" inert={!isMain} style={{ visibility: isMain ? 'visible' : 'hidden' }}>
                <p className="muted small">{t('generate.hint.main')}</p>
                {withAngles && (
                  <label className="stack field">
                    <span className="small muted">{t('gallery.angle')}</span>
                    <AngleSelect
                      value={angle}
                      empty={t(current ? 'gallery.angle.none' : 'generate.angle.auto')}
                      onChange={setAngle}
                    />
                  </label>
                )}
              </div>
              <div className="stack" inert={isMain} style={{ visibility: isMain ? 'hidden' : 'visible' }}>
                <p className="muted small">{t('generate.hint.look')}</p>
                <label className="stack field">
                  <span className="small muted">{t('gallery.look')}</span>
                  <input
                    className="input small"
                    value={look}
                    maxLength={200}
                    placeholder={t('gallery.look.placeholder')}
                    onChange={(e) => setLook(e.target.value)}
                  />
                </label>
                <label className="stack field">
                  <span className="small muted">{t('gallery.chapter')}</span>
                  <ChapterSelect
                    value={chapter}
                    chapters={chapters}
                    empty={t('gallery.chapter.none')}
                    onChange={setChapter}
                  />
                </label>
              </div>
            </div>
            <div className="stack field">
              <div className="row">
                <span className="small muted">{t('generate.prompt.label')}</span>
                <span className="spacer" />
                <button
                  className="btn ghost small"
                  disabled={busy !== '' || !ready}
                  onClick={() => run('prompt')}
                >
                  <SparklesIcon />
                  {busy === 'prompt' ? t('generate.prompt.busy') : t('generate.prompt')}
                </button>
                <button
                  className="btn ghost small icon"
                  disabled={!prompt}
                  title={t('generate.copy')}
                  aria-label={t('generate.copy')}
                  onClick={() => navigator.clipboard.writeText(prompt)}
                >
                  <CopyIcon />
                </button>
              </div>
              <textarea
                className="input prompt"
                rows={6}
                value={prompt}
                maxLength={4000}
                placeholder={t('generate.prompt.placeholder')}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </div>
            <div className="row wrap">
              <select
                className="input small size-select"
                value={size}
                aria-label={t('generate.size')}
                onChange={(e) => setSize(e.target.value as ImageSize | '')}
              >
                <option value="">{t('generate.size.auto')}</option>
                {IMAGE_SIZES.map((option) => (
                  <option key={option} value={option}>
                    {t(`generate.size.${option}`)}
                  </option>
                ))}
              </select>
              <button
                className="btn small"
                disabled={busy !== '' || !hasStyle || !prompt.trim() || !ready}
                onClick={() => run('image')}
              >
                {busy === 'image' ? t('generate.image.busy') : t('generate.image')}
              </button>
              {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
            </div>
            {current && current.id !== image?.id && (
              <p className="muted small">{t('generate.made')}</p>
            )}
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn ghost" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={busy !== '' || !current} onClick={apply}>
            {t('gallery.apply')}
          </button>
        </div>
      </div>
    </div>
  )
}
