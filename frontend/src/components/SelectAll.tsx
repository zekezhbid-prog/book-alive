import { useEffect, useRef } from 'react'
import { useI18n } from '../i18n'

interface Props {
  /** Everything that can be ticked in the list. */
  ids: string[]
  selected: Set<string>
  onChange: (next: Set<string>) => void
}

/** One "Select all" tick above a list of ticks: on selects everything, off clears it;
 * half-filled while only some are ticked. */
export default function SelectAll({ ids, selected, onChange }: Props) {
  const { t } = useI18n()
  const box = useRef<HTMLInputElement>(null)
  const count = ids.filter((id) => selected.has(id)).length
  const all = ids.length > 0 && count === ids.length
  useEffect(() => {
    if (box.current) box.current.indeterminate = count > 0 && !all
  }, [count, all])
  return (
    <label className="row select-all">
      <input
        ref={box}
        type="checkbox"
        checked={all}
        disabled={ids.length === 0}
        onChange={() => onChange(all ? new Set() : new Set(ids))}
      />
      <span className="small">{t('select.all')}</span>
    </label>
  )
}
