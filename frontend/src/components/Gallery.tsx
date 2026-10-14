import { useCallback, useEffect, useRef, useState } from 'react'
import { ANGLES, api, type Angle, type ChapterBrief, type EntityKind, type ImageInfo } from '../api'
import { errorText, useI18n } from '../i18n'

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
  const [generating, setGenerating] = useState(false)
  const closeGenerator = useCallback(() => setGenerating(false), [])

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
          <button className="btn small" onClick={() => setGenerating(true)}>
            {t('generate.title')}
          </button>
        )}
        <button className="btn small" disabled={busy} onClick={() => picker.current?.click()}>
          {busy ? t('gallery.uploading') : t('gallery.upload')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {entityId && generating && (
        <Generator
          entityId={entityId}
          withAngles={kind === 'character'}
          chapters={chapters}
          hasStyle={hasStyle}
          onCreated={() => {
            load()
            setOpen(true) // the new picture is in view once the window closes
          }}
          onClose={closeGenerator}
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
                {entityId && image.is_main && kind === 'character' && (
                  <AngleSelect
                    value={image.angle}
                    empty={t('gallery.angle.none')}
                    onChange={(angle) => patch(image, { angle })}
                  />
                )}
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
                <div className="row wrap">
                  {entityId && (
                    <button
                      className="btn ghost small"
                      onClick={() => patch(image, { is_main: !image.is_main })}
                    >
                      {t(image.is_main ? 'gallery.unmake_main' : 'gallery.make_main')}
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

interface GeneratorProps {
  entityId: string
  withAngles: boolean
  chapters: ChapterBrief[]
  hasStyle: boolean
  onCreated: () => void
  onClose: () => void
}

/** A view of a main picture, or "other": a look for part of the story. */
type Choice = Angle | '' | 'other'

/** A window over the page. Two separate steps, each started by the user: the text model
 *  writes the prompt, then the image model draws it. The prompt can be edited, or copied
 *  to draw elsewhere. A drawn picture is stored at once; OK closes the window. */
function Generator({
  entityId,
  withAngles,
  chapters,
  hasStyle,
  onCreated,
  onClose,
}: GeneratorProps) {
  const { t } = useI18n()
  const [choice, setChoice] = useState<Choice>('')
  const isLook = choice === 'other'
  const [look, setLook] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [prompt, setPrompt] = useState('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image'>('')
  const [error, setError] = useState('')
  const [made, setMade] = useState<ImageInfo | null>(null)
  const request = isLook
    ? { angle: '' as const, look_label: look, chapter_from_id: from, chapter_to_id: to }
    : { angle: choice as Angle | '', look_label: '', chapter_from_id: '', chapter_to_id: '' }
  // The server tells a look by its label or chapters: without them it would draw a main picture.
  const ready = !isLook || Boolean(look || from || to)

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
        if (!isLook) setChoice(written.angle)
      } else {
        setMade(await api.generateImage(entityId, { ...request, prompt }))
        onCreated()
      }
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack generator">
        <div className="row">
          <h2>{t('generate.title')}</h2>
          <span className="spacer" />
          <button className="btn ghost small" aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="muted small">{t(isLook ? 'generate.hint.look' : 'generate.hint.main')}</p>
        <select
          className="input"
          value={choice}
          onChange={(e) => setChoice(e.target.value as Choice)}
        >
          <option value="">{t(withAngles ? 'generate.angle.auto' : 'generate.main')}</option>
          {withAngles &&
            ANGLES.map((angle) => (
              <option key={angle} value={angle}>
                {t(`angle.${angle}`)}
              </option>
            ))}
          <option value="other">{t('generate.other')}</option>
        </select>
        {isLook && (
          <div className="row wrap">
            <input
              className="input grow"
              value={look}
              maxLength={200}
              placeholder={t('gallery.look.placeholder')}
              onChange={(e) => setLook(e.target.value)}
            />
            <ChapterSelect
              value={from}
              chapters={chapters}
              empty={t('gallery.from.start')}
              onChange={setFrom}
            />
            —
            <ChapterSelect
              value={to}
              chapters={chapters}
              empty={t('gallery.to.end')}
              onChange={setTo}
            />
          </div>
        )}
        <div className="row">
          <h4>{t('generate.prompt.label')}</h4>
          <span className="spacer" />
          <button
            className="btn small"
            disabled={busy !== '' || !ready}
            onClick={() => run('prompt')}
          >
            <SparklesIcon />
            {busy === 'prompt' ? t('generate.prompt.busy') : t('generate.prompt')}
          </button>
          <button
            className="btn small"
            disabled={!prompt}
            onClick={() => navigator.clipboard.writeText(prompt)}
          >
            <CopyIcon />
            {t('generate.copy')}
          </button>
        </div>
        <textarea
          className="input prompt"
          rows={5}
          value={prompt}
          maxLength={4000}
          placeholder={t('generate.prompt.placeholder')}
          onChange={(e) => setPrompt(e.target.value)}
        />
        <div className="row wrap">
          <button
            className="btn primary"
            disabled={busy !== '' || !hasStyle || !prompt.trim() || !ready}
            onClick={() => run('image')}
          >
            {busy === 'image' ? t('generate.image.busy') : t('generate.image')}
          </button>
          {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
        </div>
        {error && <p className="error">{error}</p>}
        {made && (
          <div className="stack generated">
            <img src={made.url} alt="" />
            <div className="row">
              <span className="muted small">{t('generate.made')}</span>
              <span className="spacer" />
              <button className="btn primary" onClick={onClose}>
                OK
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function SparklesIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M10 2l1.9 5.6L17.5 9.5l-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z" />
      <path d="M18.5 13l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z" />
      <path d="M18 2l.6 1.9 1.9.6-1.9.6L18 7l-.6-1.9-1.9-.6 1.9-.6z" />
    </svg>
  )
}

function CopyIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}
