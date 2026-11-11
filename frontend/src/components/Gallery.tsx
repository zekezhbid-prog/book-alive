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
import { CopyIcon, GearIcon, PlusIcon, SparklesIcon, StarIcon, TrashIcon, UploadIcon } from './icons'
import { ask } from '../dialogs'

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
  const remove = async (image: ImageInfo) => {
    if (await ask(t('gallery.delete.confirm'))) api.deleteImage(image.id).then(load, fail)
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
        {/* On a card everything starts from one window: drawing and uploading alike. */}
        {entityId ? (
          <button className="btn small" onClick={() => setDialog('new')}>
            <PlusIcon />
            {t('gallery.add')}
          </button>
        ) : (
          <button className="btn small" disabled={busy} onClick={() => picker.current?.click()}>
            {busy ? t('gallery.uploading') : t('gallery.upload')}
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {entityId && dialog && (
        <ImageDialog
          projectId={projectId}
          entityId={entityId}
          image={dialog === 'new' ? null : dialog}
          bases={(images ?? []).filter((i) => i.is_main && i.current_style)}
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
  projectId: string
  entityId: string
  /** The picture whose settings are open; without it, the window starts empty for a new one. */
  image: ImageInfo | null
  /** The card's base pictures in the current style: pictures in context are drawn from them. */
  bases: ImageInfo[]
  withAngles: boolean
  chapters: ChapterBrief[]
  hasStyle: boolean
  /** A picture was drawn, uploaded or its settings were saved: the gallery reloads. */
  onChanged: () => void
  onClose: () => void
}

type Change = Parameters<typeof api.updateImage>[1]
type Mode = 'base' | 'context'

// A base set is drawn face first: that picture becomes the reference for the rest.
const SET_ORDER: Angle[] = [
  'face_front',
  'face_three_quarter',
  'face_profile',
  'full_front',
  'full_side',
  'full_back',
]

// Whether "Generate" writes the prompt itself: remembered in this browser.
const AUTO_KEY = 'imagePrompt:auto'
function readAuto() {
  try {
    return localStorage.getItem(AUTO_KEY) !== 'manual'
  } catch {
    return true
  }
}
function saveAuto(on: boolean) {
  try {
    localStorage.setItem(AUTO_KEY, on ? 'auto' : 'manual')
  } catch {
    /* private mode: the choice lasts while the window is open */
  }
}

/** The newest base picture of a view: the one its slot shows. */
function latest(bases: ImageInfo[], view: Angle) {
  return bases
    .filter((b) => b.angle === view)
    .reduce<ImageInfo | null>((best, b) => (!best || b.created_at > best.created_at ? b : best), null)
}

/**
 * One window for a picture: adding a new one (drawn or uploaded) and changing an existing
 * one's settings. A base picture shows the face or figure; a character's base pictures can
 * be drawn as a whole set of views from one prompt. A picture in context is drawn from the
 * base ones. Drawing is two steps, each started by the user: the text model writes the
 * prompt, then the image model draws it. Every drawn or uploaded picture is stored at once;
 * the settings of an existing one are a draft until "Apply". A scene opens it too, for a
 * card in that scene.
 */
export function ImageDialog({
  projectId,
  entityId,
  image,
  bases,
  withAngles,
  chapters,
  hasStyle,
  onChanged,
  onClose,
}: DialogProps) {
  const { t } = useI18n()
  const [current, setCurrent] = useState(image)
  const [mode, setMode] = useState<Mode>(image && !image.is_main ? 'context' : 'base')
  const [angle, setAngle] = useState<Angle | ''>(image?.angle ?? '')
  // Views of a new base set: the missing ones, or all of them when none is missing.
  const [views, setViews] = useState<Angle[]>(() => {
    const missing = SET_ORDER.filter((view) => !bases.some((b) => b.angle === view))
    return missing.length ? missing : SET_ORDER
  })
  const [look, setLook] = useState(image?.look_label ?? '')
  const [chapter, setChapter] = useState(image ? image.chapter_from_id || image.chapter_to_id : '')
  const [prompt, setPrompt] = useState(image?.prompt ?? '')
  const [size, setSize] = useState<ImageSize | ''>('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image' | 'upload' | 'save'>('')
  const [progress, setProgress] = useState('')
  const [autoPrompt, setAutoPrompt] = useState(readAuto)
  const chooseAuto = (on: boolean) => {
    setAutoPrompt(on)
    saveAuto(on)
  }
  // The view of a set being drawn right now: its slot shows a spinner.
  const [drawing, setDrawing] = useState<Angle | ''>('')
  const [error, setError] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  const isMain = mode === 'base'
  // A new character picture in base mode is a set of views drawn from one prompt.
  const asSet = isMain && withAngles && !image
  // Pictures in context are drawn from base ones, so they wait for the first.
  const contextLocked = !image && bases.length === 0 && !current?.is_main
  // The big picture: the one just made or clicked; in a set, otherwise the first finished view.
  const shown =
    current ?? (asSet ? (SET_ORDER.map((v) => latest(bases, v)).find(Boolean) ?? null) : null)
  // A look belongs to one chapter: the range is stored with both ends on it.
  const request = isMain
    ? { angle: withAngles ? angle : ('' as const), look_label: '', chapter_from_id: '', chapter_to_id: '' }
    : { angle: '' as const, look_label: look.trim(), chapter_from_id: chapter, chapter_to_id: chapter }
  // The server tells a look by its label or chapter: without them it would draw a base picture.
  const ready = isMain ? !asSet || views.length > 0 : Boolean(look.trim() || chapter)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // The text model writes the prompt; null when it failed (the error is shown).
  const collect = async () => {
    try {
      const written = await api.imagePrompt(entityId, { ...request, view_free: asSet })
      setPrompt(written.prompt)
      // The view the service picked stays chosen, so the picture is drawn as written.
      if (isMain && !asSet) setAngle(written.angle)
      return written
    } catch (e) {
      setError(errorText(t, e))
      return null
    }
  }

  const writePrompt = async () => {
    setBusy('prompt')
    setError('')
    await collect()
    setBusy('')
  }

  const draw = async () => {
    setError('')
    // Automatic prompt: written quietly right before drawing, nothing to check in between.
    let text = prompt
    let chosen = angle
    if (autoPrompt) {
      setBusy('prompt')
      const written = await collect()
      if (!written) return setBusy('')
      text = written.prompt
      if (isMain && !asSet) chosen = written.angle
    }
    setBusy('image')
    try {
      if (asSet) {
        const order = SET_ORDER.filter((view) => views.includes(view))
        for (const [n, view] of order.entries()) {
          setProgress(
            t('generate.set.progress', { done: n + 1, total: order.length, view: t(`angle.${view}`) }),
          )
          setDrawing(view)
          const made = await api.generateImage(entityId, {
            ...request,
            angle: view,
            prompt: text,
            size,
            add_view: true,
          })
          setCurrent(made)
          onChanged()
        }
        setProgress(t('generate.set.done', { n: order.length }))
        // A drawn view is not drawn again by the next press unless ticked anew.
        setViews([])
      } else {
        const made = await api.generateImage(entityId, {
          ...request,
          ...(isMain && withAngles ? { angle: chosen } : {}),
          prompt: text,
          size,
        })
        setCurrent(made)
        setAngle(made.angle)
        onChanged()
      }
    } catch (e) {
      setProgress('')
      setError(errorText(t, e))
    }
    setDrawing('')
    setBusy('')
  }

  // An uploaded file is filed as the mode says: a base picture (a reference for drawing) or
  // a picture in context with its look and chapter.
  const upload = async (files: FileList | File[] | null) => {
    if (!files?.length) return
    setBusy('upload')
    setError('')
    try {
      let last: ImageInfo | null = null
      for (const made of await api.uploadImages(projectId, [...files], entityId)) {
        last = await api.updateImage(made.id, isMain ? { is_main: true } : { ...request, is_main: false })
      }
      setCurrent(last)
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    if (picker.current) picker.current.value = ''
    setBusy('')
  }

  // A picture copied elsewhere goes in like a file: Ctrl+V in the window or the "Paste" button.
  const canAdd = !image && busy === '' && ready
  useEffect(() => {
    if (!canAdd) return
    const onPaste = (e: ClipboardEvent) => {
      const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith('image/'))
      if (!files.length) return
      e.preventDefault()
      upload(files)
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })
  const pasteClipboard = async () => {
    try {
      const files: File[] = []
      for (const item of await navigator.clipboard.read()) {
        const type = item.types.find((kind) => kind.startsWith('image/'))
        if (type) files.push(new File([await item.getType(type)], `pasted.${type.split('/')[1]}`, { type }))
      }
      if (files.length) upload(files)
      else setError(t('gallery.paste.empty'))
    } catch {
      setError(t('gallery.paste.denied'))
    }
  }

  const apply = async () => {
    // A new picture is stored the moment it is drawn or uploaded.
    if (!image || !current) return onClose()
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

  const toggleView = (view: Angle) =>
    setViews((chosen) => (chosen.includes(view) ? chosen.filter((v) => v !== view) : [...chosen, view]))

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog generator image-dialog">
        <div className="row">
          <h2>{t(image ? 'gallery.settings' : 'gallery.add.title')}</h2>
          <span className="spacer" />
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="dialog-body">
          <div className="stack">
          <div className="picture-slot">
            {shown ? (
              <div className="stack slot-picture">
                <a href={shown.url} target="_blank" rel="noreferrer">
                  <img src={shown.url} alt="" />
                </a>
                {shown.origin === 'upload' && (
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
          {/* The set as slots: what is there, what is missing, what is drawn on the next press. */}
          {asSet && (
            <div className="view-slots">
              {SET_ORDER.map((view) => {
                const made = latest(bases, view)
                const ticked = views.includes(view)
                return (
                  <div
                    key={view}
                    className={`view-slot ${made ? 'filled' : ''} ${ticked ? 'ticked' : ''} ${
                      made && shown?.id === made.id ? 'shown' : ''
                    }`}
                  >
                    <button
                      className="view-slot-face"
                      disabled={!made}
                      title={made ? t('generate.slot.show') : ''}
                      onClick={() => made && setCurrent(made)}
                    >
                      {made && <img src={made.url} alt="" loading="lazy" />}
                      {drawing === view && <span className="view-slot-busy" aria-hidden />}
                    </button>
                    <label className="view-slot-label small">
                      <input
                        type="checkbox"
                        checked={ticked}
                        disabled={busy !== ''}
                        title={t(made ? 'generate.slot.redraw' : 'generate.slot.draw')}
                        onChange={() => toggleView(view)}
                      />
                      {t(`angle.${view}`)}
                    </label>
                  </div>
                )
              })}
            </div>
          )}
          </div>
          <div className="stack">
            {/* One of the two is always pressed. Pictures in context are drawn from base ones,
                so before the first base picture there is nothing to choose. */}
            {!contextLocked && (
            <div className="segmented mode-switch" role="radiogroup">
              {(['base', 'context'] as const).map((option) => (
                <button
                  key={option}
                  role="radio"
                  aria-checked={mode === option}
                  className={mode === option ? 'active' : ''}
                  disabled={busy !== ''}
                  onClick={() => setMode(option)}
                >
                  {t(`gallery.mode.${option}`)}
                </button>
              ))}
            </div>
            )}
            {/* Both sets of fields sit in one grid cell, the hidden one keeping its space:
                switching never changes the window's size or moves the buttons. */}
            <div className="mode-fields">
              <div className="stack" inert={!isMain} style={{ visibility: isMain ? 'visible' : 'hidden' }}>
                <p className="muted small">{t(asSet ? 'generate.hint.base_set' : 'generate.hint.main')}</p>
                {asSet ? (
                  <p className="muted small">{t('generate.views.hint')}</p>
                ) : (
                  withAngles && (
                    <label className="stack field">
                      <span className="small muted">{t('gallery.angle')}</span>
                      <AngleSelect
                        value={angle}
                        empty={t(current ? 'gallery.angle.none' : 'generate.angle.auto')}
                        onChange={setAngle}
                      />
                    </label>
                  )
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
            <div className="row">
              {!image && (
                <>
                  <input
                    ref={picker}
                    type="file"
                    accept="image/png,image/jpeg,image/webp"
                    multiple
                    hidden
                    onChange={(e) => upload(e.target.files)}
                  />
                  <button
                    className="btn ghost small upload-ref"
                    disabled={busy !== '' || !ready}
                    title={isMain ? t('gallery.upload.reference.hint') : ''}
                    onClick={() => picker.current?.click()}
                  >
                    <UploadIcon />
                    {busy === 'upload'
                      ? t('gallery.uploading')
                      : t(isMain ? 'gallery.upload.reference' : 'gallery.upload.file')}
                  </button>
                  <button
                    className="btn ghost small"
                    disabled={!canAdd}
                    title={t('gallery.paste.hint')}
                    onClick={pasteClipboard}
                  >
                    <CopyIcon />
                    {t('gallery.paste')}
                  </button>
                </>
              )}
            </div>
            <div className="stack field">
              <div className="row">
                <span className="small muted">{t('generate.prompt.label')}</span>
                {/* Auto: pressing "Generate" writes the prompt and draws at once. By hand: the
                    prompt is written first and shown for editing, drawing is the next press. */}
                <div className="segmented small-switch" role="radiogroup">
                  {([true, false] as const).map((on) => (
                    <button
                      key={String(on)}
                      role="radio"
                      aria-checked={autoPrompt === on}
                      className={autoPrompt === on ? 'active' : ''}
                      disabled={busy !== ''}
                      onClick={() => chooseAuto(on)}
                    >
                      {t(on ? 'generate.prompt.auto' : 'generate.prompt.manual')}
                    </button>
                  ))}
                </div>
                <span className="spacer" />
                {!autoPrompt && (
                  <button className="btn ghost small" disabled={busy !== '' || !ready} onClick={writePrompt}>
                    <SparklesIcon />
                    {busy === 'prompt' ? t('generate.prompt.busy') : t('generate.prompt')}
                  </button>
                )}
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
              {autoPrompt ? (
                <>
                  <p className="faint small">{t('generate.prompt.auto.hint')}</p>
                  {prompt && (
                    <details>
                      <summary className="muted small">{t('generate.prompt.last')}</summary>
                      <p className="small prompt-last">{prompt}</p>
                    </details>
                  )}
                </>
              ) : (
                <textarea
                  className="input prompt"
                  rows={6}
                  value={prompt}
                  maxLength={4000}
                  placeholder={t('generate.prompt.placeholder')}
                  onChange={(e) => setPrompt(e.target.value)}
                />
              )}
            </div>
            <select
              className="input small"
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
            <div className="row wrap">
              <button
                className="btn primary generate-big"
                disabled={busy !== '' || !hasStyle || (!autoPrompt && !prompt.trim()) || !ready}
                onClick={draw}
              >
                <SparklesIcon />
                {busy === 'prompt' && autoPrompt
                  ? t('generate.prompt.busy')
                  : busy === 'image'
                  ? t('generate.image.busy')
                  : asSet
                    ? t('generate.set', { n: views.length })
                    : t('generate.image')}
              </button>
            </div>
            {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
            {progress && <p className="muted small">{progress}</p>}
            {!progress && current && current.id !== image?.id && (
              <p className="muted small">{t('generate.made')}</p>
            )}
          </div>
        </div>
        {error && <p className="error">{error}</p>}
        {/* A new picture is stored as soon as it is made: the cross above closes the window. */}
        {image && (
          <div className="row">
            <span className="spacer" />
            <button className="btn ghost" onClick={onClose}>
              {t('app.cancel')}
            </button>
            <button className="btn primary" disabled={busy !== ''} onClick={apply}>
              {t('gallery.apply')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
