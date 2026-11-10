import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { api, peek, type EntityBrief, type EntityKind, type Project, type SceneBrief } from '../api'
import { errorText, useI18n } from '../i18n'
import { BoldPlusIcon, PlusIcon, SparklesIcon } from './icons'
import { AddCardDialog } from './AddCardDialog'

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
 * The list of the open part of the book (chapters, characters, locations or scenes) in a
 * column on the left. The parts themselves are the tabs of the top bar.
 */
export default function ProjectNav({ project, activeChapter, onAddChapter, ...given }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { entityId, sceneId } = useParams()
  const base = `/projects/${project.id}`
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
  }>(() => ({
    // The last lists are shown at once (no blink when switching tabs), then refreshed.
    characters: peek.entities(project.id, 'character'),
    locations: peek.entities(project.id, 'location'),
    scenes: peek.scenes(project.id),
  }))
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
    const link = (item: EntityBrief) => (
      <button
        key={item.id}
        className={`chapter-link entity-link ${item.uncertain ? 'uncertain' : ''} ${current === section && item.id === entityId ? 'active' : ''}`}
        title={item.uncertain ? t('entities.uncertain.hint') : undefined}
        onClick={() => navigate(`${base}/${section}/${item.id}`)}
      >
        <span>
          {item.uncertain && <span className="uncertain-mark">? </span>}
          {item.name}
        </span>
        {item.stale && <span className="dot" title={t('entities.stale.hint')} />}
        <span className="faint small">{item.chapters}</span>
      </button>
    )
    const doubtful = list?.filter((item) => item.uncertain) ?? []
    return (
      <>
        {list?.filter((item) => !item.uncertain).map(link)}
        {/* No proper name or a group: probably someone already known, waiting for a merge. */}
        {doubtful.length > 0 && (
          <>
            <p className="nav-subhead" title={t('entities.uncertain.hint')}>
              {t('entities.uncertain')}
            </p>
            {doubtful.map(link)}
          </>
        )}
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
          <BoldPlusIcon />
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
      <div className="nav-list">
        {error && <p className="error small">{error}</p>}
        <div className="nav-list-head">
          <h4>{t(`nav.${current}`)}</h4>
          {(current === 'characters' || current === 'locations') && cardActions(current)}
        </div>
        <nav>{body[current]}</nav>
      </div>
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
