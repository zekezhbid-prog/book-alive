import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, type EntityBrief, type EntityKind, type Project, type SceneBrief, type SearchHit } from '../api'
import { errorText, useI18n } from '../i18n'
import { markMatches } from '../markMatches'
import { PlusIcon, SparklesIcon } from './icons'
import { askText } from '../dialogs'

type Section = 'chapters' | 'characters' | 'locations' | 'scenes'
const SECTIONS: Section[] = ['chapters', 'characters', 'locations', 'scenes']
const KIND: Record<'characters' | 'locations', EntityKind> = { characters: 'character', locations: 'location' }

interface Props {
  project: Project
  /** The chapter shown on the book page (it falls back to the first one). */
  activeChapter?: string
  /** A page passes the list it keeps current itself, so a running search shows up here too. */
  characters?: EntityBrief[] | null
  locations?: EntityBrief[] | null
  scenes?: SceneBrief[] | null
  /** Only while writing: adds a chapter after the open one. */
  onAddChapter?: () => void
}

/**
 * The left menu of a project: the book search and the parts of the book in a narrow
 * column, the list of the chosen part beside it. Choosing a part goes to its page, so the
 * tab above lights up with it.
 */
export default function ProjectNav({ project, activeChapter, onAddChapter, ...given }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { entityId, sceneId } = useParams()
  const base = `/projects/${project.id}`
  const current: Section =
    SECTIONS.find((s) => s !== 'chapters' && pathname.startsWith(`${base}/${s}`)) ?? 'chapters'

  const [fetched, setFetched] = useState<{
    characters?: EntityBrief[]
    locations?: EntityBrief[]
    scenes?: SceneBrief[]
  }>({})
  const [error, setError] = useState('')
  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    api.entities(project.id, 'character').then((characters) => setFetched((f) => ({ ...f, characters })), fail)
    api.entities(project.id, 'location').then((locations) => setFetched((f) => ({ ...f, locations })), fail)
    api.scenes(project.id).then((scenes) => setFetched((f) => ({ ...f, scenes })), fail)
  }, [project.id, t])
  const characters = given.characters ?? fetched.characters
  const locations = given.locations ?? fetched.locations
  const scenes = given.scenes ?? fetched.scenes

  // The current section's list unfolds to the right as a second column. Another section
  // goes to its page with the list open; the current one folds the list away and back.
  const [open, setOpen] = useState(() => localStorage.getItem('nav:folded') !== '1')
  const remember = (next: boolean) => {
    setOpen(next)
    localStorage.setItem('nav:folded', next ? '0' : '1')
  }
  const choose = (section: Section) => {
    if (section === current) return remember(!open)
    remember(true)
    navigate(section === 'chapters' ? base : `${base}/${section}`)
  }

  // Chapters whose scenes are folded away in the list; a click on the chapter title toggles.
  const [foldedChapters, setFoldedChapters] = useState<Set<string>>(new Set())
  const toggleChapter = (id: string) =>
    setFoldedChapters((folded) => {
      const next = new Set(folded)
      if (!next.delete(id)) next.add(id)
      return next
    })
  const [showVivid, setShowVivid] = useState(() => localStorage.getItem('nav:vivid') !== '0')
  const toggleVivid = () => {
    setShowVivid(!showVivid)
    localStorage.setItem('nav:vivid', showVivid ? '0' : '1')
  }

  const [query, setQuery] = useState('')
  const [found, setHits] = useState<SearchHit[] | null>(null)
  const searching = query.trim().length >= 2
  const hits = searching ? found : null
  useEffect(() => {
    if (!searching) return
    const timer = setTimeout(
      () => api.search(project.id, query).then(setHits, (e) => setError(errorText(t, e))),
      250,
    )
    return () => clearTimeout(timer)
  }, [query, searching, project.id, t])
  const openHit = (hit: SearchHit) => {
    const params = new URLSearchParams({ p: String(hit.paragraph), q: query.trim() })
    navigate(`${base}/chapters/${hit.chapter_id}?${params}`)
  }

  // A card for someone the search has not reached yet, so pictures can be attached now.
  const addCard = async (section: 'characters' | 'locations') => {
    const name = (await askText(t('entities.add.prompt')))?.trim()
    if (!name) return
    try {
      const created = await api.createEntity(project.id, KIND[section], name)
      setFetched((f) => ({ ...f, [section]: [...(f[section] ?? []), created] }))
      navigate(`${base}/${section}/${created.id}`)
    } catch (e) {
      setError(errorText(t, e))
    }
  }

  const count = (section: Section) =>
    ({
      chapters: project.chapters.length,
      characters: characters?.length,
      locations: locations?.length,
      scenes: scenes?.length,
    })[section]

  const body: Record<Section, ReactNode> = {
    chapters: (
      <>
        {project.chapters.map((item, index) => (
          <button
            key={item.id}
            className={`chapter-link ${current === 'chapters' && item.id === activeChapter ? 'active' : ''}`}
            onClick={() => navigate(`${base}/chapters/${item.id}`)}
          >
            {/* A title like "Глава 3" or "III" already carries its number. */}
            {!/\d|^[IVXLC]+\b/.test(item.title) && <span className="chapter-num">{index + 1}</span>}
            <span className={item.title ? '' : 'faint'}>{item.title || t('book.untitled')}</span>
            {project.changes?.edited.includes(item.id) || project.changes?.added.includes(item.id) ? (
              <span className="dot" title={t('versions.dirty')} />
            ) : null}
          </button>
        ))}
        {onAddChapter && (
          <button className="nav-add" onClick={onAddChapter}>
            <PlusIcon /> {t('chapter.add')}
          </button>
        )}
      </>
    ),
    characters: cards('characters', characters),
    locations: cards('locations', locations),
    scenes: (
      <>
        {scenes?.length === 0 && <p className="faint small nav-empty">{t('scenes.empty')}</p>}
        {scenes?.some((s) => s.vivid) && (
          <button
            className={`nav-toggle ${showVivid ? 'on' : ''}`}
            aria-pressed={showVivid}
            title={t('scenes.vivid.hint')}
            onClick={toggleVivid}
          >
            {t('scenes.vivid.toggle')}
          </button>
        )}
        {scenes?.map((item, i) => (
          <div key={item.id}>
            {item.chapter_id !== scenes[i - 1]?.chapter_id && (
              <button
                className="nav-group"
                aria-expanded={!foldedChapters.has(item.chapter_id)}
                onClick={() => toggleChapter(item.chapter_id)}
              >
                <span className="nav-group-chevron">{foldedChapters.has(item.chapter_id) ? '▸' : '▾'}</span>
                <span className="grow">{item.chapter_title || t('book.untitled')}</span>
              </button>
            )}
            <button
              className={`chapter-link entity-link ${item.id === sceneId ? 'active' : ''}`}
              hidden={foldedChapters.has(item.chapter_id)}
              onClick={() => navigate(`${base}/scenes/${item.id}`)}
            >
              <span>
                {showVivid && item.vivid && (
                  <span className="vivid" title={t('scenes.vivid')}>
                    ★{' '}
                  </span>
                )}
                {item.title || t('book.untitled')}
              </span>
              {item.stale && <span className="dot" title={t('scene.stale')} />}
              {item.has_prompt && (
                <span className="has-prompt" title={t('scenes.has_prompt')}>
                  ✓
                </span>
              )}
            </button>
          </div>
        ))}
      </>
    ),
  }

  function cards(section: 'characters' | 'locations', list?: EntityBrief[] | null) {
    return (
      <>
        {list?.map((item) => (
          <button
            key={item.id}
            className={`chapter-link entity-link ${current === section && item.id === entityId ? 'active' : ''}`}
            onClick={() => navigate(`${base}/${section}/${item.id}`)}
          >
            <span>{item.name}</span>
            {item.stale && <span className="dot" title={t('entities.stale.hint')} />}
            <span className="faint small">{item.chapters}</span>
          </button>
        ))}
        <button className="nav-add" onClick={() => addCard(section)}>
          <PlusIcon /> {t(`nav.add.${section}`)}
        </button>
        {/* AI reads the chosen chapters and fills the list; the dialog opens on the section's page. */}
        <button
          className="nav-add"
          title={t(`entities.search.hint.${KIND[section]}`)}
          onClick={() => navigate(`${base}/${section}?find=1`)}
        >
          <SparklesIcon /> {t(`nav.find.${section}`)}
        </button>
      </>
    )
  }

  return (
    <aside className="project-nav">
      <div className="nav-rail">
        <input
          className="input"
          type="search"
          placeholder={t('book.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <nav className="nav-sections">
          {SECTIONS.map((section) => (
            <button
              key={section}
              className={`nav-head ${section === current ? 'current' : ''}`}
              aria-expanded={section === current && open}
              onClick={() => choose(section)}
            >
              <span className="grow">{t(`nav.${section}`)}</span>
              {count(section) !== undefined && <span className="nav-count">{count(section)}</span>}
              <span className="nav-chevron">{section === current && open ? '‹' : '›'}</span>
            </button>
          ))}
        </nav>
      </div>
      {/* Search results take the list's place while there is a query. */}
      {(hits || open) && (
        <div className="nav-list">
          {error && <p className="error small">{error}</p>}
          {hits ? (
            <>
              <h4>{hits.length ? t('book.search.results', { n: hits.length }) : t('book.search.none')}</h4>
              <nav>
                {hits.map((hit, i) => (
                  <button key={i} className="hit" onClick={() => openHit(hit)}>
                    <span className="faint small">{hit.chapter_title || t('book.untitled')}</span>
                    <span>…{markMatches(hit.snippet, query, (text) => [text])}…</span>
                  </button>
                ))}
              </nav>
            </>
          ) : (
            <>
              <h4>{t(`nav.${current}`)}</h4>
              <nav>{body[current]}</nav>
            </>
          )}
        </div>
      )}
    </aside>
  )
}
