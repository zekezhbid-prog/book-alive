import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type ChatMessage, type ChatStatus, type Citation } from '../api'
import { errorText, useI18n } from '../i18n'
import { ask } from '../dialogs'
import AiNotice, { useTextModelReady } from './AiNotice'

interface Props {
  projectId: string
  /** The chapter open in the reader: lets the user ask about "here". */
  chapterId?: string
  /** Writer projects: offer ideas for what happens next in the open chapter. */
  canSuggest?: boolean
}

/** Questions about the book. Answers come only from its text, with links to the source. */
export default function ChatPanel({ projectId, chapterId, canSuggest }: Props) {
  const { t } = useI18n()
  const aiReady = useTextModelReady()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [waiting, setWaiting] = useState(false)
  // What the agent is doing right now, so a long answer does not look like a hang.
  const [status, setStatus] = useState<ChatStatus | null>(null)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const asked = useRef(false)

  useEffect(() => {
    api.chat(projectId).then(setMessages, (e) => setError(errorText(t, e)))
  }, [projectId, t])
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, waiting])
  useEffect(() => {
    // The field was disabled while the agent worked: give it back for the next question.
    if (!waiting && asked.current) input.current?.focus()
  }, [waiting])

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || waiting) return
    asked.current = true
    setWaiting(true)
    setError('')
    try {
      const added = await api.ask(projectId, text, chapterId, setStatus)
      setMessages((list) => [...list, ...added])
      setQuestion('')
    } catch (e) {
      setError(errorText(t, e))
    } finally {
      setWaiting(false)
      setStatus(null)
    }
  }
  const suggest = async () => {
    if (waiting) return
    setWaiting(true)
    setError('')
    try {
      const added = await api.suggest(projectId, t('chat.suggest.question'), chapterId)
      setMessages((list) => [...list, ...added])
    } catch (e) {
      setError(errorText(t, e))
    } finally {
      setWaiting(false)
    }
  }
  const clear = async () => {
    if (!(await ask(t('chat.clear.confirm')))) return
    await api.clearChat(projectId)
    setMessages([])
  }

  return (
    <div className="chat">
      <div className="row">
        <h4>{t('chat.title')}</h4>
        <span className="spacer" />
        {messages.length > 0 && (
          <button className="btn ghost small" onClick={clear}>
            {t('chat.clear')}
          </button>
        )}
      </div>
      <div className="chat-log">
        {messages.length === 0 && !waiting && <p className="faint small">{t('chat.hint')}</p>}
        {messages.map((message) => (
          <div key={message.id} className={`bubble ${message.role}`}>
            {message.role === 'user' ? (
              message.content
            ) : (
              <Answer projectId={projectId} message={message} />
            )}
          </div>
        ))}
        {waiting && <Waiting status={status} />}
        <div ref={end} />
      </div>
      <AiNotice ready={aiReady} />
      {error && <p className="error small">{error}</p>}
      {canSuggest && (
        <button className="btn small" disabled={waiting || !chapterId} onClick={suggest}>
          {t('chat.suggest')}
        </button>
      )}
      <form className="chat-form" onSubmit={send}>
        <textarea
          className="input"
          rows={2}
          value={question}
          placeholder={t('chat.placeholder')}
          maxLength={4000}
          // No typing while the agent works: the next question waits for this answer.
          disabled={waiting}
          ref={input}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) send(e)
          }}
        />
        {/* Stays bright with an empty field too: a dim button reads as broken. */}
        <button className="btn primary" disabled={waiting}>
          {t('chat.send')}
        </button>
      </form>
    </div>
  )
}

/** The agent's current step and the seconds since the question was sent. */
function Waiting({ status }: { status: ChatStatus | null }) {
  const { t } = useI18n()
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])
  const text = status
    ? t(`chat.status.${status.code}`, { detail: status.detail })
    : t('chat.waiting')
  return (
    <div className="bubble assistant faint chat-status">
      <span className="pulse" />
      <span>
        {text}
        <span className="dots" aria-hidden="true">
          <span>.</span>
          <span>.</span>
          <span>.</span>
        </span>
      </span>
      {seconds > 0 && <span className="small">{t('chat.status.seconds', { n: seconds })}</span>}
    </div>
  )
}

function Answer({ projectId, message }: { projectId: string; message: ChatMessage }) {
  const { t } = useI18n()
  if (!message.content) return <span className="faint">{t('chat.empty_book')}</span>
  const byNumber = new Map(message.citations.map((c) => [c.n, c]))
  const href = (c: Citation) => `/projects/${projectId}/chapters/${c.chapter_id}?p=${c.paragraph}`
  // "[2]" in the answer becomes a link to passage 2; other brackets stay as text.
  const body: ReactNode[] = message.content.split(/(\[\d+\])/).map((part, i) => {
    const citation = byNumber.get(Number(part.slice(1, -1)))
    return /^\[\d+\]$/.test(part) && citation ? (
      <Link key={i} className="cite" to={href(citation)} title={citation.chapter_title}>
        {citation.n}
      </Link>
    ) : (
      part
    )
  })
  return (
    <>
      <div>{body}</div>
      {message.citations.length > 0 && (
        <ol className="sources">
          {message.citations.map((citation) => (
            <li key={citation.n} value={citation.n}>
              <Link to={href(citation)}>
                <b>{citation.chapter_title || t('book.untitled')}</b>
                {citation.quote && <span className="quote-inline"> «{citation.quote}»</span>}
              </Link>
            </li>
          ))}
        </ol>
      )}
    </>
  )
}
