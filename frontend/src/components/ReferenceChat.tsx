import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  api,
  isAngle,
  type EntityKind,
  type ImageInfo,
  type ImageSize,
  type PlaceView,
  type RefLine,
  type RefLineIn,
  type Variant,
} from '../api'
import { ask } from '../dialogs'
import { errorText, useI18n, type MessageKey } from '../i18n'
import { useShowPrompt } from '../showPrompt'
import { useTwoLang } from '../twoLang'
import { HelpButton } from './HelpButton'
import { CheckIcon, CopyIcon, RefreshIcon, TrashIcon, UploadIcon } from './icons'
import { zoomLink } from './Lightbox'
import { Composer } from './Composer'
import { latest, orderOf, padTo } from './refViews'

interface Props {
  projectId: string
  entityId: string
  kind: EntityKind
  /** The card's name, shown in the header. */
  name?: string
  /** The card's base pictures in the current style. */
  bases: ImageInfo[]
  hasStyle: boolean
  /** A picture was drawn, put in or deleted: the gallery reloads. */
  onChanged: () => void
  onClose: () => void
}

// The first picture of a place or object, when it has none (owner's answers 27.11).
const FIRST_NOTE: Record<EntityKind, string> = {
  character: '',
  location: 'A general view of the whole place, seen from a distance.',
  item: 'The whole object seen from the front, on a plain background.',
}

// A place or object without its general picture: a few ways to see it first (owner's notes
// 27.11, item 44); each is the general picture, drawn from another side.
const FIRST_CHOICES: Record<EntityKind, { label: MessageKey; note: string }[]> = {
  character: [],
  location: [
    { label: 'ref.first.location.far', note: FIRST_NOTE.location },
    { label: 'ref.first.location.inside', note: 'The place seen from inside, at eye level, close enough to show its details.' },
    { label: 'ref.first.location.above', note: 'The whole place seen from above, at a high angle.' },
  ],
  item: [
    { label: 'ref.first.item.front', note: FIRST_NOTE.item },
    { label: 'ref.first.item.side', note: 'The whole object seen from the side, on a plain background.' },
    { label: 'ref.first.item.angle', note: 'The whole object seen at three quarters, slightly from above, on a plain background.' },
  ],
}

type Busy = '' | 'prompt' | 'image' | 'upload' | 'variants' | 'views'

/**
 * The card's references as a dialogue, like the "Pictures" section (owner's notes 27.11, item
 * 19): the window offers the next view, collects the prompt (shown as a step that unfolds,
 * in English or the interface language), draws on "Draw" and asks "OK, next" or "Fix". Typed
 * words fix the picture just drawn, or describe the next one. The paperclip puts in the
 * user's own picture: the window asks which view it is. The lines are kept with the card.
 */
export function ReferenceChat({ projectId, entityId, kind, name, bases: allBases, hasStyle, onChanged, onClose }: Props) {
  const { t } = useI18n()
  const withAngles = kind === 'character'
  const [lines, setLines] = useState<RefLine[] | null>(null)
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<Busy>('')
  // The English prompt; the step that shows it can be edited while it waits for "Draw".
  const [prompt, setPrompt] = useState('')
  const [promptReady, setPromptReady] = useState(false)
  // The picture just drawn waits for "OK, next" or "Fix": the references it was drawn with.
  const [pending, setPending] = useState<{ image: ImageInfo; references: string[] } | null>(null)
  const [fixing, setFixing] = useState(false)
  // "Change" on a finished view (owner's notes 27.11, item 22): attached, the model edits
  // that very picture; detached, it draws the view anew from the card's other references.
  const [editing, setEditing] = useState<{ image: ImageInfo; attached: boolean } | null>(null)
  // A picture put in with the paperclip, waiting for the user to say which view it is.
  const [upload, setUpload] = useState<{ id: string; file: File } | null>(null)
  // The user's own pictures kept as samples for the next drawing.
  const [samples, setSamples] = useState<string[]>([])
  const [nextView, setNextView] = useState('')
  // Views drawn or put in here, `look:view`: the gallery may not have reloaded them yet.
  const [drawnHere, setDrawnHere] = useState<string[]>([])
  // A finished look whose face starts a new look.
  const [refLook, setRefLook] = useState('')
  const [size, setSize] = useState<ImageSize>('1:1')
  const [variants, setVariants] = useState<Variant[]>([])
  const [variantKey, setVariantKey] = useState('')
  // Looks the model found, waiting for "Save" or "Cancel".
  const [found, setFound] = useState<Variant[] | null>(null)
  const [looksChecked, setLooksChecked] = useState(true)
  const [placeViews, setPlaceViews] = useState<PlaceView[]>([])
  // Which half of the two-language prompt is shown.
  const [half, setHalf] = useState<'english' | 'local'>('local')
  const clip = useRef<HTMLInputElement>(null)
  const field = useRef<HTMLTextAreaElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const fail = (e: unknown) => setError(errorText(t, e))

  useEffect(() => {
    const failed = (e: unknown) => setError(errorText(t, e))
    api.refChat(entityId).then(setLines, failed)
    if (!withAngles) {
      api.views(entityId).then(setPlaceViews, failed)
      return
    }
    api.variants(entityId).then(({ variants: list, checked }) => {
      setVariants(list)
      setLooksChecked(checked)
      setVariantKey((now) => now || list[0]?.key || '')
    }, failed)
  }, [entityId, withAngles, t])
  // Braces matter: new Chrome returns a Promise from scrollIntoView (see Illustrations).
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [lines, busy, pending, promptReady, upload, found, fixing])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !busy && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, busy])

  const twoLang = useTwoLang(entityId, prompt, setPrompt, true, setError)
  const showPrompt = useShowPrompt()
  const variant = variants.find((v) => v.key === variantKey) ?? null
  const SET_ORDER = orderOf(variant?.shape)
  const bases = allBases.filter((b) => (b.variant || '') === (variant?.key ?? ''))
  const has = (view: string, look = variant?.key ?? '') =>
    Boolean(latest(allBases.filter((b) => (b.variant || '') === look), view)) ||
    drawnHere.includes(`${look}:${view}`)
  // The views still without a picture, in their order.
  const openViews = (except = '') =>
    (withAngles ? SET_ORDER : placeViews.map((v) => v.key)).filter((v) => v !== except && !has(v))
  // A place or object starts with its general picture (the free view '').
  const first = !withAngles && !has('')
  const open = openViews()
  const upNext = first ? '' : open.includes(nextView) ? nextView : (open[0] ?? '')
  // A character with every view of its look drawn has nothing to draw next.
  const ready = !withAngles || upNext !== ''
  const viewLabel = (view: string) =>
    !view
      ? first
        ? t(kind === 'item' ? 'ref.view.front' : 'ref.view.general')
        : t('ref.view.free')
      : (placeViews.find((v) => v.key === view)?.label ?? (isAngle(view) ? t(`angle.${view}`) : view))
  // Finished looks of the character whose face can start this one, while it is empty.
  const refLooks =
    withAngles && bases.length === 0 && variant?.shape !== 'object'
      ? variants.filter(
          (v) =>
            v.key !== variant?.key &&
            (v.shape ?? 'human') === (variant?.shape ?? 'human') &&
            has(orderOf(v.shape)[0], v.key),
        )
      : []
  // Another look of the character that still has empty views.
  const nextLook = () =>
    variants.find((v) => v.key !== variant?.key && orderOf(v.shape).some((view) => !has(view, v.key))) ?? null

  // Lines shown at once and saved in the background; the next save waits for them.
  const say = async (add: RefLineIn[]) => {
    try {
      setLines(await api.addRefChat(entityId, add))
    } catch (e) {
      fail(e)
    }
  }
  // A press on a link: the offer and the pick stay where they were, the model's progress
  // comes under them (owner's notes 27.11, item 37). They are shown now and saved with the
  // answer (or alone, if the model fails).
  const keep = (offer: string, pick: string): RefLineIn[] => {
    const add: RefLineIn[] = [
      ...(offer ? [{ role: 'assistant' as const, kind: 'offer' as const, text: offer }] : []),
      { role: 'user', kind: 'text', text: pick },
    ]
    const blank = { kind: 'text', text: '', prompt: '', image_id: '', view: '', image_url: '' } as const
    setLines((now) => [...(now ?? []), ...add.map((l) => ({ ...blank, ...l }) as RefLine)])
    return add
  }

  // A picture put in "as a sample" only helps the drawing here: it never stays among the
  // card's pictures (owner's notes 27.11, item 40), so it goes when the window closes.
  const sampleIds = useRef<string[]>([])
  const changedRef = useRef(onChanged)
  useEffect(() => {
    changedRef.current = onChanged
  }, [onChanged])
  useEffect(
    () => () => {
      const ids = sampleIds.current
      sampleIds.current = []
      if (!ids.length) return
      void Promise.allSettled(ids.map((id) => api.deleteImage(id))).then(() => changedRef.current())
    },
    [],
  )

  const generate = (view: string, english: string, references: string[], lookKey: string) =>
    api.generateImage(entityId, {
      angle: view,
      look_label: '',
      chapter_from_id: '',
      chapter_to_id: '',
      variant: lookKey,
      prompt: english,
      size,
      add_view: true,
      reference_ids: references,
    })

  // A picture drawn: it waits for "OK, next" or "Fix", and a place gets its views after its
  // first picture so that "OK, next" has something to offer.
  const drawn = async (made: ImageInfo, view: string, references: string[], lookKey: string, before: RefLineIn[] = []) => {
    onChanged()
    setDrawnHere((had) => [...had, `${lookKey}:${view}`])
    setPending({ image: made, references })
    setNextView(openViews(view)[0] ?? '')
    await say([...before, { role: 'assistant', kind: 'image', image_id: made.id, view }])
    if (!withAngles && !placeViews.length) {
      setBusy('views')
      try {
        const saved = await api.saveViews(entityId, await api.findViews(entityId))
        setPlaceViews(saved)
        setNextView(saved.find((v) => v.key !== view)?.key ?? '')
      } catch (e) {
        fail(e)
      }
    }
  }

  /** The text model writes the prompt of the next picture; `words` are the user's own. */
  const collect = async (words = '', view = upNext, note = '', before: RefLineIn[] = []) => {
    setError('')
    let lookKey = variant?.key ?? ''
    const said: RefLineIn[] = [...before, ...(words ? [{ role: 'user' as const, text: words }] : [])]
    // The first drawing of a character asks once whether it has several outward looks.
    if (withAngles && !looksChecked && !variants.length) {
      setBusy('variants')
      try {
        const list = await api.findVariants(entityId)
        setLooksChecked(true)
        if (list.length > 1) {
          setFound(list)
          if (said.length) await say(said)
          return setBusy('')
        }
        // One look that is not a person (an animal, a thing) is kept: it has its own views.
        if (list.length === 1 && list[0].shape !== 'human') {
          const saved = await api.saveVariants(entityId, list)
          setVariants(saved)
          setVariantKey(saved[0]?.key ?? '')
          lookKey = saved[0]?.key ?? ''
          onChanged()
        }
      } catch (e) {
        fail(e)
        if (before.length) await say(before)
        return setBusy('')
      }
    }
    setBusy('prompt')
    try {
      let written = (
        await api.imagePrompt(entityId, {
          angle: '',
          look_label: '',
          chapter_from_id: '',
          chapter_to_id: '',
          variant: lookKey,
          // One prompt serves every view; the view is put in front of it when drawn.
          view_free: true,
          reference_ids: [],
          note: withAngles ? '' : words || note || (first ? FIRST_NOTE[kind] : ''),
        })
      ).prompt
      if (withAngles && words) written = (await api.refineImagePrompt(entityId, written, words)).text
      setPrompt(written)
      // "Show the prompt" off: no stop at the prompt, the picture is drawn at once (item 46).
      if (!showPrompt) return await draw({ english: written, view, lookKey, before: said })
      setPromptReady(true)
      await say([...said, { role: 'assistant', kind: 'prompt', prompt: written, view }])
    } catch (e) {
      fail(e)
      if (before.length) await say(before)
    }
    setBusy('')
  }

  // Words said while the prompt waits for "Draw" go into it.
  const refine = async (words: string) => {
    setError('')
    setBusy('prompt')
    try {
      const english = (await api.refineImagePrompt(entityId, await twoLang.flush(), words)).text
      setPrompt(english)
      await say([
        { role: 'user', text: words },
        { role: 'assistant', kind: 'prompt', prompt: english, view: upNext },
      ])
    } catch (e) {
      fail(e)
    }
    setBusy('')
  }

  /** `given`: the prompt just written, drawn without waiting for "Draw" (item 46). */
  const draw = async (given?: { english: string; view: string; lookKey: string; before: RefLineIn[] }) => {
    setError('')
    const lookKey = given?.lookKey ?? variant?.key ?? ''
    const view = given?.view ?? upNext
    let references = samples.slice(-3)
    const from = refLooks.find((v) => v.key === refLook)
    const fromImage = from && latest(allBases.filter((b) => b.variant === from.key), orderOf(from.shape)[0])
    if (fromImage) references = [fromImage.id, ...references].slice(0, 3)
    setBusy('image')
    try {
      const made = await generate(view, given?.english ?? (await twoLang.flush()), references, lookKey)
      setPromptReady(false)
      setSamples([])
      await drawn(made, view, references, lookKey, given?.before)
    } catch (e) {
      fail(e)
      if (given?.before.length) await say(given.before)
    }
    setBusy('')
  }

  // The picture is liked: the next view is drawn with the prompt as it is.
  const goOn = async (chosen?: string) => {
    if (!pending) return
    const following = openViews(pending.image.angle)
    const view = chosen ?? (following.includes(nextView) ? nextView : (following[0] ?? ''))
    setFixing(false)
    if (!view) {
      setPending(null)
      const after = withAngles ? nextLook() : null
      if (after) {
        setPrompt('')
        setVariantKey(after.key)
        setRefLook('')
      }
      return say([
        { role: 'user', text: t('generate.step.done') },
        { role: 'assistant', text: after ? t('ref.look_next', { look: after.label }) : t('ref.done') },
      ])
    }
    const before = keep('', viewLabel(view))
    setError('')
    setBusy('image')
    const lookKey = pending.image.variant || ''
    try {
      const made = await generate(view, await twoLang.flush(), pending.references, lookKey)
      await drawn(made, view, pending.references, lookKey, before)
    } catch (e) {
      setPending(null)
      fail(e)
      await say(before)
    }
    setBusy('')
  }

  // The user's remark goes into the prompt; the picture is removed and drawn again.
  const fix = async (remark: string) => {
    if (!pending) return
    const { image, references } = pending
    setError('')
    setFixing(false)
    setBusy('prompt')
    await say([{ role: 'user', text: remark }])
    let english = await twoLang.flush()
    try {
      english = (await api.refineImagePrompt(entityId, english, remark)).text
      setPrompt(english)
    } catch (e) {
      fail(e)
      return setBusy('')
    }
    setBusy('image')
    try {
      await api.deleteImage(image.id)
      onChanged()
      const made = await generate(image.angle, english, references, image.variant || '')
      onChanged()
      setPending({ image: made, references })
      await say([
        { role: 'assistant', kind: 'prompt', prompt: english, view: image.angle },
        { role: 'assistant', kind: 'image', image_id: made.id, view: image.angle },
      ])
    } catch (e) {
      setPending(null)
      fail(e)
    }
    setBusy('')
  }

  // Not kept: the user's own press removes the picture just drawn.
  const drop = async () => {
    if (!pending) return
    const { image } = pending
    setPending(null)
    setFixing(false)
    setDrawnHere((had) => had.filter((k) => k !== `${image.variant || ''}:${image.angle}`))
    try {
      await api.deleteImage(image.id)
      onChanged()
    } catch (e) {
      fail(e)
    }
    await say([{ role: 'user', text: t('ref.drop') }])
  }

  const startEdit = (image: ImageInfo) => {
    if (busy) return
    setFixing(false)
    setEditing({ image, attached: true })
  }
  // The field waits for what to change.
  const editingId = editing?.image.id
  useEffect(() => {
    if (editingId) field.current?.focus()
  }, [editingId])

  const edit = async (words: string) => {
    if (!editing) return
    const { image, attached } = editing
    setError('')
    setBusy('image')
    await say([{ role: 'user', text: words }])
    try {
      let made: ImageInfo
      if (attached) made = await api.redoImage(image.id, { remark: words, size })
      else {
        const english = (await api.refineImagePrompt(entityId, image.prompt || (await twoLang.flush()), words)).text
        const others = doneViews.filter((d) => d.id !== image.id).map((d) => d.id).slice(0, 3)
        made = await api.redoImage(image.id, { prompt: english, size, reference_ids: others })
      }
      onChanged()
      setEditing({ image: made, attached })
      await say([{ role: 'assistant', kind: 'image', image_id: made.id, view: made.angle }])
    } catch (e) {
      fail(e)
    }
    setBusy('')
  }

  const removeView = async (image: ImageInfo) => {
    if (busy || !(await ask(t('gallery.delete.confirm')))) return
    setError('')
    try {
      await api.deleteImage(image.id)
      onChanged()
      setDrawnHere((had) => had.filter((k) => k !== `${image.variant || ''}:${image.angle}`))
      if (editing?.image.id === image.id) setEditing(null)
      if (pending?.image.id === image.id) setPending(null)
      await say([{ role: 'user', text: t('ref.deleted', { view: viewLabel(image.angle) }) }])
    } catch (e) {
      fail(e)
    }
  }

  // The paperclip: the picture is stored as a plain picture of the card, then the user says
  // which view it is (or that it is only a sample).
  const putIn = async (files: FileList | null) => {
    const file = [...(files ?? [])].find((f) => f.type.startsWith('image/'))
    if (clip.current) clip.current.value = ''
    if (!file) return
    setError('')
    setBusy('upload')
    try {
      const ratio = size.split(':').map(Number)
      const ready = await padTo(file, ratio[0] / ratio[1])
      const [made] = await api.uploadImages(projectId, [ready], entityId)
      await api.updateImage(made.id, { is_main: false, angle: '', look_label: '' })
      setUpload({ id: made.id, file: ready })
      await say([{ role: 'user', kind: 'upload', image_id: made.id }])
    } catch (e) {
      fail(e)
    }
    setBusy('')
  }
  // A view: the picture goes into it if it is in the project style, otherwise it is a sample.
  const placeUpload = async (view: string | null) => {
    if (!upload) return
    const { id, file } = upload
    setUpload(null)
    // Named a view but in another style: it stays with the card as before, and helps as a sample.
    const asSample = () => setSamples((had) => [...had, id].slice(-3))
    if (view === null) {
      sampleIds.current.push(id)
      asSample()
      return say([
        { role: 'user', text: t('ref.upload.sample') },
        { role: 'assistant', text: t('ref.upload.sampled') },
      ])
    }
    setBusy('upload')
    try {
      const verdict = await api.checkStyle(projectId, file)
      if (!verdict.matches) {
        asSample()
        await say([
          { role: 'user', text: viewLabel(view) },
          { role: 'assistant', text: t('ref.upload.style', { reason: verdict.reason }) },
        ])
      } else {
        await api.updateImage(id, { is_main: true, angle: view, variant: variant?.key ?? '' })
        setDrawnHere((had) => [...had, `${variant?.key ?? ''}:${view}`])
        onChanged()
        await say([
          { role: 'user', text: viewLabel(view) },
          { role: 'assistant', text: t('ref.upload.placed', { view: viewLabel(view) }) },
        ])
      }
    } catch (e) {
      fail(e)
    }
    setBusy('')
  }

  const keepLooks = async () => {
    if (!found) return
    setBusy('variants')
    try {
      const saved = await api.saveVariants(entityId, found)
      setVariants(saved)
      setVariantKey(saved[0]?.key ?? '')
      setFound(null)
      onChanged()
    } catch (e) {
      fail(e)
    }
    setBusy('')
  }

  const send = () => {
    const words = text.trim()
    if (!words || busy) return
    setText('')
    if (editing) return edit(words)
    if (pending) return fix(words)
    if (promptReady) return refine(words)
    if (!ready) return say([{ role: 'user', text: words }, { role: 'assistant', text: t('ref.done') }])
    return collect(words)
  }

  const chooseLook = (key: string) => {
    if (key === variantKey) return
    setVariantKey(key)
    setPrompt('')
    setPromptReady(false)
    setNextView('')
    setRefLook('')
  }

  // "OK, next" offers the open views; the one picked is drawn.
  const stepChoices = pending ? openViews(pending.image.angle) : []
  const stepLook = pending && !stepChoices.length && withAngles ? nextLook() : null
  // Two or three views to choose the next picture from (owner's notes 27.11, item 29).
  // Nothing drawn yet: a character starts from the front face, the rest lean on it.
  // About six at once (item 37), the usual next one first.
  const offerViews = [upNext, ...open.filter((v) => v !== upNext)].filter((v) => v !== '' || !withAngles).slice(0, 6)
  // The views a put in picture can take: the open ones, and a place's general picture.
  const uploadViews = withAngles ? open : [...(first ? [''] : []), ...open]
  // The finished views of this look, small, above the dialogue.
  const doneViews = (withAngles ? SET_ORDER : ['', ...placeViews.map((v) => v.key)])
    .map((view) => latest(bases, view))
    .filter((made): made is ImageInfo => made !== null)
  const lastPrompt = lines ? lines.map((m) => m.kind).lastIndexOf('prompt') : -1
  const off = busy !== ''

  const line = (m: RefLine, n: number): ReactNode => {
    if (m.kind === 'prompt') {
      const title = `${t('ref.prompt')}${m.view ? ` · ${viewLabel(m.view)}` : ''}`
      if (!(n === lastPrompt && promptReady && !pending))
        return (
          <details>
            <summary className="small muted">{title}</summary>
            <p className="prompt-full">{m.prompt}</p>
          </details>
        )
      // The prompt waiting for "Draw": plain text across the line, the language switch, "build
      // again" and "copy" on the right of its title (owner's notes 27.11, items 37, 39, 44).
      // Typed words change it.
      const showLocal = twoLang.both && half === 'local' && twoLang.local.trim() !== ''
      return (
        <>
          <div className="row bubble-head">
            <p className="grow">{title}</p>
            {twoLang.both && (
              <div className="segmented small" role="group" aria-label={t('generate.prompt.lang')}>
                <button className={half === 'english' ? 'active' : ''} aria-pressed={half === 'english'} onClick={() => setHalf('english')}>
                  EN
                </button>
                <button className={half === 'local' ? 'active' : ''} aria-pressed={half === 'local'} onClick={() => setHalf('local')}>
                  {t('generate.prompt.lang.local')}
                </button>
              </div>
            )}
            <button
              className="btn ghost small icon"
              disabled={off}
              title={t('ref.collect.again')}
              aria-label={t('ref.collect.again')}
              onClick={() => collect()}
            >
              <RefreshIcon />
            </button>
            <button
              className="btn ghost small icon"
              title={t('generate.copy')}
              aria-label={t('generate.copy')}
              onClick={() => navigator.clipboard.writeText(prompt)}
            >
              <CopyIcon />
            </button>
          </div>
          <p className="prompt-full">{showLocal ? twoLang.local : prompt}</p>
          {twoLang.both && half === 'local' && !showLocal && twoLang.busy && (
            <p className="chat-progress">{t('generate.prompt.translating')}</p>
          )}
        </>
      )
    }
    if (m.kind === 'image' || m.kind === 'upload') {
      if (!m.image_url) return <p className="faint small">{t('ref.image.gone')}</p>
      const urls = (lines ?? []).map((l) => l.image_url).filter(Boolean)
      return (
        <a {...zoomLink(urls, urls.indexOf(m.image_url))}>
          <img className="illustration-picture" src={m.image_url} alt="" />
        </a>
      )
    }
    return <p>{m.text}</p>
  }

  // The window's own turn: what it offers now, with the buttons to answer.
  const live = (): ReactNode => {
    if (busy)
      return (
        <p className="chat-progress">
          {t(
            busy === 'prompt'
              ? 'generate.prompt.busy'
              : busy === 'image'
                ? 'generate.image.busy'
                : busy === 'upload'
                  ? 'gallery.uploading'
                  : busy === 'variants'
                    ? 'variants.finding'
                    : 'views.finding',
          )}
        </p>
      )
    if (found)
      return (
        <div className="stack variant-offer">
          <p>{t('variants.found', { n: found.length })}</p>
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
          <div className="row wrap">
            <button className="btn primary small" onClick={keepLooks}>
              <CheckIcon />
              {t('generate.face.apply')}
            </button>
            <button className="btn ghost small" onClick={() => setFound(null)}>
              {t('app.cancel')}
            </button>
          </div>
        </div>
      )
    if (upload)
      return (
        <>
          <p>{t('ref.upload.ask')}</p>
          <div className="quick-replies">
            {uploadViews.map((view) => (
              <button key={view || 'free'} className="quick-reply" onClick={() => placeUpload(view)}>
                {viewLabel(view)}
              </button>
            ))}
            <button className="quick-reply dim" onClick={() => placeUpload(null)}>
              {t('ref.upload.sample')}
            </button>
          </div>
        </>
      )
    if (pending)
      return (
        <>
          {fixing && <p>{t('ref.fix.ask')}</p>}
          {/* The next views as links, just their names; a press draws it. A remark on this
              picture is typed in the field; the bin removes it (owner's notes 27.11, item 38). */}
          <div className="quick-replies">
            {stepChoices.length > 0 ? (
              stepChoices.slice(0, 6).map((view) => (
                <button key={view} className="quick-reply" onClick={() => goOn(view)}>
                  {viewLabel(view)}
                </button>
              ))
            ) : (
              <button className="quick-reply" onClick={() => goOn()}>
                {stepLook ? t('generate.step.next_look', { look: stepLook.label }) : t('generate.step.done')}
              </button>
            )}
            <span className="spacer" />
            <button className="btn ghost small icon" title={t('ref.drop')} aria-label={t('ref.drop')} onClick={drop}>
              <TrashIcon />
            </button>
          </div>
        </>
      )
    if (promptReady)
      return (
        <div className="quick-replies">
          <button className="quick-reply" disabled={!hasStyle || !prompt.trim()} onClick={() => void draw()}>
            {t('ref.draw', { view: viewLabel(upNext) })}
          </button>
          {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
        </div>
      )
    if (!ready) {
      const after = nextLook()
      return (
        <>
          <p>{t('ref.done')}</p>
          {after && (
            <div className="quick-replies">
              <button className="quick-reply" onClick={() => chooseLook(after.key)}>
                {t('generate.step.next_look', { look: after.label })}
              </button>
            </div>
          )}
        </>
      )
    }
    const offerText = t(bases.length ? 'ref.offer.pick' : 'ref.offer.start')
    return (
      <>
        <p>{offerText}</p>
        {refLooks.length > 0 && (
          <div className="row wrap" title={t('variants.ref.hint')}>
            <span className="small muted">{t('variants.ref')}</span>
            {refLooks.map((v) => (
              <button
                key={v.key}
                className={`chip ${refLook === v.key ? 'active' : ''}`}
                onClick={() => setRefLook(refLook === v.key ? '' : v.key)}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
        {/* About six views as links at once; a press collects the prompt (item 37). */}
        <div className="quick-replies">
          {first
            ? FIRST_CHOICES[kind].map((c) => (
                <button
                  key={c.label}
                  className="quick-reply"
                  onClick={() => void collect('', '', c.note, keep(offerText, t(c.label)))}
                >
                  {t(c.label)}
                </button>
              ))
            : offerViews.map((view) => (
                <button
                  key={view}
                  className="quick-reply"
                  onClick={() => {
                    setNextView(view)
                    void collect('', view, '', keep(offerText, viewLabel(view)))
                  }}
                >
                  {viewLabel(view)}
                </button>
              ))}
          {samples.length > 0 && <span className="faint small">{t('ref.samples', { n: samples.length })}</span>}
        </div>
      </>
    )
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="dialog ref-chat">
        <div className="row">
          <h2 className="grow">{name ? t('ref.title.of', { name }) : t('ref.title')}</h2>
          <HelpButton
            title={t('ref.title')}
            paragraphs={[t('ref.help.flow'), t('ref.help.text'), t('ref.help.clip'), t('generate.help.lang')]}
          />
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        {withAngles && variants.length > 1 && (
          <div className="row wrap">
            {variants.map((v) => (
              <button
                key={v.key}
                className={`chip ${v.key === variantKey ? 'active' : ''}`}
                disabled={off || !!pending || promptReady}
                title={v.description}
                onClick={() => chooseLook(v.key)}
              >
                {v.label}
              </button>
            ))}
          </div>
        )}
        {doneViews.length > 0 && (
          <div className="ref-done">
            {doneViews.map((made, n) => (
              <a
                key={made.id}
                title={viewLabel(made.angle)}
                {...zoomLink(
                  doneViews.map((d) => d.url),
                  n,
                  {
                    captions: doneViews.map((d) => viewLabel(d.angle)),
                    actions: [
                      { label: t('ref.edit'), onClick: (at) => startEdit(doneViews[at]) },
                      { label: t('app.delete'), onClick: (at) => removeView(doneViews[at]) },
                    ],
                  },
                )}
              >
                <img src={made.url} alt={viewLabel(made.angle)} loading="lazy" />
              </a>
            ))}
          </div>
        )}
        <div className="stack illustration-log ref-tape">
          {lines === null && <p className="muted">{t('app.loading')}</p>}
          {lines?.map((m, n) => (
            <div key={n} className={`illustration-bubble ${m.role}${m.kind === 'prompt' ? ' wide' : ''}`}>
              {line(m, n)}
            </div>
          ))}
          {/* While the model works, only a grey line at the end (item 37). */}
          {lines !== null && (busy ? live() : <div className="illustration-bubble assistant">{live()}</div>)}
          <div ref={end} />
        </div>
        {error && <p className="error small">{error}</p>}
        <input
          ref={clip}
          type="file"
          accept="image/png,image/jpeg,image/webp"
          hidden
          onChange={(e) => putIn(e.target.files)}
        />
        {editing && (
          <div className="ref-attach">
            {editing.attached ? (
              <>
                <img src={editing.image.url} alt="" />
                <span className="grow small">{t('ref.edit.attached', { view: viewLabel(editing.image.angle) })}</span>
                <button
                  className="btn ghost small icon"
                  disabled={off}
                  title={t('ref.edit.detach')}
                  aria-label={t('ref.edit.detach')}
                  onClick={() => setEditing({ ...editing, attached: false })}
                >
                  ✕
                </button>
              </>
            ) : (
              <span className="grow small muted">{t('ref.edit.detached', { view: viewLabel(editing.image.angle) })}</span>
            )}
            <button className="quick-reply" disabled={off} onClick={() => setEditing(null)}>
              {t('ref.edit.stop')}
            </button>
          </div>
        )}
        {/* The same field as in every dialogue (owner's notes 27.11, items 21 and 30). */}
        <Composer
          value={text}
          onChange={setText}
          onSend={send}
          placeholder={t(editing ? 'ref.placeholder.edit' : pending ? 'ref.placeholder.fix' : 'ref.placeholder')}
          disabled={off || !!upload || !!found}
          sendDisabled={!text.trim()}
          maxLength={1000}
          fieldRef={field}
          onError={setError}
          size={{ value: size, onChange: setSize }}
          tools={
            <button
              className="btn ghost small icon"
              disabled={off || !!pending || !!upload}
              title={t('ref.clip')}
              aria-label={t('ref.clip')}
              onClick={() => clip.current?.click()}
            >
              <UploadIcon />
            </button>
          }
        />
      </div>
    </div>
  )
}
