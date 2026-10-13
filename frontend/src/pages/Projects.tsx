import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, type Mode, type ProjectBrief } from '../api'
import { errorText, useI18n } from '../i18n'

export default function Projects() {
  const { t } = useI18n()
  const [projects, setProjects] = useState<ProjectBrief[] | null>(null)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState('')

  const load = () =>
    api
      .projects()
      .then(setProjects)
      .catch((e) => setError(errorText(t, e)))
  useEffect(() => {
    load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const remove = async (project: ProjectBrief) => {
    if (!confirm(t('projects.delete.confirm', { title: project.title }))) return
    await api.deleteProject(project.id)
    load()
  }

  return (
    <main className="page">
      <div className="page-head">
        <h1>{t('projects.title')}</h1>
        <span className="spacer" />
        <button className="btn primary" onClick={() => setCreating(true)}>
          {t('projects.new')}
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {projects === null && !error && <p className="muted">{t('app.loading')}</p>}
      {projects?.length === 0 && <p className="muted">{t('projects.empty')}</p>}
      <div className="grid">
        {projects?.map((project) => (
          <div key={project.id} className="card project-card">
            <Link to={`/projects/${project.id}`} className="project-link">
              <span className={`badge ${project.mode}`}>{t(`mode.${project.mode}`)}</span>
              <h3>{project.title}</h3>
              {project.author && <div className="muted">{project.author}</div>}
              <div className="faint small">
                {t('projects.chapters', { n: project.chapters })} ·{' '}
                {t('app.chars', { n: project.chars.toLocaleString() })}
              </div>
            </Link>
            <button className="btn ghost small danger" onClick={() => remove(project)}>
              {t('app.delete')}
            </button>
          </div>
        ))}
      </div>
      {creating && <NewProject onClose={() => setCreating(false)} />}
    </main>
  )
}

function NewProject({ onClose }: { onClose: () => void }) {
  const { t } = useI18n()
  const navigate = useNavigate()
  const [mode, setMode] = useState<Mode>('reader')
  const [title, setTitle] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const project = await api.createProject(mode, title, file)
      navigate(`/projects/${project.id}`)
    } catch (e) {
      setError(errorText(t, e))
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form className="dialog stack" onSubmit={submit}>
        <h2>{t('new.title')}</h2>
        <div className="mode-choice">
          {(['reader', 'writer'] as const).map((option) => (
            <label key={option} className={`mode-option ${mode === option ? 'active' : ''}`}>
              <input
                type="radio"
                name="mode"
                checked={mode === option}
                onChange={() => setMode(option)}
              />
              <b>{t(`mode.${option}`)}</b>
              <span className="muted small">{t(`mode.${option}.hint`)}</span>
            </label>
          ))}
        </div>
        <label className="field">
          {t('new.file')}
          <input
            type="file"
            className="input"
            accept=".txt,.md,.epub,.fb2,.docx,.pdf"
            required={mode === 'reader'}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <span className="faint">
            {t('new.file.formats')}
            {mode === 'writer' && `. ${t('new.file.optional')}`}
          </span>
        </label>
        <label className="field">
          {t('new.name')}
          <input
            className="input"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required={mode === 'writer' && !file}
          />
          {file && <span className="faint">{t('new.name.hint')}</span>}
        </label>
        {error && <p className="error">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button type="button" className="btn" onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={busy}>
            {busy ? t('new.creating') : t('new.create')}
          </button>
        </div>
      </form>
    </div>
  )
}
