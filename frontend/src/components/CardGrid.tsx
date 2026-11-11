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
  /** Drawn large and faint behind the text: the list's + or ✨. */
  icon: ReactNode
  title: string
  hint: string
  onClick: () => void
  disabled?: boolean
}

interface Props {
  /** The first tiles: add by hand, make with AI (the list's + and ✨, spelled out). */
  actions: TileAction[]
  tiles: Tile[]
  onOpen: (id: string) => void
  /** Under the grid, a heading and more tiles (doubtful cards). */
  more?: { title: string; hint?: string; tiles: Tile[] }
  /** Tiles get a check box: several cards are picked and removed at once. */
  selection?: {
    selected: Set<string>
    onChange: (next: Set<string>) => void
    label: string
    allLabel: string
  }
}

/** The page of a section when nothing is open: every card as a tile, the actions first. */
export default function CardGrid({ actions, tiles, onOpen, more, selection }: Props) {
  const toggle = (ids: string[], on: boolean) => {
    if (!selection) return
    const next = new Set(selection.selected)
    for (const id of ids) {
      if (on) next.add(id)
      else next.delete(id)
    }
    selection.onChange(next)
  }
  const tile = (item: Tile) => {
    const picked = selection?.selected.has(item.id) ?? false
    const body = (
    <button
      key={item.id}
      className={`tile ${item.cover ? 'with-cover' : ''} ${item.faded ? 'faded' : ''} ${picked ? 'picked' : ''}`}
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
    if (!selection) return body
    // The box sits beside the button, not inside it: a control inside a button is not allowed.
    return (
      <div key={item.id} className="tile-wrap">
        {body}
        <input
          type="checkbox"
          className="tile-check"
          checked={picked}
          aria-label={`${selection.label}: ${item.title}`}
          onChange={(e) => toggle([item.id], e.target.checked)}
        />
      </div>
    )
  }
  const pickAll = (list: Tile[]) =>
    selection &&
    list.length > 1 && (
      <label className="pick-all muted">
        <input
          type="checkbox"
          checked={list.every((item) => selection.selected.has(item.id))}
          onChange={(e) => toggle(list.map((item) => item.id), e.target.checked)}
        />{' '}
        {selection.allLabel}
      </label>
    )
  return (
    <>
      {/* The actions take the first row between them; the cards start below. */}
      <div className="card-actions">
        {actions.map((action) => (
          <button
            key={action.title}
            className="tile tile-action"
            disabled={action.disabled}
            onClick={action.onClick}
          >
            <span className="tile-action-icon" aria-hidden>
              {action.icon}
            </span>
            <span className="tile-title">{action.title}</span>
            <span className="tile-text">{action.hint}</span>
          </button>
        ))}
      </div>
      {tiles.length > 0 && selection && <div className="row card-grid-tools">{pickAll(tiles)}</div>}
      {tiles.length > 0 && <div className="card-grid">{tiles.map(tile)}</div>}
      {more && more.tiles.length > 0 && (
        <>
          <div className="row card-grid-subhead">
            <h4 title={more.hint}>{more.title}</h4>
            <span className="spacer" />
            {pickAll(more.tiles)}
          </div>
          <div className="card-grid">{more.tiles.map(tile)}</div>
        </>
      )}
    </>
  )
}
