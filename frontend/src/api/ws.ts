import type { WSEvent } from '../types/index.ts'
import {
  streamingMessage,
  streamingAgentId,
  appendMessage,
  lastTranscription,
} from '../state/conversations.ts'
import { activeCall, currentSpeaker } from '../state/call.ts'
import { generateId } from '../utils/format.ts'

type EventHandler = (event: WSEvent) => void

class WebSocketManager {
  private ws: WebSocket | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private currentConvId: string | null = null
  private handlers: Set<EventHandler> = new Set()

  connect(convId: string) {
    if (this.currentConvId === convId && this.ws?.readyState === WebSocket.OPEN) return
    this.disconnect()
    this.currentConvId = convId

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws/conversations/${convId}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      console.log(`[WS] Connected to conversation ${convId}`)
    }

    this.ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data)
        this.dispatch(event)
      } catch {
        console.error('[WS] Failed to parse message', e.data)
      }
    }

    this.ws.onclose = () => {
      console.log('[WS] Disconnected')
      if (this.currentConvId === convId) {
        this.reconnectTimer = setTimeout(() => this.connect(convId), 2000)
      }
    }

    this.ws.onerror = (e) => {
      console.error('[WS] Error', e)
    }
  }

  disconnect() {
    this.currentConvId = null
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    if (this.ws) {
      this.ws.onclose = null
      this.ws.close()
      this.ws = null
    }
  }

  send(data: Record<string, unknown>) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  onEvent(handler: EventHandler) {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  private dispatch(event: WSEvent) {
    switch (event.type) {
      case 'message_chunk':
        streamingAgentId.value = event.agent_id
        streamingMessage.value = (streamingMessage.value ?? '') + event.content
        break
      case 'message_complete':
        streamingMessage.value = null
        streamingAgentId.value = null
        appendMessage(event.message)
        break
      case 'oracle_reasoning':
        appendMessage({
          id: generateId(),
          role: 'system',
          content: `🧠 ${event.reasoning}\n→ ${event.next_speaker_name}: ${event.hint}`,
          timestamp: new Date().toISOString(),
        })
        break
      case 'turn_change':
        currentSpeaker.value = event.agent_id
        break
      case 'call_started':
        activeCall.value = event.call
        break
      case 'call_ended':
        activeCall.value = null
        currentSpeaker.value = null
        break
      case 'transcription':
        lastTranscription.value = event.text
        break
    }

    for (const handler of this.handlers) {
      handler(event)
    }
  }
}

export const wsManager = new WebSocketManager()
