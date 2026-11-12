import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { api, type BookNumbers, type ChapterNumbers, type Project } from '../api'
import { errorText, useI18n, type MessageKey } from '../i18n'

interface Props {
  project: Project
  busy?: boolean
}

type Metric = 'words' | 'avg_sentence' | 'dialogue'
type SortKey = 'position' | 'words' | 'sentences' | 'avg_sentence' | 'dialogue'

const METRICS: Metric[] = ['words', 'avg_sentence', 'dialogue']
/** How far from the usual chapter a number must be to be worth a note. */
const LONG = 1.8
const SHORT = 0.5
const HEAVY = 1.4
const TALKY = 0.7
const SILENT = 0.05
const NOTES_MAX = 6

const median = (values: number[]) => {
  const sorted = values.filter((v) => v > 0).sort((a, b) => a - b)
  if (!sorted.length) return 0
  const mid = sorted.length >> 1
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2
}

const percent = (share: number) => `${Math.round(share * 100)}%`
/** Numbers the way the interface language writes them: 4 097 and 2,6 in Russian. */
const formatter = (lang: string) => {
  const locale = lang === 'en' ? 'en' : lang === 'by' ? 'be' : 'ru'
  return (value: number) => value.toLocaleString(locale, { maximumFractionDigits: 1 })
}
/** A title that is only «Глава 4», «Раздзел 4», «Chapter 4» or a bare number. */
const BARE_TITLE = /^((глава|раздзел|chapter|часть|частка|part)\s+)?[\divxlc]+\.?$/i

/** Free numbers by chapter: a button in the checks column and a wide window with a chart. */
export default function ChapterStats({ project, busy }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useState(false)
  return (
    <div className="stack">
      <button className="btn badge-btn" disabled={busy} onClick={() => setOpen(true)}>
        <span className="grow">{t('stats.title')}</span>
      </button>
      {open && <StatsDialog project={project} onClose={() => setOpen(false)} />}
    </div>
  )
}

function StatsDialog({ project, onClose }: { project: Project; onClose: () => void }) {
  const { t, lang } = useI18n()
  const navigate = useNavigate()
  const num = useCallback((v: number) => formatter(lang)(v), [lang])
  // «Глава 4» rather than «Глава 4 «Глава 4»» when the title is just the number.
  const chapterName = useCallback(
    (c: ChapterNumbers, n: number) =>
      !c.title || BARE_TITLE.test(c.title.trim()) ? t('stats.chapter', { n }) : t('stats.chapter.named', { n, name: c.title }),
    [t],
  )
  const [data, setData] = useState<BookNumbers | null>(null)
  const [error, setError] = useState('')
  const [metric, setMetric] = useState<Metric>('words')
  const [sort, setSort] = useState<{ key: SortKey; down: boolean }>({ key: 'position', down: false })
  const [chosen, setChosen] = useState<string | null>(null)

  useEffect(() => {
    api.reviewStats(project.id).then(setData, (e) => setError(errorText(t, e)))
  }, [project.id, t])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const chapters = useMemo(() => data?.chapters ?? [], [data])
  const usual = useMemo(
    () => ({
      words: median(chapters.map((c) => c.words)),
      avg_sentence: median(chapters.map((c) => c.avg_sentence)),
      dialogue: median(chapters.map((c) => c.dialogue)),
    }),
    [chapters],
  )
  const notes = useMemo(() => {
    if (chapters.length < 3) return []
    const out: { id: string; text: string }[] = []
    chapters.forEach((c, i) => {
      const parts: string[] = []
      if (usual.words && c.words >= usual.words * LONG) parts.push(t('stats.note.long', { x: num(c.words / usual.words) }))
      else if (usual.words && c.words > 0 && c.words <= usual.words * SHORT)
        parts.push(t('stats.note.short', { x: num(usual.words / c.words) }))
      if (usual.avg_sentence && c.avg_sentence >= usual.avg_sentence * HEAVY)
        parts.push(t('stats.note.heavy', { w: num(c.avg_sentence), usual: num(usual.avg_sentence) }))
      if (c.dialogue >= TALKY) parts.push(t('stats.note.talky', { p: percent(c.dialogue) }))
      else if (c.words >= 300 && c.dialogue <= SILENT && usual.dialogue > SILENT * 3) parts.push(t('stats.note.silent'))
      if (parts.length) out.push({ id: c.chapter_id, text: `${chapterName(c, i + 1)}: ${parts.join('; ')}` })
    })
    return out.slice(0, NOTES_MAX)
  }, [chapters, usual, t, num, chapterName])

  const rows = useMemo(() => {
    const indexed = chapters.map((c, i) => ({ c, n: i + 1 }))
    if (sort.key === 'position') return sort.down ? indexed.reverse() : indexed
    const key = sort.key
    return indexed.sort((a, b) => (sort.down ? b.c[key] - a.c[key] : a.c[key] - b.c[key]))
  }, [chapters, sort])

  const go = (chapterId: string, paragraph?: number) => {
    onClose()
    navigate(`/projects/${project.id}/chapters/${chapterId}` + (paragraph === undefined ? '' : `?p=${paragraph}`))
  }
  const pick = (id: string) => {
    setChosen((current) => (current === id ? null : id))
    // The details open under the row: bring both into view.
    requestAnimationFrame(() =>
      (document.getElementById(`stats-detail-${id}`) ?? document.getElementById(`stats-row-${id}`))?.scrollIntoView({
        block: 'nearest',
        behavior: 'smooth',
      }),
    )
  }
  const header = (key: SortKey, label: MessageKey, className = '') => (
    <th className={className}>
      <button
        className={'sort' + (sort.key === key ? ' on' : '')}
        onClick={() => setSort({ key, down: sort.key === key ? !sort.down : key !== 'position' })}
      >
        {t(label)}
        {sort.key === key && <span aria-hidden>{sort.down ? ' ↓' : ' ↑'}</span>}
      </button>
    </th>
  )

  return createPortal(
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll stats-dialog">
        <div className="row">
          <h2>{t('stats.title')}</h2>
          <span className="spacer" />
          <button className="btn ghost small" onClick={onClose}>
            {t('app.close')}
          </button>
        </div>
        <p className="muted small">{t('stats.hint')}</p>
        {error && <p className="error">{error}</p>}
        {!data && !error && <p className="muted">{t('stats.loading')}</p>}
        {data && chapters.length === 0 && <p className="muted">{t('stats.empty')}</p>}
        {data && chapters.length > 0 && (
          <>
            <div className="stats-tiles">
              <Tile label={t('stats.book.words')} value={num(data.words)} />
              <Tile label={t('stats.book.chapters')} value={String(chapters.length)} />
              <Tile label={t('stats.book.sentence')} value={num(data.avg_sentence)} unit={t('stats.unit.words')} />
              <Tile label={t('stats.book.dialogue')} value={percent(data.dialogue)} />
            </div>
            {notes.length > 0 && (
              <div className="stack stats-notes">
                <h4>{t('stats.notes')}</h4>
                {notes.map((note, i) => (
                  <button key={i} className="hit" onClick={() => pick(note.id)}>
                    <span className="small">{note.text}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="row stats-switch" role="tablist">
              {METRICS.map((m) => (
                <button
                  key={m}
                  role="tab"
                  aria-selected={metric === m}
                  className={'btn small' + (metric === m ? ' primary' : ' ghost')}
                  onClick={() => setMetric(m)}
                >
                  {t(`stats.metric.${m}` as MessageKey)}
                </button>
              ))}
            </div>
            <Chart num={num} chapters={chapters} metric={metric} usual={usual[metric]} chosen={chosen} onPick={pick} />
            {data.top_words.length > 0 && (
              <div className="stack">
                <h4>{t('stats.book.top')}</h4>
                <div className="stats-words">
                  {data.top_words.map((w) => (
                    <span key={w.word} className="chip plain small">
                      {w.word} <span className="faint">{w.count}</span>
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="stats-table-wrap">
              <table className="stats-table">
                <thead>
                  <tr>
                    {header('position', 'stats.col.n', 'num')}
                    <th>{t('stats.col.title')}</th>
                    {header('words', 'stats.col.words', 'num')}
                    {header('sentences', 'stats.col.sentences', 'num wide-only')}
                    {header('avg_sentence', 'stats.col.sentence', 'num')}
                    {header('dialogue', 'stats.col.dialogue', 'num')}
                    <th className="wide-only">{t('stats.col.top')}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map(({ c, n }) => (
                    <Fragment key={c.chapter_id}>
                      <tr
                        id={`stats-row-${c.chapter_id}`}
                        className={'pick' + (chosen === c.chapter_id ? ' on' : '')}
                        onClick={() => pick(c.chapter_id)}
                      >
                        <td className="num faint">{n}</td>
                        <td>{c.title || t('book.untitled')}</td>
                        <td className={'num' + (usual.words && (c.words >= usual.words * LONG || (c.words > 0 && c.words <= usual.words * SHORT)) ? ' odd' : '')}>
                          {num(c.words)}
                        </td>
                        <td className="num wide-only">{num(c.sentences)}</td>
                        <td className={'num' + (usual.avg_sentence && c.avg_sentence >= usual.avg_sentence * HEAVY ? ' odd' : '')}>
                          {num(c.avg_sentence)}
                        </td>
                        <td className={'num' + (c.dialogue >= TALKY ? ' odd' : '')}>{percent(c.dialogue)}</td>
                        <td className="wide-only faint small">
                          {c.top_words.slice(0, 5).map((w) => w.word).join(', ')}
                        </td>
                      </tr>
                      {chosen === c.chapter_id && (
                        <tr className="stats-detail" id={`stats-detail-${c.chapter_id}`}>
                          <td colSpan={7}>
                            <Detail num={num} chapter={c} onOpen={(p) => go(c.chapter_id, p)} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>,
    document.body,
  )
}

function Tile({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="stats-tile">
      <span className="faint small">{label}</span>
      <b>
        {value}
        {unit && <span className="faint small"> {unit}</span>}
      </b>
    </div>
  )
}

interface ChartProps {
  chapters: ChapterNumbers[]
  metric: Metric
  usual: number
  chosen: string | null
  onPick: (id: string) => void
  num: (v: number) => string
}

const W = 1000
const H = 220
const PAD = { top: 14, bottom: 26, left: 8, right: 8 }

/** One bar per chapter; the dashed line is the usual chapter (the median). */
function Chart({ chapters, metric, usual, chosen, onPick, num }: ChartProps) {
  const { t } = useI18n()
  const values = chapters.map((c) => c[metric])
  const top = Math.max(metric === 'dialogue' ? 0.01 : 1, ...values) * 1.08
  const inner = W - PAD.left - PAD.right
  const step = inner / chapters.length
  const bar = Math.max(2, Math.min(56, step * 0.72))
  const y = (v: number) => PAD.top + (H - PAD.top - PAD.bottom) * (1 - v / top)
  const every = Math.ceil(chapters.length / 30)
  const show = (v: number) => (metric === 'dialogue' ? percent(v) : num(v))
  const odd = (v: number) =>
    usual > 0 &&
    (metric === 'words'
      ? v >= usual * LONG || (v > 0 && v <= usual * SHORT)
      : metric === 'avg_sentence'
        ? v >= usual * HEAVY
        : v >= TALKY)
  return (
    <figure className="stats-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={t(`stats.metric.${metric}` as MessageKey)}>
        {chapters.map((c, i) => {
          const v = values[i]
          const x = PAD.left + step * i + (step - bar) / 2
          const cls = 'bar' + (odd(v) ? ' odd' : '') + (chosen === c.chapter_id ? ' on' : '')
          return (
            <g key={c.chapter_id} className={cls} onClick={() => onPick(c.chapter_id)}>
              <rect className="hitbox" x={PAD.left + step * i} y={PAD.top} width={step} height={H - PAD.top - PAD.bottom} />
              <rect x={x} y={y(v)} width={bar} height={Math.max(0, y(0) - y(v))} rx={Math.min(4, bar / 3)} />
              <title>{`${i + 1}. ${c.title || t('book.untitled')}: ${show(v)}`}</title>
              {i % every === 0 && (
                <text x={PAD.left + step * i + step / 2} y={H - 8} textAnchor="middle">
                  {i + 1}
                </text>
              )}
            </g>
          )
        })}
        {usual > 0 && (
          <line className="usual" x1={PAD.left} x2={W - PAD.right} y1={y(usual)} y2={y(usual)} />
        )}
      </svg>
      <figcaption className="faint small">
        <span className="legend-line" /> {t('stats.usual', { v: show(usual) })}
        <span className="legend-odd" /> {t('stats.odd')}
      </figcaption>
    </figure>
  )
}

function Detail({ chapter, onOpen, num }: { chapter: ChapterNumbers; onOpen: (paragraph?: number) => void; num: (v: number) => string }) {
  const { t } = useI18n()
  return (
    <div className="stack">
      <div className="row wrap small faint">
        <span>{t('stats.detail.chars', { n: num(chapter.chars) })}</span>
        <span>{t('stats.detail.paragraphs', { n: chapter.paragraphs })}</span>
        <span>{t('stats.detail.sentences', { n: chapter.sentences })}</span>
        <span className="spacer" />
        <button className="btn ghost small" onClick={() => onOpen()}>
          {t('stats.detail.open')}
        </button>
      </div>
      {chapter.longest.length > 0 && (
        <>
          <b className="small">{t('stats.detail.longest')}</b>
          {chapter.longest.map((s, i) => (
            <button key={i} className="hit" title={t('review.open')} onClick={() => onOpen(s.paragraph)}>
              <span className="faint small">{t('stats.detail.words', { n: s.words })}</span>
              <span className="small">«{s.quote}»</span>
            </button>
          ))}
        </>
      )}
      {chapter.top_words.length > 0 && (
        <>
          <b className="small">{t('stats.detail.top')}</b>
          <div className="stats-words">
            {chapter.top_words.map((w) => (
              <span key={w.word} className="chip plain small">
                {w.word} <span className="faint">{w.count}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
