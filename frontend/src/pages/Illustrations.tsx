import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  api,
  peek,
  sectionOf,
  type ChapterBrief,
  type EntityKind,
  type Illustration,
  type IllustrationBrief,
  type ImageSize,
  type Project,
} from '../api'
import ProjectHeader from '../components/ProjectHeader'
import { Composer } from '../components/Composer'
import { ProposalList } from '../components/SceneProposals'
import { zoomLink } from '../components/Lightbox'
import { BoldPlusIcon, BookIcon, ImageIcon, TrashIcon } from '../components/icons'
import { HelpButton } from '../components/HelpButton'
import { errorText, useI18n } from '../i18n'
import { ask } from '../dialogs'

/**
 * The "Pictures" section: illustrations of the book as a board of cards. A card is added by
 * hand; inside it the user says what to draw, the model finds the moment of the book, who
 * and what is in it, takes their pictures as references and draws (owner's notes 25.11).
 */
export default function Illustrations() {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { projectId = '', illustrationId } = useParams()
  const [project, setProject] = useState<Project | null>(() => peek.project(projectId) ?? null)
  const [items, setItems] = useState<IllustrationBrief[] | null>(null)
  const [error, setError] = useState('')
  const base = `/projects/${projectId}/images`

  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    api.project(projectId).then(setProject, fail)
    api.illustrations(projectId).then(setItems, fail)
  }, [projectId, t, illustrationId])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const add = async () => {
    try {
      const made = await api.createIllustration(projectId)
      navigate(`${base}/${made.id}`)
    } catch (e) {
      setError(errorText(t, e))
    }
  }

  return (
    <>
      <ProjectHeader project={project} />
      <main className="page stack">
        <div className="page-head">
          <div className="grow">
            <h1>{t('images.title')}</h1>
            <p className="muted">{t('images.hint')}</p>
          </div>
          {/* A "+" without words; the section has no close button, it closes by going to
              another one (owner's notes 27.11, items 26 and 27). */}
          <button className="btn primary icon" title={t('images.add')} aria-label={t('images.add')} onClick={add}>
            <BoldPlusIcon />
          </button>
          <HelpButton title={t('images.title')} paragraphs={[t('images.help')]} />
        </div>
        {error && <p className="error">{error}</p>}
        {!project.style_id && <p className="faint small">{t('generate.no_style')}</p>}
        {illustrationId ? (
          <IllustrationChat
            key={illustrationId}
            id={illustrationId}
            project={project}
            onClose={() => navigate(base)}
            onDeleted={() => navigate(base)}
          />
        ) : (
          <div className="illustration-grid">
            {items?.length === 0 && <p className="faint">{t('images.empty')}</p>}
            {items?.map((item) => (
              <button key={item.id} className="illustration-tile" onClick={() => navigate(`${base}/${item.id}`)}>
                {item.cover ? (
                  <img src={item.cover} alt="" loading="lazy" />
                ) : (
                  <span className="illustration-blank" aria-hidden>
                    <ImageIcon />
                  </span>
                )}
                <span className="small">{item.title || t('images.untitled')}</span>
              </button>
            ))}
          </div>
        )}
      </main>
    </>
  )
}

interface ChatProps {
  id: string
  project: Project
  onClose: () => void
  onDeleted: () => void
}

/** The dialogue of one picture: the user's words, the model's questions and plans, pictures. */
function IllustrationChat({ id, project, onClose, onDeleted }: ChatProps) {
  const { t } = useI18n()
  const [item, setItem] = useState<Illustration | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<'' | 'think' | 'draw'>('')
  const [size, setSize] = useState<ImageSize>('1:1')
  const [error, setError] = useState('')
  const [picking, setPicking] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  const navigate = useNavigate()

  useEffect(() => {
    api.illustration(id).then(setItem, (e) => setError(errorText(t, e)))
  }, [id, t])
  // Braces matter: new Chrome returns a Promise from scrollIntoView, and React would call it
  // as the effect's cleanup ("l is not a function", owner's notes 26.11).
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [item, busy])

  const openCard = (who: { entity_id: string; kind: string }) =>
    navigate(`/projects/${project.id}/${sectionOf(who.kind as EntityKind)}/${who.entity_id}`)

  /** Draws the last plan. Cards of it without a reference are named first (owner's notes
   * 27.11): "No" opens the first such card to make one, and the plan waits for "Draw". */
  const draw = async (current: Illustration) => {
    const plan = current.messages[current.messages.length - 1]
    if (!plan?.prompt) return
    if (plan.missing.length) {
      const names = plan.missing.map((m) => m.name).join(', ')
      const go = await ask(t('images.missing.confirm', { names }), {
        yes: t('images.missing.yes'),
        no: t('images.missing.no'),
      })
      if (!go) return openCard(plan.missing[0])
    }
    setBusy('draw')
    setItem(await api.drawIllustration(id, size))
  }

  // A plan is drawn at once: the user sees what the model found, then the picture.
  const send = async () => {
    const words = text.trim()
    if (!words) return
    setBusy('think')
    setError('')
    setText('')
    try {
      const answered = await api.askIllustration(id, words)
      setItem(answered)
      setBusy('')
      await draw(answered)
    } catch (e) {
      setError(errorText(t, e))
      api.illustration(id).then(setItem, () => {})
    }
    setBusy('')
  }
  const drawAgain = async () => {
    if (!item) return
    setError('')
    try {
      await draw(item)
    } catch (e) {
      setError(errorText(t, e))
      api.illustration(id).then(setItem, () => {})
    }
    setBusy('')
  }
  // The name being typed; null while it is not being changed.
  const [name, setName] = useState<string | null>(null)
  const rename = async () => {
    if (name === null || !item) return
    if (name.trim() === item.title) return setName(null)
    try {
      setItem(await api.renameIllustration(id, name))
    } catch (e) {
      setError(errorText(t, e))
    }
    setName(null)
  }
  const remove = async () => {
    if (!(await ask(t('images.delete.confirm')))) return
    try {
      await api.deleteIllustration(id)
      onDeleted()
    } catch (e) {
      setError(errorText(t, e))
    }
  }

  // Every picture of the dialogue, to leaf through in the lightbox.
  const drawn = (item?.messages ?? []).map((m) => m.image_url).filter(Boolean)
  // The last message is a plan not drawn yet: the user said "No" to drawing without a reference.
  const waiting = item?.messages.length ? item.messages[item.messages.length - 1].prompt !== '' : false

  return (
    <section className="stack illustration-chat">
      {/* The name can be changed; "Pick from the book" is an icon beside the bin (owner's notes 27.11, item 15). */}
      <div className="row illustration-head">
        <input
          className="illustration-title grow"
          value={name ?? item?.title ?? ''}
          maxLength={300}
          placeholder={t('images.untitled')}
          title={t('images.rename')}
          aria-label={t('images.rename')}
          disabled={!item}
          onChange={(e) => setName(e.target.value)}
          onBlur={rename}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.currentTarget.blur()
            if (e.key === 'Escape') {
              setName(null)
              e.currentTarget.blur()
            }
          }}
        />
        <button
          className="btn ghost small icon"
          disabled={busy !== ''}
          title={t('images.pick')}
          aria-label={t('images.pick')}
          onClick={() => setPicking(true)}
        >
          <BookIcon />
        </button>
        <button className="btn ghost small icon gold" title={t('app.delete')} aria-label={t('app.delete')} onClick={remove}>
          <TrashIcon />
        </button>
        <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="stack illustration-log">
        {item?.messages.length === 0 && <p className="faint">{t('images.start')}</p>}
        {item?.messages.map((m, n) => (
          <div key={n} className={`illustration-bubble ${m.role}`}>
            {m.text && <p>{m.text}</p>}
            {m.cast.length > 0 && (
              <p className="small muted">
                {t('images.cast')}: {m.cast.join(', ')}
              </p>
            )}
            {m.prompt && (
              <details>
                <summary className="small muted">{t('gallery.prompt.show')}</summary>
                <p className="small prompt-last">{m.prompt}</p>
              </details>
            )}
            {m.reference_urls.length > 0 && (
              <div className="used-refs">
                {m.reference_urls.map((url, k) => (
                  <a key={url} {...zoomLink(m.reference_urls, k)}>
                    <img src={url} alt="" loading="lazy" />
                  </a>
                ))}
              </div>
            )}
            {m.image_url && (
              <a {...zoomLink(drawn, drawn.indexOf(m.image_url))}>
                <img className="illustration-picture" src={m.image_url} alt="" />
              </a>
            )}
            {waiting && n === item.messages.length - 1 && !busy && (
              <>
                {m.missing.length > 0 && (
                  <div className="quick-replies">
                    <span className="small muted">{t('images.missing.title')}</span>
                    {m.missing.map((who) => (
                      <button
                        key={who.entity_id}
                        className="quick-reply dim"
                        title={t('images.missing.hint')}
                        onClick={() => openCard(who)}
                      >
                        {who.name}
                      </button>
                    ))}
                  </div>
                )}
                {/* Ready answers in the gold of the chat's source numbers (owner's notes 27.11, item 21). */}
                <div className="quick-replies">
                  <button className="quick-reply" onClick={drawAgain}>
                    {t('images.draw')}
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
        {busy && (
          <div className="illustration-bubble assistant">
            <p className="muted">{busy === 'think' ? t('images.thinking') : t('images.drawing')}</p>
          </div>
        )}
        <div ref={end} />
      </div>
      {error && <p className="error small">{error}</p>}
      {picking && (
        <BookPicker
          project={project}
          onPick={(words) => {
            setText(words)
            setPicking(false)
          }}
          onClose={() => setPicking(false)}
        />
      )}
      {/* The same field as in every dialogue, with the picture's aspect ratio (owner's notes 27.11, items 21 and 30). */}
      <Composer
        value={text}
        onChange={setText}
        onSend={send}
        placeholder={t('images.placeholder')}
        disabled={busy !== ''}
        sendDisabled={!text.trim()}
        maxLength={2000}
        onError={setError}
        size={{ value: size, onChange: setSize }}
      />
    </section>
  )
}

interface PickerProps {
  project: Project
  onPick: (words: string) => void
  onClose: () => void
}

/** "Pick from the book": a chapter, then its scenes; a press puts the scene's description
 * into the request box (owner's notes 26.11). The scenes are the chapter's one kept split,
 * the same list "Split into scenes" shows (owner's notes 27.11, item 25). */
function BookPicker({ project, onPick, onClose }: PickerProps) {
  const { t } = useI18n()
  const chapters = project.chapters.filter((c) => !c.private).sort((a, b) => a.position - b.position)
  const [chapter, setChapter] = useState<ChapterBrief | null>(null)

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll">
        <div className="row">
          {chapter && (
            <button className="btn ghost small icon" title={t('images.pick.back')} aria-label={t('images.pick.back')} onClick={() => setChapter(null)}>
              ‹
            </button>
          )}
          <h3 className="grow">{chapter ? chapter.title || t('book.untitled') : t('images.pick')}</h3>
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        {!chapter && (
          <div className="stack">
            {chapters.length === 0 && <p className="faint">{t('images.pick.no_chapters')}</p>}
            {chapters.map((c) => (
              <button key={c.id} className="btn ghost" style={{ justifyContent: 'flex-start' }} onClick={() => setChapter(c)}>
                {c.title || t('book.untitled')}
              </button>
            ))}
          </div>
        )}
        {chapter && (
          <ProposalList chapterId={chapter.id} confirm={false} onPick={(p) => onPick(p.summary || p.title)} />
        )}
      </div>
    </div>
  )
}
