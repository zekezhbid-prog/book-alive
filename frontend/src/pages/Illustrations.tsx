import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, peek, type Illustration, type IllustrationBrief, type Project } from '../api'
import PageClose from '../components/PageClose'
import ProjectHeader from '../components/ProjectHeader'
import { MicButton } from '../components/MicButton'
import { BoldPlusIcon, ImageIcon, SparklesIcon, TrashIcon } from '../components/icons'
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
          <button className="btn primary" onClick={add}>
            <BoldPlusIcon />
            {t('images.add')}
          </button>
          <PageClose fallback={`/projects/${projectId}`} />
        </div>
        {error && <p className="error">{error}</p>}
        {!project.style_id && <p className="faint small">{t('generate.no_style')}</p>}
        {illustrationId ? (
          <IllustrationChat
            key={illustrationId}
            id={illustrationId}
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
  onClose: () => void
  onDeleted: () => void
}

/** The dialogue of one picture: the user's words, the model's questions and plans, pictures. */
function IllustrationChat({ id, onClose, onDeleted }: ChatProps) {
  const { t } = useI18n()
  const [item, setItem] = useState<Illustration | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState<'' | 'think' | 'draw'>('')
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.illustration(id).then(setItem, (e) => setError(errorText(t, e)))
  }, [id, t])
  useEffect(() => end.current?.scrollIntoView({ block: 'end' }), [item, busy])

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
      if (answered.messages[answered.messages.length - 1]?.prompt) {
        setBusy('draw')
        setItem(await api.drawIllustration(id))
      }
    } catch (e) {
      setError(errorText(t, e))
      api.illustration(id).then(setItem, () => {})
    }
    setBusy('')
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

  return (
    <section className="stack illustration-chat">
      <div className="row">
        <h3 className="grow">{item?.title || t('images.untitled')}</h3>
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
                {m.reference_urls.map((url) => (
                  <a key={url} href={url} target="_blank" rel="noreferrer">
                    <img src={url} alt="" loading="lazy" />
                  </a>
                ))}
              </div>
            )}
            {m.image_url && (
              <a href={m.image_url} target="_blank" rel="noreferrer">
                <img className="illustration-picture" src={m.image_url} alt="" />
              </a>
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
      <div className="row">
        <textarea
          className="input grow"
          rows={2}
          value={text}
          maxLength={2000}
          placeholder={t('images.placeholder')}
          disabled={busy !== ''}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        <MicButton
          disabled={busy !== ''}
          onText={(spoken) => setText((now) => (now.trim() ? `${now.trim()} ${spoken}` : spoken))}
          onError={setError}
        />
        <button className="btn primary" disabled={busy !== '' || !text.trim()} onClick={send}>
          <SparklesIcon />
          {t('images.send')}
        </button>
      </div>
    </section>
  )
}
