import type { ChapterBrief } from '../api'
import { useI18n } from '../i18n'
import { useChatOpen, useSide } from '../view'
import ChatPanel from './ChatPanel'
import { ChatIcon } from './icons'

interface Props {
  projectId: string
  chapters: ChapterBrief[]
  /** The chapter open in the reader, on the book page. */
  chapterId?: string
  canSuggest?: boolean
}

/** The book chat on every page of a project: a button in the bottom right corner that
 * unfolds into a panel along the right edge, and folds back with its cross. */
export default function ChatDock({ projectId, chapters, chapterId, canSuggest }: Props) {
  const { t } = useI18n()
  const [open, setOpen] = useChatOpen()
  const [, setSide] = useSide(projectId)
  if (!open)
    return (
      <button className="btn primary chat-fab" onClick={() => {
          // One panel on the right at a time: the chat takes the place of the checklist or versions.
          setSide('chat')
          setOpen(true)
        }}
        aria-label={t('chat.title')}>
        <ChatIcon /> <span className="chat-fab-label">{t('chat.title')}</span>
      </button>
    )
  return (
    <aside className="chat-dock" aria-label={t('chat.title')}>
      <ChatPanel
        projectId={projectId}
        chapters={chapters}
        chapterId={chapterId}
        canSuggest={canSuggest}
        onClose={() => setOpen(false)}
      />
    </aside>
  )
}
