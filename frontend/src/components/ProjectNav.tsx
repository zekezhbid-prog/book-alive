import { useEffect, useState, type ReactNode } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, type EntityBrief, type EntityKind, type Project, type SceneBrief, type SearchHit } from '../api'
import { errorText, useI18n } from '../i18n'
import { markMatches } from '../markMatches'
import { HandIcon, PlusIcon, SparklesIcon } from './icons'
import { AddCardDialog } from './AddCardDialog'
import { useSessionActions } from '../session'
import { useView } from '../view'

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
  const { accounts, email, logout } = useSessionActions()
  // The style belongs to the illustrator's work, not to the writer's.
  const illustrating = useView(project) === 'illustrator'
  // The search dialogs start from the chapter the user was last reading.
  useEffect(() => {
    if (!activeChapter) return
    try {
      localStorage.setItem(`lastChapter:${project.id}`, activeChapter)
    } catch {
      /* private mode: the dialog falls back to the first chapter */
    }
  }, [activeChapter, project.id])
  const current: Section =
    SECTIONS.find((s) => s !== 'chapters' && pathname.startsWith(`${base}/${s}`)) ?? 'chapters'

  const [fetched, setFetched] = useState<{
    characters?: EntityBrief[]
    locations?: EntityBrief[]
    scenes?: SceneBrief[]
  }>({})
  const [error, setError] = useState('')
  // A list the page passes in (even while it is still loading) is not fetched again here.
  const hasCharacters = given.characters !== undefined
  const hasLocations = given.locations !== undefined
  const hasScenes = given.scenes !== undefined
  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    if (!hasCharacters)
      api.entities(project.id, 'character').then((characters) => setFetched((f) => ({ ...f, characters })), fail)
    if (!hasLocations)
      api.entities(project.id, 'location').then((locations) => setFetched((f) => ({ ...f, locations })), fail)
    if (!hasScenes) api.scenes(project.id).then((scenes) => setFetched((f) => ({ ...f, scenes })), fail)
  }, [project.id, t, hasCharacters, hasLocations, hasScenes])
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
  const [adding, setAdding] = useState<'characters' | 'locations' | null>(null)
  const addCard = (section: 'characters' | 'locations') => setAdding(section)
  const added = (section: 'characters' | 'locations', created: EntityBrief) => {
    setAdding(null)
    setFetched((f) => {
      const list = f[section] ?? []
      // The server returns the existing card when the name is already taken.
      return { ...f, [section]: list.some((e) => e.id === created.id) ? list : [...list, created] }
    })
    navigate(`${base}/${section}/${created.id}`)
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
      </>
    )
  }

  /** Beside the list's heading, where they are seen at once: add by hand or find in the book. */
  function cardActions(section: 'characters' | 'locations') {
    return (
      <span className="nav-actions">
        <button
          className="btn primary nav-action"
          title={t(`nav.add.${section}`)}
          aria-label={t(`nav.add.${section}`)}
          onClick={() => addCard(section)}
        >
          <PlusIcon />
          <HandIcon />
        </button>
        {/* AI reads the chosen chapters and fills the list; the dialog opens on the section's page. */}
        <button
          className="btn primary nav-action"
          title={t(`nav.find.${section}`)}
          aria-label={t(`nav.find.${section}`)}
          onClick={() => navigate(`${base}/${section}?find=1`)}
        >
          <SparklesIcon />
        </button>
      </span>
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
          {/* The style is a step of the illustrator's work (references and frames wait for it),
              so it stands with the parts of the book, flagged while it is not chosen. */}
          {illustrating && (
            <Link
              to={`${base}/style`}
              className={`nav-head ${pathname.startsWith(`${base}/style`) ? 'current' : ''}`}
            >
              <span className="grow">{t('tabs.style')}</span>
              {!project.style_id && <span className="nav-count nav-flag">{t('style.not_chosen')}</span>}
              <span className="nav-chevron">›</span>
            </Link>
          )}
        </nav>
        {/* The project's own links and the app's settings, at the foot of the first column. */}
        <nav className="nav-footer">
          <Link to="/">{t('nav.my_projects')}</Link>
          <Link to={`${base}/usage`}>{t('tabs.usage')}</Link>
          <Link to="/settings">{t('app.settings')}</Link>
          {accounts && (
            <button title={email} onClick={logout}>
              {t('login.logout')}
            </button>
          )}
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
              <div className="nav-list-head">
                <h4>{t(`nav.${current}`)}</h4>
                {(current === 'characters' || current === 'locations') && cardActions(current)}
              </div>
              <nav>{body[current]}</nav>
            </>
          )}
        </div>
      )}
      {adding && (
        <AddCardDialog
          projectId={project.id}
          kind={KIND[adding]}
          onClose={() => setAdding(null)}
          onCreated={(created) => added(adding, created)}
        />
      )}
    </aside>
  )
}
