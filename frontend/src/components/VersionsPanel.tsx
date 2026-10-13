import { useEffect, useState, type FormEvent } from 'react'
import { api, type Project, type Version } from '../api'
import { useI18n, versionLabel } from '../i18n'
import { savesSettled } from '../saveQueue'

interface Props {
  project: Project
  onChanged: () => void
  onError: (error: unknown) => void
}

/** Whole-book versions: one commit covers edits in any number of chapters. */
export default function VersionsPanel({ project, onChanged, onError }: Props) {
  const { t, lang } = useI18n()
  const [versions, setVersions] = useState<Version[]>([])
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const { version, changes } = project

  useEffect(() => {
    api.versions(project.id).then(setVersions, onError)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, version?.id])

  const commit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    await savesSettled()
    await api.commit(project.id, label).then(() => {
      setLabel('')
      onChanged()
    }, onError)
    setBusy(false)
  }
  const rollback = async (target: Version) => {
    if (!confirm(t('versions.rollback.confirm', { n: target.number }))) return
    setBusy(true)
    await savesSettled()
    await api.rollback(project.id, target.id).then(onChanged, onError)
    setBusy(false)
  }

  const summary = changes
    ? [
        changes.edited.length && t('versions.edited', { n: changes.edited.length }),
        changes.added.length && t('versions.added', { n: changes.added.length }),
        changes.removed.length && t('versions.removed', { n: changes.removed.length }),
        changes.renamed.length && t('versions.renamed', { n: changes.renamed.length }),
        changes.reordered && t('versions.reordered'),
      ].filter(Boolean)
    : []
  const date = (iso: string) =>
    new Date(iso).toLocaleString(lang, { dateStyle: 'short', timeStyle: 'short' })

  return (
    <div className="stack">
      <h4>{t('versions.title')}</h4>
      {version && (
        <div>
          <b>{t('versions.current', { n: version.number })}</b>
          <div className="muted small">
            {versionLabel(t, version.label)} · {date(version.created_at)}
          </div>
        </div>
      )}
      {changes?.dirty ? (
        <form className="stack" onSubmit={commit}>
          <div className="notice">
            {t('versions.dirty')}
            <ul>
              {summary.map((line) => (
                <li key={String(line)}>{line}</li>
              ))}
            </ul>
          </div>
          <input
            className="input"
            placeholder={t('versions.label')}
            value={label}
            maxLength={300}
            onChange={(e) => setLabel(e.target.value)}
          />
          <button className="btn primary" disabled={busy}>
            {t('versions.commit')}
          </button>
        </form>
      ) : (
        <p className="muted small">{t('versions.clean')}</p>
      )}
      <h4>{t('versions.history')}</h4>
      <ul className="history">
        {versions.map((item) => (
          <li key={item.id}>
            <div>
              <b>{item.number}</b> {versionLabel(t, item.label)}
              <div className="faint small">{date(item.created_at)}</div>
            </div>
            {item.id !== version?.id && (
              <button className="btn ghost small" disabled={busy} onClick={() => rollback(item)}>
                {t('versions.rollback')}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
