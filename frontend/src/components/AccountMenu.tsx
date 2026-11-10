import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useI18n } from '../i18n'
import { UserIcon } from './icons'

interface Props {
  accounts: boolean
  email: string
  onLogout: () => void
}

/** The account button in the top right corner: my projects, the open book's usage, the
 * settings and signing out. */
export default function AccountMenu({ accounts, email, onLogout }: Props) {
  const { t } = useI18n()
  const { pathname } = useLocation()
  // Open on the page where it was opened: following one of its links closes it.
  const [openOn, setOpenOn] = useState<string | null>(null)
  const open = openOn === pathname
  const setOpen = (next: boolean) => setOpenOn(next ? pathname : null)
  const box = useRef<HTMLDivElement>(null)
  const projectId = /^\/projects\/([^/]+)/.exec(pathname)?.[1]

  useEffect(() => {
    if (!open) return
    const away = (e: MouseEvent) => box.current?.contains(e.target as Node) || setOpen(false)
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', away)
    document.addEventListener('keydown', esc)
    return () => {
      document.removeEventListener('mousedown', away)
      document.removeEventListener('keydown', esc)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  return (
    <div className="account" ref={box}>
      <button
        className={`btn ghost icon account-button ${open ? 'active' : ''}`}
        title={email || t('account.menu')}
        aria-label={t('account.menu')}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <UserIcon />
      </button>
      {open && (
        <nav className="account-menu">
          {email && <p className="faint small account-email">{email}</p>}
          <Link to="/">{t('nav.my_projects')}</Link>
          {projectId && <Link to={`/projects/${projectId}/usage`}>{t('tabs.usage')}</Link>}
          <Link to="/settings">{t('app.settings')}</Link>
          {accounts && <button onClick={onLogout}>{t('login.logout')}</button>}
        </nav>
      )}
    </div>
  )
}
