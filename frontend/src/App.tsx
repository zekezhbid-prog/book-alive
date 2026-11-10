import { useEffect, useState, type FormEvent } from 'react'
import { Link, Route, Routes, useLocation } from 'react-router-dom'
import { api, type SessionInfo } from './api'
import { errorText, LANGS, useI18n, type Lang } from './i18n'
import AccountMenu from './components/AccountMenu'
import About from './pages/About'
import Book from './pages/Book'
import Entities from './pages/Entities'
import Projects from './pages/Projects'
import Scenes from './pages/Scenes'
import Settings from './pages/Settings'
import Style from './pages/Style'
import Usage from './pages/Usage'

export default function App() {
  const { lang, setLang } = useI18n()
  // A hosted instance has accounts (e-mail and password); locally there is no login.
  const [session, setSession] = useState<SessionInfo | null>(null)
  const { pathname } = useLocation()

  useEffect(() => {
    api.session().then(setSession, () => setSession({ accounts: false, authenticated: true, email: '', is_admin: true }))
    const expired = () => setSession({ accounts: true, authenticated: false, email: '', is_admin: false })
    window.addEventListener('login-required', expired)
    return () => window.removeEventListener('login-required', expired)
  }, [])

  const languageButton = (
    <select
      className="input lang-select"
      value={lang}
      onChange={(e) => setLang(e.target.value as Lang)}
      title="Language / Мова / Язык"
    >
      {LANGS.map((code) => (
        <option key={code} value={code}>
          {code.toUpperCase()}
        </option>
      ))}
    </select>
  )
  if (!session) return null
  if (!session.authenticated) {
    return (
      <>
        <header className="topbar">
          <Link to="/about" className="brand">
            <span className="brand-mark">
              <img src="/favicon.svg" alt="" />
            </span>
            <span className="brand-name">Lorebook</span>
          </Link>
          <span className="spacer" />
          {languageButton}
        </header>
        {pathname === '/about' ? <About signedIn={false} /> : <Auth onDone={setSession} />}
      </>
    )
  }
  return (
    <>
      {/* The mark on the left, then the open book's title, tabs and search (pages put them
          into the slot); the name of the app and the account menu in the right corner. */}
      <header className="topbar">
        {/* The name of the app leads to what it is; the projects are in the account menu. */}
        <Link to="/about" className="brand brand-mark-only" title="Lorebook">
          <span className="brand-mark">
            <img src="/favicon.svg" alt="Lorebook" />
          </span>
        </Link>
        <div id="topbar-slot" className="topbar-slot" />
        <Link to="/about" className="brand brand-right">
          <span className="brand-name">Lorebook</span>
        </Link>
        <AccountMenu
          accounts={session.accounts}
          email={session.email}
          onLogout={() => void api.logout().then(setSession)}
        />
      </header>
      <Routes>
        <Route path="/" element={<Projects />} />
        <Route path="/projects/:projectId" element={<Book />} />
        <Route path="/projects/:projectId/chapters/:chapterId" element={<Book />} />
        {/* `key` gives each section its own state when switching between the two. */}
        {['characters', 'characters/:entityId'].map((path) => (
          <Route
            key={path}
            path={`/projects/:projectId/${path}`}
            element={<Entities key="character" kind="character" />}
          />
        ))}
        {['locations', 'locations/:entityId'].map((path) => (
          <Route
            key={path}
            path={`/projects/:projectId/${path}`}
            element={<Entities key="location" kind="location" />}
          />
        ))}
        <Route path="/projects/:projectId/scenes" element={<Scenes />} />
        <Route path="/projects/:projectId/scenes/:sceneId" element={<Scenes />} />
        <Route path="/projects/:projectId/style" element={<Style />} />
        <Route path="/projects/:projectId/usage" element={<Usage />} />
        <Route path="/settings" element={<Settings />} />
        <Route path="/about" element={<About signedIn />} />
      </Routes>
    </>
  )
}

function Auth({ onDone }: { onDone: (session: SessionInfo) => void }) {
  const { t } = useI18n()
  const resetToken = new URLSearchParams(window.location.search).get('token') ?? ''
  const [mode, setMode] = useState<'login' | 'register' | 'forgot' | 'reset'>(
    window.location.pathname === '/reset' && resetToken ? 'reset' : 'login',
  )
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const go = (next: typeof mode) => {
    setMode(next)
    setError('')
    setNotice('')
  }
  const finish = (session: SessionInfo) => {
    // The reset link is single-use: leave its address.
    if (window.location.pathname === '/reset') window.history.replaceState(null, '', '/')
    onDone(session)
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setError('')
    const fail = (e: unknown) => setError(errorText(t, e))
    if (mode === 'login') api.login(email, password).then(finish, fail)
    else if (mode === 'register') api.register(email, password).then(finish, fail)
    else if (mode === 'reset') api.resetPassword(resetToken, password).then(finish, fail)
    else api.forgotPassword(email).then(() => setNotice(t('auth.forgot.sent')), fail)
  }
  const title = {
    login: t('login.title'),
    register: t('auth.register'),
    forgot: t('auth.forgot.title'),
    reset: t('auth.reset.title'),
  }[mode]
  const submitLabel = {
    login: t('login.submit'),
    register: t('auth.register.submit'),
    forgot: t('auth.forgot.submit'),
    reset: t('auth.reset.submit'),
  }[mode]
  return (
    <main className="page narrow">
      <form className="dialog stack login" onSubmit={submit}>
        <h2>{title}</h2>
        {mode === 'forgot' && <p className="muted small">{t('auth.forgot.hint')}</p>}
        {mode !== 'reset' && (
          <label className="field">
            {t('login.email')}
            <input
              className="input"
              type="email"
              autoFocus
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </label>
        )}
        {mode !== 'forgot' && (
          <label className="field">
            {t('login.password')}
            <input
              className="input"
              type="password"
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {mode !== 'login' && <span className="faint">{t('auth.password.hint')}</span>}
          </label>
        )}
        {error && <p className="error">{error}</p>}
        {notice && <p className="notice">{notice}</p>}
        <button className="btn primary" disabled={(mode !== 'reset' && !email) || (mode !== 'forgot' && !password)}>
          {submitLabel}
        </button>
        <div className="stack">
          {mode === 'login' && (
            <>
              <button type="button" className="btn ghost small" onClick={() => go('forgot')}>
                {t('auth.forgot')}
              </button>
              <button type="button" className="btn ghost small" onClick={() => go('register')}>
                {t('auth.to_register')}
              </button>
            </>
          )}
          {mode === 'register' && (
            <button type="button" className="btn ghost small" onClick={() => go('login')}>
              {t('auth.to_login')}
            </button>
          )}
          {(mode === 'forgot' || mode === 'reset') && (
            <button type="button" className="btn ghost small" onClick={() => go('login')}>
              {t('auth.back')}
            </button>
          )}
        </div>
      </form>
    </main>
  )
}
