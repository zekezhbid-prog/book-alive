import { useCallback, useEffect, useRef, useState } from 'react'
import {
  api,
  IMAGE_SIZES,
  type Angle,
  isAngle,
  type ChapterBrief,
  type EntityKind,
  type ImageInfo,
  type ImageSize,
  type PlaceView,
  type Variant,
} from '../api'
import { errorText, useI18n } from '../i18n'
import { CheckIcon, CopyIcon, PencilIcon, PlusIcon, SparklesIcon, TrashIcon, UploadIcon } from './icons'
import { ask } from '../dialogs'
import { MicButton } from './MicButton'
import { zoomLink } from './Lightbox'
import { AutoTextarea } from './AutoTextarea'
import { TwoLangPrompt } from './TwoLangPrompt'
import { useTwoLang } from '../twoLang'

interface Props {
  projectId: string
  /** A card's pictures; without it, the project's general references. */
  entityId?: string
  /** Main pictures of a character are marked with a view (face, full length). */
  kind?: EntityKind
  chapters: ChapterBrief[]
  /** Whether a project style is chosen: pictures cannot be generated without one. */
  hasStyle: boolean
  /** After any picture was added or removed: the card's tile shows one of them. */
  onChanged?: () => void
}

/** Reference pictures: uploaded by the user or generated here, labelled with their style. */
export default function Gallery({ projectId, entityId, kind, chapters, hasStyle, onChanged }: Props) {
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
          <ImageDialog
            projectId={projectId}
            entityId={entityId}
            bases={(images ?? []).filter((i) => i.is_main && i.current_style)}
            looks={(images ?? []).filter((i) => !i.is_main && (i.look_label || i.chapter_from_id))}
            withAngles={kind === 'character'}
            chapters={chapters}
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
const FULL_ORDER: Angle[] = [
  'face_front',
  'face_three_quarter',
  'face_profile',
  'full_front',
  'full_side',
  'full_back',
]
// A thing-like look (a seed, a stone) needs only two views (owner's notes 25.11).
const OBJECT_ORDER: Angle[] = ['face_front', 'full_front']
// An animal or a bird is drawn whole, a few views without face portraits (owner's notes 26.11).
const CREATURE_ORDER: Angle[] = ['full_front', 'full_three_quarter', 'full_side', 'full_back']
const orderOf = (shape: Variant['shape'] | undefined): Angle[] =>
  shape === 'object' ? OBJECT_ORDER : shape === 'creature' ? CREATURE_ORDER : FULL_ORDER

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
  /** The AI found someone else on it than on the other samples. */
  odd?: boolean
}

/** At most this many samples are looked at together before a set is drawn. */
const MAX_SAMPLES = 6

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
function latest(bases: ImageInfo[], view: string) {
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
  bases: allBases,
  looks = [],
  withAngles,
  chapters,
  hasStyle,
  onChanged,
  onClose,
}: DialogProps) {
  const { t } = useI18n()
  const [current, setCurrent] = useState<ImageInfo | null>(null)
  // Pictures in context now live in the "Pictures" section: the window draws base ones only.
  const [mode] = useState<Mode>('base')
  // The view the next press draws, leafed through in the step window (owner's notes 26.11);
  // '' is the first free picture of a place or the first empty view of a set.
  const [nextView, setNextView] = useState('')
  // Views drawn in this window, `look:view`: the gallery may not have reloaded them yet.
  const [drawnHere, setDrawnHere] = useState<string[]>([])
  // A finished look whose face starts a new look (owner's notes 26.11).
  const [refLook, setRefLook] = useState('')
  const [look, setLook] = useState('')
  // A place or object: the user's wish for the next picture ("a view from above").
  const [note, setNote] = useState('')
  const [chapter, setChapter] = useState('')
  const [prompt, setPrompt] = useState('')
  // Square unless the user picks another shape (owner's notes 26.11).
  const [size, setSize] = useState<ImageSize>('1:1')
  const [busy, setBusy] = useState<'' | 'prompt' | 'image' | 'upload' | 'delete' | 'sort' | 'variants'>('')
  // The picture just drawn waits for "OK, next" or "Redraw": the references it was drawn with.
  const [pending, setPending] = useState<{ references: string[] } | null>(null)
  // That picture shown large in its own little window.
  const [faceCheck, setFaceCheck] = useState<ImageInfo | null>(null)
  const [progress, setProgress] = useState('')
  const [autoPrompt, setAutoPrompt] = useState(readAuto)
  const chooseAuto = (on: boolean) => {
    setAutoPrompt(on)
    saveAuto(on)
  }
  // The user's own samples, kept in the window until used: drawn from, or put in as they are.
  const [samples, setSamples] = useState<Sample[]>([])
  // The new picture in context, when its plus menu is open.
  const [menuFor, setMenuFor] = useState<'look' | ''>('')
  const slotPicker = useRef<HTMLInputElement>(null)
  const [adding, setAdding] = useState(false)
  // A sample clicked to see it large.
  const [peek, setPeek] = useState('')
  // In context: the earlier picture whose settings are loaded; '' is the new one.
  const [picked, setPicked] = useState('')
  const draft = useRef({ prompt: '', look: '', chapter: '' })
  const [error, setError] = useState('')
  const picker = useRef<HTMLInputElement>(null)
  // What the user wants changed in the redraw of the face, typed or spoken.
  const [remark, setRemark] = useState('')
  // The small "what to change" window over the face, opened by its pencil.
  const [remarkOpen, setRemarkOpen] = useState(false)
  // A filled slot or picture clicked: its prompt and references are shown instead of the form.
  const [inspected, setInspected] = useState<ImageInfo | null>(null)
  // A character's outward looks, each a set of its own; the one whose slots are shown.
  const [variants, setVariants] = useState<Variant[]>([])
  const [variantKey, setVariantKey] = useState('')
  // Looks the model found, waiting for "Save" or "Cancel".
  const [found, setFound] = useState<Variant[] | null>(null)
  // The looks were searched for once: the first drawing searches only while this is false.
  const [looksChecked, setLooksChecked] = useState(true)
  // A place or object: its views, proposed by the model after its first picture.
  const [placeViews, setPlaceViews] = useState<PlaceView[]>([])
  useEffect(() => {
    if (!withAngles) {
      api.views(entityId).then(setPlaceViews, (e) => setError(errorText(t, e)))
      return
    }
    api.variants(entityId).then(({ variants: list, checked }) => {
      setVariants(list)
      setLooksChecked(checked)
      setVariantKey((now) => now || list[0]?.key || '')
    }, (e) => setError(errorText(t, e)))
  }, [entityId, withAngles, t])
  const viewLabel = (view: string) =>
    !view
      ? t('generate.step.free')
      : (placeViews.find((v) => v.key === view)?.label ?? (isAngle(view) ? t(`angle.${view}`) : view))
  const variant = variants.find((v) => v.key === variantKey) ?? null
  const SET_ORDER = orderOf(variant?.shape)
  const bases = allBases.filter((b) => (b.variant || '') === (variant?.key ?? ''))
  const has = (view: string, look = variant?.key ?? '') =>
    Boolean(latest(allBases.filter((b) => (b.variant || '') === look), view)) ||
    drawnHere.includes(`${look}:${view}`)
  // The views still without a picture, in their order: what "OK, next" offers.
  const openViews = (except = '') =>
    (withAngles ? SET_ORDER : placeViews.map((v) => v.key)).filter((v) => v !== except && !has(v))
  // The prompt in English and in the interface language, wherever it can be edited.
  const twoLang = useTwoLang(entityId, prompt, setPrompt, !autoPrompt || !!faceCheck, setError)

  const isMain = mode === 'base'
  // A filled base slot or tile in view: only looked at or deleted, never drawn over.
  const viewing = isMain && !peek ? inspected : null
  // A character's base pictures are a set of views drawn from one prompt.
  const asSet = isMain && withAngles
  // A set is started from the user's samples only while it is empty: once there is a view,
  // the rest are drawn from it.
  const samplesAllowed = !(asSet && bases.length > 0)
  // The view the next press of "Generate" draws: the chosen one while it is still empty,
  // otherwise the first empty one. A place draws a free picture first and when all its
  // views are there.
  const open = openViews()
  const upNext = open.includes(nextView) ? nextView : asSet || bases.length > 0 ? (open[0] ?? '') : ''
  // Finished looks of the character whose face can start this one, while it is empty.
  const refLooks =
    asSet && bases.length === 0 && variant?.shape !== 'object'
      ? variants.filter((v) => v.key !== variant?.key && (v.shape ?? 'human') === (variant?.shape ?? 'human') && has(orderOf(v.shape)[0], v.key))
      : []
  // The big picture: the one just made or clicked; in a set, otherwise the first finished view.
  const pickedLook = looks.find((l) => l.id === picked) ?? null
  // A place or object opens on the "new picture" tile: nothing large until one is clicked.
  const firstView = asSet ? (SET_ORDER.map((v) => latest(bases, v)).find(Boolean) ?? null) : null
  const shown = current ?? firstView ?? (!isMain ? pickedLook : null)
  // A look belongs to one chapter: the range is stored with both ends on it.
  const request = isMain
    ? { angle: '' as const, look_label: '', chapter_from_id: '', chapter_to_id: '', variant: variant?.key ?? '' }
    : { angle: '' as const, look_label: look.trim(), chapter_from_id: chapter, chapter_to_id: chapter }
  // The server tells a look by its label or chapter: without them it would draw a base picture.
  const ready = isMain ? !asSet || upNext !== '' : Boolean(look.trim() || chapter)

  useEffect(() => {
    // While the face waits for an answer, Escape does not throw the window away.
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !faceCheck && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, faceCheck])

  // The text model writes the prompt; null when it failed (the error is shown).
  const collect = async (reference_ids: string[] = [], lookKey = variant?.key ?? '') => {
    try {
      const written = await api.imagePrompt(entityId, {
        ...request,
        ...(isMain ? { variant: lookKey } : {}),
        // One prompt serves every view of a set or a place: the view is put in front of it.
        view_free: isMain,
        reference_ids,
        note: withAngles ? '' : note.trim(),
      })
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
  const storeSamples = async (list: Sample[]) => {
    const ids: string[] = []
    for (const sample of list) {
      let id = sample.id
      if (!id) {
        const [made] = await api.uploadImages(projectId, [sample.file], entityId)
        // A sample is not a base picture or a look: the card's pictures stay as they were.
        await api.updateImage(made.id, { is_main: false, angle: '', look_label: '' })
        id = made.id
      }
      ids.push(id)
    }
    setSamples((had) => had.map((s) => ({ ...s, id: s.id ?? ids[list.indexOf(s)] })))
    return ids
  }

  // The views of a set, one after another; each new one is drawn from those already there.
  const drawViews = async (order: string[], text: string, reference_ids: string[], lookKey = variant?.key ?? '') => {
    let last: ImageInfo | null = null
    for (const [n, view] of order.entries()) {
      setProgress(t('generate.set.progress', { done: n + 1, total: order.length, view: viewLabel(view) }))
      const made = await api.generateImage(entityId, {
        ...request,
        ...(isMain ? { variant: lookKey } : {}),
        angle: view,
        prompt: text,
        size,
        add_view: true,
        reference_ids,
      })
      setCurrent(made)
      onChanged()
      last = made
    }
    return last
  }

  // Before a set is drawn from samples, the AI looks at all of them: someone else among them
  // stops everything; a clean picture in the project style goes into its empty slot as it is
  // (padded to the chosen shape), the others guide the drawing. Returns the views put in and
  // the ids of the samples left as references, or null when it stopped.
  const sortSamples = async () => {
    setBusy('sort')
    const verdict = await api.sortReferences(entityId, samples.map((s) => s.file))
    if (!verdict.same_person) {
      setSamples((had) => had.map((s, n) => ({ ...s, odd: verdict.others.includes(n) })))
      const numbers = verdict.others.map((n) => n + 1).join(', ')
      setError(t('gallery.samples.others', { numbers, reason: verdict.reason }))
      return null
    }
    setBusy('upload')
    const ratio = size ? size.split(':').map(Number) : null
    const filled: Angle[] = []
    for (const { index, angle } of verdict.placed) {
      const file = samples[index].file
      const ready = ratio ? await padTo(file, ratio[0] / ratio[1]) : file
      const [made] = await api.uploadImages(projectId, [ready], entityId)
      const saved = await api.updateImage(made.id, { is_main: true, angle, variant: variant?.key ?? '', look_label: '' })
      setCurrent(saved)
      filled.push(angle)
    }
    const rest = samples.filter((_, n) => !verdict.placed.some((p) => p.index === n))
    const references = await storeSamples(rest.slice(0, 3))
    setSamples(rest.map((s, n) => ({ ...s, id: references[n] ?? s.id })))
    if (filled.length) {
      setProgress(t('gallery.samples.placed', { views: filled.map((v) => t(`angle.${v}`)).join(', ') }))
      onChanged()
    }
    return { filled, references: references.slice(0, 3) }
  }

  // One picture is drawn and shown large: the user likes it ("OK, next") or redraws it.
  // Nothing is drawn in a batch (owner's notes 26.11).
  const drawStep = async (view: string, text: string, references: string[], lookKey = variant?.key ?? '') => {
    const made = await drawViews([view], text, references, lookKey)
    if (!made) return
    setDrawnHere((had) => [...had, `${lookKey}:${view}`])
    setPending({ references })
    setFaceCheck(made)
    setProgress('')
    setNextView(openViews(view)[0] ?? '')
    // A place gets its views after the first picture, so "OK, next" has something to offer.
    if (!withAngles && !placeViews.length) {
      setBusy('variants')
      try {
        const proposed = await api.findViews(entityId)
        const saved = await api.saveViews(entityId, proposed)
        setPlaceViews(saved)
        setNextView(saved.find((v) => v.key !== view)?.key ?? '')
      } catch (e) {
        setError(errorText(t, e))
      }
    }
  }

  const draw = async () => {
    setError('')
    setProgress('')
    let looksNow = variants
    // The first drawing of a character asks once whether it has several outward looks
    // (owner's notes 26.11): with two or more, the user picks the one to draw first.
    if (asSet && !looksChecked && !variants.length) {
      setBusy('variants')
      try {
        const list = await api.findVariants(entityId)
        setLooksChecked(true)
        if (list.length > 1) {
          setFound(list)
          setProgress(t('variants.auto'))
          return setBusy('')
        }
        // One look that is not a person (an animal, a thing) is kept: it has its own views.
        if (list.length === 1 && list[0].shape !== 'human') {
          looksNow = await api.saveVariants(entityId, list)
          setVariants(looksNow)
          setVariantKey(looksNow[0]?.key ?? '')
          onChanged()
        }
      } catch (e) {
        setError(errorText(t, e))
        return setBusy('')
      }
    }
    const lookNow = looksNow.find((v) => v.key === variantKey) ?? looksNow[0] ?? null
    let reference_ids: string[] = []
    let view = upNext
    if (asSet && looksNow !== variants) view = orderOf(lookNow?.shape)[0]
    const useSamples = samplesAllowed && samples.length > 0
    try {
      if (useSamples && asSet) {
        const sorted = await sortSamples()
        if (!sorted) return setBusy('')
        reference_ids = sorted.references
        if (sorted.filled.includes(view as Angle)) {
          view = orderOf(lookNow?.shape).find((v) => !sorted.filled.includes(v) && !has(v)) ?? ''
          if (!view) return setBusy('')
        }
      } else if (useSamples) {
        setBusy('upload')
        reference_ids = await storeSamples(samples.slice(0, 3))
      }
    } catch (e) {
      setError(errorText(t, e))
      return setBusy('')
    }
    if (asSet && !view) return setBusy('')
    // A new look may start from the face of a finished one, chosen by the user.
    const from = refLooks.find((v) => v.key === refLook)
    const fromImage = from && latest(allBases.filter((b) => b.variant === from.key), orderOf(from.shape)[0])
    if (fromImage) reference_ids = [fromImage.id, ...reference_ids].slice(0, 3)
    // Automatic prompt: written quietly right before drawing, nothing to check in between.
    // By hand: the English half takes in the last edit of the translation first.
    let text = autoPrompt ? prompt : await twoLang.flush()
    if (autoPrompt) {
      setBusy('prompt')
      const written = await collect(reference_ids, lookNow?.key ?? '')
      if (!written) return setBusy('')
      text = written.prompt
    }
    setBusy('image')
    try {
      await drawStep(view, text, reference_ids, lookNow?.key ?? '')
    } catch (e) {
      setProgress('')
      setError(errorText(t, e))
    }
    setBusy('')
  }

  // The picture is liked: the next view, as chosen in the window, is drawn with the prompt
  // as it is now. With no view left, the window closes or moves on to the next look.
  const goOn = async () => {
    if (!pending || !faceCheck) return
    const following = openViews(faceCheck.angle)
    const view = following.includes(nextView) ? nextView : (following[0] ?? '')
    if (!view) {
      setFaceCheck(null)
      setPending(null)
      setRemark('')
      const after = asSet ? nextLook() : null
      if (after) {
        setVariantKey(after.key)
        setRefLook('')
        setCurrent(null)
        setInspected(null)
        setProgress(t('generate.step.look_next', { look: after.label }))
      } else setProgress(t('generate.set.done', { n: (withAngles ? SET_ORDER.length : placeViews.length + 1) - openViews().length }))
      return
    }
    const text = await twoLang.flush()
    setFaceCheck(null)
    setRemark('')
    setError('')
    setBusy('image')
    try {
      await drawStep(view, text, pending.references)
    } catch (e) {
      setPending(null)
      setProgress('')
      setError(errorText(t, e))
    }
    setBusy('')
  }

  // Another look of the character that still has empty views: offered after the last view.
  const nextLook = () =>
    variants.find((v) => v.key !== variant?.key && orderOf(v.shape).some((view) => !has(view, v.key))) ?? null

  // The picture is not liked: the user's own press removes it and draws it again, with the
  // prompt as it is now (it may have been changed in the meantime).
  const redrawFace = async () => {
    if (!pending) return
    setError('')
    setRemarkOpen(false)
    let text = await twoLang.flush()
    // The remark goes into the English prompt first; on a failure the picture stays in view.
    if (remark.trim()) {
      setBusy('prompt')
      try {
        text = (await api.refineImagePrompt(entityId, text, remark.trim())).text
        setPrompt(text)
        setRemark('')
      } catch (e) {
        setError(errorText(t, e))
        return setBusy('')
      }
    }
    const face = faceCheck
    const view = face ? face.angle : ''
    setFaceCheck(null)
    setBusy('image')
    try {
      if (face) await api.deleteImage(face.id)
      setCurrent(null)
      onChanged()
      const made = await drawViews([view], text, pending.references)
      setFaceCheck(made)
      setProgress('')
    } catch (e) {
      setPending(null)
      setProgress('')
      setError(errorText(t, e))
    }
    setBusy('')
  }

  // Neither "apply" nor "redraw": the set stops and the face is not kept. Pressing "Cancel"
  // is the user's own word against it (decisions.md 25.11): the slot was empty before, so it
  // is empty again.
  const cancelFace = async () => {
    const face = faceCheck
    setFaceCheck(null)
    if (face) setDrawnHere((had) => had.filter((k) => k !== `${face.variant || ''}:${face.angle}`))
    setPending(null)
    setRemark('')
    setRemarkOpen(false)
    setProgress('')
    if (!face) return
    setBusy('delete')
    try {
      await api.deleteImage(face.id)
      if (current?.id === face.id) setCurrent(null)
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }

  // A new picture in context put in as it is: checked against the project style first (a picture in
  // another style is refused, not redrawn), then only padded to the chosen shape.
  const putIn = async (files: FileList | File[] | null) => {
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
      const saved = await api.updateImage(made.id, { ...request, is_main: false })
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
      setDrawnHere((had) => had.filter((k) => k !== `${target.variant || ''}:${target.angle}`))
      if (current?.id === target.id) setCurrent(null)
      // The freed slot or tile is empty again: the form to draw it comes back.
      if (inspected?.id === target.id) setInspected(null)
      if (picked === target.id) pickLook('')
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  const pasteInto = async () => {
    try {
      const files = await readClipboard()
      if (files.length) putIn(files)
      else setError(t('gallery.paste.empty'))
    } catch {
      setError(t('gallery.paste.denied'))
    }
  }
  // Kept looks replace the old list; pictures drawn before any look go to the first one.
  const keepLooks = async () => {
    if (!found) return
    setBusy('variants')
    try {
      const saved = await api.saveVariants(entityId, found)
      setVariants(saved)
      setVariantKey(saved[0]?.key ?? '')
      setFound(null)
      if (saved.length > 1) setProgress(t('variants.kept'))
      setCurrent(null)
      setInspected(null)
      onChanged()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  // The small menu of the new picture's plus: from a file or from the clipboard.
  const insertMenu = (target: 'look') =>
    menuFor === target && (
      <div className="add-sample-menu insert-menu">
        <button className="btn ghost small" onClick={() => slotPicker.current?.click()}>
          <UploadIcon />
          {t('gallery.upload.file')}
        </button>
        <button className="btn ghost small" onClick={pasteInto}>
          <CopyIcon />
          {t('gallery.paste')}
        </button>
        <span className="faint small">{t('gallery.insert.hint')}</span>
      </div>
    )

  const addSamples = (files: FileList | File[] | null) => {
    const list = [...(files ?? [])].filter((f) => f.type.startsWith('image/'))
    if (!list.length) return
    setSamples((had) =>
      [...had.map((s) => ({ ...s, odd: false })), ...list.map((file) => ({ file, url: URL.createObjectURL(file) }))].slice(
        0,
        MAX_SAMPLES,
      ),
    )
    setAdding(false)
    if (picker.current) picker.current.value = ''
  }
  const dropSample = (url: string) => {
    setSamples((had) => had.filter((s) => s.url !== url).map((s) => ({ ...s, odd: false })))
    if (peek === url) setPeek('')
  }

  // A picture copied elsewhere goes in like a file: Ctrl+V in the window or the "Paste" button.
  const canAdd = busy === '' && samplesAllowed && samples.length < MAX_SAMPLES
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

  // The step window: the views "OK, next" can draw, the one chosen, and the next look once
  // this one is complete.
  const stepChoices = faceCheck ? openViews(faceCheck.angle) : []
  const stepNext = stepChoices.includes(nextView) ? nextView : (stepChoices[0] ?? '')
  const stepLook = faceCheck && !stepNext && asSet ? nextLook() : null
  const leaf = (by: number) => {
    const at = Math.max(0, stepChoices.indexOf(stepNext))
    setNextView(stepChoices[(at + by + stepChoices.length) % stepChoices.length])
  }

  // The full explanation of the form: in the empty picture, or on hover over "Generate".
  const longHint = asSet
    ? `${t('generate.hint.base_set')} ${t('generate.views.hint')}`
    : t(withAngles ? 'generate.hint.main' : 'generate.hint.place')

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
                <a {...zoomLink(bases.some((b) => b.id === shown.id) ? bases.map((b) => b.url) : [shown.url], Math.max(0, bases.findIndex((b) => b.id === shown.id)))}>
                  <img src={shown.url} alt="" />
                </a>
              </div>
            ) : (
              <span className="stack slot-hint">
                <span className="faint small">{busy === 'image' ? t('generate.image.busy') : t('generate.slot')}</span>
                {busy !== 'image' && <span className="muted small">{longHint}</span>}
              </span>
            )}
          </div>
          {/* A character's outward looks: each one is a set of its own (owner's notes 25.11). */}
          {asSet && (
            <div className="stack variant-bar">
              <div className="row wrap">
                {variants.map((v) => (
                  <button
                    key={v.key}
                    className={`chip ${v.key === variantKey ? 'active' : ''}`}
                    disabled={busy !== '' || !!pending}
                    title={v.description}
                    onClick={() => {
                      setVariantKey(v.key)
                      setCurrent(null)
                      setInspected(null)
                      setPeek('')
                    }}
                  >
                    {v.label}
                  </button>
                ))}
                {/* Looks are found by the first "Generate" only (owner's notes 26.11). */}
                {busy === 'variants' && <span className="muted small">{t('variants.finding')}</span>}
              </div>
              {variant && <p className="faint small">{variant.description}</p>}
              {refLooks.length > 0 && (
                <div className="row wrap" title={t('variants.ref.hint')}>
                  <span className="small muted">{t('variants.ref')}</span>
                  {refLooks.map((v) => (
                    <button
                      key={v.key}
                      className={`chip ${refLook === v.key ? 'active' : ''}`}
                      disabled={busy !== ''}
                      onClick={() => setRefLook(refLook === v.key ? '' : v.key)}
                    >
                      {v.label}
                    </button>
                  ))}
                </div>
              )}
              {found && (
                <div className="stack variant-offer">
                  <span className="small muted">{t('variants.found', { n: found.length })}</span>
                  {found.map((v) => (
                    <div key={v.key} className="row">
                      <span className="grow small">
                        <b>{v.label}</b> · {t(`variants.shape.${v.shape}`)} — {v.description}
                      </span>
                      <button
                        className="btn ghost small icon"
                        title={t('app.delete')}
                        aria-label={t('app.delete')}
                        onClick={() => setFound(found.filter((x) => x.key !== v.key))}
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                  <div className="row">
                    <button className="btn primary small" disabled={busy !== ''} onClick={keepLooks}>
                      <CheckIcon />
                      {t('generate.face.apply')}
                    </button>
                    <button className="btn ghost small" onClick={() => setFound(null)}>
                      {t('app.cancel')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
          {/* The views already drawn; empty ones are not shown: which view comes next is
              chosen when it is drawn (owner's notes 26.11). */}
          {asSet && bases.some((b) => b.angle) && (
            <div className="view-slots">
              {SET_ORDER.map((view) => latest(bases, view))
                .filter((made): made is ImageInfo => made !== null)
                .map((made) => (
                  <div key={made.id} className={`view-slot filled ${shown?.id === made.id ? 'shown' : ''}`}>
                    <div className="view-slot-box">
                      <button
                        className="view-slot-face"
                        disabled={busy !== '' || !!pending}
                        title={t('generate.slot.show')}
                        onClick={() => {
                          setPeek('')
                          setCurrent(made)
                          setInspected(made)
                        }}
                      >
                        <img src={made.url} alt="" loading="lazy" />
                      </button>
                    </div>
                    <span className="view-slot-label small">{t(`angle.${made.angle as Angle}`)}</span>
                  </div>
                ))}
            </div>
          )}
          {/* A place or object: every base picture in a row, the one in view lit; each press
              of "Generate" adds one more here. */}
          {isMain && !withAngles && (
            <div className="look-strip base-strip">
              {/* No limit here: the first tile always starts a new picture from scratch. */}
              <div className="look-new-wrap">
                <button
                  className={`look-tile look-new ${!inspected ? 'shown' : ''}`}
                  disabled={busy !== ''}
                  title={t('generate.bases.new')}
                  aria-label={t('generate.bases.new')}
                  onClick={() => {
                    setPeek('')
                    setCurrent(null)
                    setInspected(null)
                  }}
                >
                  <span className="look-new-icon" aria-hidden>
                    <ThinPlus />
                  </span>
                </button>
              </div>
              {[...bases].reverse().map((item) => (
                <div key={item.id} className="look-tile-wrap">
                  <button
                    className={`look-tile ${inspected?.id === item.id ? 'shown' : ''}`}
                    disabled={busy !== ''}
                    title={item.angle ? viewLabel(item.angle) : t('generate.slot.show')}
                    onClick={() => {
                      setPeek('')
                      setCurrent(item)
                      setInspected(item)
                    }}
                  >
                    <img src={item.url} alt="" loading="lazy" />
                  </button>
                </div>
              ))}
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
                onChange={(e) => putIn(e.target.files)}
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
                    className="btn ghost small icon gold slot-drop"
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
          {!peek && !viewing && (shown?.prompt || pickedLook?.prompt) && (
            <details key={(shown ?? pickedLook)!.id} className="shown-prompt">
              <summary className="muted small">{t('gallery.prompt.show')}</summary>
              <p className="small prompt-last">{(shown ?? pickedLook)!.prompt}</p>
            </details>
          )}
          </div>
          {viewing ? (
            <RedoPanel
              key={viewing.id}
              image={viewing}
              hasStyle={hasStyle}
              disabled={busy !== ''}
              onDone={(made) => {
                setCurrent(made)
                setInspected(made)
                onChanged()
              }}
              onDelete={() => remove(viewing)}
            />
          ) : (
          <div className="stack">
            {/* Pictures in context moved to the "Pictures" section (owner's notes 25.11). The
                long explanation sits in the empty picture or on the "Generate" button; here only
                a line or two (owner's notes 26.11). */}
            <p className="muted small">{t(asSet ? 'generate.short.set' : 'generate.short.place')}</p>
            {/* The user's own samples. For a set: the AI puts the fitting ones into slots and
                draws the rest from them; once a view is there, the set is drawn from it. */}
              {samplesAllowed && (
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
                    <p className="faint small">{t(asSet ? 'gallery.samples.hint.set' : 'gallery.samples.hint')}</p>
                    <div className="sample-strip">
                      {samples.map((sample) => (
                        <div key={sample.url} className={`sample ${peek === sample.url ? 'shown' : ''} ${sample.odd ? 'odd' : ''}`}>
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
              )}
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
                {/* Hidden, not removed, under "Auto": the row keeps its height. */}
                <button
                  className="btn ghost small"
                  disabled={busy !== '' || !ready || autoPrompt}
                  style={{ visibility: autoPrompt ? 'hidden' : 'visible' }}
                  onClick={writePrompt}
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
              {/* One box of fixed height either way: ticking "Auto" moves nothing in the form. */}
              <div className={`prompt-box ${twoLang.both ? 'both' : ''}`}>
                {autoPrompt ? (
                  <div className="stack prompt-auto">
                    <p className="faint small">{t('generate.prompt.auto.note')}</p>
                    {prompt && (
                      <details>
                        <summary className="muted small">{t('generate.prompt.last')}</summary>
                        <p className="small prompt-last">{prompt}</p>
                      </details>
                    )}
                  </div>
                ) : (
                  <TwoLangPrompt
                    english={prompt}
                    onEnglish={setPrompt}
                    local={twoLang.local}
                    onLocal={twoLang.setLocal}
                    both={twoLang.both}
                    busy={twoLang.busy}
                    placeholder={t('generate.prompt.placeholder')}
                  />
                )}
              </div>
            </div>
            {/* A place or object: the wish for the next picture, under the prompt as for
                characters (owner's notes 26.11). */}
            {!withAngles && (
              <label className="stack field">
                <span className="small muted">{t('generate.note')}</span>
                <AutoTextarea
                  className="input small"
                  value={note}
                  maxLength={1000}
                  placeholder={t('generate.note.placeholder')}
                  disabled={busy !== ''}
                  onChange={(e) => setNote(e.target.value)}
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
            {/* At the bottom of the column, in one row with the last row of slots. */}
            <div className="stack generate-row">
            <div className="row wrap">
          <button
            className="btn primary generate-big"
            disabled={busy !== '' || !hasStyle || (!autoPrompt && !prompt.trim()) || !ready}
            title={longHint}
            onClick={draw}
          >
            <SparklesIcon />
            {busy === 'sort'
              ? t('gallery.samples.sorting')
              : busy === 'upload'
              ? t('gallery.uploading')
              : busy === 'prompt' && autoPrompt
              ? t('generate.prompt.busy')
              : busy === 'image'
              ? t('generate.image.busy')
              : busy === 'variants'
              ? t(withAngles ? 'variants.finding' : 'views.finding')
              : upNext
                ? t('generate.step.draw', { view: viewLabel(upNext) })
                : t('generate.image')}
          </button>
        </div>
        {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
        {progress && <p className="muted small">{progress}</p>}
            </div>
          </div>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
      {/* The picture just drawn, large: "OK, next" draws the next view (leafed with the
          arrows), the pencil redraws this one (owner's notes 26.11). */}
      {faceCheck && pending && (
        <div className="overlay face-check-overlay">
          <div className="dialog face-check">
            <div className="row">
              <h3 className="grow">
                {t('generate.step.title', {
                  view: faceCheck.angle ? viewLabel(faceCheck.angle) : t('generate.step.free'),
                })}
              </h3>
              <button
                className="btn ghost small icon"
                title={t('app.cancel')}
                aria-label={t('app.cancel')}
                disabled={busy !== ''}
                onClick={cancelFace}
              >
                ✕
              </button>
            </div>
            <img src={faceCheck.url} alt="" />
            <div className="face-check-prompt">
              <TwoLangPrompt
                english={prompt}
                onEnglish={setPrompt}
                local={twoLang.local}
                onLocal={twoLang.setLocal}
                both={twoLang.both}
                busy={twoLang.busy}
                disabled={busy !== ''}
              />
            </div>
            {error && <p className="error small">{error}</p>}
            {busy === 'prompt' && <p className="muted small">{t('generate.face.refining')}</p>}
            {busy === 'image' && <p className="muted small">{t('generate.image.busy')}</p>}
            {/* "Apply" draws the other views from this face; the pencil asks what to change
                and draws the face again; "Cancel" does not keep it. */}
            <div className="row wrap face-check-buttons">
              {stepChoices.length > 1 && (
                <button
                  className="btn ghost icon"
                  disabled={busy !== ''}
                  title={t('generate.step.prev_view')}
                  aria-label={t('generate.step.prev_view')}
                  onClick={() => leaf(-1)}
                >
                  ‹
                </button>
              )}
              <button className="btn primary" disabled={busy !== ''} onClick={goOn}>
                <CheckIcon />
                {stepNext
                  ? t('generate.step.next', { view: viewLabel(stepNext) })
                  : stepLook
                    ? t('generate.step.next_look', { look: stepLook.label })
                    : t('generate.step.done')}
              </button>
              {stepChoices.length > 1 && (
                <button
                  className="btn ghost icon"
                  disabled={busy !== ''}
                  title={t('generate.step.next_view')}
                  aria-label={t('generate.step.next_view')}
                  onClick={() => leaf(1)}
                >
                  ›
                </button>
              )}
              <button className="btn ghost" disabled={busy !== ''} onClick={() => setRemarkOpen(true)}>
                <PencilIcon />
                {t('generate.face.redraw')}
              </button>
              <span className="spacer" />
              <button className="btn ghost" disabled={busy !== ''} onClick={cancelFace}>
                {t('app.cancel')}
              </button>
            </div>
          </div>
          {remarkOpen && (
            <div className="overlay remark-overlay" onMouseDown={(e) => e.target === e.currentTarget && setRemarkOpen(false)}>
              <div className="dialog remark-dialog">
                <h3>{t('generate.face.remark')}</h3>
                <div className="row">
                  <textarea
                    className="input small grow"
                    rows={3}
                    autoFocus
                    value={remark}
                    maxLength={1000}
                    placeholder={t(withAngles ? 'generate.face.remark.placeholder' : 'views.remark.placeholder')}
                    onChange={(e) => setRemark(e.target.value)}
                  />
                  <MicButton
                    onText={(text) => setRemark((now) => (now.trim() ? `${now.trim()} ${text}` : text))}
                    onError={setError}
                  />
                </div>
                <div className="row wrap">
                  <button className="btn primary" onClick={redrawFace}>
                    <PencilIcon />
                    {t('generate.face.redraw')}
                  </button>
                  <span className="spacer" />
                  <button className="btn ghost" onClick={() => setRemarkOpen(false)}>
                    {t('app.cancel')}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
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
      <p className="muted small">{t(image.prompt ? 'generate.short.done' : 'generate.short.upload')}</p>
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
      <label className="stack field">
        <span className="small muted">{t('generate.prompt.label')}</span>
        <textarea
          className="input small redo-prompt"
          value={prompt}
          maxLength={4000}
          disabled={busy || remarked}
          title={remarked ? t('generate.remark.placeholder') : undefined}
          placeholder={t('generate.redo.prompt.placeholder')}
          onChange={(e) => setPrompt(e.target.value)}
        />
      </label>
      <div className="stack field">
        <span className="small muted">{t('generate.remark')}</span>
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
