import { useEffect, useRef, useCallback } from 'preact/hooks'
import { isMicOn, isRecording } from '../state/call.ts'
import { wsManager } from '../api/ws.ts'
import { useWebSocket } from './useWebSocket.ts'
import type { WSEvent } from '../types/index.ts'

export function useVoice() {
  const recorderRef = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const audioCtxRef = useRef<AudioContext | null>(null)
  const playQueueRef = useRef<AudioBuffer[]>([])
  const isPlayingRef = useRef(false)

  const getAudioContext = () => {
    if (!audioCtxRef.current) {
      audioCtxRef.current = new AudioContext()
    }
    return audioCtxRef.current
  }

  const playNext = useCallback(() => {
    const ctx = getAudioContext()
    const buffer = playQueueRef.current.shift()
    if (!buffer) {
      isPlayingRef.current = false
      return
    }
    isPlayingRef.current = true
    const source = ctx.createBufferSource()
    source.buffer = buffer
    source.connect(ctx.destination)
    source.onended = playNext
    source.start()
  }, [])

  const enqueueAudio = useCallback(
    async (base64: string) => {
      const ctx = getAudioContext()
      const binary = atob(base64)
      const bytes = new Uint8Array(binary.length)
      for (let i = 0; i < binary.length; i++) {
        bytes[i] = binary.charCodeAt(i)
      }
      try {
        const buffer = await ctx.decodeAudioData(bytes.buffer)
        playQueueRef.current.push(buffer)
        if (!isPlayingRef.current) playNext()
      } catch (err) {
        console.error('[Voice] Failed to decode audio chunk', err)
      }
    },
    [playNext],
  )

  useWebSocket(
    useCallback(
      (event: WSEvent) => {
        if (event.type === 'audio_chunk') {
          enqueueAudio(event.data)
        }
      },
      [enqueueAudio],
    ),
  )

  const toggleMic = useCallback(async () => {
    if (isMicOn.value) {
      // Stop recording
      recorderRef.current?.stop()
      streamRef.current?.getTracks().forEach((t) => t.stop())
      recorderRef.current = null
      streamRef.current = null
      isMicOn.value = false
      isRecording.value = false
      return
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const recorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
      recorderRef.current = recorder

      recorder.ondataavailable = async (e) => {
        if (e.data.size === 0) return
        const reader = new FileReader()
        reader.onloadend = () => {
          const base64 = (reader.result as string).split(',')[1]
          wsManager.send({ type: 'audio', data: base64 })
        }
        reader.readAsDataURL(e.data)
      }

      recorder.start(250) // 250ms chunks
      isMicOn.value = true
      isRecording.value = true
    } catch (err) {
      console.error('[Voice] Failed to get microphone', err)
    }
  }, [])

  useEffect(() => {
    return () => {
      recorderRef.current?.stop()
      streamRef.current?.getTracks().forEach((t) => t.stop())
      audioCtxRef.current?.close()
    }
  }, [])

  return { toggleMic }
}
