import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Chapter, type EntityKind, type Project } from '../api'
import { useI18n } from '../i18n'
import { markMatches } from '../markMatches'

export interface NamedEntity {
  id: string
  kind: EntityKind
  names: string[]
}

interface Props {
  project: Project
  chapter: Chapter
  /** Known characters and locations: their names in the text link to the cards. */
  names: NamedEntity[]
  highlighted?: number
  /** The search that led here: its matches are marked in the text. */
  found?: string
  onStructureChange: (goTo?: string) => void
  onError: (error: unknown) => void
}

const TITLE_MAX = 300

/** Read-only chapter with the tools for fixing chapter boundaries after import. */
export default function ChapterReader({
  project,
  chapter,
  names,
  highlighted,
  found,
  onStructureChange,
  onError,
}: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [title, setTitle] = useState(chapter.title)
  const [splitting, setSplitting] = useState(false)
  // Paragraphs covered by the current text selection: a scene the user can mark.
  const [picked, setPicked] = useState<[number, number] | null>(null)
  const target = useRef<HTMLParagraphElement>(null)
  const paragraphs = chapter.text ? chapter.text.split('\n\n') : []
  const isLast = project.chapters.at(-1)?.id === chapter.id
  const linker = useMemo<Linker>(() => {
    const link = buildLinker(project.id, names)
    return (text, key) => markMatches(text, found, (part, sub) => link(part, `${key}${sub}`))
  }, [project.id, names, found])

  useEffect(() => {
    target.current?.scrollIntoView({ block: 'center' })
  }, [highlighted, chapter.id])

  const rename = async () => {
    if (title.trim() === chapter.title) return
    await api.updateChapter(chapter.id, { title }).then(() => onStructureChange(chapter.id), onError)
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
  const splitIntoScenes = async () => {
    try {
      const estimate = await api.splitEstimate(chapter.id)
      const question =
        t('scenes.split.confirm', {
          input: estimate.input_tokens.toLocaleString(),
          output: estimate.output_tokens.toLocaleString(),
        }) + (estimate.existing ? t('scenes.split.replace', { n: estimate.existing }) : '')
      if (!confirm(question)) return
      setSplitting(true)
      const scenes = await api.splitScenes(chapter.id)
      navigate(`/projects/${project.id}/scenes/${scenes[0]?.id ?? ''}`)
    } catch (e) {
      onError(e)
    } finally {
      setSplitting(false)
    }
  }
  const readSelection = () => {
    const selection = window.getSelection()
    const paragraphOf = (node: Node | null) =>
      (node instanceof Element ? node : node?.parentElement)?.closest<HTMLElement>('p[data-index]')
    const first = paragraphOf(selection?.anchorNode ?? null)
    const last = paragraphOf(selection?.focusNode ?? null)
    if (!selection || selection.isCollapsed || !first || !last) return setPicked(null)
    const range = [Number(first.dataset.index), Number(last.dataset.index)].sort((a, b) => a - b)
    setPicked([range[0], range[1]])
  }
  const markScene = async () => {
    if (!picked) return
    await api
      .markScene(chapter.id, picked[0], picked[1])
      .then((scene) => navigate(`/projects/${project.id}/scenes/${scene.id}`), onError)
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
    <article className="chapter" onMouseUp={readSelection}>
      <div className="chapter-tools">
        <span className="faint small">{t('app.chars', { n: chapter.chars.toLocaleString() })}</span>
        <span className="spacer" />
        <button className="btn small" disabled={splitting || !paragraphs.length} onClick={splitIntoScenes}>
          {splitting ? t('scenes.split.busy') : t('scenes.split')}
        </button>
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
        maxLength={TITLE_MAX}
        placeholder={t('chapter.title.placeholder')}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={rename}
        onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
      />
      {paragraphs.map((paragraph, index) => (
        <p
          key={index}
          data-index={index}
          ref={index === highlighted ? target : undefined}
          className={index === highlighted ? 'highlighted' : ''}
        >
          {index > 0 && (
            <button className="split" title={t('chapter.split.here')} onClick={() => split(index)}>
              ✂
            </button>
          )}
          {renderInline(paragraph, linker)}
        </p>
      ))}
      {picked && (
        // onMouseDown: a click would clear the selection before it is read.
        <button className="btn primary floating" onMouseDown={(e) => e.preventDefault()} onClick={markScene}>
          {t('scenes.mark', { from: picked[0] + 1, to: picked[1] + 1 })}
        </button>
      )}
    </article>
  )
}

type Linker = (text: string, keyPrefix: string) => ReactNode[]

/** The editor's only formatting, **bold** and *italic*, plus links on known names. */
function renderInline(text: string, link: Linker): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*|\*[^*\s][^*\n]*\*)/).flatMap((part, i): ReactNode[] => {
    if (part.startsWith('**') && part.length > 4) return [<b key={i}>{link(part.slice(2, -2), `${i}`)}</b>]
    if (part.startsWith('*') && part.length > 2) return [<i key={i}>{link(part.slice(1, -1), `${i}`)}</i>]
    return link(part, `${i}`)
  })
}

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Finds names without any AI. Slavic names change their endings ("Люта", "Люты", "Люту"),
 * so a final vowel is dropped and up to three letters are allowed after the stem.
 */
function buildLinker(projectId: string, entities: NamedEntity[]): Linker {
  const targets = new Map<string, NamedEntity>()
  for (const entity of entities) {
    for (const name of entity.names) {
      const stem = name.trim().toLowerCase().replace(/(?<=.{3})[аяоеыиьйуюіaeo]$/, '')
      if (stem.length >= 3 && !targets.has(stem)) targets.set(stem, entity)
    }
  }
  if (!targets.size) return (text) => [text]
  // Longest first, so "Нашчадак Кука" wins over "Кука".
  const stems = [...targets.keys()].sort((a, b) => b.length - a.length)
  const pattern = new RegExp(
    `(?<![\\p{L}\\p{N}])(${stems.map(escapeRegExp).join('|')})\\p{L}{0,3}(?![\\p{L}\\p{N}])`,
    'giu',
  )
  return (text, keyPrefix) => {
    const out: ReactNode[] = []
    let last = 0
    for (const match of text.matchAll(pattern)) {
      const entity = targets.get(match[1].toLowerCase())
      if (!entity) continue
      out.push(text.slice(last, match.index))
      const section = entity.kind === 'character' ? 'characters' : 'locations'
      out.push(
        <Link
          key={`${keyPrefix}:${match.index}`}
          className={`name ${entity.kind}`}
          to={`/projects/${projectId}/${section}/${entity.id}`}
        >
          {match[0]}
        </Link>,
      )
      last = match.index + match[0].length
    }
    out.push(text.slice(last))
    return out
  }
}
