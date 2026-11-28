import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useNavigate } from 'react-router-dom'
import type { Project } from '../api'
import { useI18n } from '../i18n'
import { useSide, useView, type Side } from '../view'
import BookSearch from './BookSearch'
import { BookIcon, FilmIcon, ImageIcon, HistoryIcon, KeyIcon, PinIcon, ReviewIcon, UsersIcon } from './icons'
import ChatDock from './ChatDock'

interface Props {
  project: Project
  children?: ReactNode
  /** The book page tells the chat which chapter is open and whether ideas can be offered. */
  chat?: { chapterId?: string; canSuggest?: boolean }
}

/** The book's title, the tabs of its parts, for a writer the checks and versions, and the
 * book search, rendered into the app's top bar; and the book chat, on every project page. */
export default function ProjectHeader({ project, children, chat }: Props) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const view = useView(project)
  const [side, setSide] = useSide(project.id)
  // The style is a step of the illustrator's work (references and frames wait for it).
  const illustrating = view === 'illustrator'
  const slot = document.getElementById('topbar-slot')
  if (!slot) return null
  const base = `/projects/${project.id}`
  // The checklist and versions are the writer's tools: they open beside the text of the
  // book. They look like the tabs and follow them in the same row.
  const writerTool = (tool: Side) => (
    <button
      className={`tab tool-tab ${side === tool ? 'active' : ''}`}
      title={t(`side.${tool}`)}
      aria-pressed={side === tool}
      onClick={() => {
        // A second press folds the panel; nothing opens in its place.
        setSide(side === tool ? 'chat' : tool)
        if (!location.pathname.startsWith(`${base}/chapters/`) && location.pathname !== base) navigate(base)
      }}
    >
      {tool === 'review' ? <ReviewIcon /> : <HistoryIcon />}
      <span>{t(`side.${tool}`)}</span>
      {tool === 'versions' && project.changes?.dirty && <span className="dot" />}
    </button>
  )
  const bar = createPortal(
    <>
      <b className="book-title" title={project.title}>
        {project.title}
      </b>
      <nav className="tabs">
        {/* The book tab also covers /chapters/:id, the others are exact sections. */}
        <NavLink to={base} end={false} className={({ isActive }) => tabClass(isActive && !isSection())}>
          <BookIcon />
          <span>{t('tabs.book')}</span>
        </NavLink>
        <NavLink to={`${base}/characters`} className={({ isActive }) => tabClass(isActive)}>
          <UsersIcon />
          <span>{t('tabs.character')}</span>
        </NavLink>
        <NavLink to={`${base}/locations`} className={({ isActive }) => tabClass(isActive)}>
          <PinIcon />
          <span>{t('tabs.location')}</span>
        </NavLink>
        <NavLink to={`${base}/items`} className={({ isActive }) => tabClass(isActive)}>
          <KeyIcon />
          <span>{t('tabs.item')}</span>
        </NavLink>
        {/* Pictures of the book, made in a dialogue from the cards' references. */}
        {illustrating && (
          <NavLink to={`${base}/images`} className={({ isActive }) => tabClass(isActive)}>
            <ImageIcon />
            <span>{t('tabs.images')}</span>
          </NavLink>
        )}
        {/* Scenes are frames to draw and animate: the illustrator's part only. */}
        {illustrating && (
          <NavLink to={`${base}/scenes`} className={({ isActive }) => tabClass(isActive)}>
            <FilmIcon />
            <span>{t('tabs.scenes')}</span>
          </NavLink>
        )}
        {project.mode === 'writer' && view === 'writer' && (
          <>
            {writerTool('review')}
            {writerTool('versions')}
          </>
        )}
      </nav>
      <span className="spacer" />
      {children}
      <BookSearch projectId={project.id} />
    </>,
    slot,
  )
  return (
    <>
      {bar}
      <ChatDock
        projectId={project.id}
        chapters={project.chapters}
        chapterId={chat?.chapterId}
        canSuggest={chat?.canSuggest}
      />
    </>
  )
}

const tabClass = (active: boolean) => `tab ${active ? 'active' : ''}`
const isSection = () => /\/(characters|locations|items|scenes|images|usage)(\/|$)/.test(location.pathname)
