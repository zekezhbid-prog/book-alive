import { useCallback, useEffect, useRef, useState } from 'react'
import { api, IMAGE_SIZES, type ChapterBrief, type EntityKind, type ImageInfo, type ImageSize } from '../api'
import { errorText, useI18n } from '../i18n'
import { PencilIcon, SparklesIcon, TrashIcon, UploadIcon } from './icons'
import { ask } from '../dialogs'
import { MicButton } from './MicButton'
import { zoomLink } from './Lightbox'
import { AutoTextarea } from './AutoTextarea'
import { ReferenceChat } from './ReferenceChat'

interface Props {
  projectId: string
  /** A card's pictures; without it, the project's general references. */
  entityId?: string
  /** Main pictures of a character are marked with a view (face, full length). */
  kind?: EntityKind
  /** Not used since the references window became a dialogue; kept for the callers. */
  chapters?: ChapterBrief[]
  /** Whether a project style is chosen: pictures cannot be generated without one. */
  hasStyle: boolean
  /** After any picture was added or removed: the card's tile shows one of them. */
  onChanged?: () => void
}

/** Reference pictures: uploaded by the user or generated here, labelled with their style. */
export default function Gallery({ projectId, entityId, kind, hasStyle, onChanged }: Props) {
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
  const changed = () => {
    load()
    onChanged?.()
  }

  const upload = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    setError('')
    await api.uploadImages(projectId, [...files], entityId).then(changed, fail)
    setBusy(false)
    if (picker.current) picker.current.value = ''
  }
  const remove = async (image: ImageInfo) => {
    if (await ask(t('gallery.delete.confirm'))) api.deleteImage(image.id).then(changed, fail)
  }
  // The references window: every base view and picture in context, drawn or put in there.
  const [dialog, setDialog] = useState(false)
  const closeDialog = useCallback(() => setDialog(false), [])

  // On a card: the pictures in one row right under the name, nothing to unfold; drawing and
  // putting in happen in the references window behind "Edit" (owner's notes, 24.11.2026).
  if (entityId) {
    return (
      <div className="stack">
        <div className="ref-row">
          {images?.length === 0 ? (
            <button className="ref-add" onClick={() => setDialog(true)}>
              <span className="ref-add-frame" aria-hidden>
                <ThinPlus />
              </span>
              <span className="ref-add-text">
                <span className="ref-add-title">{t('gallery.add.reference')}</span>
                <span className="faint small">{t(`gallery.add.hint.${kind ?? 'location'}`)}</span>
              </span>
            </button>
          ) : (
            <RefStrip images={images ?? []} onRemove={remove} />
          )}
          {/* With pictures, only a pencil like the other icons: the row keeps its room. */}
          {!!images?.length && (
            <button
              className="btn primary nav-action ref-edit"
              title={t('gallery.edit')}
              aria-label={t('gallery.edit')}
              onClick={() => setDialog(true)}
            >
              <PencilIcon />
            </button>
          )}
        </div>
        {error && <p className="error">{error}</p>}
        {dialog && (
          <ReferenceChat
            projectId={projectId}
            entityId={entityId}
            kind={kind ?? 'location'}
            bases={(images ?? []).filter((i) => i.is_main && i.current_style)}
            hasStyle={hasStyle}
            onChanged={changed}
            onClose={closeDialog}
          />
        )}
      </div>
    )
  }

  return (
    <div className="stack">
      <div className="row">
        <h4>{t('gallery.general')}</h4>
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
      {images?.length === 0 && <p className="faint small">{t('gallery.general.empty')}</p>}
      {(
        <div className="gallery">
          {images?.map((image, n) => (
            <figure key={image.id} className={`shot ${image.current_style ? '' : 'other-style'}`}>
              <a {...zoomLink(images.map((i) => i.url), n)}>
                <img src={image.url} alt="" loading="lazy" />
              </a>
              <figcaption className="over">
                <div className="row">
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
                  <button
                    className="btn ghost small icon gold slot-drop"
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

/** A card's pictures in one row of fixed height. When they do not fit, arrows at the ends
 *  scroll the row; it never grows into a second line. */
function RefStrip({ images, onRemove }: { images: ImageInfo[]; onRemove: (image: ImageInfo) => void }) {
  const { t } = useI18n()
  const track = useRef<HTMLDivElement>(null)
  const [edges, setEdges] = useState({ left: false, right: false })
  const measure = useCallback(() => {
    const el = track.current
    if (!el) return
    setEdges({ left: el.scrollLeft > 2, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 2 })
  }, [])
  useEffect(() => {
    measure()
    const el = track.current
    if (!el) return
    const watcher = new ResizeObserver(measure)
    watcher.observe(el)
    return () => watcher.disconnect()
  }, [measure, images.length])
  const go = (direction: number) => {
    const el = track.current
    el?.scrollBy({ left: direction * el.clientWidth * 0.8, behavior: 'smooth' })
  }
  return (
    <div className="ref-strip">
      <button
        className="ref-strip-arrow left"
        hidden={!edges.left}
        title={t('gallery.prev')}
        aria-label={t('gallery.prev')}
        onClick={() => go(-1)}
      >
        ‹
      </button>
      <div className="ref-strip-track" ref={track} onScroll={measure}>
        {images.map((image, n) => (
          <figure key={image.id} className={`shot ref-shot ${image.current_style ? '' : 'other-style'}`}>
            <a {...zoomLink(images.map((i) => i.url), n)}>
              <img src={image.url} alt="" loading="lazy" />
            </a>
            <button
              className="btn ghost small icon gold slot-drop"
              title={t('app.delete')}
              aria-label={t('app.delete')}
              onClick={() => onRemove(image)}
            >
              <TrashIcon />
            </button>
          </figure>
        ))}
      </div>
      <button
        className="ref-strip-arrow right"
        hidden={!edges.right}
        title={t('gallery.next')}
        aria-label={t('gallery.next')}
        onClick={() => go(1)}
      >
        ›
      </button>
    </div>
  )
}

/** A large thin plus for empty places: faint at rest, glowing gold under the pointer. */
function ThinPlus() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden>
      <path d="M24 8v32M8 24h32" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  )
}


interface RedoProps {
  image: ImageInfo
  hasStyle: boolean
  disabled: boolean
  onDone: (image: ImageInfo) => void
  onDelete: () => void
}

/**
 * A finished or put in picture, in the same order as the form of a new one: hint, the
 * references it was drawn from, the prompt, remarks, size, the button (owner's notes 26.11).
 * The prompt and the remarks lock each other: a changed prompt draws the picture anew from
 * its first references, a remark improves the picture as it is.
 */
export function RedoPanel({ image, hasStyle, disabled, onDone, onDelete }: RedoProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(image.prompt)
  const [remark, setRemark] = useState('')
  const [size, setSize] = useState<ImageSize>('1:1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const edited = prompt.trim() !== image.prompt.trim() && prompt.trim() !== ''
  const remarked = remark.trim() !== ''
  const urls = image.reference_ids.map((id) => `/api/images/${id}/file`)

  const redo = async () => {
    setBusy(true)
    setError('')
    try {
      const made = await api.redoImage(image.id, edited ? { prompt: prompt.trim(), size } : { remark: remark.trim(), size })
      setRemark('')
      onDone(made)
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy(false)
  }

  return (
    <div className="stack picture-info">
      <div className="stack field">
        <span className="small muted">{t('generate.references.used')}</span>
        {urls.length ? (
          <div className="used-refs">
            {urls.map((url, n) => (
              <a key={url} {...zoomLink(urls, n)}>
                {/* A reference deleted since leaves no broken picture behind. */}
                <img src={url} alt="" loading="lazy" onError={(e) => (e.currentTarget.parentElement!.style.display = 'none')} />
              </a>
            ))}
          </div>
        ) : (
          <p className="faint small">{t('generate.references.none')}</p>
        )}
      </div>
      {/* The remark is what the user is meant to write; the prompt stays editable but faded,
          and a picture put in from a file has none (owner's notes 27.11). */}
      <div className="stack field remark-field">
        <span className="small">{t('generate.remark')}</span>
        <div className="row">
          <AutoTextarea
            className="input small grow"
            value={remark}
            maxLength={1000}
            disabled={busy || edited}
            title={edited ? t('generate.prompt.locked') : undefined}
            placeholder={edited ? t('generate.prompt.locked') : t('generate.remark.placeholder')}
            onChange={(e) => setRemark(e.target.value)}
          />
          <MicButton
            disabled={busy || edited}
            onText={(text) => setRemark((now) => (now.trim() ? `${now.trim()} ${text}` : text))}
            onError={setError}
          />
        </div>
      </div>
      {image.prompt && (
      <label className="stack field">
        <span className="small muted">{t('generate.prompt.label')}</span>
        <textarea
          className="input small redo-prompt quiet"
          value={prompt}
          maxLength={4000}
          disabled={busy || remarked}
          title={remarked ? t('generate.remark.placeholder') : undefined}
          placeholder={t('generate.redo.prompt.placeholder')}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      )}
      <select
        className="input small"
        value={size}
        aria-label={t('generate.size')}
        onChange={(e) => setSize(e.target.value as ImageSize)}
      >
        {IMAGE_SIZES.map((option) => (
          <option key={option} value={option}>
            {t(`generate.size.${option}`)}
          </option>
        ))}
      </select>
      {error && <p className="error small">{error}</p>}
      <div className="stack generate-row">
        <div className="row wrap">
          <button
            className="btn primary generate-big grow"
            disabled={busy || disabled || !hasStyle || (!edited && !remarked)}
            title={!edited && !remarked ? t('generate.redo.hint') : undefined}
            onClick={redo}
          >
            <SparklesIcon />
            {busy ? t('generate.redo.busy') : remarked ? t('generate.improve') : t('generate.redo')}
          </button>
          <button className="btn danger" disabled={busy || disabled} onClick={onDelete}>
            <TrashIcon />
            {t('app.delete')}
          </button>
        </div>
        {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
      </div>
    </div>
  )
}
