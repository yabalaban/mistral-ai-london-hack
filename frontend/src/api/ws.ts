import type { WSEvent } from '../types/index.ts'
import {
  streamingMessage,
  streamingAgentId,
  appendMessage,
  updateConversationTopic,
} from '../state/conversations.ts'
import { activeCall, currentSpeaker, agentSpeaking, partialTranscript } from '../state/call.ts'
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

    this.ws.onclose = (e) => {
      console.log('[WS] Disconnected', e.code, e.reason)
      // Don't reconnect if server explicitly rejected (conversation not found)
      if (e.code === 4004) return
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
      case 'topic_set':
        updateConversationTopic(event.topic)
        appendMessage({
          id: generateId(),
          role: 'system',
          content: `📌 Topic: ${event.topic}`,
          timestamp: new Date().toISOString(),
        })
        break
      case 'oracle_reasoning': {
        const reasoning = event.reasoning
        let text: string
        if (event.next_speaker_name && event.hint) {
          text = `🧠 ${reasoning}\n→ ${event.next_speaker_name}: ${event.hint}`
        } else {
          // Oracle decided the round is done
          text = `🧠 ${reasoning}\n✋ Round complete.`
        }
        appendMessage({
          id: generateId(),
          role: 'system',
          content: text,
          timestamp: new Date().toISOString(),
        })
        break
      }
      case 'summary':
        appendMessage({
          id: generateId(),
          role: 'system',
          content: `📋 **Round Summary**\n${event.content}`,
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
        agentSpeaking.value = null
        partialTranscript.value = null
        break
      case 'transcription':
        partialTranscript.value = null
        // Add user's transcribed speech to the message list
        appendMessage({
          id: generateId(),
          role: 'user',
          content: event.text,
          timestamp: new Date().toISOString(),
        })
        break
      case 'partial_transcript':
        partialTranscript.value = event.text
        break
      case 'agent_speaking':
        agentSpeaking.value = event.agent_id
        currentSpeaker.value = event.agent_id
        break
      case 'agent_done':
        if (agentSpeaking.value === event.agent_id) {
          agentSpeaking.value = null
        }
        currentSpeaker.value = null
        break
      case 'interrupt':
        // Agent was interrupted — handled by useVoice to flush audio playback
        agentSpeaking.value = null
        currentSpeaker.value = null
        break
      case 'agent_interrupted':
        // Agent-to-agent interruption
        agentSpeaking.value = null
        currentSpeaker.value = null
        appendMessage({
          id: generateId(),
          role: 'system',
          content: `⚡ ${event.by} interrupted ${event.agent_id}`,
          timestamp: new Date().toISOString(),
        })
        break
      default:
        break
    }

    for (const handler of this.handlers) {
      handler(event)
    }
  }
}

export const wsManager = new WebSocketManager()
