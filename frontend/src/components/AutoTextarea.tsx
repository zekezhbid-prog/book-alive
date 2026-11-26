import { useLayoutEffect, useRef, type TextareaHTMLAttributes } from 'react'

/** A text field for wishes and remarks: starts at two lines and grows with the text up to
 *  `maxRows`, then scrolls (owner's notes 26.11: there can be many wishes). */
export function AutoTextarea({
  maxRows = 8,
  rows = 2,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { maxRows?: number }) {
  const box = useRef<HTMLTextAreaElement>(null)
  useLayoutEffect(() => {
    const area = box.current
    if (!area) return
    const line = parseFloat(getComputedStyle(area).lineHeight) || 20
    area.style.height = 'auto'
    const limit = line * maxRows + (area.offsetHeight - area.clientHeight) + 16
    area.style.height = `${Math.min(area.scrollHeight + (area.offsetHeight - area.clientHeight), limit)}px`
  }, [props.value, maxRows])
  return <textarea ref={box} rows={rows} {...props} style={{ resize: 'none', overflowY: 'auto', ...props.style }} />
}
