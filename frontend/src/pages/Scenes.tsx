import { useCallback, useEffect, useState, type ReactNode } from 'react'
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
  type SceneProposal,
} from '../api'
import CardGrid from '../components/CardGrid'
import { ReferenceChat } from '../components/ReferenceChat'
import SceneExport from '../components/SceneExport'
import { SceneDialog } from '../components/SceneDialog'
import { marked } from '../marked'
import { zoomLink } from '../components/Lightbox'
import { AutoTextarea } from '../components/AutoTextarea'
import { MicButton } from '../components/MicButton'
import ProjectHeader from '../components/ProjectHeader'
import ProjectNav from '../components/ProjectNav'
import DescriptionEditor from '../components/DescriptionEditor'
import { errorText, useI18n } from '../i18n'
import { saveView, useView } from '../view'
import { ask } from '../dialogs'
import { ProposalList } from '../components/SceneProposals'
import AiNotice, { useTextModelReady } from '../components/AiNotice'
import { CheckIcon, DownloadIcon, GoldPlusSymbol, GoldSparklesSymbol, PencilIcon, PlusIcon, SparklesIcon, TrashIcon, UploadIcon } from '../components/icons'
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

/** Pick a chapter, then one of its proposed scenes becomes a card (as in the reader). The
 * chapter is split once, with the price asked first; later it shows the kept split. */
function SplitDialog({ projectId, chapters, onClose, onDone }: SplitProps) {
  const { t } = useI18n()
  const aiReady = useTextModelReady()
  const [chapterId, setChapterId] = useState(() => lastChapter(projectId, chapters))
  const [opened, setOpened] = useState(false)
  const [error, setError] = useState('')
  const pick = async (p: SceneProposal) => {
    setError('')
    if (p.scene_id) return onDone(p.scene_id)
    try {
      onDone((await api.pickProposal(chapterId, p.number)).id)
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog stack scroll">
        <h2>{t('tiles.scene.split')}</h2>
        <label className="field">
          {t('tiles.scene.split.chapter')}
          <select className="input" value={chapterId} onChange={(e) => setChapterId(e.target.value)}>
            {chapters.map((chapter, index) => (
              <option key={chapter.id} value={chapter.id}>
                {chapter.title || `${index + 1}. ${t('book.untitled')}`}
              </option>
            ))}
          </select>
        </label>
        <AiNotice ready={aiReady} />
        {error && <p className="error">{error}</p>}
        {opened && chapterId ? (
          <>
            <p className="small faint">{t('scenes.proposals.hint')}</p>
            <ProposalList chapterId={chapterId} confirm onPick={pick} />
          </>
        ) : (
          <div className="row">
            <span className="spacer" />
            <button className="btn" onClick={onClose}>
              {t('app.cancel')}
            </button>
            <button className="btn primary" disabled={!chapterId} onClick={() => setOpened(true)}>
              {t('scenes.split')}
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

interface TextsProps {
  scene: Scene
  writing: boolean
  aiReady: boolean
  onChange: (scene: Scene) => void
  /** "Add to the description" for an illustrator: the scene's dialogue makes the offer. */
  onEnrich?: () => void
}

/** Two folds like a card's sections: the scene as written for the screen, and the book's
 *  own text. "Add more" suggests what fits but the book does not say; it is shown marked
 *  and saved only by "Apply" (owner's notes 25.11). */
function SceneTexts({ scene, writing, aiReady, onChange, onEnrich }: TextsProps) {
  const { t } = useI18n()
  const [open, setOpen] = useState({ scene: true, book: false })
  const [enriching, setEnriching] = useState(false)
  return (
    <div className="stack scene-texts">
      {/* The book's own text first, the scene's text under it (owner's notes 28.11, item 50). */}
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
      <FoldHead
        title={t('scene.description')}
        open={open.scene}
        onToggle={() => setOpen((now) => ({ ...now, scene: !now.scene }))}
      />
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
      {open.scene && (
        <>
          {writing ? (
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
          )}
          {/* "Add to the description" sits at the end of the open scene text, not on its
              heading (items 34, 35, 43, 50); for an illustrator the offer comes in the dialogue. */}
          {!writing && onEnrich && (
            <div className="row">
              <button className="quick-reply" disabled={!aiReady} title={t('scene.enrich.hint')} onClick={onEnrich}>
                {t('scene.chat.enrich')}
              </button>
            </div>
          )}
          {writing && (
            <div className="row">
              <button
                className="btn ghost small"
                disabled={!aiReady}
                title={t('scene.enrich.hint')}
                onClick={() => setEnriching(true)}
              >
                <SparklesIcon />
                {t('scene.enrich')}
              </button>
            </div>
          )}
        </>
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
  const [error, setError] = useState('')
  // The picture window over the scene, for a card in it.
  const [adding, setAdding] = useState<{ who: Participant; bases: ImageInfo[]; editId?: string } | null>(null)
  const closeAdding = useCallback(() => setAdding(null), [])
  const [exporting, setExporting] = useState(false)
  const [enrichAsk, setEnrichAsk] = useState(0)
  const [changeAsk, setChangeAsk] = useState(0)
  const closeExport = useCallback(() => setExporting(false), [])
  // The user changed the pictures by hand after the prompt was written: its numbers may be off.
  const [refsChanged, setRefsChanged] = useState(false)
  // `editId`: "Change" on a picture, the card's dialogue opens on changing it (item 49).
  const addFor = async (who: Participant, editId?: string) => {
    try {
      const images = await api.images(projectId, who.id)
      setAdding({ who, bases: images.filter((i) => i.is_main && i.current_style), editId })
    } catch (e) {
      setError(errorText(t, e))
    }
  }
  // A card's new picture changes the scene's references, so the scene is fetched again.
  const reload = () => api.scene(scene.id).then(onChange, (e) => setError(errorText(t, e)))

  const download = () => {
    location.href = api.sceneArchiveUrl(scene.id)
  }
  // Not every picture the scene wants is there: the user is asked before going on with what
  // there is (owner's notes 26.11).
  const enoughRefs = async () => !scene.missing.length || (await ask(t('scene.missing.confirm')))
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
      <SceneTexts
        scene={scene}
        writing={writing}
        aiReady={!!aiReady}
        onChange={onChange}
        onEnrich={() => setEnrichAsk((n) => n + 1)}
      />

      {!writing && (
        <>
      <h4>{t('scene.references')}</h4>
      {/* What the scene still lacks, at a glance (owner's notes 28.11, item 49). */}
      {!scene.participants.length ? (
        <p className="scene-status ok small">✓ {t('scene.status.refs.none')}</p>
      ) : scene.missing.length ? (
        <p className="scene-status small">
          {t('scene.status.refs.missing', {
            names: [...new Set(scene.missing.map((m) => m.name))].join(', '),
          })}
        </p>
      ) : (
        <p className="scene-status ok small">✓ {t('scene.status.refs.ok')}</p>
      )}
      {!hasStyle && <p className="faint small">{t('scene.references.no_style')}</p>}
      <div className="refs">
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
            onEdit={(imageId) => void addFor(who, imageId)}
          />
        ))}
      </div>
      {refsChanged && <p className="muted small">{t('scene.refs.changed')}</p>}
      {adding && (
        <ReferenceChat
          projectId={projectId}
          entityId={adding.who.id}
          bases={adding.bases}
          kind={adding.who.kind}
          name={adding.who.name}
          hasStyle={hasStyle}
          onChanged={reload}
          onClose={closeAdding}
          editId={adding.editId}
        />
      )}

      {/* The video prompt, the first frame and a fuller description in one dialogue
          (owner's notes 27.11). */}
      <h4>{t('scene.prompt')}</h4>
      {scene.prompt ? (
        <div className="row scene-status ok small">
          <span>✓ {t('scene.status.prompt.ok')}</span>
          <button className="btn ghost small" disabled={aiReady === false} onClick={() => setChangeAsk((n) => n + 1)}>
            {t('scene.change')}
          </button>
        </div>
      ) : (
        <p className="scene-status small">{t('scene.status.prompt.none')}</p>
      )}
      <SceneDialog
        changeAsk={changeAsk}
        scene={scene}
        aiReady={aiReady !== false}
        onChange={onChange}
        enrichAsk={enrichAsk}
        onAddReference={(entityId) => {
          const who = scene.participants.find((p) => p.id === entityId)
          if (who) void addFor(who)
        }}
      />
      {aiReady === false && <AiNotice ready={aiReady} />}
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
  /** "Change" on a picture that goes to the video (item 49). */
  onEdit?: (imageId: string) => void
}

/** One frame among the references: its pictures one at a time, and a "+" to add another. */
function RefSlot({ title, pictures, empty, addTitle, onAdd, onToggle, onEdit }: SlotProps) {
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
        {/* "Change" in the picture's corner: the caption below stays wide enough for the name. */}
        {onEdit && shown?.id && shown.inVideo && (
          <button
            className="btn ghost small icon ref-edit"
            title={t('scene.change')}
            aria-label={t('scene.change')}
            onClick={() => onEdit(shown.id!)}
          >
            <PencilIcon />
          </button>
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

