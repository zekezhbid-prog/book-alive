import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { api, type Chapter, type Project } from '../api'
import { useI18n } from '../i18n'
import { enqueueSave, savesSettled } from '../saveQueue'

interface Props {
  project: Project
  chapter: Chapter
  onSaved: (saved: Chapter) => void
  onStructureChange: (goTo?: string) => void
  onError: (error: unknown) => void
}

const AUTOSAVE_MS = 800
const TITLE_MAX = 300

/** Plain-text chapter editor. The draft saves itself; versions are committed separately. */
export default function ChapterEditor({ project, chapter, onSaved, onStructureChange, onError }: Props) {
  const { t } = useI18n()
  const [title, setTitle] = useState(chapter.title)
  const [text, setText] = useState(chapter.text)
  const [status, setStatus] = useState<'saved' | 'saving' | 'unsaved'>('saved')
  const area = useRef<HTMLTextAreaElement>(null)
  // What the server is known to have; anything different is still to be saved.
  const saved = useRef({ title: chapter.title, text: chapter.text })
  const latest = useRef({ title, text })
  latest.current = { title, text }

  const flush = () => {
    const sending = { ...latest.current }
    const before = saved.current
    const patch: { title?: string; text?: string } = {}
    if (sending.title !== before.title) patch.title = sending.title
    if (sending.text !== before.text) patch.text = sending.text
    if (!Object.keys(patch).length) return savesSettled()
    // Optimistic, so the next flush does not resend the same text while this one is in flight.
    saved.current = sending
    setStatus('saving')
    return enqueueSave(() =>
      api.updateChapter(chapter.id, patch).then(
        (result) => {
          setStatus('saved')
          onSaved(result)
        },
        (error) => {
          // Not on the server after all: the next keystroke, blur or leaving the chapter retries.
          if (saved.current === sending) saved.current = before
          setStatus('unsaved')
          onError(error)
        },
      ),
    )
  }

  useEffect(() => {
    const timer = setTimeout(flush, AUTOSAVE_MS)
    return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [title, text])
  // Leaving the chapter must not lose the last keystrokes.
  useEffect(
    () => () => {
      flush()
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  )

  const wrapSelection = (mark: string) => {
    const el = area.current
    if (!el) return
    const { selectionStart: start, selectionEnd: end } = el
    setText(text.slice(0, start) + mark + text.slice(start, end) + mark + text.slice(end))
    requestAnimationFrame(() => el.setSelectionRange(start + mark.length, end + mark.length))
  }
  const onKeyDown = (event: KeyboardEvent) => {
    if (!(event.ctrlKey || event.metaKey)) return
    const mark = { KeyB: '**', KeyI: '*' }[event.code]
    if (!mark) return
    event.preventDefault()
    wrapSelection(mark)
  }

  const ids = project.chapters.map((c) => c.id)
  const index = ids.indexOf(chapter.id)
  const move = async (delta: number) => {
    const next = [...ids]
    next.splice(index, 1)
    next.splice(index + delta, 0, chapter.id)
    await flush()
    await api.reorder(project.id, next).then(() => onStructureChange(chapter.id), onError)
  }
  const remove = async () => {
    const name = title || t('book.untitled')
    if (!confirm(t('chapter.delete.confirm', { title: name }))) return
    saved.current = { ...latest.current } // the chapter is going away: nothing left to save
    await savesSettled()
    await api.deleteChapter(chapter.id).then(() => onStructureChange(), onError)
  }

  return (
    <article className="chapter editor">
      <div className="chapter-tools">
        <span className="faint small">
          {t('app.chars', { n: text.length.toLocaleString() })} ·{' '}
          <span className={status === 'unsaved' ? 'error' : ''}>{t(`app.${status}`)}</span> ·{' '}
          {t('chapter.format.hint')}
        </span>
        <span className="spacer" />
        <button className="btn ghost small" disabled={index <= 0} onClick={() => move(-1)}>
          ↑ {t('chapter.up')}
        </button>
        <button className="btn ghost small" disabled={index >= ids.length - 1} onClick={() => move(1)}>
          ↓ {t('chapter.down')}
        </button>
        <button className="btn ghost small danger" onClick={remove}>
          {t('chapter.delete')}
        </button>
      </div>
      <input
        className="chapter-title"
        value={title}
        maxLength={TITLE_MAX}
        placeholder={t('chapter.title.placeholder')}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={flush}
      />
      <textarea
        ref={area}
        className="chapter-text"
        value={text}
        placeholder={t('chapter.text.placeholder')}
        onChange={(e) => setText(e.target.value)}
        onBlur={flush}
        onKeyDown={onKeyDown}
      />
    </article>
  )
}
