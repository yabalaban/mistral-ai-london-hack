import { useEffect, useRef, useCallback } from 'preact/hooks'
import { agentSpeaking, partialTranscript, isPTTActive, activeCall, callMode } from '../state/call.ts'
import { wsManager } from '../api/ws.ts'
import { useWebSocket } from './useWebSocket.ts'
import type { WSEvent } from '../types/index.ts'

/**
 * Push-to-talk voice capture and playback.
 *
 * Mic hardware is set up once (on first PTT press) and stays active.
 * Audio only streams to the server while PTT is held down.
 * On release, the server commits the partial transcript and triggers the response.
 */

const TARGET_SAMPLE_RATE = 16000
const BUFFER_SIZE = 4096

function float32ToInt16(float32: Float32Array): Int16Array {
  const int16 = new Int16Array(float32.length)
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]))
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff
  }
  return int16
}

function int16ToBase64(int16: Int16Array): string {
  const bytes = new Uint8Array(int16.buffer)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i])
  }
  return btoa(binary)
}

function downsample(buffer: Float32Array, inputRate: number, outputRate: number): Float32Array {
  if (inputRate === outputRate) return buffer
  const ratio = inputRate / outputRate
  const newLength = Math.round(buffer.length / ratio)
  const result = new Float32Array(newLength)
  for (let i = 0; i < newLength; i++) {
    const index = Math.round(i * ratio)
    result[i] = buffer[Math.min(index, buffer.length - 1)]
  }
  return result
}

export function useVoice() {
  const streamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const processorRef = useRef<ScriptProcessorNode | null>(null)
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null)
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([])
  const nextStartTimeRef = useRef(0)
  const decodeChainRef = useRef<Promise<void>>(Promise.resolve())

  const getAudioContext = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext()
    }
    return audioCtxRef.current
  }

  const enqueueAudio = useCallback(
    (base64: string) => {
      const ctx = getAudioContext()
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
      }
      const arrayBuf = bytes.buffer

      // Chain decodes sequentially so chunks are always scheduled in arrival order
      decodeChainRef.current = decodeChainRef.current.then(() =>
        ctx.decodeAudioData(arrayBuf).then((buffer) => {
          const source = ctx.createBufferSource()
          source.buffer = buffer
          source.connect(ctx.destination)
          const startAt = Math.max(nextStartTimeRef.current, ctx.currentTime)
          source.start(startAt)
          nextStartTimeRef.current = startAt + buffer.duration
          scheduledSourcesRef.current.push(source)
          source.onended = () => {
            const idx = scheduledSourcesRef.current.indexOf(source)
            if (idx >= 0) scheduledSourcesRef.current.splice(idx, 1)
          }
        }).catch(() => {
          // skip bad chunk
        })
      )
    },
    [],
  )

  const flushPlayback = useCallback(() => {
    for (const source of scheduledSourcesRef.current) {
      try { source.stop() } catch { /* already stopped */ }
    }
    scheduledSourcesRef.current = []
    nextStartTimeRef.current = 0
    decodeChainRef.current = Promise.resolve()
  }, [])

  useWebSocket(
    useCallback(
      (event: WSEvent) => {
        if (event.type === 'audio_chunk') {
          enqueueAudio(event.data)
        } else if (event.type === 'interrupt') {
          flushPlayback()
          agentSpeaking.value = null
        } else if (event.type === 'agent_interrupted') {
          flushPlayback()
        }
      },
      [enqueueAudio, flushPlayback],
    ),
  )

  /** Ensure mic hardware is set up (called on first PTT press). */
  const ensureMic = useCallback(async () => {
    if (streamRef.current) return // already set up

    console.log('[Voice] Requesting microphone access...')
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    })
    streamRef.current = stream

    const ctx = getAudioContext()
    const source = ctx.createMediaStreamSource(stream)
    sourceRef.current = source

    const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1)
    processorRef.current = processor

    processor.onaudioprocess = (e) => {
      const inputData = e.inputBuffer.getChannelData(0)

      // Only send audio while PTT is held
      if (!isPTTActive.value) return

      const downsampled = downsample(inputData, ctx.sampleRate, TARGET_SAMPLE_RATE)
      const int16 = float32ToInt16(downsampled)
      const base64 = int16ToBase64(int16)

      wsManager.send({ type: 'audio_stream', data: base64 })
    }

    source.connect(processor)
    processor.connect(ctx.destination)

    console.log('[Voice] Mic ready, PTT mode')
  }, [])

  /** Start push-to-talk (pointer down). */
  const startPTT = useCallback(async () => {
    try {
      await ensureMic()
    } catch (err) {
      console.error('[Voice] Failed to get microphone', err)
      return
    }
    isPTTActive.value = true
    partialTranscript.value = null
    wsManager.send({ type: 'voice_state', active: true })
    console.log('[Voice] PTT started')
  }, [ensureMic])

  /** Stop push-to-talk (pointer up) — server commits partial transcript. */
  const stopPTT = useCallback(() => {
    if (!isPTTActive.value) return
    isPTTActive.value = false
    wsManager.send({ type: 'voice_state', active: false })
    console.log('[Voice] PTT released')
  }, [])

  /** Tear down mic hardware (called on end call). */
  const teardownMic = useCallback(() => {
    isPTTActive.value = false
    if (processorRef.current) {
      processorRef.current.disconnect()
      processorRef.current = null
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect()
      sourceRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    partialTranscript.value = null
  }, [])

  // Spacebar push-to-talk: hold space to talk, release to send
  useEffect(() => {
    const isInputFocused = () => {
      const tag = document.activeElement?.tagName
      return tag === 'INPUT' || tag === 'TEXTAREA' || (document.activeElement as HTMLElement)?.isContentEditable
    }

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.code !== 'Space' || e.repeat) return
      if (!activeCall.value || callMode.value !== 'voice') return
      if (isInputFocused()) return
      e.preventDefault()
      startPTT()
    }

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.code !== 'Space') return
      if (!activeCall.value || callMode.value !== 'voice') return
      if (isInputFocused()) return
      e.preventDefault()
      stopPTT()
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
    }
  }, [startPTT, stopPTT])

  useEffect(() => {
    return () => {
      teardownMic()
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close()
      }
    }
  }, [teardownMic])

  return { startPTT, stopPTT, teardownMic, flushPlayback }
}
