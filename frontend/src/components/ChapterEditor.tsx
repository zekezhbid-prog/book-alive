import { useEffect, useRef, useState, type KeyboardEvent, type RefObject } from 'react'
import { api, type Chapter } from '../api'
import { useI18n } from '../i18n'
import { enqueueSave, savesSettled } from '../saveQueue'

interface Props {
  chapter: Chapter
  onSaved: (saved: Chapter) => void
  onError: (error: unknown) => void
  /** Filled in while the editor is open, so the chapter list can save the draft before it
   * moves chapters, and forget it when the open chapter is deleted. */
  control?: RefObject<EditorControl | null>
}

export interface EditorControl {
  flush: () => Promise<void>
  discard: () => Promise<void>
}

const AUTOSAVE_MS = 800
const TITLE_MAX = 300

/** Plain-text chapter editor. The draft saves itself; versions are committed separately. */
export default function ChapterEditor({ chapter, onSaved, onError, control }: Props) {
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

  useEffect(() => {
    if (!control) return
    control.current = {
      flush: async () => {
        await flush()
      },
      discard: async () => {
        saved.current = { ...latest.current } // the chapter is going away: nothing left to save
        await savesSettled()
      },
    }
    return () => {
      control.current = null
    }
  })

  return (
    <article className="chapter editor">
      <div className="chapter-tools">
        {/* The formatting hint lives in the tooltip, so the row never wraps and squeezes the buttons. */}
        <span className="faint small chapter-status" title={t('chapter.format.hint')}>
          {t('app.chars', { n: text.length.toLocaleString() })} ·{' '}
          <span className={status === 'unsaved' ? 'error' : ''}>{t(`app.${status}`)}</span>
        </span>
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
