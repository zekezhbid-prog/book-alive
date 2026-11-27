import { useEffect, useSyncExternalStore, type MouseEvent } from 'react'
import { useI18n } from '../i18n'

/**
 * Pictures open over the page, not in a new browser tab, and the arrows (or the keyboard)
 * leaf through the other pictures of the same row (owner's notes 26.11). One host in the App
 * shows whatever `showPictures` was last given.
 */
interface State {
  urls: string[]
  index: number
}

let state: State | null = null
const listeners = new Set<() => void>()
const set = (next: State | null) => {
  state = next
  listeners.forEach((listen) => listen())
}
const subscribe = (listen: () => void) => {
  listeners.add(listen)
  return () => listeners.delete(listen)
}

export function showPictures(urls: string[], index = 0) {
  if (urls.length) set({ urls, index: Math.max(0, Math.min(index, urls.length - 1)) })
}

/** Props for a link around a picture: a plain click opens the lightbox, a middle click or
 *  Ctrl+click still opens the file in a new tab as before. */
export function zoomLink(urls: string[], index: number) {
  return {
    href: urls[index],
    // The link takes no focus on a press: a focused link half out of view is scrolled into
    // it, and the window under the picture jumped (owner's notes 27.11, item 18).
    onMouseDown: (e: MouseEvent) => {
      if (e.button === 0) e.preventDefault()
    },
    onClick: (e: MouseEvent) => {
      if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return
      e.preventDefault()
      e.stopPropagation()
      showPictures(urls, index)
    },
  }
}

export function LightboxHost() {
  const { t } = useI18n()
  const shown = useSyncExternalStore(subscribe, () => state)
  const count = shown?.urls.length ?? 0
  const step = (by: number) => shown && set({ ...shown, index: (shown.index + by + count) % count })

  useEffect(() => {
    if (!shown) return
    const keys = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        set(null)
      } else if (e.key === 'ArrowLeft') step(-1)
      else if (e.key === 'ArrowRight') step(1)
    }
    // Capture: Escape closes the picture, not the window under it.
    window.addEventListener('keydown', keys, true)
    return () => window.removeEventListener('keydown', keys, true)
  })

  if (!shown) return null
  return (
    <div className="lightbox" onMouseDown={(e) => e.target === e.currentTarget && set(null)}>
      <img src={shown.urls[shown.index]} alt="" />
      <button className="btn ghost icon lightbox-close" title={t('app.close')} aria-label={t('app.close')} onClick={() => set(null)}>
        ✕
      </button>
      {count > 1 && (
        <>
          <button className="lightbox-arrow left" aria-label={t('lightbox.prev')} onClick={() => step(-1)}>
            ‹
          </button>
          <button className="lightbox-arrow right" aria-label={t('lightbox.next')} onClick={() => step(1)}>
            ›
          </button>
          <span className="lightbox-count">
            {shown.index + 1} / {count}
          </span>
        </>
      )}
    </div>
  )
}
