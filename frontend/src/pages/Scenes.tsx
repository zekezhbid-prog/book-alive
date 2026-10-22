import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Project, type Scene, type SceneBrief } from '../api'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import { errorText, useI18n } from '../i18n'

/** Scenes of the book and, for the open one, everything needed to animate it elsewhere. */
export default function Scenes() {
  const { t } = useI18n()
  const { projectId = '', sceneId } = useParams()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [list, setList] = useState<SceneBrief[] | null>(null)
  const [scene, setScene] = useState<Scene | null>(null)
  const [error, setError] = useState('')

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadList = useCallback(() => api.scenes(projectId).then(setList, fail), [projectId, fail])
  useEffect(() => {
    api.project(projectId).then(setProject, fail)
    loadList()
  }, [projectId, loadList, fail])

  const activeId = list?.some((s) => s.id === sceneId) ? sceneId : undefined
  useEffect(() => {
    if (!activeId) return setScene(null)
    setScene(null)
    api.scene(activeId).then(setScene, fail)
  }, [activeId, fail])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>

  const remove = async () => {
    if (!scene || !confirm(t('scene.delete.confirm'))) return
    await api.deleteScene(scene.id).then(loadList, fail)
    navigate(`/projects/${projectId}/scenes`)
  }
  return (
    <>
      <ProjectHeader project={project} />
      <div className="workspace">
        <ProjectNav project={project} scenes={list} />
        <section className="reading">
          <div className="chapter stack">
            {error && <p className="error">{error}</p>}
            {list && list.length > 0 && !activeId && <p className="muted">{t('scenes.select')}</p>}
            {scene && (
              <SceneView
                key={scene.id}
                projectId={projectId}
                scene={scene}
                hasStyle={Boolean(project.style_id)}
                onChange={(next) => {
                  setScene(next)
                  loadList()
                }}
                onDelete={remove}
              />
            )}
          </div>
        </section>
      </div>
    </>
  )
}

interface ViewProps {
  projectId: string
  scene: Scene
  hasStyle: boolean
  onChange: (scene: Scene) => void
  onDelete: () => void
}

function SceneView({ projectId, scene, hasStyle, onChange, onDelete }: ViewProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(scene.prompt)
  const [note, setNote] = useState('')
  const [change, setChange] = useState('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'refine' | 'frame'>('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)

  const run = async (step: 'prompt' | 'refine' | 'frame', call: () => Promise<Scene>) => {
    setBusy(step)
    setError('')
    try {
      const next = await call()
      setPrompt(next.prompt)
      onChange(next)
      if (step === 'refine') setChange('')
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  // The copy and the archive must carry what is on screen, so an edit is saved first.
  const saveEdit = async () => {
    if (prompt.trim() === scene.prompt) return scene
    const saved = await api.saveScenePrompt(scene.id, prompt)
    onChange(saved)
    return saved
  }
  const copy = async () => {
    const saved = await saveEdit()
    await navigator.clipboard.writeText(saved.prompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  const download = async () => {
    await saveEdit()
    location.href = api.sceneArchiveUrl(scene.id)
  }
  const section = (kind: string) => (kind === 'character' ? 'characters' : 'locations')

  return (
    <>
      <div className="row">
        <h1 className="entity-name grow">{scene.title || t('book.untitled')}</h1>
        <button className="btn ghost small danger" onClick={onDelete}>
          {t('scene.delete')}
        </button>
      </div>
      <div className="row wrap muted">
        <Link to={`/projects/${projectId}/chapters/${scene.chapter_id}?p=${scene.paragraph_from}`}>
          {scene.chapter_title || t('book.untitled')} ↗
        </Link>
        {scene.stale && (
          <span className="badge stale" title={t('scene.stale.hint')}>
            {t('entities.stale')}
          </span>
        )}
        {scene.participants.map((who) => (
          <Link
            key={who.id}
            className="chip plain"
            to={`/projects/${projectId}/${section(who.kind)}/${who.id}`}
          >
            {who.name}
          </Link>
        ))}
      </div>
      {scene.summary && <p className="muted">{scene.summary}</p>}
      <details>
        <summary className="muted">{t('scene.text')}</summary>
        {scene.text.split('\n\n').map((paragraph, i) => (
          <p key={i}>{paragraph}</p>
        ))}
      </details>

      <h4>{t('scene.references')}</h4>
      {scene.references.length === 0 ? (
        <p className="faint small">
          {t(hasStyle ? 'scene.references.none' : 'scene.references.no_style')}
        </p>
      ) : (
        <div className="refs">
          {scene.references.map((ref) => (
            <figure key={ref.number}>
              <img src={ref.url} alt="" loading="lazy" />
              <figcaption>
                <b>{ref.number}</b> {ref.entity_name}
                <div className="faint small">
                  {ref.role === 'main'
                    ? [t('gallery.main'), ref.angle && t(`angle.${ref.angle}`)]
                        .filter(Boolean)
                        .join(', ')
                    : ref.look_label || t('scene.look')}
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
      )}

      <h4>{t('scene.prompt')}</h4>
      {!scene.prompt && (
        <input
          className="input"
          value={note}
          maxLength={2000}
          placeholder={t('scene.note.placeholder')}
          onChange={(e) => setNote(e.target.value)}
        />
      )}
      {scene.prompt && (
        <>
          <textarea
            className="input prompt"
            rows={7}
            value={prompt}
            maxLength={6000}
            onChange={(e) => setPrompt(e.target.value)}
            onBlur={() => saveEdit().catch((e) => setError(errorText(t, e)))}
          />
          <div className="row">
            <input
              className="input grow"
              value={change}
              maxLength={2000}
              placeholder={t('scene.refine.placeholder')}
              onChange={(e) => setChange(e.target.value)}
              onKeyDown={(e) =>
                e.key === 'Enter' &&
                change.trim() &&
                run('refine', () => api.refineScenePrompt(scene.id, change))
              }
            />
            <button
              className="btn"
              disabled={busy !== '' || !change.trim()}
              onClick={() => run('refine', () => api.refineScenePrompt(scene.id, change))}
            >
              {busy === 'refine' ? t('scene.refine.busy') : t('scene.refine')}
            </button>
          </div>
        </>
      )}
      <div className="row wrap">
        <button
          className={`btn ${scene.prompt ? '' : 'primary'}`}
          disabled={busy !== ''}
          onClick={() => run('prompt', () => api.buildScenePrompt(scene.id, note))}
        >
          {busy === 'prompt'
            ? t('scene.build.busy')
            : t(scene.prompt ? 'scene.rebuild' : 'scene.build')}
        </button>
        {scene.prompt && (
          <>
            <button className="btn primary" onClick={copy}>
              {copied ? t('scene.copied') : t('scene.copy')}
            </button>
            <button className="btn" onClick={download}>
              {t('scene.archive')}
            </button>
            <button
              className="btn"
              disabled={busy !== ''}
              onClick={() => run('frame', () => api.generateSceneFrame(scene.id))}
            >
              {busy === 'frame' ? t('generate.image.busy') : t('scene.frame')}
            </button>
          </>
        )}
      </div>
      {error && <p className="error">{error}</p>}
      {scene.frames.length > 0 && (
        <>
          <h4>{t('scene.frames')}</h4>
          <div className="refs wide">
            {scene.frames.map((frame, i) => (
              <figure key={frame.id}>
                <a href={frame.url} target="_blank" rel="noreferrer">
                  <img src={frame.url} alt="" loading="lazy" />
                </a>
                {i === 0 && (
                  <figcaption className="faint small">{t('scene.frame.latest')}</figcaption>
                )}
              </figure>
            ))}
          </div>
        </>
      )}
    </>
  )
}
