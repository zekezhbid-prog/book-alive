import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type SearchHit } from '../api'
import { errorText, useI18n } from '../i18n'
import { markMatches } from '../markMatches'
import { SearchIcon } from './icons'

/** Search through the book's text, in the top bar: the hits drop down under the field and
 * a click opens the chapter at the found paragraph. */
export default function BookSearch({ projectId }: { projectId: string }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [found, setFound] = useState<SearchHit[] | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const searching = query.trim().length >= 2

  useEffect(() => {
    if (!searching) return
    const timer = setTimeout(
      () =>
        api.search(projectId, query).then(
          (hits) => {
            setError('')
            setFound(hits)
          },
          (e) => setError(errorText(t, e)),
        ),
      250,
    )
    return () => clearTimeout(timer)
  }, [query, searching, projectId, t])

  // A click elsewhere or Esc folds the results away; the query stays for the next look.
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
  }, [open])

  const go = (hit: SearchHit) => {
    setOpen(false)
    const params = new URLSearchParams({ p: String(hit.paragraph), q: query.trim() })
    navigate(`/projects/${projectId}/chapters/${hit.chapter_id}?${params}`)
  }
  const hits = searching ? found : null

  return (
    <div className="book-search" ref={box}>
      <SearchIcon />
      <input
        className="input"
        type="search"
        placeholder={t('book.search')}
        aria-label={t('book.search')}
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
      />
      {open && searching && (error || hits) && (
        <div className="book-search-results">
          {error && <p className="error small">{error}</p>}
          {hits && (
            <>
              <h4>{hits.length ? t('book.search.results', { n: hits.length }) : t('book.search.none')}</h4>
              <nav>
                {hits.map((hit, i) => (
                  <button key={i} className="hit" onClick={() => go(hit)}>
                    <span className="faint small">{hit.chapter_title || t('book.untitled')}</span>
                    <span>…{markMatches(hit.snippet, query, (text) => [text])}…</span>
                  </button>
                ))}
              </nav>
            </>
          )}
        </div>
      )}
    </div>
  )
}
