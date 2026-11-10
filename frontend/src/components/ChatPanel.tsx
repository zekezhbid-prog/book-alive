import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import {
  api,
  ApiError,
  type ChapterBrief,
  type ChatMessage,
  type ChatStatus,
  type ChatThread,
  type Citation,
} from '../api'
import { errorText, useI18n } from '../i18n'
import { ask } from '../dialogs'
import AiNotice, { useTextModelReady } from './AiNotice'
import { BoldPlusIcon, CloseIcon, GearIcon, SaveIcon, TrashIcon } from './icons'

interface Props {
  projectId: string
  chapters: ChapterBrief[]
  /** The chapter open in the reader: lets the user ask about "here". */
  chapterId?: string
  /** Writer projects: offer ideas for what happens next in the open chapter. */
  canSuggest?: boolean
}

/** Errors the reader can act on are named; anything else (a model that broke its format,
 * a provider or network failure) is one plain line, with no technical details. */
function useChatError() {
  const { t } = useI18n()
  return (error: unknown) =>
    error instanceof ApiError && ['text_model_not_configured', 'chat_busy'].includes(error.code)
      ? errorText(t, error)
      : t('error.chat_failed')
}

/** Questions about the book. Answers come only from its text, with links to the source.
 * The book has several conversations; each keeps its own history and may be limited to
 * chosen chapters. */
export default function ChatPanel({ projectId, chapters, chapterId, canSuggest }: Props) {
  const { t } = useI18n()
  const aiReady = useTextModelReady()
  const chatError = useChatError()
  const [threads, setThreads] = useState<ChatThread[]>([])
  const [threadId, setThreadId] = useState('')
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [question, setQuestion] = useState('')
  const [waiting, setWaiting] = useState(false)
  // What the agent is doing right now, so a long answer does not look like a hang.
  const [status, setStatus] = useState<ChatStatus | null>(null)
  const [error, setError] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const asked = useRef(false)
  // A question asked earlier and still being answered on the server: the reader left
  // the page and came back. Shown with the agent's step until the answer is saved.
  const [resumed, setResumed] = useState('')
  const sending = useRef(false)
  const thread = threads.find((th) => th.id === threadId) ?? null

  const reloadThreads = useCallback(
    () =>
      api.chats(projectId).then((list) => {
        setThreads(list)
        return list
      }),
    [projectId],
  )
  useEffect(() => {
    setThreadId('')
    setMessages([])
    // The most recent conversation opens first.
    reloadThreads().then(
      (list) => setThreadId(list[0]?.id ?? ''),
      (e) => setError(errorText(t, e)),
    )
  }, [reloadThreads, t])
  useEffect(() => {
    setSettingsOpen(false)
    setResumed('')
    if (!threadId) return setMessages([])
    let stopped = false
    let timer = 0
    const load = async () => {
      const [list, info] = await Promise.all([
        api.chatMessages(projectId, threadId),
        api.chatThread(projectId, threadId),
      ])
      if (stopped) return
      setMessages(list)
      // While this page sends a question itself, its own stream shows the progress.
      const pending = sending.current ? '' : info.pending_question
      setResumed(pending)
      if (pending) {
        setStatus(info.status)
        timer = window.setTimeout(() => load().catch(() => {}), 2000)
      } else if (!sending.current) {
        setStatus(null)
      }
    }
    load().catch((e) => !stopped && setError(errorText(t, e)))
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  }, [projectId, threadId, t])
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'end' })
  }, [messages, waiting])
  useEffect(() => {
    // The field was disabled while the agent worked: give it back for the next question.
    if (!waiting && asked.current) input.current?.focus()
  }, [waiting])

  /** The open conversation, created on the first question if there is none yet. */
  const currentThread = async (): Promise<string> => {
    if (threadId) return threadId
    const created = await api.newChat(projectId)
    setThreads((list) => [created, ...list])
    setThreadId(created.id)
    return created.id
  }
  const afterAnswer = (added: ChatMessage[]) => {
    setMessages((list) => [...list, ...added])
    // The first question names the conversation and moves it to the top.
    reloadThreads().catch(() => {})
  }

  const send = async (event: FormEvent) => {
    event.preventDefault()
    const text = question.trim()
    if (!text || waiting) return
    asked.current = true
    sending.current = true
    setWaiting(true)
    setError('')
    try {
      const id = await currentThread()
      afterAnswer(await api.ask(projectId, id, text, chapterId, setStatus))
      setQuestion('')
    } catch (e) {
      setError(chatError(e))
    } finally {
      sending.current = false
      setWaiting(false)
      setStatus(null)
    }
  }
  const suggest = async () => {
    if (waiting) return
    setWaiting(true)
    setError('')
    try {
      const id = await currentThread()
      afterAnswer(await api.suggest(projectId, id, t('chat.suggest.question'), chapterId))
    } catch (e) {
      setError(chatError(e))
    } finally {
      setWaiting(false)
    }
  }
  const newChat = async () => {
    if (waiting) return
    // An empty conversation is already new: no need for another one.
    if (thread && messages.length === 0) return input.current?.focus()
    setError('')
    try {
      const created = await api.newChat(projectId)
      setThreads((list) => [created, ...list])
      setThreadId(created.id)
      input.current?.focus()
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  const remove = async () => {
    if (!thread || !(await ask(t('chat.delete.confirm', { title: label(thread) })))) return
    try {
      await api.deleteChat(projectId, thread.id)
      const list = await reloadThreads()
      setThreadId(list[0]?.id ?? '')
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  const label = (th: ChatThread) => th.title || t('chat.untitled')
  /** "Whole book", the chosen chapters by number and title when few, else how many. */
  const scopeText = (th: ChatThread) => {
    if (th.chapter_ids.length === 0) return t('chat.scope.book')
    if (th.chapter_ids.length > 3) return t('chat.scope.many', { n: th.chapter_ids.length })
    const names = chapters.flatMap((c, i) =>
      th.chapter_ids.includes(c.id) ? [`${i + 1}. ${c.title || t('book.untitled')}`] : [],
    )
    return t('chat.scope.chapters', { list: names.join('; ') })
  }

  return (
    <div className="chat">
      <div className="row chat-head">
        <h4>{t('chat.title')}</h4>
        <span className="spacer" />
        <button
          className="btn primary nav-action"
          onClick={newChat}
          disabled={waiting}
          title={t('chat.new')}
          aria-label={t('chat.new')}
        >
          <BoldPlusIcon />
        </button>
      </div>
      {threads.length > 0 && (
        <div className="row chat-threads">
          {/* Opens over the conversation, so the messages below never move. */}
          <select
            className="input small"
            value={threadId}
            disabled={waiting}
            aria-label={t('chat.choose')}
            onChange={(e) => setThreadId(e.target.value)}
          >
            {threads.map((th) => (
              <option key={th.id} value={th.id}>
                {label(th)}
              </option>
            ))}
          </select>
          {thread && (
            <button
              className="btn primary nav-action"
              onClick={() => setSettingsOpen((open) => !open)}
              disabled={waiting}
              title={t('chat.settings')}
              aria-label={t('chat.settings')}
              aria-expanded={settingsOpen}
            >
              <GearIcon />
            </button>
          )}
          {thread && settingsOpen && (
            <ThreadSettings
              key={thread.id}
              thread={thread}
              chapters={chapters}
              onCancel={() => setSettingsOpen(false)}
              onDelete={remove}
              onSave={async (fields) => {
                try {
                  const saved = await api.updateChat(projectId, thread.id, fields)
                  setThreads((list) => list.map((th) => (th.id === saved.id ? saved : th)))
                  setSettingsOpen(false)
                } catch (e) {
                  setError(errorText(t, e))
                }
              }}
            />
          )}
        </div>
      )}
      {thread && (
        <button className="chat-scope faint small" onClick={() => setSettingsOpen(true)}>
          {scopeText(thread)}
        </button>
      )}
      <div className="chat-log">
        {messages.length === 0 && !waiting && !resumed && <p className="faint small">{t('chat.hint')}</p>}
        {messages.map((message) => (
          <div key={message.id} className={`bubble ${message.role}`}>
            {message.role === 'user' ? (
              message.content
            ) : (
              <Answer projectId={projectId} message={message} />
            )}
          </div>
        ))}
        {resumed && !waiting && <div className="bubble user">{resumed}</div>}
        {(waiting || resumed) && <Waiting status={status} />}
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
          disabled={waiting || !!resumed}
          ref={input}
          onChange={(e) => setQuestion(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) send(e)
          }}
        />
        {/* Stays bright with an empty field too: a dim button reads as broken. */}
        <button className="btn primary" disabled={waiting || !!resumed}>
          {t('chat.send')}
        </button>
      </form>
    </div>
  )
}

/** Name of a conversation and where it looks: the whole book (the default) or the
 * chapters ticked here. Nothing changes until Save. */
function ThreadSettings({
  thread,
  chapters,
  onSave,
  onCancel,
  onDelete,
}: {
  thread: ChatThread
  chapters: ChapterBrief[]
  onSave: (fields: { title: string; chapter_ids: string[] }) => Promise<void>
  onCancel: () => void
  onDelete: () => void
}) {
  const { t } = useI18n()
  const [title, setTitle] = useState(thread.title)
  const [whole, setWhole] = useState(thread.chapter_ids.length === 0)
  const [chosen, setChosen] = useState<Set<string>>(new Set(thread.chapter_ids))
  const [saving, setSaving] = useState(false)
  useEffect(() => {
    const close = (e: KeyboardEvent) => e.key === 'Escape' && onCancel()
    window.addEventListener('keydown', close)
    return () => window.removeEventListener('keydown', close)
  }, [onCancel])
  const toggle = (id: string) =>
    setChosen((set) => {
      const next = new Set(set)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  // Ticking nothing would mean "nowhere": not allowed, the whole book is the way back.
  const valid = whole || chosen.size > 0
  const save = async () => {
    setSaving(true)
    await onSave({
      title,
      chapter_ids: whole ? [] : chapters.filter((c) => chosen.has(c.id)).map((c) => c.id),
    })
    setSaving(false)
  }
  return (
    <div className="chat-settings" role="dialog" aria-label={t('chat.settings')}>
      <div className="row">
        <label className="small faint" htmlFor="chat-title">
          {t('chat.settings.name')}
        </label>
        <span className="spacer" />
        <button
          className="btn ghost icon chat-settings-close"
          onClick={onCancel}
          title={t('app.cancel')}
          aria-label={t('app.cancel')}
        >
          <CloseIcon />
        </button>
      </div>
      <input
        id="chat-title"
        className="input small"
        value={title}
        maxLength={200}
        placeholder={t('chat.untitled')}
        onChange={(e) => setTitle(e.target.value)}
      />
      <span className="small faint">{t('chat.settings.scope')}</span>
      <label className="row">
        <input type="radio" checked={whole} onChange={() => setWhole(true)} />
        {t('chat.settings.book')}
      </label>
      <label className="row">
        <input type="radio" checked={!whole} onChange={() => setWhole(false)} />
        {t('chat.settings.chapters')}
      </label>
      {!whole && (
        <div className="chapter-picker">
          {chapters.map((chapter, i) => (
            <label key={chapter.id} className="row">
              <input
                type="checkbox"
                checked={chosen.has(chapter.id)}
                onChange={() => toggle(chapter.id)}
              />
              <span className="grow">
                {i + 1}. {chapter.title || t('book.untitled')}
              </span>
            </label>
          ))}
        </div>
      )}
      {!valid && <p className="error small">{t('chat.settings.none')}</p>}
      <div className="row chat-settings-actions">
        <button
          className="btn primary nav-action"
          disabled={!valid || saving}
          onClick={save}
          title={t('chat.settings.save')}
          aria-label={t('chat.settings.save')}
        >
          <SaveIcon />
        </button>
        <span className="spacer" />
        <button
          className="btn ghost icon danger"
          onClick={onDelete}
          title={t('chat.delete')}
          aria-label={t('chat.delete')}
        >
          <TrashIcon />
        </button>
      </div>
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
