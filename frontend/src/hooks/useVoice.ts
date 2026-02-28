import { useEffect, useRef, useCallback } from 'preact/hooks'
import { isMicOn, agentSpeaking, partialTranscript } from '../state/call.ts'
import { wsManager } from '../api/ws.ts'
import { useWebSocket } from './useWebSocket.ts'
import type { WSEvent } from '../types/index.ts'

/**
 * PCM 16kHz audio capture and real-time voice streaming.
 *
 * Instead of MediaRecorder (WebM blobs), this uses a ScriptProcessorNode
 * to capture raw PCM at 16kHz, converts float32→int16→base64, and streams
 * continuously via WebSocket as `audio_stream` events.
 *
 * Voice state is managed via `voice_state` messages to the server,
 * which controls the ElevenLabs STT session lifecycle.
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
  const playQueueRef = useRef<ArrayBuffer[]>([])
  const isPlayingRef = useRef(false)
  const currentSourceRef = useRef<AudioBufferSourceNode | null>(null)

  const getAudioContext = () => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext()
    }
    return audioCtxRef.current
  }

  const playNext = useCallback(() => {
    const ctx = getAudioContext()
    const data = playQueueRef.current.shift()
    if (!data) {
      isPlayingRef.current = false
      currentSourceRef.current = null
      return
    }
    isPlayingRef.current = true
    ctx.decodeAudioData(
      data,
      (buffer) => {
        const source = ctx.createBufferSource()
        source.buffer = buffer
        source.connect(ctx.destination)
        source.onended = playNext
        currentSourceRef.current = source
        source.start()
      },
      (err) => {
        console.error('[Voice] Failed to decode audio chunk', err)
        playNext() // skip bad chunk, continue playback
      },
    )
  }, [])

  const enqueueAudio = useCallback(
    (base64: string) => {
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
      }
      playQueueRef.current.push(bytes.buffer)
      if (!isPlayingRef.current) playNext()
    },
    [playNext],
  )

  const flushPlayback = useCallback(() => {
    // Stop current audio and clear queue
    if (currentSourceRef.current) {
      try {
        currentSourceRef.current.stop()
      } catch {
        // already stopped
      }
      currentSourceRef.current = null
    }
    playQueueRef.current = []
    isPlayingRef.current = false
  }, [])

  useWebSocket(
    useCallback(
      (event: WSEvent) => {
        if (event.type === 'audio_chunk') {
          enqueueAudio(event.data)
        } else if (event.type === 'interrupt') {
          // User interrupted agent — flush all audio
          flushPlayback()
          agentSpeaking.value = null
        } else if (event.type === 'agent_interrupted') {
          // Agent-to-agent interruption — flush audio
          flushPlayback()
        }
      },
      [enqueueAudio, flushPlayback],
    ),
  )

  const toggleMic = useCallback(async () => {
    if (isMicOn.value) {
      // Stop recording and close voice session
      wsManager.send({ type: 'voice_state', active: false })

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

      isMicOn.value = false
      partialTranscript.value = null
      return
    }

    try {
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

      // ScriptProcessorNode for raw PCM access
      const processor = ctx.createScriptProcessor(BUFFER_SIZE, 1, 1)
      processorRef.current = processor

      processor.onaudioprocess = (e) => {
        const inputData = e.inputBuffer.getChannelData(0)

        // Downsample to 16kHz and convert to int16 PCM
        const downsampled = downsample(inputData, ctx.sampleRate, TARGET_SAMPLE_RATE)
        const int16 = float32ToInt16(downsampled)
        const base64 = int16ToBase64(int16)

        // Send continuous audio stream
        wsManager.send({ type: 'audio_stream', data: base64 })
      }

      source.connect(processor)
      processor.connect(ctx.destination) // Required for ScriptProcessor to work

      // Tell server to start STT session
      wsManager.send({ type: 'voice_state', active: true })

      isMicOn.value = true
    } catch (err) {
      console.error('[Voice] Failed to get microphone', err)
    }
  }, [])

  useEffect(() => {
    return () => {
      if (processorRef.current) {
        processorRef.current.disconnect()
      }
      if (sourceRef.current) {
        sourceRef.current.disconnect()
      }
      streamRef.current?.getTracks().forEach((t) => t.stop())
      if (audioCtxRef.current && audioCtxRef.current.state !== 'closed') {
        audioCtxRef.current.close()
      }
    }
  }, [])

  return { toggleMic, flushPlayback }
}
