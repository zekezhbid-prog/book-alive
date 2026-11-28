import { useI18n } from '../i18n'

export interface StripItem {
  id: string
  url: string
  /** The picture drawn before this one, not a card's own. */
  previous?: boolean
}

/**
 * The references the next picture will be drawn from, above the dialogue's field (owner's
 * notes 28.11, item 58): the picture drawn before and the cards' pictures that go in by
 * themselves. A cross leaves one out of the next drawings.
 */
export function RefStrip({ items, disabled, onRemove }: { items: StripItem[]; disabled: boolean; onRemove: (id: string) => void }) {
  const { t } = useI18n()
  if (!items.length) return null
  return (
    <div className="ref-attach ref-strip">
      <span className="small muted">{t('refs.strip')}</span>
      {items.map((item) => (
        <span key={item.id} className="ref-strip-item" title={item.previous ? t('refs.previous') : undefined}>
          <img src={item.url} alt="" />
          <button
            className="ref-strip-remove"
            disabled={disabled}
            title={t('refs.remove')}
            aria-label={t('refs.remove')}
            onClick={() => onRemove(item.id)}
          >
            ✕
          </button>
        </span>
      ))}
    </div>
  )
}
