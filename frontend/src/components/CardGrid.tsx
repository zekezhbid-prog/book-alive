import type { ReactNode } from 'react'

export interface Tile {
  id: string
  title: string
  /** A few words about it, cut to three lines. */
  text?: string
  /** The small line at the bottom: chapters, where it appears. */
  meta?: string
  /** A picture behind the text, dimmed so the text stays readable. */
  cover?: string
  /** Before the title: a star for a vivid scene, a question mark for a doubtful card. */
  mark?: ReactNode
  /** After the meta line: a stale dot, a "has prompt" tick. */
  extra?: ReactNode
  faded?: boolean
}

export interface TileAction {
  icon: ReactNode
  title: string
  hint: string
  onClick: () => void
  disabled?: boolean
}

interface Props {
  /** The first tiles: add by hand, make with AI. Bigger versions of the list's icons. */
  actions: TileAction[]
  tiles: Tile[]
  onOpen: (id: string) => void
  /** Under the grid, a heading and more tiles (doubtful cards). */
  more?: { title: string; hint?: string; tiles: Tile[] }
}

/** The page of a section when nothing is open: every card as a tile, the actions first. */
export default function CardGrid({ actions, tiles, onOpen, more }: Props) {
  const tile = (item: Tile) => (
    <button
      key={item.id}
      className={`tile ${item.cover ? 'with-cover' : ''} ${item.faded ? 'faded' : ''}`}
      onClick={() => onOpen(item.id)}
    >
      {item.cover && <img className="tile-cover" src={item.cover} alt="" loading="lazy" />}
      <span className="tile-title">
        {item.mark}
        {item.title}
      </span>
      {item.text && <span className="tile-text">{item.text}</span>}
      <span className="tile-meta">
        <span className="grow">{item.meta}</span>
        {item.extra}
      </span>
    </button>
  )
  return (
    <>
      <div className="card-grid">
        {actions.map((action) => (
          <button
            key={action.title}
            className="tile tile-action"
            disabled={action.disabled}
            onClick={action.onClick}
          >
            <span className="tile-action-icon">{action.icon}</span>
            <span className="tile-title">{action.title}</span>
            <span className="tile-text">{action.hint}</span>
          </button>
        ))}
        {tiles.map(tile)}
      </div>
      {more && more.tiles.length > 0 && (
        <>
          <h4 className="card-grid-subhead" title={more.hint}>
            {more.title}
          </h4>
          <div className="card-grid">{more.tiles.map(tile)}</div>
        </>
      )}
    </>
  )
}
