// Small inline icons; they take the button's text colour.
import { useId, type ReactNode } from 'react'

const stroke = {
  width: 16,
  height: 16,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
} as const

export function SparklesIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M10 2l1.9 5.6L17.5 9.5l-5.6 1.9L10 17l-1.9-5.6L2.5 9.5l5.6-1.9z" />
      <path d="M18.5 13l.9 2.6 2.6.9-2.6.9-.9 2.6-.9-2.6-2.6-.9 2.6-.9z" />
      <path d="M18 2l.6 1.9 1.9.6-1.9.6L18 7l-.6-1.9-1.9-.6 1.9-.6z" />
    </svg>
  )
}

export function CopyIcon() {
  return (
    <svg {...stroke}>
      <rect x="9" y="9" width="12" height="12" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  )
}

export function PlusIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function PencilIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  )
}

/** A thick plus for the gold "add" buttons. */
export function BoldPlusIcon() {
  return (
    <svg {...stroke} strokeWidth={3.4}>
      <path d="M12 4v16M4 12h16" />
    </svg>
  )
}

export function HandIcon() {
  return (
    <svg {...stroke}>
      <path d="M18 11V6a2 2 0 0 0-4 0" />
      <path d="M14 10V4a2 2 0 0 0-4 0v2" />
      <path d="M10 10.5V6a2 2 0 0 0-4 0v8" />
      <path d="M18 8a2 2 0 1 1 4 0v6a8 8 0 0 1-8 8h-2c-2.8 0-4.5-.86-6-2.34l-3.6-3.6a2 2 0 0 1 2.83-2.82L7 15" />
    </svg>
  )
}

/** Filled when `on`, an outline otherwise. */
export function StarIcon({ on }: { on: boolean }) {
  return (
    <svg {...stroke} fill={on ? 'currentColor' : 'none'}>
      <path d="M12 2.5l2.9 6 6.6.9-4.8 4.6 1.2 6.5L12 17.4l-5.9 3.1 1.2-6.5-4.8-4.6 6.6-.9z" />
    </svg>
  )
}

export function TrashIcon() {
  return (
    <svg {...stroke}>
      <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6" />
    </svg>
  )
}

export function RefreshIcon() {
  return (
    <svg {...stroke}>
      <path d="M21 12a9 9 0 0 1-15.5 6.2M3 12a9 9 0 0 1 15.5-6.2M18.5 2.5v3.7h-3.7M5.5 21.5v-3.7h3.7" />
    </svg>
  )
}

export function GearIcon() {
  return (
    <svg {...stroke}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
    </svg>
  )
}

export function DownloadIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 3v12M7 10l5 5 5-5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
    </svg>
  )
}

export function UploadIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 15V3M7 8l5-5 5 5M4 15v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" />
    </svg>
  )
}

export function SaveIcon() {
  return (
    <svg {...stroke}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z" />
      <path d="M17 21v-8H7v8M7 3v5h8" />
    </svg>
  )
}

export function CloseIcon() {
  return (
    <svg {...stroke}>
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  )
}

export function SearchIcon() {
  return (
    <svg {...stroke}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  )
}

export function UserIcon() {
  return (
    <svg {...stroke}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21a8 8 0 0 1 16 0" />
    </svg>
  )
}

export function ChatIcon() {
  return (
    <svg {...stroke}>
      <path d="M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.9A8 8 0 1 1 21 12z" />
    </svg>
  )
}

export function ReviewIcon() {
  return (
    <svg {...stroke}>
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
      <path d="M14 3v6h6M9 15l2 2 4-4" />
    </svg>
  )
}

export function HistoryIcon() {
  return (
    <svg {...stroke}>
      <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
      <path d="M3 3v5h5M12 7v5l3 2" />
    </svg>
  )
}

export function PenIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z" />
    </svg>
  )
}

export function ImageIcon() {
  return (
    <svg {...stroke}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <circle cx="9" cy="9" r="2" />
      <path d="m21 15-5-5L5 21" />
    </svg>
  )
}

/** The large symbols behind the action tiles: drawn for their size (not a stretched line
 * icon), gold with a highlight that slowly runs across, a lit top edge and a soft shadow. */
function GoldSymbol({ id, children }: { id: string; children: (fill: string) => ReactNode }) {
  return (
    <svg viewBox="0 0 100 100" className="gold-symbol" aria-hidden="true">
      <defs>
        <linearGradient id={`${id}-gold`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset="0.3" stopColor="#ffd45e" />
          <stop offset="0.55" stopColor="#e9a21c" />
          <stop offset="0.8" stopColor="#b8720a" />
          <stop offset="1" stopColor="#ffd77a" />
        </linearGradient>
        {/* A band of light sweeping across, again and again. */}
        <linearGradient id={`${id}-shine`} x1="0" y1="0" x2="1" y2="0.6">
          <stop offset="0" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.45" stopColor="#fff" stopOpacity="0" />
          <stop offset="0.5" stopColor="#fffbe8" stopOpacity="0.85" />
          <stop offset="0.55" stopColor="#fff" stopOpacity="0" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
          <animateTransform
            attributeName="gradientTransform"
            type="translate"
            values="-1.2 0; 1.2 0; 1.2 0"
            keyTimes="0; 0.6; 1"
            dur="4.5s"
            repeatCount="indefinite"
          />
        </linearGradient>
        <linearGradient id={`${id}-edge`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#fff" stopOpacity="0.7" />
          <stop offset="0.35" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
        <filter id={`${id}-depth`} x="-20%" y="-20%" width="140%" height="150%">
          <feDropShadow dx="0" dy="3" stdDeviation="2.5" floodColor="#3a2000" floodOpacity="0.55" />
          <feDropShadow dx="0" dy="0" stdDeviation="6" floodColor="#f6b93b" floodOpacity="0.35" />
        </filter>
      </defs>
      <g filter={`url(#${id}-depth)`}>{children(`url(#${id}-gold)`)}</g>
      {children(`url(#${id}-edge)`)}
      {children(`url(#${id}-shine)`)}
    </svg>
  )
}

// A cross with rounded arms and soft inner corners.
const PLUS =
  'M43 12h14a6 6 0 0 1 6 6v19h19a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6H63v19a6 6 0 0 1-6 6H43a6 6 0 0 1-6-6V63H18a6 6 0 0 1-6-6V43a6 6 0 0 1 6-6h19V18a6 6 0 0 1 6-6z'
// One large four-pointed star and two small ones, with slightly curved sides.
const STARS = [
  'M40 12c2.5 14 8 21.5 24 26-16 4.5-21.5 12-24 26-2.5-14-8-21.5-24-26 16-4.5 21.5-12 24-26z',
  'M76 52c1.4 7.5 4.2 11 12 13-7.8 2-10.6 5.5-12 13-1.4-7.5-4.2-11-12-13 7.8-2 10.6-5.5 12-13z',
  'M74 8c1 5 2.8 7.4 8 8.6-5.2 1.2-7 3.6-8 8.6-1-5-2.8-7.4-8-8.6 5.2-1.2 7-3.6 8-8.6z',
]

export function GoldPlusSymbol() {
  return <GoldSymbol id="gold-plus">{(fill) => <path d={PLUS} fill={fill} />}</GoldSymbol>
}

export function GoldSparklesSymbol() {
  return (
    <GoldSymbol id="gold-stars">
      {(fill) => (
        <>
          {STARS.map((d) => (
            <path key={d} d={d} fill={fill} />
          ))}
        </>
      )}
    </GoldSymbol>
  )
}

export function BookIcon() {
  return (
    <svg {...stroke}>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20V3H6.5A2.5 2.5 0 0 0 4 5.5z" />
      <path d="M4 19.5A2.5 2.5 0 0 0 6.5 22H20v-5" />
    </svg>
  )
}

export function UsersIcon() {
  return (
    <svg {...stroke}>
      <circle cx="9" cy="8" r="3.5" />
      <path d="M2.5 20a6.5 6.5 0 0 1 13 0" />
      <path d="M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8" />
    </svg>
  )
}

export function PinIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 21s-7-6.2-7-11.5a7 7 0 0 1 14 0C19 14.8 12 21 12 21z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  )
}

export function FilmIcon() {
  return (
    <svg {...stroke}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M7 3v18M17 3v18M3 8h4M3 16h4M17 8h4M17 16h4M3 12h18" />
    </svg>
  )
}

export function PaletteIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.8-.8 1.8-1.8 0-.5-.2-.9-.5-1.2-.3-.3-.5-.7-.5-1.2 0-1 .8-1.8 1.8-1.8H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z" />
      <circle cx="7.5" cy="11" r="1" />
      <circle cx="10" cy="7" r="1" />
      <circle cx="15" cy="7" r="1" />
    </svg>
  )
}

export function ArrowUpIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  )
}

export function ArrowDownIcon() {
  return (
    <svg {...stroke}>
      <path d="M12 5v14M19 12l-7 7-7-7" />
    </svg>
  )
}

/** The mark of a check that asks the AI: the same gold stars as the AI action tiles, small. */
export function AiMark({ title }: { title?: string }) {
  const id = useId().replace(/:/g, '')
  return (
    <svg viewBox="0 0 100 100" className="ai-mark" role={title ? 'img' : undefined} aria-label={title} aria-hidden={title ? undefined : true}>
      {title && <title>{title}</title>}
      <defs>
        <linearGradient id={`${id}-ai`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#fff3c4" />
          <stop offset="0.35" stopColor="#ffd45e" />
          <stop offset="0.65" stopColor="#e9a21c" />
          <stop offset="1" stopColor="#ffd77a" />
        </linearGradient>
      </defs>
      {STARS.map((d) => (
        <path key={d} d={d} fill={`url(#${id}-ai)`} />
      ))}
    </svg>
  )
}
