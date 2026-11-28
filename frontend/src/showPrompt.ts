import { useEffect, useState } from 'react'
import { api } from './api'

/**
 * Settings → Pictures → "Show the prompt" (owner's notes 28.11, item 46): on, a picture's
 * prompt is shown to read and change before drawing; off, it is drawn at once. Read once
 * from the server and shared by every dialogue that draws.
 */
let cached: boolean | null = null
let loading = false
const listeners = new Set<(on: boolean) => void>()

export function setShowPrompt(on: boolean) {
  cached = on
  for (const listener of listeners) listener(on)
}

export function useShowPrompt(): boolean {
  const [on, setOn] = useState(cached ?? true)
  useEffect(() => {
    listeners.add(setOn)
    if (cached === null && !loading) {
      loading = true
      api.settings().then(
        (settings) => setShowPrompt(settings.image_show_prompt !== 'off'),
        () => {
          loading = false
        },
      )
    }
    return () => {
      listeners.delete(setOn)
    }
  }, [])
  return on
}
