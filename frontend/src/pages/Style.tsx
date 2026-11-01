import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, type Project, type StylePreset } from '../api'
import Gallery from '../components/Gallery'
import PageClose from '../components/PageClose'
import ProjectHeader from '../components/ProjectHeader'
import { errorText, useI18n, type MessageKey } from '../i18n'
import { ask } from '../dialogs'

/** One look for every picture in the project, plus references that belong to no card. */
export default function Style() {
  const { t } = useI18n()
  const { projectId = '' } = useParams()
  const [project, setProject] = useState<Project | null>(null)
  const [presets, setPresets] = useState<StylePreset[]>([])
  const [custom, setCustom] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    const fail = (e: unknown) => setError(errorText(t, e))
    api.project(projectId).then((loaded) => {
      setProject(loaded)
      setCustom(loaded.style_text)
    }, fail)
    api.styles().then(setPresets, fail)
  }, [projectId, t])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const choose = async (styleId: string, text = '') => {
    // Pictures made so far carry the old style's label and stop being offered as references.
    if (project.style_id && !(await ask(t('style.change.confirm')))) return
    try {
      const saved = await api.setStyle(projectId, styleId, text)
      setProject({ ...project, ...saved })
      setError('')
    } catch (e) {
      setError(errorText(t, e))
    }
  }

  return (
    <>
      <ProjectHeader project={project} />
      <main className="page narrow stack">
        <div className="page-head">
          <div className="grow">
            <h1>{t('style.title')}</h1>
            <p className="muted">{t('style.hint')}</p>
          </div>
          <PageClose fallback={`/projects/${projectId}`} />
        </div>
        {error && <p className="error">{error}</p>}
        <div className="style-grid">
          {presets.map((preset) => (
            <button
              key={preset.id}
              className={`mode-option ${project.style_id === preset.id ? 'active' : ''}`}
              onClick={() => project.style_id !== preset.id && choose(preset.id)}
            >
              <b>{t(`style.preset.${preset.id}` as MessageKey)}</b>
              <span className="muted small">{preset.prompt}</span>
            </button>
          ))}
        </div>
        <div className={`mode-option ${project.style_id === 'custom' ? 'active' : ''}`}>
          <b>{t('style.custom')}</b>
          <textarea
            className="input"
            rows={2}
            maxLength={1000}
            value={custom}
            placeholder={t('style.custom.placeholder')}
            onChange={(e) => setCustom(e.target.value)}
          />
          <div>
            <button
              className="btn small"
              disabled={!custom.trim() || (project.style_id === 'custom' && custom.trim() === project.style_text)}
              onClick={() => choose('custom', custom)}
            >
              {t('style.custom.use')}
            </button>
          </div>
        </div>
        <section className="panel pad">
          <Gallery projectId={projectId} chapters={project.chapters} hasStyle={Boolean(project.style_id)} />
        </section>
      </main>
    </>
  )
}
