import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { errorText, useI18n } from './i18n'

/** How long the typing must stop before the other half follows. */
const PAUSE_MS = 1500

/**
 * An image prompt in two halves: English, which the image model gets, and the interface
 * language, which the user reads. Either half can be edited; once the typing stops, the
 * text model rewrites the other half (the owner's choice, 24.11.2026: no separate button).
 * With an English interface there is only the English half and nothing is translated.
 * `flush` brings the English half up to date at once, for a press of "Generate".
 */
export function useTwoLang(
  entityId: string,
  english: string,
  setEnglish: (text: string) => void,
  enabled: boolean,
  onError: (message: string) => void,
) {
  const { t, lang } = useI18n()
  const both = lang !== 'en'
  const [local, setLocalState] = useState('')
  const [busy, setBusy] = useState(false)
  // The last pair known to say the same: a half equal to its pair needs no translation.
  const synced = useRef({ english: '', local: '' })
  const current = useRef({ english, local })
  useEffect(() => {
    current.current = { english, local }
  }, [english, local])
  // The half the user changed last and that the other half has not followed yet.
  const dirty = useRef<'' | 'english' | 'local'>('')
  const timer = useRef<number | undefined>(undefined)

  const sync = useCallback(
    async (from: 'english' | 'local') => {
      const text = current.current[from].trim()
      if (!text) {
        dirty.current = ''
        if (from === 'english') setLocalState('')
        else setEnglish('')
        return current.current.english
      }
      if (text === synced.current[from].trim()) {
        dirty.current = ''
        return current.current.english
      }
      setBusy(true)
      try {
        const { text: other } = await api.translateImagePrompt(entityId, text, from === 'english' ? lang : 'en')
        // Typed on while the answer was coming: the next pause translates the newer text.
        if (current.current[from].trim() !== text) return current.current.english
        dirty.current = ''
        if (from === 'english') {
          synced.current = { english: text, local: other }
          setLocalState(other)
          return text
        }
        synced.current = { english: other, local: text }
        setEnglish(other)
        return other
      } catch (e) {
        onError(errorText(t, e))
        return current.current.english
      } finally {
        setBusy(false)
      }
    },
    [entityId, lang, setEnglish, onError, t],
  )

  const schedule = useCallback(
    (from: 'english' | 'local') => {
      dirty.current = from
      window.clearTimeout(timer.current)
      timer.current = window.setTimeout(() => sync(from), PAUSE_MS)
    },
    [sync],
  )
  useEffect(() => () => window.clearTimeout(timer.current), [])

  // The English half changed (typed, or written by the model): the other half follows.
  useEffect(() => {
    if (!both || !enabled || english.trim() === synced.current.english.trim()) return
    if (dirty.current === 'local') return // our own answer to the user's local edit is on its way
    schedule('english')
  }, [english, both, enabled, schedule])

  const setLocal = (text: string) => {
    setLocalState(text)
    if (both && enabled) schedule('local')
  }

  /** The English prompt with the user's last local edit in it. */
  const flush = async () => {
    window.clearTimeout(timer.current)
    if (both && dirty.current === 'local') return sync('local')
    return current.current.english
  }

  return { both, local, setLocal, busy, flush }
}
