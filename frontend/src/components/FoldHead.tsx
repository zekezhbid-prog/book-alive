import type { ReactNode } from 'react'

interface Props {
  title: ReactNode
  open: boolean
  onToggle: () => void
  /** Beside the title, inside the fold button: a count, for example. */
  note?: ReactNode
  /** On the right: the section's own button (edit). */
  children?: ReactNode
}

/** The heading of a card's section: one look for every section, the whole title folds it. */
export default function FoldHead({ title, open, onToggle, note, children }: Props) {
  return (
    <div className="row profile-head">
      <button className="fold" aria-expanded={open} onClick={onToggle}>
        <svg className={`fold-mark ${open ? 'open' : ''}`} viewBox="0 0 16 16" aria-hidden>
          <path d="M6 3.5 10.5 8 6 12.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" fill="none" />
        </svg>
        <h4>{title}</h4>
        {note}
      </button>
      <span className="spacer" />
      {children}
    </div>
  )
}
