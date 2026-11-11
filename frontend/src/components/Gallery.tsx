import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  IMAGE_SIZES,
  type Angle,
  type ChapterBrief,
  type EntityKind,
  type ImageInfo,
  type ImageSize,
} from '../api'
import { errorText, useI18n } from '../i18n'
import FoldHead from './FoldHead'
import { CopyIcon, PencilIcon, PlusIcon, SparklesIcon, TrashIcon, UploadIcon } from './icons'
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
  const remove = async (image: ImageInfo) => {
    if (await ask(t('gallery.delete.confirm'))) api.deleteImage(image.id).then(load, fail)
  }
  // A card's references start folded so the description is in view; the project's
  // general gallery is the whole point of its page and stays open.
  const [open, setOpen] = useState(!entityId)
  // The references window: every base view and picture in context, drawn or put in there.
  const [dialog, setDialog] = useState(false)
  const closeDialog = useCallback(() => setDialog(false), [])

  return (
    <div className="stack">
      {/* On a card everything happens in one window: drawing, putting in, viewing; its
          button is the pencil, like the other sections of the card. */}
      {entityId ? (
        <FoldHead
          title={t('gallery.title')}
          open={open}
          onToggle={() => setOpen(!open)}
          note={images && <span className="faint small">{images.length}</span>}
        >
          <button
            className="btn primary nav-action"
            title={t('gallery.settings')}
            aria-label={t('gallery.settings')}
            onClick={() => setDialog(true)}
          >
            <PencilIcon />
          </button>
        </FoldHead>
      ) : (
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
      )}
      {error && <p className="error">{error}</p>}
      {entityId && dialog && (
        <ImageDialog
          projectId={projectId}
          entityId={entityId}
          bases={(images ?? []).filter((i) => i.is_main && i.current_style)}
          looks={(images ?? []).filter((i) => !i.is_main && (i.look_label || i.chapter_from_id))}
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

interface DialogProps {
  projectId: string
  entityId: string
  /** The card's base pictures in the current style: pictures in context are drawn from them. */
  bases: ImageInfo[]
  /** The card's pictures in context made earlier: their settings can be taken again. */
  looks?: ImageInfo[]
  withAngles: boolean
  chapters: ChapterBrief[]
  hasStyle: boolean
  /** A picture was drawn, put in or deleted: the gallery reloads. */
  onChanged: () => void
  onClose: () => void
}

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

/** A large thin plus for empty places: faint at rest, glowing gold under the pointer. */
function ThinPlus() {
  return (
    <svg viewBox="0 0 48 48" aria-hidden>
      <path d="M24 8v32M8 24h32" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
    </svg>
  )
}

/** A sample picked in the window; `id` once it is stored on the server. */
interface Sample {
  file: File
  url: string
  id?: string
}

/** The picture whole, centred on a canvas of the given width/height ratio; the margins are
 * the same picture blurred, so nothing in the picture itself changes. */
async function padTo(file: File, ratio: number): Promise<File> {
  const bitmap = await createImageBitmap(file)
  const { width, height } = bitmap
  const w = Math.max(width, Math.round(height * ratio))
  const h = Math.max(height, Math.round(width / ratio))
  if (w === width && h === height) return file
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  const cover = Math.max(w / width, h / height)
  ctx.filter = 'blur(24px) brightness(0.7)'
  ctx.drawImage(bitmap, (w - width * cover) / 2, (h - height * cover) / 2, width * cover, height * cover)
  ctx.filter = 'none'
  ctx.drawImage(bitmap, (w - width) / 2, (h - height) / 2)
  const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, 'image/png'))
  return blob ? new File([blob], file.name.replace(/\.\w+$/, '') + '.png', { type: 'image/png' }) : file
}

/** Pictures in the clipboard; throws when the browser does not let it be read. */
async function readClipboard(): Promise<File[]> {
  const files: File[] = []
  for (const item of await navigator.clipboard.read()) {
    const type = item.types.find((kind) => kind.startsWith('image/'))
    if (type) files.push(new File([await item.getType(type)], `pasted.${type.split('/')[1]}`, { type }))
  }
  return files
}

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
 * The card's references in one window. A base picture shows the face or figure; a
 * character's base pictures are slots of views, drawn as a set from one prompt or put in
 * one by one. A picture in context is drawn from the base ones. A filled slot or picture is
 * only looked at or deleted: nothing is drawn or put in over it. Every drawn or put in
 * picture is stored at once. A scene opens it too, for a card in that scene.
 */
export function ImageDialog({
  projectId,
  entityId,
  bases,
  looks = [],
  withAngles,
  chapters,
  hasStyle,
  onChanged,
  onClose,
}: DialogProps) {
  const { t } = useI18n()
  const [current, setCurrent] = useState<ImageInfo | null>(null)
  const [mode, setMode] = useState<Mode>('base')
  // Ticked views; only empty slots are drawn, so a filled one counts only once deleted.
  const [views, setViews] = useState<Angle[]>(SET_ORDER)
  const [look, setLook] = useState('')
  const [chapter, setChapter] = useState('')
  const [prompt, setPrompt] = useState('')
  const [size, setSize] = useState<ImageSize | ''>('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image' | 'upload' | 'delete'>('')
  const [progress, setProgress] = useState('')
  const [autoPrompt, setAutoPrompt] = useState(readAuto)
  const chooseAuto = (on: boolean) => {
    setAutoPrompt(on)
    saveAuto(on)
  }
  // The user's own samples, kept in the window until used: drawn from, or put in as they are.
  const [samples, setSamples] = useState<Sample[]>([])
  // Where a picture put in as it is goes: a view's slot, or a new picture in context.
  const [menuFor, setMenuFor] = useState<Angle | 'look' | ''>('')
  const slotPicker = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  // A sample clicked to see it large.
  const [peek, setPeek] = useState('')
  // In context: the earlier picture whose settings are loaded; '' is the new one.
  const [picked, setPicked] = useState('')
  const draft = useRef({ prompt: '', look: '', chapter: '' })
  // The view of a set being drawn right now: its slot shows a spinner.
  const [drawing, setDrawing] = useState<Angle | ''>('')
  const [error, setError] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  const isMain = mode === 'base'
  // A character's base pictures are a set of views drawn from one prompt.
  const asSet = isMain && withAngles
  // The views the next press draws: ticked and still empty.
  const wanted = SET_ORDER.filter((view) => views.includes(view) && !latest(bases, view))
  // Pictures in context are drawn from base ones, so they wait for the first.
  const contextLocked = bases.length === 0 && !current?.is_main
  // The big picture: the one just made or clicked; in a set, otherwise the first finished view.
  const pickedLook = looks.find((l) => l.id === picked) ?? null
  const firstView = asSet ? (SET_ORDER.map((v) => latest(bases, v)).find(Boolean) ?? null) : null
  const shown = current ?? firstView ?? (!isMain ? pickedLook : null)
  // A look belongs to one chapter: the range is stored with both ends on it.
  const request = isMain
    ? { angle: '' as const, look_label: '', chapter_from_id: '', chapter_to_id: '' }
    : { angle: '' as const, look_label: look.trim(), chapter_from_id: chapter, chapter_to_id: chapter }
  // The server tells a look by its label or chapter: without them it would draw a base picture.
  const ready = isMain ? !asSet || wanted.length > 0 : Boolean(look.trim() || chapter)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // The text model writes the prompt; null when it failed (the error is shown).
  const collect = async (reference_ids: string[] = []) => {
    try {
      const written = await api.imagePrompt(entityId, { ...request, view_free: asSet, reference_ids })
      setPrompt(written.prompt)
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

  // Samples go to the server once; their ids are passed to the image model as references.
  const storeSamples = async () => {
    const ids: string[] = []
    const next = [...samples]
    for (const [n, sample] of next.entries()) {
      if (!sample.id) {
        const [made] = await api.uploadImages(projectId, [sample.file], entityId)
        // A sample is not a base picture or a look: the card's pictures stay as they were.
        await api.updateImage(made.id, { is_main: false, angle: '', look_label: '' })
        next[n] = { ...sample, id: made.id }
      }
      ids.push(next[n].id!)
    }
    setSamples(next)
    return ids.slice(0, 3)
  }

  const draw = async () => {
    setError('')
    let reference_ids: string[] = []
    if (samples.length) {
      setBusy('upload')
      try {
        reference_ids = await storeSamples()
      } catch (e) {
        setError(errorText(t, e))
        return setBusy('')
      }
    }
    // Automatic prompt: written quietly right before drawing, nothing to check in between.
    let text = prompt
    if (autoPrompt) {
      setBusy('prompt')
      const written = await collect(reference_ids)
      if (!written) return setBusy('')
      text = written.prompt
    }
    setBusy('image')
    try {
      if (asSet) {
        const order = wanted
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
            reference_ids,
          })
          setCurrent(made)
          onChanged()
        }
        setProgress(t('generate.set.done', { n: order.length }))
      } else {
        const made = await api.generateImage(entityId, { ...request, prompt: text, size, reference_ids })
        setCurrent(made)
        onChanged()
      }
    } catch (e) {
      setProgress('')
      setError(errorText(t, e))
    }
    setDrawing('')
    setBusy('')
  }

  // A picture put in as it is: checked against the project style first (a picture in
  // another style is refused, not redrawn), then only padded to the chosen shape.
  const putIn = async (files: FileList | File[] | null, target: Angle | 'look') => {
    const file = [...(files ?? [])].find((f) => f.type.startsWith('image/'))
    setMenuFor('')
    if (slotPicker.current) slotPicker.current.value = ''
    if (!file) return
    setBusy('upload')
    setError('')
    try {
      const ratio = size ? size.split(':').map(Number) : null
      const ready = ratio ? await padTo(file, ratio[0] / ratio[1]) : file
      const verdict = await api.checkStyle(projectId, ready)
      if (!verdict.matches) {
        setError(t('gallery.style.mismatch', { reason: verdict.reason }))
        return setBusy('')
      }
      const [made] = await api.uploadImages(projectId, [ready], entityId)
      const saved = await api.updateImage(
        made.id,
        target === 'look'
          ? { ...request, is_main: false }
          : { is_main: true, angle: target, look_label: '' },
      )
      setPeek('')
      setCurrent(saved)
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  // Deleting is the only way to change a filled slot: the empty one can be drawn or filled
  // again, and a deleted view is ticked to be drawn.
  const remove = async (target: ImageInfo) => {
    if (!(await ask(t('gallery.delete.confirm')))) return
    setBusy('delete')
    setError('')
    try {
      await api.deleteImage(target.id)
      if (target.angle) setViews((had) => (had.includes(target.angle as Angle) ? had : [...had, target.angle as Angle]))
      if (current?.id === target.id) setCurrent(null)
      if (picked === target.id) pickLook('')
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  const pasteInto = async (target: Angle | 'look') => {
    try {
      const files = await readClipboard()
      if (files.length) putIn(files, target)
      else setError(t('gallery.paste.empty'))
    } catch {
      setError(t('gallery.paste.denied'))
    }
  }
  // The small menu of a slot's or the new picture's plus: from a file or from the clipboard.
  const insertMenu = (target: Angle | 'look') =>
    menuFor === target && (
      <div className="add-sample-menu insert-menu">
        <button className="btn ghost small" onClick={() => slotPicker.current?.click()}>
          <UploadIcon />
          {t('gallery.upload.file')}
        </button>
        <button className="btn ghost small" onClick={() => pasteInto(target)}>
          <CopyIcon />
          {t('gallery.paste')}
        </button>
        <span className="faint small">{t('gallery.insert.hint')}</span>
      </div>
    )

  const addSamples = (files: FileList | File[] | null) => {
    const list = [...(files ?? [])].filter((f) => f.type.startsWith('image/'))
    if (!list.length) return
    setSamples((had) => [...had, ...list.map((file) => ({ file, url: URL.createObjectURL(file) }))])
    setAdding(false)
    if (picker.current) picker.current.value = ''
  }
  const dropSample = (url: string) => {
    setSamples((had) => had.filter((s) => s.url !== url))
    if (peek === url) setPeek('')
  }

  // A picture copied elsewhere goes in like a file: Ctrl+V in the window or the "Paste" button.
  const canAdd = busy === ''
  useEffect(() => {
    if (!canAdd) return
    const onPaste = (e: ClipboardEvent) => {
      const files = [...(e.clipboardData?.files ?? [])].filter((f) => f.type.startsWith('image/'))
      if (!files.length) return
      e.preventDefault()
      addSamples(files)
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  })
  const pasteClipboard = async () => {
    try {
      const files = await readClipboard()
      if (files.length) addSamples(files)
      else setError(t('gallery.paste.empty'))
    } catch {
      setError(t('gallery.paste.denied'))
    }
  }

  // In context: an earlier picture's settings are taken into the form; "New" brings back
  // what was typed before.
  const pickLook = (id: string) => {
    if (id === picked) return
    if (!picked) draft.current = { prompt, look, chapter }
    const from = looks.find((l) => l.id === id)
    const next = from
      ? { prompt: from.prompt, look: from.look_label, chapter: from.chapter_from_id || from.chapter_to_id }
      : draft.current
    setPrompt(next.prompt)
    setLook(next.look)
    setChapter(next.chapter)
    setPicked(id)
    setCurrent(null)
  }

  const toggleView = (view: Angle) =>
    setViews((chosen) => (chosen.includes(view) ? chosen.filter((v) => v !== view) : [...chosen, view]))

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog generator image-dialog">
        <div className="row">
          <h2>{t('gallery.settings')}</h2>
          <span className="spacer" />
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="dialog-body">
          <div className="stack">
          <div className="picture-slot">
            {peek ? (
              <div className="stack slot-picture">
                <img src={peek} alt="" />
              </div>
            ) : shown ? (
              <div className="stack slot-picture">
                <a href={shown.url} target="_blank" rel="noreferrer">
                  <img src={shown.url} alt="" />
                </a>
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
              <input
                ref={slotPicker}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={(e) => menuFor && putIn(e.target.files, menuFor)}
              />
              {SET_ORDER.map((view) => {
                const made = latest(bases, view)
                const ticked = !made && views.includes(view)
                return (
                  <div
                    key={view}
                    className={`view-slot ${made ? 'filled' : ''} ${ticked ? 'ticked' : ''} ${
                      made && shown?.id === made.id ? 'shown' : ''
                    }`}
                  >
                    <div className="view-slot-box">
                    <button
                      className="view-slot-face"
                      disabled={!made}
                      title={made ? t('generate.slot.show') : ''}
                      onClick={() => {
                        setPeek('')
                        if (made) setCurrent(made)
                      }}
                    >
                      {made && <img src={made.url} alt="" loading="lazy" />}
                      {drawing === view && <span className="view-slot-busy" aria-hidden />}
                    </button>
                    {made ? (
                      <button
                        className="btn ghost small icon danger slot-drop"
                        disabled={busy !== ''}
                        title={t('app.delete')}
                        aria-label={`${t('app.delete')}: ${t(`angle.${view}`)}`}
                        onClick={() => remove(made)}
                      >
                        <TrashIcon />
                      </button>
                    ) : (
                      <button
                        className="slot-plus"
                        disabled={busy !== ''}
                        title={t('gallery.insert')}
                        aria-label={`${t('gallery.insert')}: ${t(`angle.${view}`)}`}
                        onClick={() => setMenuFor(menuFor === view ? '' : view)}
                      >
                        <ThinPlus />
                      </button>
                    )}
                    </div>
                    {insertMenu(view)}
                    <label className="view-slot-label small">
                      {/* A filled view keeps the box's place, so the labels stay in line. */}
                      <input
                        type="checkbox"
                        className={made ? 'hidden-check' : ''}
                        checked={ticked}
                        disabled={busy !== '' || !!made}
                        title={t('generate.slot.draw')}
                        onChange={() => toggleView(view)}
                      />
                      {t(`angle.${view}`)}
                    </label>
                  </div>
                )
              })}
            </div>
          )}
          {/* In context: the new picture first, then every earlier one; a click takes its settings. */}
          {!isMain && (
            <div className="look-strip">
              <input
                ref={slotPicker}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={(e) => putIn(e.target.files, 'look')}
              />
              <div className="look-new-wrap">
                <button
                  className={`look-tile look-new ${picked === '' ? 'shown' : ''}`}
                  disabled={busy !== ''}
                  title={t('gallery.insert.look')}
                  onClick={() => {
                    setPeek('')
                    pickLook('')
                    setMenuFor(menuFor === 'look' ? '' : 'look')
                  }}
                >
                  <span className="look-new-icon" aria-hidden>
                    <ThinPlus />
                  </span>
                  <span className="small">{t('gallery.look.new')}</span>
                </button>
                {insertMenu('look')}
              </div>
              {looks.map((item) => (
                <div key={item.id} className="look-tile-wrap">
                  <button
                    className={`look-tile ${picked === item.id ? 'shown' : ''}`}
                    disabled={busy !== ''}
                    title={[item.look_label, chapters.find((c) => c.id === item.chapter_from_id)?.title]
                      .filter(Boolean)
                      .join(' · ')}
                    onClick={() => {
                      setPeek('')
                      pickLook(item.id)
                    }}
                  >
                    <img src={item.url} alt="" loading="lazy" />
                  </button>
                  <button
                    className="btn ghost small icon danger slot-drop"
                    disabled={busy !== ''}
                    title={t('app.delete')}
                    aria-label={t('app.delete')}
                    onClick={() => remove(item)}
                  >
                    <TrashIcon />
                  </button>
                </div>
              ))}
            </div>
          )}
          {/* What the picture in view was drawn from; a picture put in has no prompt. */}
          {!peek && (shown?.prompt || pickedLook?.prompt) && (
            <details key={(shown ?? pickedLook)!.id} className="shown-prompt">
              <summary className="muted small">{t('gallery.prompt.show')}</summary>
              <p className="small prompt-last">{(shown ?? pickedLook)!.prompt}</p>
            </details>
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
                  onClick={() => {
                    setMode(option)
                    setMenuFor('')
                    setPeek('')
                    // A picture just made in the other mode is not this mode's picture.
                    setCurrent(null)
                  }}
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
                {asSet && <p className="muted small">{t('generate.views.hint')}</p>}
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
            {/* The user's own samples: shown small, drawn from or put in as they are. */}
              <div className="stack field samples">
                <input
                  ref={picker}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  multiple
                  hidden
                  onChange={(e) => addSamples(e.target.files)}
                />
                <div className="row">
                  <span className="small muted">
                    {t('gallery.samples')}
                    {samples.length > 0 && ` · ${samples.length}`}
                  </span>
                  <span className="spacer" />
                  <div className="add-sample">
                    <button
                      className="btn ghost small"
                      disabled={!canAdd}
                      aria-expanded={adding}
                      onClick={() => setAdding(!adding)}
                    >
                      <PlusIcon />
                      {t('gallery.upload.reference')}
                    </button>
                    {adding && (
                      <div className="add-sample-menu">
                        <button className="btn ghost small" onClick={() => picker.current?.click()}>
                          <UploadIcon />
                          {t('gallery.upload.file')}
                        </button>
                        <button className="btn ghost small" onClick={pasteClipboard}>
                          <CopyIcon />
                          {t('gallery.paste')}
                        </button>
                        <span className="faint small">{t('gallery.paste.ctrlv')}</span>
                      </div>
                    )}
                  </div>
                </div>
                {samples.length > 0 && (
                  <>
                    <p className="faint small">{t('gallery.samples.hint')}</p>
                    <div className="sample-strip">
                      {samples.map((sample) => (
                        <div key={sample.url} className={`sample ${peek === sample.url ? 'shown' : ''}`}>
                          <button
                            className="sample-face"
                            title={t('generate.slot.show')}
                            onClick={() => setPeek(peek === sample.url ? '' : sample.url)}
                          >
                            <img src={sample.url} alt="" />
                          </button>
                          <button
                            className="sample-drop"
                            title={t('gallery.sample.remove')}
                            aria-label={t('gallery.sample.remove')}
                            disabled={busy !== ''}
                            onClick={() => dropSample(sample.url)}
                          >
                            ✕
                          </button>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            <div className="stack field">
              <div className="row">
                <span className="small muted">{t('generate.prompt.label')}</span>
                {/* Auto: pressing "Generate" writes the prompt and draws at once. Unticked: the
                    prompt is written first and shown for editing, drawing is the next press. */}
                <label className="small auto-prompt" title={t('generate.prompt.auto.hint')}>
                  <input
                    type="checkbox"
                    checked={autoPrompt}
                    disabled={busy !== ''}
                    onChange={(e) => chooseAuto(e.target.checked)}
                  />
                  {t('generate.prompt.auto')}
                </label>
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
                prompt && (
                  <details>
                    <summary className="muted small">{t('generate.prompt.last')}</summary>
                    <p className="small prompt-last">{prompt}</p>
                  </details>
                )
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
            {/* At the bottom of the column, in one row with the last row of slots. */}
            <div className="stack generate-row">
            <div className="row wrap">
          <button
            className="btn primary generate-big"
            disabled={busy !== '' || !hasStyle || (!autoPrompt && !prompt.trim()) || !ready}
            onClick={draw}
          >
            <SparklesIcon />
            {busy === 'upload'
              ? t('gallery.uploading')
              : busy === 'prompt' && autoPrompt
              ? t('generate.prompt.busy')
              : busy === 'image'
              ? t('generate.image.busy')
              : asSet
                ? t('generate.set', { n: wanted.length })
                : t('generate.image')}
          </button>
        </div>
        {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
        {progress && <p className="muted small">{progress}</p>}
            </div>
          </div>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
