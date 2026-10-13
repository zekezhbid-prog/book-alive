import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Project, type Usage as UsageData } from '../api'
import ProjectHeader from '../components/ProjectHeader'
import { errorText, useI18n, type MessageKey } from '../i18n'

/** Where the tokens went, grouped by operation and model. */
export default function Usage() {
  const { t, has } = useI18n()
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    api.project(projectId).then(setProject, fail)
    api.usage(projectId).then(setUsage, fail)
  }, [projectId, t])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>
  const number = (n: number) => n.toLocaleString()
  const operation = (code: string) => {
    const key = `usage.op.${code}` as MessageKey
    return has(key) ? t(key) : code
  }

  return (
    <>
      <ProjectHeader project={project} />
      <main className="page narrow stack">
        <h1>{t('usage.title')}</h1>
        {error && <p className="error">{error}</p>}
        {usage?.rows.length === 0 && <p className="muted">{t('usage.empty')}</p>}
        {usage && usage.rows.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>{t('usage.operation')}</th>
                <th>{t('usage.model')}</th>
                <th className="num">{t('usage.calls')}</th>
                <th className="num">{t('usage.input')}</th>
                <th className="num">{t('usage.output')}</th>
              </tr>
            </thead>
            <tbody>
              {usage.rows.map((row, i) => (
                <tr key={i}>
                  <td>{operation(row.operation)}</td>
                  <td className="muted">
                    {row.connection_name} · {row.model}
                  </td>
                  <td className="num">{number(row.calls)}</td>
                  <td className="num">{number(row.input_tokens)}</td>
                  <td className="num">{number(row.output_tokens)}</td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <td colSpan={3}>{t('usage.total')}</td>
                <td className="num">{number(usage.input_tokens)}</td>
                <td className="num">{number(usage.output_tokens)}</td>
              </tr>
            </tfoot>
          </table>
        )}
      </main>
    </>
  )
}
