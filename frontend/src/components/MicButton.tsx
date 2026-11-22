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
  const mounted = useRef(false)
  const pending = useRef(false)
  const started = useRef(0)
  const [seconds, setSeconds] = useState(0)
  const [levels, setLevels] = useState<number[]>([])
  // Recording stops with the component too: the microphone must not stay on.
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      const rec = recorder.current
      if (rec) {
        rec.onstop = null
        if (rec.state === 'recording') rec.stop()
        rec.stream.getTracks().forEach(track => track.stop())
      }
    }
  }, [])
  useEffect(() => {
    const stream = recorder.current?.stream
    if (state !== 'recording' || !stream) return
    let context: AudioContext | undefined
    let meter: AnalyserNode | undefined
    try {
      context = new AudioContext()
      meter = context.createAnalyser()
      context.createMediaStreamSource(stream).connect(meter)
      void context.resume().catch(() => {})
    } catch { /* The timer also works without audio metering. */ }
    const samples = new Uint8Array(256)
    const tick = window.setInterval(() => {
      setSeconds(Math.floor((performance.now() - started.current) / 1000))
      if (!meter) return
      meter.getByteTimeDomainData(samples)
      let peak = 0
      for (const sample of samples) peak = Math.max(peak, Math.abs(sample - 128))
      setLevels(previous => [...previous.slice(1), Math.min(16, 2 + peak / 3)])
    }, 100)
    return () => {
      clearInterval(tick)
      if (context) void context.close().catch(() => {})
    }
  }, [state])

  const start = async () => {
    if (pending.current || recorder.current) return
    pending.current = true
    let rec: MediaRecorder
    let stream: MediaStream | undefined
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!mounted.current) {
        stream.getTracks().forEach(track => track.stop())
        return
      }
      rec = new MediaRecorder(stream)
    } catch {
      stream?.getTracks().forEach(track => track.stop())
      if (mounted.current) onError(t('voice.denied'))
      return
    } finally { pending.current = false }
    const chunks: Blob[] = []
    rec.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    rec.onstop = () => {
      rec.stream.getTracks().forEach((track) => track.stop())
      recorder.current = null
      const audio = new Blob(chunks, { type: rec.mimeType || 'audio/webm' })
      if (!audio.size) {
        setState('idle')
        return
      }
      setState('busy')
      api.transcribe(audio).then(
        ({ text }) => {
          if (!mounted.current) return
          setState('idle')
          if (text.trim()) onText(text.trim())
          else onError(t('voice.empty'))
        },
        () => {
          if (!mounted.current) return
          setState('idle')
          onError(t('voice.failed'))
        },
      )
    }
    recorder.current = rec
    try { rec.start() } catch {
      recorder.current = null
      rec.stream.getTracks().forEach(track => track.stop())
      onError(t('voice.failed'))
      return
    }
    started.current = performance.now()
    setSeconds(0)
    setLevels(Array(12).fill(2))
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
      {state === 'recording' ? <>
        <span aria-hidden="true">■</span>
        <span className="mic-wave" aria-hidden="true">{levels.map((height, i) => <i key={i} style={{ height }} />)}</span>
        <span className="mic-time">{Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, '0')}</span>
      </> : state === 'busy' ? '…' : <MicIcon />}
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
