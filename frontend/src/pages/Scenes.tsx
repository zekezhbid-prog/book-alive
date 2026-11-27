import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  api,
  peek,
  sectionOf,
  isAngle,
  type ChapterBrief,
  type EntityKind,
  type ImageInfo,
  type Project,
  type Scene,
  type SceneBrief,
} from '../api'
import CardGrid from '../components/CardGrid'
import { RedoPanel } from '../components/Gallery'
import { ReferenceChat } from '../components/ReferenceChat'
import SceneExport from '../components/SceneExport'
import { zoomLink } from '../components/Lightbox'
import { AutoTextarea } from '../components/AutoTextarea'
import { MicButton } from '../components/MicButton'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import DescriptionEditor from '../components/DescriptionEditor'
import { errorText, useI18n } from '../i18n'
import { saveView, useView } from '../view'
import { ask } from '../dialogs'
import { chooseSplit } from '../sceneSplit'
import AiNotice, { useTextModelReady } from '../components/AiNotice'
import {
  CheckIcon,
  CopyIcon,
  TrashIcon,
  GoldPlusSymbol,
  GoldSparklesSymbol,
  DownloadIcon,
  PlusIcon,
  SparklesIcon,
  UploadIcon,
} from '../components/icons'
import { HelpButton } from '../components/HelpButton'
import FoldHead from '../components/FoldHead'

type Participant = Scene['participants'][number]

/** Scenes of the book and, for the open one, everything needed to animate it elsewhere. */
export default function Scenes() {
  const { t } = useI18n()
  const { projectId = '', sceneId } = useParams()
  const navigate = useNavigate()
  // The last answers are shown at once (no blink when switching tabs), then refreshed.
  const [project, setProject] = useState<Project | null>(() => peek.project(projectId) ?? null)
  const [list, setList] = useState<SceneBrief[] | null>(() => peek.scenes(projectId) ?? null)
  const [scene, setScene] = useState<Scene | null>(() => (sceneId && peek.scene(sceneId)) || null)
  const [error, setError] = useState('')
  const [splitting, setSplitting] = useState(false)
  const view = useView({ id: projectId, mode: project?.mode ?? 'reader' })

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t])
  const loadList = useCallback(() => api.scenes(projectId).then(setList, fail), [projectId, fail])
  useEffect(() => {
    api.project(projectId).then(setProject, fail)
    loadList()
  }, [projectId, loadList, fail])

  const activeId = list?.some((s) => s.id === sceneId) ? sceneId : undefined
  useEffect(() => {
    if (!activeId) return setScene(null)
    setScene((shown) => (shown?.id === activeId ? shown : (peek.scene(activeId) ?? null)))
    api.scene(activeId).then(setScene, fail)
  }, [activeId, fail])

  if (!project) return <main className="page muted">{error || t('app.loading')}</main>
  const writing = view === 'writer'

  // A scene is marked in the reading view of a chapter, by selecting its text.
  const markByHand = () => {
    if (project.mode === 'writer') saveView(projectId, 'illustrator')
    navigate(`/projects/${projectId}/chapters/${lastChapter(projectId, project.chapters)}`)
  }
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
            {/* Nothing open: every scene as a tile, marking by hand and splitting with AI first. */}
            {list && !sceneId && (
              <CardGrid
                actions={[
                  {
                    icon: <GoldPlusSymbol />,
                    title: t('tiles.scene.mark'),
                    hint: t('tiles.scene.mark.hint'),
                    onClick: markByHand,
                    disabled: !project.chapters.length,
                  },
                  {
                    icon: <GoldSparklesSymbol />,
                    title: t('tiles.scene.split'),
                    hint: t('tiles.scene.split.hint'),
                    onClick: () => setSplitting(true),
                    disabled: !project.chapters.length,
                  },
                ]}
                tiles={list.map((item) => ({
                  id: item.id,
                  title: item.title || t('book.untitled'),
                  text: item.summary,
                  meta: item.chapter_title || t('book.untitled'),
                  cover: item.cover,
                  mark: item.vivid ? (
                    <span className="vivid" title={t('scenes.vivid')}>
                      ★{' '}
                    </span>
                  ) : undefined,
                  extra: (
                    <>
                      {item.stale && <span className="dot" title={t('scene.stale')} />}
                      {item.has_prompt && (
                        <span className="has-prompt" title={t('scenes.has_prompt')}>
                          ✓
                        </span>
                      )}
                    </>
                  ),
                }))}
                onOpen={(id) => navigate(`/projects/${projectId}/scenes/${id}`)}
              />
            )}
            {scene && sceneId && (
              <SceneView
                onClose={() => navigate(`/projects/${projectId}/scenes`)}
                key={scene.id}
                projectId={projectId}
                scene={scene}
                hasStyle={Boolean(project.style_id)}
                chapters={project.chapters}
                writing={writing}
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
      {splitting && (
        <SplitDialog
          projectId={projectId}
          chapters={project.chapters}
          onClose={() => setSplitting(false)}
          onDone={(first) => {
            setSplitting(false)
            loadList()
            if (first) navigate(`/projects/${projectId}/scenes/${first}`)
          }}
        />
      )}
    </>
  )
}

/** The chapter the reader was last in, or the first one. */
function lastChapter(projectId: string, chapters: ChapterBrief[]): string {
  let last: string | null = null
  try {
    last = localStorage.getItem(`lastChapter:${projectId}`)
  } catch {
    /* private mode */
  }
  return chapters.some((c) => c.id === last) && last ? last : (chapters[0]?.id ?? '')
}

interface SplitProps {
  projectId: string
  chapters: ChapterBrief[]
  onClose: () => void
  onDone: (firstSceneId: string | undefined) => void
}

/** Pick a chapter, see the price, then the AI splits it into scenes (as in the reader). */
function SplitDialog({ projectId, chapters, onClose, onDone }: SplitProps) {
  const { t } = useI18n()
  const aiReady = useTextModelReady()
  const [chapterId, setChapterId] = useState(() => lastChapter(projectId, chapters))
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const start = async () => {
    setError('')
    try {
      const choice = await chooseSplit(t, chapterId)
      if (!choice) return
      if ('show' in choice) return onDone(choice.show)
      setBusy(true)
      const scenes = await api.splitScenes(chapterId, choice.again)
      onDone(scenes[0]?.id)
    } catch (e) {
      setError(errorText(t, e))
      setBusy(false)
    }
  }
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="dialog stack">
        <h2>{t('tiles.scene.split')}</h2>
        <label className="field">
          {t('tiles.scene.split.chapter')}
          <select className="input" value={chapterId} disabled={busy} onChange={(e) => setChapterId(e.target.value)}>
            {chapters.map((chapter, index) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title || `${index + 1}. ${t('book.untitled')}`}
              </option>
            ))}
          </select>
        </label>
        <AiNotice ready={aiReady} />
        {error && <p className="error">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn" disabled={busy} onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={busy || !chapterId} onClick={start}>
            {busy ? t('scenes.split.busy') : t('scenes.split')}
          </button>
        </div>
      </div>
    </div>
  )
}

/** The text with the fragments the model added lit, in the order they stand. */
function marked(text: string, added: string[]): ReactNode[] {
  const parts: ReactNode[] = []
  let rest = text
  for (;;) {
    const hits = added
      .map((fragment) => ({ fragment, at: rest.indexOf(fragment) }))
      .filter((hit) => hit.fragment && hit.at >= 0)
      .sort((a, b) => a.at - b.at)
    if (!hits.length) break
    const { fragment, at } = hits[0]
    parts.push(rest.slice(0, at), <mark key={parts.length}>{fragment}</mark>)
    rest = rest.slice(at + fragment.length)
  }
  parts.push(rest)
  return parts
}

interface TextsProps {
  scene: Scene
  writing: boolean
  aiReady: boolean
  onChange: (scene: Scene) => void
}

/** Two folds like a card's sections: the scene as written for the screen, and the book's
 *  own text. "Add more" suggests what fits but the book does not say; it is shown marked
 *  and saved only by "Apply" (owner's notes 25.11). */
function SceneTexts({ scene, writing, aiReady, onChange }: TextsProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState({ scene: true, book: false })
  const [enriching, setEnriching] = useState(false)
  return (
    <div className="stack scene-texts">
      <FoldHead
        title={t('scene.description')}
        open={open.scene}
        onToggle={() => setOpen((now) => ({ ...now, scene: !now.scene }))}
      >
        <button
          className="btn ghost small"
          disabled={!aiReady}
          title={t('scene.enrich.hint')}
          onClick={() => setEnriching(true)}
        >
          <SparklesIcon />
          {t('scene.enrich')}
        </button>
      </FoldHead>
      {enriching && (
        <EnrichDialog
          scene={scene}
          onApplied={(next) => {
            onChange(next)
            setOpen((now) => ({ ...now, scene: true }))
          }}
          onClose={() => setEnriching(false)}
        />
      )}
      {open.scene &&
        (writing ? (
          <DescriptionEditor
            value={scene.summary}
            label={t('description.title')}
            placeholder={t('description.scene.placeholder')}
            onSave={(text) => api.saveSceneSummary(scene.id, text).then(onChange)}
          />
        ) : scene.summary ? (
          <p className="scene-summary">{scene.summary}</p>
        ) : (
          <p className="faint small">{t('scene.description.empty')}</p>
        ))}
      <FoldHead
        title={t('scene.text')}
        open={open.book}
        onToggle={() => setOpen((now) => ({ ...now, book: !now.book }))}
      />
      {open.book && (
        <div className="stack scene-book-text">
          {scene.text.split('\n\n').map((paragraph, i) => (
            <p key={i}>{paragraph}</p>
          ))}
        </div>
      )}
    </div>
  )
}

/** "Add more" in a window of its own: the author's wishes (typed or spoken, may be empty),
 *  then the progress and the result in the same place; "Apply" saves it to the scene,
 *  "Cancel" leaves the scene as it was (owner's notes 26.11). */
function EnrichDialog({
  scene,
  onApplied,
  onClose,
}: {
  scene: Scene
  onApplied: (scene: Scene) => void
  onClose: () => void
}) {
  const { t } = useI18n()
  const [wishes, setWishes] = useState('')
  const [offer, setOffer] = useState<{ text: string; added: string[]; why: string } | null>(null)
  const [busy, setBusy] = useState<'' | 'enrich' | 'apply'>('')
  const [error, setError] = useState('')
  const enrich = async () => {
    setBusy('enrich')
    setError('')
    try {
      setOffer(await api.enrichScene(scene.id, wishes.trim()))
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  const apply = async () => {
    if (!offer) return
    setBusy('apply')
    setError('')
    try {
      onApplied(await api.saveSceneSummary(scene.id, offer.text))
      onClose()
    } catch (e) {
      setError(errorText(t, e))
      setBusy('')
    }
  }
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="dialog stack enrich-dialog">
        <div className="row">
          <h2 className="grow">{t('scene.enrich.title')}</h2>
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} disabled={busy !== ''} onClick={onClose}>
            ✕
          </button>
        </div>
        <p className="muted small">{t('scene.enrich.hint')}</p>
        <div className="row">
          <AutoTextarea
            className="input grow"
            value={wishes}
            maxLength={2000}
            placeholder={t('scene.enrich.wishes')}
            disabled={busy !== ''}
            onChange={(e) => setWishes(e.target.value)}
          />
          <MicButton
            disabled={busy !== ''}
            onText={(spoken) => setWishes((now) => (now.trim() ? `${now.trim()} ${spoken}` : spoken))}
            onError={setError}
          />
        </div>
        <div className="row">
          <button className="btn" disabled={busy !== ''} onClick={enrich}>
            <SparklesIcon />
            {busy === 'enrich' ? t('scene.enrich.busy') : t('scene.enrich')}
          </button>
        </div>
        {offer && (
          <div className="stack enrich-offer">
            <p className="scene-summary">{marked(offer.text, offer.added)}</p>
            {offer.why && <p className="muted small">{offer.why}</p>}
            {!offer.added.length && <p className="faint small">{t('scene.enrich.none')}</p>}
          </div>
        )}
        {error && <p className="error small">{error}</p>}
        <div className="row">
          <span className="spacer" />
          <button className="btn ghost" disabled={busy !== ''} onClick={onClose}>
            {t('app.cancel')}
          </button>
          <button className="btn primary" disabled={busy !== '' || !offer} onClick={apply}>
            <CheckIcon />
            {t('generate.face.apply')}
          </button>
        </div>
      </div>
    </div>
  )
}

interface ViewProps {
  /** The ✕ in the corner: back to the tiles of the section. */
  onClose: () => void
  projectId: string
  scene: Scene
  hasStyle: boolean
  chapters: ChapterBrief[]
  /** A writer describes the scene in words; pictures and video belong to the illustrator. */
  writing: boolean
  onChange: (scene: Scene) => void
  onDelete: () => void
}

function SceneView({ onClose, projectId, scene, hasStyle, writing, onChange, onDelete }: ViewProps) {
  const { t } = useI18n()
  const aiReady = useTextModelReady()
  const [prompt, setPrompt] = useState(scene.prompt)
  const [note, setNote] = useState('')
  const [change, setChange] = useState('')
  const [busy, setBusy] = useState<'' | 'prompt' | 'refine'>('')
  const [promptOpen, setPromptOpen] = useState(Boolean(scene.prompt))
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  // The picture window over the scene: for a card in it, or for the first frame.
  const [adding, setAdding] = useState<{ who: Participant; bases: ImageInfo[] } | 'frame' | null>(
    null,
  )
  const closeAdding = useCallback(() => setAdding(null), [])
  const [exporting, setExporting] = useState(false)
  const closeExport = useCallback(() => setExporting(false), [])
  // The user changed the pictures by hand after the prompt was written: its numbers may be off.
  const [refsChanged, setRefsChanged] = useState(false)
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
  // Not every picture the scene wants is there: the user is asked before going on with what
  // there is (owner's notes 26.11).
  const enoughRefs = async () => !scene.missing.length || (await ask(t('scene.missing.confirm')))
  const build = async () => {
    if (await enoughRefs()) {
      setRefsChanged(false)
      setPromptOpen(true)
      run('prompt', () => api.buildScenePrompt(scene.id, note))
    }
  }
  const openExport = async () => {
    if (await enoughRefs()) setExporting(true)
  }
  // A picture taken into the video or left out by hand (owner's notes 26.11).
  const toggleRef = async (imageId: string) => {
    const now = scene.references.map((r) => r.image_id)
    const next = now.includes(imageId) ? now.filter((id) => id !== imageId) : [...now, imageId]
    setError('')
    try {
      onChange(await api.chooseSceneReferences(scene.id, next))
      if (scene.prompt) setRefsChanged(true)
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  const section = (kind: EntityKind) => sectionOf(kind)
  // A place's own view (owner's notes 26.11) has no caption here, only a character's.
  const describe = (main: boolean, angle: string, look: string) =>
    main
      ? [t('gallery.main'), isAngle(angle) && t(`angle.${angle}`)].filter(Boolean).join(', ')
      : look || t('scene.look')

  return (
    <>
      <div className="row">
        <h1 className="entity-name grow">{scene.title || t('book.untitled')}</h1>
        {/* Saving the scene and deleting it are icons beside the ✕ (owner's notes 26.11). */}
        <button
          className="btn ghost small icon"
          disabled={aiReady === false}
          title={t('export.button')}
          aria-label={t('export.button')}
          onClick={openExport}
        >
          <UploadIcon />
        </button>
        <button
          className="btn ghost small icon gold"
          title={t('scene.delete')}
          aria-label={t('scene.delete')}
          onClick={onDelete}
        >
          <TrashIcon />
        </button>
        <button className="btn ghost card-close" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
          ✕
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
      <SceneTexts scene={scene} writing={writing} aiReady={!!aiReady} onChange={onChange} />

      {!writing && (
        <>
      <h4>{t('scene.references')}</h4>
      {!hasStyle && <p className="faint small">{t('scene.references.no_style')}</p>}
      {/* What the scene still lacks: a click opens the card's picture window (owner's notes 26.11). */}
      {hasStyle && scene.missing.length > 0 && (
        <div className="row wrap missing-refs">
          <span className="small muted">{t('scene.missing.title')}</span>
          {scene.missing.map((m) => {
            const who = scene.participants.find((p) => p.id === m.entity_id)
            return (
              <button
                key={`${m.entity_id}-${m.need}`}
                className="chip plain missing-ref"
                title={t('scene.missing.hint')}
                disabled={!who}
                onClick={() => who && addFor(who)}
              >
                <PlusIcon />
                {m.name} — {t(`scene.missing.${m.need}`)}
              </button>
            )
          })}
        </div>
      )}
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
                  id: ref.image_id,
                  inVideo: true,
                  url: ref.url,
                  number: ref.number,
                  note: `${describe(ref.role === 'main', ref.angle, ref.look_label)} · ${t('scene.ref.in_video')}`,
                })),
              ...who.images
                .filter((image) => !scene.references.some((ref) => ref.url === image.url))
                .map((image) => ({
                  // Only a picture in the current style can be taken into the video.
                  id: image.current_style ? image.id : undefined,
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
            onToggle={toggleRef}
          />
        ))}
      </div>
      {refsChanged && <p className="muted small">{t('scene.refs.changed')}</p>}
      {adding === 'frame' && (
        <FrameDialog
          scene={scene}
          hasStyle={hasStyle}
          onChanged={onChange}
          onClose={closeAdding}
          onBuild={async () => {
            if (!(await enoughRefs())) return null
            const next = await api.buildScenePrompt(scene.id, '')
            setPrompt(next.prompt)
            onChange(next)
            return next
          }}
          onToggle={toggleRef}
        />
      )}
      {adding && adding !== 'frame' && (
        <ReferenceChat
          projectId={projectId}
          entityId={adding.who.id}
          bases={adding.bases}
          kind={adding.who.kind}
          name={adding.who.name}
          hasStyle={hasStyle}
          onChanged={reload}
          onClose={closeAdding}
        />
      )}

      {/* The prompt folds away; building it opens the fold. The busy line sits in the
          heading, so nothing below moves while it is written (owner's notes 26.11). */}
      <FoldHead
        title={t('scene.prompt')}
        open={promptOpen || busy !== ''}
        onToggle={() => setPromptOpen((now) => !now)}
        note={busy === 'prompt' ? <span className="muted small">{t('scene.build.busy')}</span> : undefined}
      >
        <button
          className="btn ghost small icon gold"
          disabled={busy !== '' || aiReady === false}
          title={busy === 'prompt' ? t('scene.build.busy') : scene.prompt ? t('scene.rebuild') : t('scene.build')}
          aria-label={scene.prompt ? t('scene.rebuild') : t('scene.build')}
          onClick={build}
        >
          <SparklesIcon />
        </button>
        {scene.prompt && (
          <button
            className={`btn ghost small icon ${copied ? 'on' : ''}`}
            title={copied ? t('scene.copied') : t('scene.copy')}
            aria-label={t('scene.copy')}
            onClick={copy}
          >
            <CopyIcon />
          </button>
        )}
      </FoldHead>
      {(promptOpen || busy !== '') && !scene.prompt && (
        <AutoTextarea
          className="input"
          value={note}
          maxLength={2000}
          placeholder={t('scene.note.placeholder')}
          onChange={(e) => setNote(e.target.value)}
        />
      )}
      {(promptOpen || busy !== '') && scene.prompt && (
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
      {!scene.prompt && <AiNotice ready={aiReady} />}
      {/* The archive is what the work here is for: one large button at the end. */}
      <div className="row scene-export-row">
        <button
          className="btn primary large grow"
          disabled={!scene.prompt}
          title={scene.prompt ? t('scene.archive.hint') : t('scene.archive.no_prompt')}
          onClick={download}
        >
          <DownloadIcon />
          {t('scene.archive.big')}
        </button>
      </div>
        </>
      )}
      {exporting && <SceneExport scene={scene} onClose={closeExport} />}
      {error && <p className="error">{error}</p>}
    </>
  )
}

interface SlotPicture {
  /** Set when the picture may go to the video: it can be taken in or left out by hand. */
  id?: string
  inVideo?: boolean
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
  onToggle?: (imageId: string) => void
}

/** One frame among the references: its pictures one at a time, and a "+" to add another. */
function RefSlot({ title, pictures, empty, addTitle, onAdd, onToggle }: SlotProps) {
  const { t } = useI18n()
  const [index, setIndex] = useState(0)
  const at = Math.min(index, pictures.length - 1)
  const shown = pictures[at]
  const step = (by: number) => setIndex((at + by + pictures.length) % pictures.length)
  return (
    <figure className={shown ? '' : 'empty'}>
      <div className="ref-pic">
        {shown ? (
          <a {...zoomLink(pictures.map((p) => p.url), at)}>
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
          {onToggle && shown?.id && (
            <button
              className={`btn ghost small icon ${shown.inVideo ? 'on' : ''}`}
              title={t(shown.inVideo ? 'scene.ref.drop' : 'scene.ref.take')}
              aria-label={t(shown.inVideo ? 'scene.ref.drop' : 'scene.ref.take')}
              onClick={() => onToggle(shown.id!)}
            >
              {shown.inVideo ? '✕' : <CheckIcon />}
            </button>
          )}
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
  /** Writes the video prompt, asking first when pictures are missing; null when not written. */
  onBuild: () => Promise<Scene | null>
  /** Takes a picture into the scene's references or leaves it out. */
  onToggle: (imageId: string) => void
}

/**
 * The first frame's window, laid out like the card's picture window (owner's notes 26.11):
 * the prompt is ready (the video prompt turned into a still, editable here), the scene's
 * references are already in, and one press draws it. A finished frame opens with its prompt
 * and remarks: a changed prompt draws it anew, a remark improves the frame itself. The
 * user's own picture can be put in too. The newest frame goes into the archive.
 */
function FrameDialog({ scene, hasStyle, onChanged, onClose, onBuild, onToggle }: FrameProps) {
  const { t } = useI18n()
  const [prompt, setPrompt] = useState(scene.frame_prompt)
  // The frame in view; '' is a new one.
  const [pickedId, setPickedId] = useState(scene.frames[0]?.id ?? '')
  const picked = scene.frames.find((f) => f.id === pickedId) ?? null
  const [busy, setBusy] = useState<'' | 'image' | 'upload' | 'prompt' | 'delete'>('')
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
      setPickedId(next.frames[0]?.id ?? '')
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
  // No video prompt yet: it is written here, and the frame prompt comes from it.
  const build = async () => {
    setBusy('prompt')
    setError('')
    try {
      const next = await onBuild()
      if (next) setPrompt(next.frame_prompt)
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }
  const reload = () => api.scene(scene.id).then(onChanged, (e) => setError(errorText(t, e)))
  const removeFrame = async (frame: ImageInfo) => {
    if (!(await ask(t('gallery.delete.confirm')))) return
    setBusy('delete')
    setError('')
    try {
      await api.deleteImage(frame.id)
      setPickedId('')
      await reload()
    } catch (e) {
      setError(errorText(t, e))
    }
    setBusy('')
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog generator image-dialog">
        <div className="row">
          <h2>{t('scene.frame.title')}</h2>
          <span className="spacer" />
          {/* Every explanation of the window lives behind its "?" (owner's notes 27.11). */}
          <HelpButton
            title={t('scene.frame.title')}
            paragraphs={[t('scene.frame.hint'), t('scene.frame.short'), t('generate.help.done')]}
          />
          <button className="btn ghost small icon" title={t('app.close')} aria-label={t('app.close')} onClick={onClose}>
            ✕
          </button>
        </div>
        <div className="dialog-body">
          <div className="stack">
            <div className="picture-slot">
              {picked ? (
                <div className="stack slot-picture">
                  <a {...zoomLink(scene.frames.map((f) => f.url), Math.max(0, scene.frames.indexOf(picked)))}>
                    <img src={picked.url} alt="" />
                  </a>
                </div>
              ) : (
                <span className="stack slot-hint">
                  <span className="faint small">
                    {busy === 'image' ? t('generate.image.busy') : t('generate.slot')}
                  </span>
                </span>
              )}
            </div>
            {/* The new frame first, then every frame made so far, newest first. */}
            <div className="look-strip base-strip">
              <div className="look-new-wrap">
                <button
                  className={`look-tile look-new ${!picked ? 'shown' : ''}`}
                  disabled={busy !== ''}
                  title={t('scene.frame.new')}
                  onClick={() => setPickedId('')}
                >
                  <span className="look-new-icon" aria-hidden>
                    <PlusIcon />
                  </span>
                  <span className="small">{t('scene.frame.new')}</span>
                </button>
              </div>
              {scene.frames.map((frame) => (
                <div key={frame.id} className="look-tile-wrap">
                  <button
                    className={`look-tile ${picked?.id === frame.id ? 'shown' : ''}`}
                    disabled={busy !== ''}
                    title={t('generate.slot.show')}
                    onClick={() => setPickedId(frame.id)}
                  >
                    <img src={frame.url} alt="" loading="lazy" />
                  </button>
                </div>
              ))}
            </div>
          </div>
          {picked ? (
            <RedoPanel
              key={picked.id}
              image={picked}
              hasStyle={hasStyle}
              disabled={busy !== ''}
              onDone={() => reload()}
              onDelete={() => removeFrame(picked)}
            />
          ) : (
            <div className="stack">
              {/* The scene's references go with the frame; one can be left out here, more are
                  taken in under the scene. */}
              <div className="stack field">
                <span className="small muted">{t('scene.references')}</span>
                {scene.references.length ? (
                  <div className="used-refs">
                    {scene.references.map((ref) => (
                      <span key={ref.image_id} className="used-ref" title={ref.entity_name}>
                        <a {...zoomLink(scene.references.map((r) => r.url), ref.number - 1)}>
                          <img src={ref.url} alt="" loading="lazy" />
                        </a>
                        <button
                          className="btn ghost small icon"
                          disabled={busy !== ''}
                          title={t('scene.ref.drop')}
                          aria-label={t('scene.ref.drop')}
                          onClick={() => onToggle(ref.image_id)}
                        >
                          ✕
                        </button>
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="faint small">{t('scene.frame.no_refs')}</span>
                )}
              </div>
              <label className="stack field">
                <span className="small muted">{t('generate.prompt.label')}</span>
                {scene.prompt ? (
                  <AutoTextarea
                    className="input prompt"
                    value={prompt}
                    maxLength={6000}
                    onChange={(e) => setPrompt(e.target.value)}
                  />
                ) : (
                  <span className="row wrap">
                    <span className="muted small grow">{t('scene.frame.needs_prompt')}</span>
                    <button className="btn small" disabled={busy !== ''} onClick={build}>
                      <SparklesIcon />
                      {busy === 'prompt' ? t('scene.build.busy') : t('scene.build')}
                    </button>
                  </span>
                )}
              </label>
              <div className="row wrap">
                <button
                  className="btn primary generate-big"
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
              {!hasStyle && <span className="muted small">{t('generate.no_style')}</span>}
            </div>
          )}
        </div>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
}
