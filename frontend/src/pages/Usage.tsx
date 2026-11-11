import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, peek, type Period, type Project, type Usage as UsageData } from '../api'
import PageClose from '../components/PageClose'
import ProjectHeader from '../components/ProjectHeader'
import { errorText, useI18n, type MessageKey } from '../i18n'

/** Where the tokens and money went: one line per action, newest first, a page at a time. */
export default function Usage() {
  const { t, has, lang } = useI18n()
  const locale = lang === 'by' ? 'be' : lang
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(() => peek.project(projectId) ?? null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState('')
  // Today by default: over months the full list says nothing.
  const [range, setRange] = useState<Range>('today')
  const [from, setFrom] = useState(() => isoDay(new Date()))
  const [to, setTo] = useState(() => isoDay(new Date()))
  const period = toPeriod(range, from, to)
  const periodKey = `${period.since ?? ''}|${period.until ?? ''}`

  useEffect(() => {
    api.project(projectId).then(setProject, (e: unknown) => setError(errorText(t, e)))
  }, [projectId, t])

  useEffect(() => {
    setUsage(null)
    api.usage(projectId, 0, period).then(setUsage, (e: unknown) => setError(errorText(t, e)))
    // periodKey stands for the period's two ends
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, t, periodKey])

  const more = () => {
    if (!usage) return
    setLoadingMore(true)
    api
      .usage(projectId, usage.rows.length, period)
      .then((next) => setUsage({ ...next, rows: [...usage.rows, ...next.rows] }))
      .catch((e: unknown) => setError(errorText(t, e)))
      .finally(() => setLoadingMore(false))
  }

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>
  const number = (n: number) => n.toLocaleString(locale)
  const rubles = (n: number | null) =>
    n == null ? '—' : n > 0 && n < 0.01 ? '<0,01' : n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  const when = (iso: string) =>
    // The server keeps UTC without a zone mark.
    new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleString(locale, {
      day: '2-digit',
      month: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  const operation = (code: string) => {
    const key = `usage.op.${code}` as MessageKey
    return has(key) ? t(key) : code
  }
  const left = usage ? usage.total_rows - usage.rows.length : 0

  return (
    <>
      <ProjectHeader project={project} />
      <main className="page usage-page stack">
        <div className="page-head">
          <h1 className="grow">{t('usage.title')}</h1>
          <PageClose fallback={`/projects/${projectId}`} />
        </div>
        {error && <p className="error">{error}</p>}
        {/* No balance, no line: an error here only gets in the way. */}
        {usage?.balance_rub != null && (
          <p className="notice">
            {t('usage.balance', { name: usage.balance_connection, sum: rubles(usage.balance_rub) })}
          </p>
        )}
        <div className="row wrap usage-period">
          <select value={range} onChange={(e) => setRange(e.target.value as Range)}>
            {RANGES.map((r) => (
              <option key={r} value={r}>
                {t(`usage.range.${r}` as MessageKey)}
              </option>
            ))}
          </select>
          {range === 'custom' && (
            <>
              <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} />
              <span className="muted">—</span>
              <input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </>
          )}
        </div>
        {!usage && !error && <p className="muted">{t('app.loading')}</p>}
        {usage?.rows.length === 0 && (
          <p className="muted">{t(range === 'all' ? 'usage.empty' : 'usage.empty.period')}</p>
        )}
        {usage && usage.rows.length > 0 && (
          <div className="table-scroll">
            <table className="table compact">
              <thead>
                <tr>
                  <th>{t('usage.date')}</th>
                  <th>{t('usage.operation')}</th>
                  <th>{t('usage.model')}</th>
                  <th className="num">{t('usage.calls')}</th>
                  <th className="num">{t('usage.input')}</th>
                  <th className="num">{t('usage.output')}</th>
                  <th className="num" title={t('usage.cost.hint')}>
                    {t('usage.cost')}
                  </th>
                </tr>
              </thead>
              <tbody>
                {usage.rows.map((row, i) => (
                  <tr key={i}>
                    <td className="muted nowrap">{when(row.created_at)}</td>
                    <td>{operation(row.operation)}</td>
                    <td className="muted small">{row.model}</td>
                    <td className="num">{number(row.calls)}</td>
                    <td className="num">{number(row.input_tokens)}</td>
                    <td className="num">{number(row.output_tokens)}</td>
                    <td className="num">{rubles(row.cost_rub)}</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>{t('usage.total')}</td>
                  <td className="num">{number(usage.input_tokens)}</td>
                  <td className="num">{number(usage.output_tokens)}</td>
                  <td className="num">{rubles(usage.cost_rub)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
        {left > 0 && (
          <button className="btn" disabled={loadingMore} onClick={more}>
            {t('usage.more', { n: left })}
          </button>
        )}
      </main>
    </>
  )
}

const RANGES = ['today', 'week', 'month', 'all', 'custom'] as const
type Range = (typeof RANGES)[number]

/** A day as the date input writes it, in the user's own time zone. */
function isoDay(day: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}`
}

/** The chosen range as UTC moments: whole local days, the last one included. */
function toPeriod(range: Range, from: string, to: string): Period {
  const midnight = (offset: number) => {
    const day = new Date()
    day.setHours(0, 0, 0, 0)
    day.setDate(day.getDate() + offset)
    return day.toISOString()
  }
  const local = (iso: string, extra = 0) => {
    const [y, m, d] = iso.split('-').map(Number)
    return new Date(y, m - 1, d + extra).toISOString()
  }
  switch (range) {
    case 'today':
      return { since: midnight(0) }
    case 'week':
      return { since: midnight(-6) }
    case 'month':
      return { since: midnight(-29) }
    case 'custom':
      return from && to ? { since: local(from), until: local(to, 1) } : {}
    default:
      return {}
  }
}
