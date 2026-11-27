import { useImperativeHandle, useLayoutEffect, useRef, type ReactNode, type Ref } from 'react'
import { IMAGE_SIZES, type ImageSize } from '../api'
import { useI18n } from '../i18n'
import { EnterIcon } from './icons'
import { MicButton } from './MicButton'

interface Props {
  value: string
  onChange: (value: string) => void
  onSend: () => void
  placeholder?: string
  /** No typing at all (the model is working). */
  disabled?: boolean
  /** Typing allowed, sending not (for example, the field is empty and that means nothing). */
  sendDisabled?: boolean
  maxLength?: number
  fieldRef?: Ref<HTMLTextAreaElement>
  onError: (message: string) => void
  /** Icons before the microphone, such as "put in a picture". */
  tools?: ReactNode
  /** The picture's aspect ratio, in dialogues that draw. */
  size?: { value: ImageSize; onChange: (size: ImageSize) => void }
}

/**
 * The one input row of every dialogue (owner's notes 27.11, items 21 and 30): a field the
 * full width, and inside it on the right small icons - the dialogue's own tools, the aspect
 * ratio as bare numbers, the microphone and "send" as an Enter arrow.
 */
export function Composer({
  value,
  onChange,
  onSend,
  placeholder,
  disabled,
  sendDisabled,
  maxLength = 4000,
  fieldRef,
  onError,
  tools,
  size,
}: Props) {
  const { t } = useI18n()
  const box = useRef<HTMLTextAreaElement | null>(null)
  // The words spoken land after whatever is in the field by the time they are ready.
  const latest = useRef(value)
  useLayoutEffect(() => {
    latest.current = value
  }, [value])
  // Two lines at first, grows with the text up to eight, then scrolls.
  useLayoutEffect(() => {
    const area = box.current
    if (!area) return
    const line = parseFloat(getComputedStyle(area).lineHeight) || 20
    area.style.height = 'auto'
    area.style.height = `${Math.min(area.scrollHeight, line * 8 + 12)}px`
  }, [value])
  // The caller may focus the field (for example, "Fix" in the references window).
  useImperativeHandle(fieldRef, () => box.current as HTMLTextAreaElement, [])
  const canSend = !disabled && !sendDisabled
  return (
    <div className={`composer${disabled ? ' off' : ''}`}>
      <textarea
        ref={box}
        rows={2}
        value={value}
        maxLength={maxLength}
        placeholder={placeholder}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            if (canSend) onSend()
          }
        }}
      />
      <div className="composer-tools">
        {tools}
        {size && (
          <select
            className="composer-size"
            value={size.value}
            title={t('generate.size')}
            aria-label={t('generate.size')}
            onChange={(e) => size.onChange(e.target.value as ImageSize)}
          >
            {IMAGE_SIZES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        )}
        <MicButton
          disabled={disabled}
          onText={(spoken) => {
            const now = latest.current.trim()
            onChange(now ? `${now} ${spoken}` : spoken)
            box.current?.focus()
          }}
          onError={onError}
        />
        <button
          type="button"
          className="btn ghost small icon composer-send"
          disabled={!canSend}
          title={t('images.send')}
          aria-label={t('images.send')}
          onClick={onSend}
        >
          <EnterIcon />
        </button>
      </div>
    </div>
  )
}
