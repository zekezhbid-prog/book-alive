import { useEffect, useRef, useState, type ReactNode } from 'react'
import { marked } from '../marked'
import { api, type ImageSize, type Scene, type SceneLine } from '../api'
import { ask } from '../dialogs'
import { errorText, useI18n } from '../i18n'
import { Composer } from './Composer'
import { zoomLink } from './Lightbox'
import { CopyIcon, UploadIcon } from './icons'

type Busy = '' | 'prompt' | 'frame' | 'enrich' | 'apply' | 'upload'

interface Props {
  scene: Scene
  aiReady: boolean
  onChange: (scene: Scene) => void
  /** "Create a reference: <name>": the card's references window over the scene. */
  onAddReference: (entityId: string) => void
}

/**
 * The scene card as one dialogue that leads to the video prompt (owner's notes 27.11): the
 * references found are already in, a missing one is a link to make it; "Build the video
 * prompt", then words change it (and may take a picture in or leave one out); the first frame
 * is drawn here with its aspect ratio and fixed by a remark; "Add to the description" offers
 * a fuller description to apply. The lines are kept with the scene.
 */
export function SceneDialog({ scene, aiReady, onChange, onAddReference }: Props) {
  const { t } = useI18n()
  const [text, setText] = useState('')
  const [said, setSaid] = useState('') // the user's words on screen while the model works
  const [busy, setBusy] = useState<Busy>('')
  const [error, setError] = useState('')
  const [size, setSize] = useState<ImageSize>('16:9')
  // The frame a remark goes to after "Fix".
  const [fixing, setFixing] = useState('')
  const [copied, setCopied] = useState(false)
  const field = useRef<HTMLTextAreaElement>(null)
  const clip = useRef<HTMLInputElement>(null)
  const end = useRef<HTMLDivElement>(null)
  const lines = scene.chat
  const last = lines[lines.length - 1]

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest' })
  }, [lines.length, busy])

  /** One step: the user's words, the model's work, then both lines are kept. */
  const step = async (
    kind: Busy,
    words: string,
    work: () => Promise<SceneLine[]>,
  ) => {
    setBusy(kind)
    setSaid(words)
    setError('')
    try {
      const answer = await work()
      const user: SceneLine[] = words ? [{ role: 'user', kind: 'text', text: words }] : []
      onChange(await api.addSceneChat(scene.id, [...user, ...answer]))
      setText('')
      return true
    } catch (e) {
      setError(errorText(t, e))
      return false
    } finally {
      setBusy('')
      setSaid('')
    }
  }
  const say = (words: string) => step('', words, async () => [])

  // Not every picture the scene wants is there: asked before going on with what there is.
  const enoughRefs = async () => !scene.missing.length || (await ask(t('scene.missing.confirm')))
  const build = async (note: string) => {
    if (!(await enoughRefs())) return
    await step('prompt', note || t('scene.chat.build'), async () => {
      const next = await api.buildScenePrompt(scene.id, note)
      return [{ role: 'assistant', kind: 'prompt', text: t('scene.chat.built'), prompt: next.prompt }]
    })
  }
  const refine = (change: string) =>
    step('prompt', change, async () => {
      const next = await api.refineScenePrompt(scene.id, change)
      return [{ role: 'assistant', kind: 'prompt', text: t('scene.chat.refined'), prompt: next.prompt }]
    })
  const frame = () =>
    step('frame', t('scene.chat.frame'), async () => {
      const next = await api.generateSceneFrame(scene.id, '', size)
      return [{ role: 'assistant', kind: 'frame', image_id: next.frames[0]?.id ?? '' }]
    })
  const fixFrame = async (remark: string) => {
    const imageId = fixing
    if (
      await step('frame', remark, async () => {
        await api.redoImage(imageId, { remark, size })
        return [{ role: 'assistant', kind: 'frame', image_id: imageId }]
      })
    )
      setFixing('')
  }
  const enrich = (wishes: string) =>
    step('enrich', wishes || t('scene.chat.enrich'), async () => {
      const offer = await api.enrichScene(scene.id, wishes)
      return [{ role: 'assistant', kind: 'enrich', text: offer.text, added: offer.added }]
    })
  const apply = (offer: Required<SceneLine>) =>
    step('apply', t('scene.chat.apply'), async () => {
      await api.saveSceneSummary(scene.id, offer.text)
      return [{ role: 'assistant', kind: 'text', text: t('scene.chat.applied') }]
    })
  const upload = (file: File | undefined) => {
    if (clip.current) clip.current.value = ''
    if (!file) return
    void step('upload', t('scene.chat.uploaded'), async () => {
      const next = await api.uploadSceneFrame(scene.id, file)
      return [{ role: 'assistant', kind: 'frame', image_id: next.frames[0]?.id ?? '' }]
    })
  }
  const copy = async () => {
    await navigator.clipboard.writeText(scene.prompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  // Typed words: a remark on the frame after "Fix", wishes for a fuller description just
  // offered, a change of the prompt, or the note the first prompt is written with.
  const send = () => {
    const words = text.trim()
    if (!words) return
    if (fixing) return void fixFrame(words)
    if (last?.kind === 'enrich') return void enrich(words)
    if (scene.prompt) return void refine(words)
    void build(words)
  }

  // Every frame of the dialogue, to leaf through; a fixed frame keeps its id, so each line
  // asks for its own copy of the file.
  const frameUrl = (m: Required<SceneLine>, n: number) => (m.image_url ? `${m.image_url}?v=${n}` : '')
  const frames = lines.map(frameUrl).filter(Boolean)
  const lastPrompt = lines.map((m) => m.kind).lastIndexOf('prompt')
  const off = busy !== '' || !aiReady

  const reply = (label: string, onClick: () => void, dim = false) => (
    <button key={label} className={`quick-reply${dim ? ' dim' : ''}`} disabled={off} onClick={onClick}>
      {label}
    </button>
  )
  // Ready answers after the last line (owner's notes 27.11, item 21).
  const replies = (): ReactNode[] => {
    if (last?.kind === 'frame' && last.image_url) {
      return [
        reply(t('scene.chat.ok'), () => void say(t('scene.chat.ok'))),
        reply(t('scene.chat.fix'), () => {
          setFixing(last.image_id)
          field.current?.focus()
        }),
      ]
    }
    if (last?.kind === 'enrich' && last.added.length) {
      return [
        reply(t('scene.chat.apply'), () => void apply(last)),
        reply(t('scene.chat.skip'), () => void say(t('scene.chat.skip')), true),
      ]
    }
    const enrichReply = reply(t('scene.chat.enrich'), () => void enrich(''), true)
    if (!scene.prompt) return [reply(t('scene.chat.build'), () => void build('')), enrichReply]
    return [
      reply(t('scene.chat.frame'), () => void frame()),
      reply(t('scene.chat.rebuild'), () => void build(''), true),
      enrichReply,
    ]
  }

  const line = (m: Required<SceneLine>, n: number) => (
    <div key={n} className={`illustration-bubble ${m.role}`}>
      {m.kind === 'enrich' ? (
        <>
          <p className="small muted">{t(m.added.length ? 'scene.chat.enrich.offer' : 'scene.enrich.none')}</p>
          {m.added.length > 0 && <p>{marked(m.text, m.added)}</p>}
        </>
      ) : (
        m.text && <p>{m.text}</p>
      )}
      {m.kind === 'prompt' && (
        <details open={n === lastPrompt}>
          <summary className="small muted">{t('scene.prompt')}</summary>
          <p className="small prompt-last">{m.prompt}</p>
          {n === lastPrompt && m.prompt === scene.prompt && (
            <button className={`btn ghost small ${copied ? 'on' : ''}`} onClick={copy}>
              <CopyIcon />
              {copied ? t('scene.copied') : t('scene.copy')}
            </button>
          )}
        </details>
      )}
      {m.kind === 'frame' &&
        (m.image_url ? (
          <a {...zoomLink(frames, frames.indexOf(frameUrl(m, n)))}>
            <img className="illustration-picture" src={frameUrl(m, n)} alt="" />
          </a>
        ) : (
          <p className="faint small">{t('scene.chat.frame.gone')}</p>
        ))}
    </div>
  )

  return (
    <section className="stack illustration-chat scene-chat">
      <div className="stack illustration-log">
        {/* The opening, not kept: what goes with the video and what is still missing. */}
        <div className="illustration-bubble assistant">
          <p>{t('scene.chat.hello')}</p>
          {scene.references.length > 0 ? (
            <div className="used-refs">
              {scene.references.map((ref) => (
                <a key={ref.image_id} title={ref.entity_name} {...zoomLink(scene.references.map((r) => r.url), ref.number - 1)}>
                  <img src={ref.url} alt="" loading="lazy" />
                </a>
              ))}
            </div>
          ) : (
            <p className="small faint">{t('scene.chat.no_refs')}</p>
          )}
          {scene.missing.length > 0 && (
            <div className="quick-replies">
              {scene.missing.map((m) => (
                <button
                  key={`${m.entity_id}-${m.need}`}
                  className="quick-reply dim"
                  title={t('scene.missing.hint')}
                  onClick={() => onAddReference(m.entity_id)}
                >
                  {t('scene.chat.create_ref', { name: m.name })} — {t(`scene.missing.${m.need}`)}
                </button>
              ))}
            </div>
          )}
        </div>
        {lines.map(line)}
        {said && (
          <div className="illustration-bubble user">
            <p>{said}</p>
          </div>
        )}
        {busy && busy !== 'apply' && (
          <div className="illustration-bubble assistant">
            <p className="muted">
              {busy === 'prompt'
                ? t('scene.build.busy')
                : busy === 'enrich'
                  ? t('scene.enrich.busy')
                  : t('generate.image.busy')}
            </p>
          </div>
        )}
        {!busy && <div className="quick-replies">{replies()}</div>}
        <div ref={end} />
      </div>
      {error && <p className="error small">{error}</p>}
      <input
        ref={clip}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => upload(e.target.files?.[0])}
      />
      {/* The same field as in every dialogue (owner's notes 27.11, items 21 and 30). */}
      <Composer
        value={text}
        onChange={setText}
        onSend={send}
        placeholder={t(fixing ? 'scene.chat.fix.placeholder' : scene.prompt ? 'scene.chat.placeholder.change' : 'scene.chat.placeholder')}
        disabled={off}
        sendDisabled={!text.trim()}
        maxLength={2000}
        fieldRef={field}
        onError={setError}
        size={{ value: size, onChange: setSize }}
        tools={
          <button
            className="btn ghost small icon"
            disabled={off}
            title={t('scene.chat.clip')}
            aria-label={t('scene.chat.clip')}
            onClick={() => clip.current?.click()}
          >
            <UploadIcon />
          </button>
        }
      />
    </section>
  )
}
