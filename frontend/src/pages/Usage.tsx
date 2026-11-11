import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, peek, type Project, type Usage as UsageData } from '../api'
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

  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    api.project(projectId).then(setProject, fail)
    api.usage(projectId).then(setUsage, fail)
  }, [projectId, t])

  const more = () => {
    if (!usage) return
    setLoadingMore(true)
    api
      .usage(projectId, usage.rows.length)
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
        {usage && (
          <p className="notice">
            {usage.balance_rub != null
              ? t('usage.balance', { name: usage.balance_connection, sum: rubles(usage.balance_rub) })
              : t('usage.balance.none')}
          </p>
        )}
        {usage?.rows.length === 0 && <p className="muted">{t('usage.empty')}</p>}
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
