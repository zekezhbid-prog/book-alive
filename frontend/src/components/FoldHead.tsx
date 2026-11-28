import type { ReactNode } from 'react'
import { GoldCheckSymbol } from './icons'

interface Props {
  title: ReactNode
  open: boolean
  onToggle: () => void
  /** Beside the title, inside the fold button: a count, for example. */
  note?: ReactNode
  /** On the right: the section's own button (edit). */
  children?: ReactNode
  /** Everything of the section is done: a gold check and a brighter title (item 63). */
  ready?: boolean
}

/** The heading of a card's section: one look for every section, the whole title folds it. */
export default function FoldHead({ title, open, onToggle, note, children, ready }: Props) {
  return (
    <div className={`row profile-head${ready ? ' fold-ready' : ''}`}>
      <button className="fold" aria-expanded={open} onClick={onToggle}>
        <svg className={`fold-mark ${open ? 'open' : ''}`} viewBox="0 0 16 16" aria-hidden>
          <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
        <h4>{title}</h4>
        {ready && (
          <span className="fold-check">
            <GoldCheckSymbol />
          </span>
        )}
        {note}
      </button>
      <span className="spacer" />
      {children}
    </div>
  )
}
