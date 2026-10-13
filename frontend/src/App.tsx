import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { useI18n } from './i18n'
import Book from './pages/Book'
import Entities from './pages/Entities'
import Projects from './pages/Projects'
import Settings from './pages/Settings'
import Style from './pages/Style'
import Usage from './pages/Usage'

export default function App() {
  const { lang, setLang, t } = useI18n()
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          <span className="brand-mark" />
          Book Alive
        </Link>
        {/* Pages put their own breadcrumb and controls here. */}
        <div id="topbar-slot" className="topbar-slot" />
        <NavLink to="/settings" className="btn ghost">
          {t('app.settings')}
        </NavLink>
        <button
          className="btn ghost"
          onClick={() => setLang(lang === 'ru' ? 'en' : 'ru')}
          title="Language / Язык"
        >
          {lang === 'ru' ? 'EN' : 'RU'}
        </button>
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
        <Route path="/projects/:projectId/style" element={<Style />} />
        <Route path="/projects/:projectId/usage" element={<Usage />} />
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </>
  )
}
