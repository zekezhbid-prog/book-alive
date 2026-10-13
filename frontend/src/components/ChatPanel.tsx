import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { api, type ChatMessage, type Citation } from '../api'
import { errorText, useI18n } from '../i18n'

interface Props {
  projectId: string
  /** The chapter open in the reader: lets the user ask about "here". */
  chapterId?: string
}

/** Questions about the book. Answers come only from its text, with links to the source. */
export default function ChatPanel({ projectId, chapterId }: Props) {
  const { t } = useI18n()
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [waiting, setWaiting] = useState(false)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.chat(projectId).then(setMessages, (e) => setError(errorText(t, e)))
  }, [projectId, t])
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, waiting])

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || waiting) return
    setWaiting(true)
    setError('')
    try {
      const added = await api.ask(projectId, text, chapterId)
      setMessages((list) => [...list, ...added])
      setQuestion('')
    } catch (e) {
      setError(errorText(t, e))
    } finally {
      setWaiting(false)
    }
  }
  const clear = async () => {
    if (!confirm(t('chat.clear.confirm'))) return
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
        {waiting && <div className="bubble assistant faint">{t('chat.waiting')}</div>}
        <div ref={end} />
      </div>
      {error && <p className="error small">{error}</p>}
      <form className="chat-form" onSubmit={send}>
        <textarea
          className="input"
          rows={2}
          value={question}
          placeholder={t('chat.placeholder')}
          maxLength={4000}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) send(e)
          }}
        />
        <button className="btn primary" disabled={waiting || !question.trim()}>
          {t('chat.send')}
        </button>
      </form>
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
