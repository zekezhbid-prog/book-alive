import { Link, NavLink, Route, Routes } from 'react-router-dom'
import { useI18n } from './i18n'
import Book from './pages/Book'
import Projects from './pages/Projects'
import Settings from './pages/Settings'

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
        <Route path="/settings" element={<Settings />} />
      </Routes>
    </>
  )
}
