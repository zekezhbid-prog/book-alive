import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  type Angle,
  type ChapterBrief,
  type ImageInfo,
  type Project,
  type Scene,
  type SceneBrief,
} from '../api'
import { ImageDialog } from '../components/Gallery'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import { errorText, useI18n } from '../i18n'
import { ask } from '../dialogs'
import { CopyIcon, DownloadIcon, PlusIcon, SparklesIcon, UploadIcon } from '../components/icons'

type Participant = Scene['participants'][number]

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
    if (!scene || !(await ask(t('scene.delete.confirm')))) return
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
                chapters={project.chapters}
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
  chapters: ChapterBrief[]
  onChange: (scene: Scene) => void
  onDelete: () => void
}

function SceneView({ projectId, scene, hasStyle, chapters, onChange, onDelete }: ViewProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(scene.prompt)
  const [note, setNote] = useState('')
  const [change, setChange] = useState('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'refine'>('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  // The picture window over the scene: for a card in it, or for the first frame.
  const [adding, setAdding] = useState<{ who: Participant; bases: ImageInfo[] } | 'frame' | null>(
    null,
  )
  const closeAdding = useCallback(() => setAdding(null), [])
  const addFor = async (who: Participant) => {
    try {
      const images = await api.images(projectId, who.id)
      setAdding({ who, bases: images.filter((i) => i.is_main && i.current_style) })
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  // A card's new picture changes the scene's references, so the scene is fetched again.
  const reload = () => api.scene(scene.id).then(onChange, (e) => setError(errorText(t, e)))

  const run = async (step: 'prompt' | 'refine', call: () => Promise<Scene>) => {
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
  const describe = (main: boolean, angle: Angle | '', look: string) =>
    main
      ? [t('gallery.main'), angle && t(`angle.${angle}`)].filter(Boolean).join(', ')
      : look || t('scene.look')

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
      {!hasStyle && <p className="faint small">{t('scene.references.no_style')}</p>}
      <div className="refs">
        {/* The first frame comes first: it is what the video starts from. */}
        <RefSlot
          title={<b>{t('scene.first_frame')}</b>}
          pictures={scene.frames.map((frame, i) => ({
            url: frame.url,
            note: i === 0 ? t('scene.frame.latest') : '',
          }))}
          empty={t('scene.frame.none')}
          addTitle={t('scene.frame.add')}
          onAdd={() => setAdding('frame')}
        />
        {/* Everyone in the scene gets a frame with all of the card's pictures, those that go
            to the video first and numbered, or an empty one. */}
        {scene.participants.map((who) => (
          <RefSlot
            key={who.id}
            title={<Link to={`/projects/${projectId}/${section(who.kind)}/${who.id}`}>{who.name}</Link>}
            pictures={[
              ...scene.references
                .filter((ref) => ref.entity_id === who.id)
                .map((ref) => ({
                  url: ref.url,
                  number: ref.number,
                  note: `${describe(ref.role === 'main', ref.angle, ref.look_label)} · ${t('scene.ref.in_video')}`,
                })),
              ...who.images
                .filter((image) => !scene.references.some((ref) => ref.url === image.url))
                .map((image) => ({
                  url: image.url,
                  note: [
                    describe(image.is_main, image.angle, image.look_label),
                    !image.current_style && t('gallery.other_style'),
                  ]
                    .filter(Boolean)
                    .join(' · '),
                })),
            ]}
            empty={t('scene.ref.missing')}
            addTitle={t('scene.ref.add')}
            onAdd={() => addFor(who)}
          />
        ))}
      </div>
      {adding === 'frame' && (
        <FrameDialog scene={scene} hasStyle={hasStyle} onChanged={onChange} onClose={closeAdding} />
      )}
      {adding && adding !== 'frame' && (
        <ImageDialog
          projectId={projectId}
          entityId={adding.who.id}
          image={null}
          bases={adding.bases}
          withAngles={adding.who.kind === 'character'}
          chapters={chapters}
          hasStyle={hasStyle}
          onChanged={reload}
          onClose={closeAdding}
        />
      )}

      <div className="row">
        <h4 className="grow">{t('scene.prompt')}</h4>
        {/* Once there is a prompt, its actions are icons beside the heading. */}
        {scene.prompt && (
          <>
            <button
              className="btn ghost small icon"
              disabled={busy !== ''}
              title={busy === 'prompt' ? t('scene.build.busy') : t('scene.rebuild')}
              aria-label={t('scene.rebuild')}
              onClick={() => run('prompt', () => api.buildScenePrompt(scene.id, note))}
            >
              <SparklesIcon />
            </button>
            <button
              className={`btn ghost small icon ${copied ? 'on' : ''}`}
              title={copied ? t('scene.copied') : t('scene.copy')}
              aria-label={t('scene.copy')}
              onClick={copy}
            >
              <CopyIcon />
            </button>
            <button
              className="btn ghost small icon"
              title={t('scene.archive.hint')}
              aria-label={t('scene.archive')}
              onClick={download}
            >
              <DownloadIcon />
            </button>
          </>
        )}
      </div>
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
      {!scene.prompt && (
        <div className="row wrap">
          <button
            className="btn primary"
            disabled={busy !== ''}
            onClick={() => run('prompt', () => api.buildScenePrompt(scene.id, note))}
          >
            {busy === 'prompt' ? t('scene.build.busy') : t('scene.build')}
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </>
  )
}

interface SlotPicture {
  url: string
  number?: number
  note: string
}

interface SlotProps {
  title: ReactNode
  /** Newest or most important first; arrows page through them when there are several. */
  pictures: SlotPicture[]
  empty: string
  addTitle: string
  onAdd: () => void
}

/** One frame among the references: its pictures one at a time, and a "+" to add another. */
function RefSlot({ title, pictures, empty, addTitle, onAdd }: SlotProps) {
  const { t } = useI18n()
  const [index, setIndex] = useState(0)
  const at = Math.min(index, pictures.length - 1)
  const shown = pictures[at]
  const step = (by: number) => setIndex((at + by + pictures.length) % pictures.length)
  return (
    <figure className={shown ? '' : 'empty'}>
      <div className="ref-pic">
        {shown ? (
          <a href={shown.url} target="_blank" rel="noreferrer">
            <img src={shown.url} alt="" loading="lazy" />
          </a>
        ) : (
          <div className="ref-blank" />
        )}
        {pictures.length > 1 && (
          <>
            <button className="ref-arrow prev" aria-label={t('scene.ref.prev')} onClick={() => step(-1)}>
              ‹
            </button>
            <button className="ref-arrow next" aria-label={t('scene.ref.next')} onClick={() => step(1)}>
              ›
            </button>
            <span className="ref-count">
              {at + 1}/{pictures.length}
            </span>
          </>
        )}
      </div>
      <figcaption>
        <div className="row">
          <span className="grow">
            {shown?.number !== undefined && <b>{shown.number} </b>}
            {title}
          </span>
          <button className="btn ghost small icon" title={addTitle} aria-label={addTitle} onClick={onAdd}>
            <PlusIcon />
          </button>
        </div>
        <div className="faint small">{shown ? shown.note : empty}</div>
      </figcaption>
    </figure>
  )
}

interface FrameProps {
  scene: Scene
  hasStyle: boolean
  onChanged: (scene: Scene) => void
  onClose: () => void
}

/**
 * The first frame's window: drawn from the video prompt turned into a still (editable here),
 * or the user's own picture. Each new frame is stored at once and the newest one goes into
 * the archive.
 */
function FrameDialog({ scene, hasStyle, onChanged, onClose }: FrameProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(scene.frame_prompt)
  const [made, setMade] = useState<ImageInfo | null>(null)
  const [busy, setBusy] = useState<'' | 'image' | 'upload'>('')
  const [error, setError] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = async (step: 'image' | 'upload', call: () => Promise<Scene>) => {
    setBusy(step)
    setError('')
    try {
      const next = await call()
      setMade(next.frames[0] ?? null)
      onChanged(next)
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  const upload = (file: File | undefined) => {
    if (picker.current) picker.current.value = ''
    if (file) run('upload', () => api.uploadSceneFrame(scene.id, file))
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog generator image-dialog">
        <div className="row">
          <h2>{t('scene.frame.title')}</h2>
          <span className="spacer" />
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="dialog-body">
          <div className="picture-slot">
            {made ? (
              <a href={made.url} target="_blank" rel="noreferrer">
                <img src={made.url} alt="" />
              </a>
            ) : (
              <span className="faint small">
                {busy === 'image' ? t('generate.image.busy') : t('generate.slot')}
              </span>
            )}
          </div>
          <div className="stack">
            <p className="muted small">{t('scene.frame.hint')}</p>
            <label className="stack field">
              <span className="small muted">{t('generate.prompt.label')}</span>
              <textarea
                className="input prompt"
                rows={8}
                value={prompt}
                maxLength={6000}
                placeholder={t('scene.frame.needs_prompt')}
                onChange={(e) => setPrompt(e.target.value)}
              />
            </label>
            <div className="row wrap">
              <button
                className="btn small primary"
                disabled={busy !== '' || !hasStyle || !scene.prompt || !prompt.trim()}
                title={scene.prompt ? '' : t('scene.frame.needs_prompt')}
                onClick={() => run('image', () => api.generateSceneFrame(scene.id, prompt))}
              >
                <SparklesIcon />
                {busy === 'image' ? t('generate.image.busy') : t('generate.image')}
              </button>
              <input
                ref={picker}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                hidden
                onChange={(e) => upload(e.target.files?.[0])}
              />
              <button className="btn small" disabled={busy !== ''} onClick={() => picker.current?.click()}>
                <UploadIcon />
                {busy === 'upload' ? t('gallery.uploading') : t('scene.frame.upload')}
              </button>
            </div>
            {!scene.prompt && <span className="muted small">{t('scene.frame.needs_prompt')}</span>}
            {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
            {made && <p className="muted small">{t('generate.made')}</p>}
          </div>
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
