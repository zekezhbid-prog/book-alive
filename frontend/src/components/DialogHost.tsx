import { useEffect, useRef, useState, type FormEvent } from 'react'
import { setDialogHost, type DialogRequest } from '../dialogs'
import { useI18n } from '../i18n'

/** Shows the questions asked through `ask` and `askText`, one at a time. */
export default function DialogHost() {
  const [queue, setQueue] = useState<{ id: number; request: DialogRequest }[]>([])
  useEffect(() => {
    let next = 0
    setDialogHost((request) => setQueue((q) => [...q, { id: next++, request }]))
    return () => setDialogHost(null)
  }, [])
  const current = queue[0]
  if (!current) return null
  return (
    <Ask
      key={current.id}
      request={current.request}
      onClose={(answer) => {
        current.request.resolve(answer)
        setQueue((q) => q.slice(1))
      }}
    />
  )
}

function Ask({ request, onClose }: { request: DialogRequest; onClose: (answer: string | boolean | null) => void }) {
  const { t } = useI18n()
  const [value, setValue] = useState(request.text ?? '')
  const input = useRef<HTMLInputElement>(null)
  const ok = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    if (request.text === null) ok.current?.focus()
    else input.current?.select()
  }, [request])

  const submit = (event: FormEvent) => {
    event.preventDefault()
    onClose(request.text === null ? true : value)
  }
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose(null)}>
      <form
        className="dialog stack ask"
        role="dialog"
        aria-modal="true"
        onSubmit={submit}
        onKeyDown={(e) => e.key === 'Escape' && onClose(null)}
      >
        <p className="ask-message">{request.message}</p>
        {request.text !== null && (
          <input ref={input} className="input" value={value} onChange={(e) => setValue(e.target.value)} />
        )}
        <div className="row">
          <span className="spacer" />
          <button type="button" className="btn" onClick={() => onClose(null)}>
            {t('app.cancel')}
          </button>
          <button ref={ok} className="btn primary">
            {t('app.ok')}
          </button>
        </div>
      </form>
    </div>
  )
}
