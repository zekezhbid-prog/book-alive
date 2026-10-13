import { useEffect, useRef, useState, type ReactNode } from 'react'
import { api, type Chapter, type Project } from '../api'
import { useI18n } from '../i18n'

interface Props {
  project: Project
  chapter: Chapter
  highlighted?: number
  onChanged: () => void
  onStructureChange: (goTo?: string) => void
  onError: (error: unknown) => void
}

/** Read-only chapter with the tools for fixing chapter boundaries after import. */
export default function ChapterReader({
  project,
  chapter,
  highlighted,
  onChanged,
  onStructureChange,
  onError,
}: Props) {
  const { t } = useI18n()
  const [title, setTitle] = useState(chapter.title)
  const target = useRef<HTMLParagraphElement>(null)
  const paragraphs = chapter.text ? chapter.text.split('\n\n') : []
  const isLast = project.chapters.at(-1)?.id === chapter.id

  useEffect(() => {
    target.current?.scrollIntoView({ block: 'center' })
  }, [highlighted, chapter.id])

  const rename = async () => {
    if (title.trim() === chapter.title) return
    await api.updateChapter(chapter.id, { title }).then(onChanged, onError)
  }
  const merge = async () => {
    if (!confirm(t('chapter.merge.confirm'))) return
    await api.mergeNext(chapter.id).then(() => onStructureChange(chapter.id), onError)
  }
  const remove = async () => {
    const name = chapter.title || t('book.untitled')
    if (!confirm(t('chapter.delete.confirm', { title: name }))) return
    await api.deleteChapter(chapter.id).then(() => onStructureChange(), onError)
  }
  const split = async (index: number) => {
    const paragraph = paragraphs[index]
    // A short line without a full stop is most likely the heading itself.
    const looksLikeHeading = paragraph.length <= 80 && !/[.!?…]$/.test(paragraph)
    const entered = prompt(t('chapter.split.title'), looksLikeHeading ? paragraph : '')
    if (entered === null) return
    await api
      .split(chapter.id, index, entered, looksLikeHeading && entered.trim() === paragraph)
      .then(([, tail]) => onStructureChange(tail.id), onError)
  }

  return (
    <article className="chapter">
      <div className="chapter-tools">
        <span className="faint small">{t('app.chars', { n: chapter.chars.toLocaleString() })}</span>
        <span className="spacer" />
        {!isLast && (
          <button className="btn ghost small" onClick={merge}>
            {t('chapter.merge')}
          </button>
        )}
        <button className="btn ghost small danger" onClick={remove}>
          {t('chapter.delete')}
        </button>
      </div>
      <input
        className="chapter-title"
        value={title}
        placeholder={t('chapter.title.placeholder')}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={rename}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          ref={index === highlighted ? target : undefined}
          className={index === highlighted ? 'highlighted' : ''}
        >
          {index > 0 && (
            <button className="split" title={t('chapter.split.here')} onClick={() => split(index)}>
              ✂
            </button>
          )}
          {renderInline(paragraph)}
        </p>
      ))}
    </article>
  )
}

/** The editor's only formatting: **bold** and *italic*. */
export function renderInline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/).map((part, i) => {
    if (part.startsWith('**') && part.length > 4) return <b key={i}>{part.slice(2, -2)}</b>
    if (part.startsWith('*') && part.length > 2) return <i key={i}>{part.slice(1, -1)}</i>
    return part
  })
}
