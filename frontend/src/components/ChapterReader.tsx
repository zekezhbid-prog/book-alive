import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { api, sectionOf, type Chapter, type EntityKind, type Project } from '../api'
import { useI18n, type MessageKey } from '../i18n'
import { markMatches } from '../markMatches'
import { chooseSplit } from '../sceneSplit'
import { ChevronIcon, ClapperIcon, CloseIcon, LockIcon } from './icons'

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
  onError: (error: unknown) => void
  /** The chapter was closed to AI or opened again. */
  onChanged?: (chapter: Chapter) => void
}

/** The chapter as read: nothing in it can be changed here, only scenes picked from it. */
export default function ChapterReader({
  project,
  chapter,
  names,
  highlighted,
  found,
  onError,
  onChanged,
}: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [splitting, setSplitting] = useState(false)
  // Paragraphs covered by the current text selection: a scene the user can mark.
  const [picked, setPicked] = useState<[number, number] | null>(null)
  const target = useRef<HTMLParagraphElement>(null)
  const paragraphs = chapter.text ? chapter.text.split('\n\n') : []
  const place = project.chapters.findIndex((c) => c.id === chapter.id)
  const previous = place > 0 ? project.chapters[place - 1] : undefined
  const next = place >= 0 ? project.chapters[place + 1] : undefined
  const linker = useMemo<Linker>(() => {
    const link = buildLinker(project.id, names)
    return (text, key) => markMatches(text, found, (part, sub) => link(part, `${key}${sub}`))
  }, [project.id, names, found])

  const article = useRef<HTMLElement>(null)
  const scroller = useRef<HTMLDivElement>(null)
  // Set by the arrows below: the bar was pinned (the text scrolled past the chapter's top).
  const pinned = (useLocation().state as { pinned?: boolean } | null)?.pinned === true
  useEffect(() => {
    const still = !!article.current && getComputedStyle(article.current).position === 'fixed'
    // On a phone only the text moves: scrollIntoView would also shift the page under the
    // still window (owner's notes 27.11, item 24).
    if (target.current && still && scroller.current) {
      const box = scroller.current
      const top = target.current.getBoundingClientRect().top - box.getBoundingClientRect().top
      box.scrollTop += top - box.clientHeight / 2 + target.current.offsetHeight / 2
      return
    }
    if (target.current) return target.current.scrollIntoView({ block: 'center' })
    // A phone scrolls the text inside the chapter: a new chapter starts at its top.
    if (scroller.current) scroller.current.scrollTop = 0
    if (still) return
    // Leafed on from the pinned bar (owner's notes 27.11): while the next chapter loaded the
    // page was short and the scroll fell back to the top; the new text starts under the bar.
    if (pinned || (article.current?.getBoundingClientRect().top ?? 0) < 0)
      article.current?.scrollIntoView({ block: 'start' })
    // Only a new chapter or paragraph scrolls; `pinned` comes with the chapter's address.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [highlighted, chapter.id])

  const splitIntoScenes = async () => {
    try {
      const choice = await chooseSplit(t, chapter.id)
      if (!choice) return
      if ('show' in choice) return navigate(`/projects/${project.id}/scenes/${choice.show}`)
      setSplitting(true)
      const scenes = await api.splitScenes(chapter.id, choice.again)
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
  const togglePrivate = () =>
    api.updateChapter(chapter.id, { private: !chapter.private }).then((c) => onChanged?.(c), onError)
  const markScene = async () => {
    if (!picked) return
    await api
      .markScene(chapter.id, picked[0], picked[1])
      .then((scene) => navigate(`/projects/${project.id}/scenes/${scene.id}`), onError)
  }

  const first = project.chapters[0]
  const last = project.chapters[project.chapters.length - 1]
  const go = (to: { id: string } | undefined) => {
    if (!to || to.id === chapter.id) return
    const pinnedNow = (article.current?.getBoundingClientRect().top ?? 0) < 0
    navigate(`/projects/${project.id}/chapters/${to.id}`, { state: { pinned: pinnedNow } })
  }
  const leaf = (key: MessageKey, to: { id: string } | undefined, icon: ReactNode, label?: ReactNode) => (
    <button
      className="btn ghost small icon"
      title={t(key)}
      aria-label={t(key)}
      disabled={!to || to.id === chapter.id}
      onClick={() => go(to)}
    >
      {icon}
      {label}
    </button>
  )
  // An icon, the name is the tooltip (owner's notes 27.11, item 24).
  const splitLabel = splitting ? t('scenes.split.busy') : t('scenes.split')
  const splitButton = (
    <button
      className="btn ghost small icon"
      title={splitLabel}
      aria-label={splitLabel}
      disabled={splitting || !paragraphs.length || chapter.private}
      onClick={splitIntoScenes}
    >
      <ClapperIcon />
    </button>
  )
  // The state is the tooltip, no text by the lock (owner's notes 27.11, item 24).
  const privateLabel = chapter.private ? t('chapter.private.on') : t('chapter.private.off')

  return (
    <article className="chapter" ref={article} onMouseUp={readSelection}>
      {/* On a phone this row stays pinned at the top while the text scrolls (owner's notes 27.11). */}
      <div className="chapter-tools chapter-bar">
        <span className="faint small" style={{ whiteSpace: 'nowrap' }}>{t('app.chars', { n: chapter.chars.toLocaleString() })}</span>
        <span className="spacer" />
        {/* Leaf through the book from the chapter itself (owner's notes 26.11 and 27.11). */}
        {leaf('chapter.first', first, <ChevronIcon dir="left" double />)}
        {/* Arrows only, the name is the tooltip (owner's notes 27.11, item 16). */}
        {leaf('chapter.prev', previous, <ChevronIcon dir="left" />)}
        {leaf('chapter.next', next, <ChevronIcon dir="right" />)}
        {leaf('chapter.last', last, <ChevronIcon dir="right" double />)}
        <button
          className={`btn ghost small icon ${chapter.private ? 'on' : ''}`}
          onClick={togglePrivate}
          title={`${privateLabel}. ${t('chapter.private.hint')}`}
          aria-label={privateLabel}
          aria-pressed={chapter.private}
        >
          <LockIcon open={!chapter.private} />
        </button>
        {splitButton}
        <button
          className="btn ghost small icon phone-only"
          title={t('chapter.close')}
          aria-label={t('chapter.close')}
          onClick={() => navigate(`/projects/${project.id}`)}
        >
          <CloseIcon />
        </button>
      </div>
      {/* On a phone the chapter fills the screen and only this part scrolls (owner's notes 27.11, item 16). */}
      <div className="chapter-scroll" ref={scroller}>
        <h2 className="chapter-title">{chapter.title || t('book.untitled')}</h2>
        {paragraphs.map((paragraph, index) => (
          <p
            key={index}
            data-index={index}
            ref={index === highlighted ? target : undefined}
            className={index === highlighted ? 'highlighted' : ''}
          >
            {renderInline(paragraph, linker)}
          </p>
        ))}
      </div>
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
 * Finds names without any AI. Slavic names change their endings ("Анна", "Анны", "Анну"),
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
  // Longest first, so "Старый Тарас" wins over "Тарас".
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
      const section = sectionOf(entity.kind)
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
