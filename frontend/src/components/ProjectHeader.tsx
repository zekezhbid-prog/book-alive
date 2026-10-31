import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { NavLink, useNavigate } from 'react-router-dom'
import type { Project } from '../api'
import { useI18n } from '../i18n'
import { useSide, useView, type Side } from '../view'

/** The book's title, the tabs of its parts and, for a writer, the checks and versions,
 * rendered into the app's top bar. The project's own links sit in the left menu. */
export default function ProjectHeader({ project, children }: { project: Project; children?: ReactNode }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const view = useView(project)
  const [side, setSide] = useSide(project.id)
  const slot = document.getElementById('topbar-slot')
  if (!slot) return null
  const base = `/projects/${project.id}`
  // Checks and versions are the writer's tools: they open beside the text of the book.
  const writerTool = (tool: Side) => (
    <button
      className={`btn ghost ${side === tool ? 'active' : ''}`}
      onClick={() => {
        setSide(side === tool ? 'chat' : tool)
        if (!location.pathname.startsWith(`${base}/chapters/`) && location.pathname !== base) navigate(base)
      }}
    >
      {t(`side.${tool}`)}
      {tool === 'versions' && project.changes?.dirty && <span className="dot" />}
    </button>
  )
  return createPortal(
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
      </nav>
      {project.mode === 'writer' && view === 'writer' && (
        <>
          {writerTool('review')}
          {writerTool('versions')}
        </>
      )}
      <span className="spacer" />
      {children}
    </>,
    slot,
  )
}

const tabClass = (active: boolean) => `tab ${active ? 'active' : ''}`
const isSection = () => /\/(characters|locations|scenes|style|usage)(\/|$)/.test(location.pathname)
