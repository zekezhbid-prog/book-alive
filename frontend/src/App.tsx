import { useEffect, useState, type FormEvent } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { api, type SessionInfo } from './api'
import { errorText, useI18n } from './i18n'
import Book from './pages/Book'
import Entities from './pages/Entities'
import Projects from './pages/Projects'
import Scenes from './pages/Scenes'
import Settings from './pages/Settings'
import Style from './pages/Style'
import Usage from './pages/Usage'

export default function App() {
  const { lang, setLang, t } = useI18n()
  // A hosted instance may be behind one shared password; locally there is none.
  const [session, setSession] = useState<SessionInfo | null>(null)

  useEffect(() => {
    api.session().then(setSession, () => setSession({ password_required: false, authenticated: true }))
    const expired = () => setSession({ password_required: true, authenticated: false })
    window.addEventListener('login-required', expired)
    return () => window.removeEventListener('login-required', expired)
  }, [])

  const languageButton = (
    <button className="btn ghost" onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')} title="Language / Язык">
      {lang === 'ru' ? 'EN' : 'RU'}
    </button>
  )
  if (!session) return null
  if (!session.authenticated) {
    return (
      <>
        <header className="topbar">
          <span className="brand">
            <img className="brand-mark" src="/favicon.svg" alt="" />
            Book Alive
          </span>
          <span className="spacer" />
          {languageButton}
        </header>
        <Login onDone={setSession} />
      </>
    )
  }
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          <img className="brand-mark" src="/favicon.svg" alt="" />
          Book Alive
        </Link>
        {/* Pages put their own breadcrumb and controls here. */}
        <div id="topbar-slot" className="topbar-slot" />
        <NavLink to="/settings" className="btn ghost">
          {t('app.settings')}
        </NavLink>
        {session.password_required && (
          <button className="btn ghost" onClick={() => api.logout().then(setSession)}>
            {t('login.logout')}
          </button>
        )}
        {languageButton}
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
      </Routes>
    </>
  )
}

function Login({ onDone }: { onDone: (session: SessionInfo) => void }) {
  const { t } = useI18n()
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const submit = (event: FormEvent) => {
    event.preventDefault()
    setError('')
    api.login(password).then(onDone, (e) => setError(errorText(t, e)))
  }
  return (
    <main className="page narrow">
      <form className="dialog stack login" onSubmit={submit}>
        <h2>{t('login.title')}</h2>
        <label className="field">
          {t('login.password')}
          <input
            className="input"
            type="password"
            autoFocus
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn primary" disabled={!password}>
          {t('login.submit')}
        </button>
      </form>
    </main>
  )
}
