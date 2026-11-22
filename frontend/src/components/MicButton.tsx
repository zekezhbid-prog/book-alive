import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useI18n } from '../i18n'

/** Speak instead of typing: records in the browser, the server's own Whisper turns it into
 *  text (the voice never leaves our server), and `onText` gets the words. */
export function MicButton({
  onText,
  onError,
  disabled,
}: {
  onText: (text: string) => void
  onError: (message: string) => void
  disabled?: boolean
}) {
  const { t } = useI18n()
  const [state, setState] = useState<'idle' | 'recording' | 'busy'>('idle')
  const recorder = useRef<MediaRecorder | null>(null)
  // Recording stops with the component too: the microphone must not stay on.
  useEffect(() => () => recorder.current?.stream.getTracks().forEach((track) => track.stop()), [])

  const start = async () => {
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      onError(t('voice.denied'))
      return
    }
    const chunks: Blob[] = []
    const rec = new MediaRecorder(stream)
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    rec.onstop = () => {
      stream.getTracks().forEach((track) => track.stop())
      recorder.current = null
      const audio = new Blob(chunks, { type: rec.mimeType || 'audio/webm' })
      if (!audio.size) {
        setState('idle')
        return
      }
      setState('busy')
      api.transcribe(audio).then(
        ({ text }) => {
          setState('idle')
          if (text.trim()) onText(text.trim())
          else onError(t('voice.empty'))
        },
        () => {
          setState('idle')
          onError(t('voice.failed'))
        },
      )
    }
    recorder.current = rec
    rec.start()
    setState('recording')
  }

  const label = t(state === 'recording' ? 'voice.stop' : state === 'busy' ? 'voice.busy' : 'voice.record')
  return (
    <button
      type="button"
      className={`btn ghost icon mic${state === 'recording' ? ' recording' : ''}`}
      title={label}
      aria-label={label}
      disabled={disabled || state === 'busy' || !navigator.mediaDevices}
      onClick={() => (state === 'recording' ? recorder.current?.stop() : start())}
    >
      {state === 'busy' ? '…' : <MicIcon />}
    </button>
  )
}

function MicIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3" />
    </svg>
  )
}
