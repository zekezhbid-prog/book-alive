import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useNavigate } from 'react-router-dom'
import type { Project } from '../api'
import { useI18n } from '../i18n'
import { useSide, useView, type Side } from '../view'
import BookSearch from './BookSearch'
import { HistoryIcon, ReviewIcon } from './icons'
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
  // Checks and versions are the writer's tools: they open beside the text of the book.
  const writerTool = (tool: Side) => (
    <button
      className={`btn ghost icon tool-icon ${side === tool ? 'active' : ''}`}
      title={t(`side.${tool}`)}
      aria-label={t(`side.${tool}`)}
      aria-pressed={side === tool}
      onClick={() => {
        setSide(side === tool ? 'chat' : tool)
        if (!location.pathname.startsWith(`${base}/chapters/`) && location.pathname !== base) navigate(base)
      }}
    >
      {tool === 'review' ? <ReviewIcon /> : <HistoryIcon />}
      {tool === 'versions' && project.changes?.dirty && <span className="dot tool-dot" />}
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
          {t('tabs.book')}
        </NavLink>
        <NavLink to={`${base}/characters`} className={({ isActive }) => tabClass(isActive)}>
          {t('tabs.character')}
        </NavLink>
        <NavLink to={`${base}/locations`} className={({ isActive }) => tabClass(isActive)}>
          {t('tabs.location')}
        </NavLink>
        <NavLink to={`${base}/scenes`} className={({ isActive }) => tabClass(isActive)}>
          {t('tabs.scenes')}
        </NavLink>
        {illustrating && (
          <NavLink to={`${base}/style`} className={({ isActive }) => tabClass(isActive)}>
            {t('tabs.style')}
            {!project.style_id && <span className="dot" title={t('style.not_chosen')} />}
          </NavLink>
        )}
      </nav>
      {project.mode === 'writer' && view === 'writer' && (
        <>
          {writerTool('review')}
          {writerTool('versions')}
        </>
      )}
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
const isSection = () => /\/(characters|locations|scenes|style|usage)(\/|$)/.test(location.pathname)
