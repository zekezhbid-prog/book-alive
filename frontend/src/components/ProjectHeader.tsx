import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { Link, NavLink } from 'react-router-dom'
import type { Project } from '../api'
import { useI18n } from '../i18n'

/** Project title, the tabs of the book's parts and the project's own settings, rendered
 * into the app's top bar. */
export default function ProjectHeader({ project, children }: { project: Project; children?: ReactNode }) {
  const { t } = useI18n()
  const slot = document.getElementById('topbar-slot')
  if (!slot) return null
  const base = `/projects/${project.id}`
  return createPortal(
    <>
      <span className="crumb">
        <Link to="/">{t('app.projects')}</Link> / <b>{project.title}</b>
      </span>
      <span className={`badge ${project.mode}`}>{t(`mode.${project.mode}`)}</span>
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
      <span className="spacer" />
      {children}
      {/* Project-wide settings sit on the right, next to the app's own settings. */}
      <NavLink to={`${base}/style`} className="btn ghost">
        {t('tabs.style')}
      </NavLink>
      <NavLink to={`${base}/usage`} className="btn ghost">
        {t('tabs.usage')}
      </NavLink>
    </>,
    slot,
  )
}

const tabClass = (active: boolean) => `tab ${active ? 'active' : ''}`
const isSection = () => /\/(characters|locations|scenes|style|usage)(\/|$)/.test(location.pathname)
