import type { WSEvent } from '../types/index.ts'
import {
  streamingAgents,
  appendMessage,
  commitMessage,
  updateConversationTopic,
} from '../state/conversations.ts'
import {
  startOracle,
  addRound,
  addVerdictToCurrentRound,
  setGraderResult,
  setOracleSummary,
  setOracleTopic,
  endOracle,
} from '../state/oracle.ts'
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
      if (data.type !== 'audio_stream') {
        console.log('[WS] Send:', data.type, data)
      }
      this.ws.send(JSON.stringify(data))
    } else {
      console.warn('[WS] Send DROPPED (not open):', data.type)
    }
  }

  onEvent(handler: EventHandler) {
    this.handlers.add(handler)
    return () => this.handlers.delete(handler)
  }

  private dispatch(event: WSEvent) {
    if (event.type === 'audio_chunk') {
      console.log('[WS] Recv: audio_chunk', { agent_id: (event as any).agent_id })
    } else {
      console.log('[WS] Recv:', event.type, event)
    }

    switch (event.type) {
      case 'message_chunk':
        // No-op — typing indicator is driven by turn_change entry existence
        break
      case 'message_complete':
        commitMessage(event.message.agent_id ?? '', event.message)
        break
      case 'oracle_start':
        startOracle(event.directed, event.directed_agent)
        break
      case 'oracle_end':
        endOracle()
        break
      case 'topic_set':
        updateConversationTopic(event.topic)
        setOracleTopic(event.topic)
        break
      case 'oracle_reasoning':
        addRound({
          round: event.round,
          mode: event.mode,
          reasoning: event.reasoning,
          speakers: event.speakers,
        })
        break
      case 'grader':
        setGraderResult(event.round, event.reasoning, event.done)
        break
      case 'agent_verdict':
        addVerdictToCurrentRound({
          agentId: event.agent_id,
          agentName: event.agent_name,
          verdict: event.verdict,
        })
        break
      case 'summary':
        setOracleSummary(event.content)
        break
      case 'turn_change': {
        currentSpeaker.value = event.agent_id
        const turnMap = new Map(streamingAgents.value)
        turnMap.set(event.agent_id, {
          agentId: event.agent_id,
          replyToId: event.reply_to_id,
        })
        streamingAgents.value = turnMap
        break
      }
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
        agentSpeaking.value = null
        currentSpeaker.value = null
        streamingAgents.value = new Map()
        break
      case 'agent_interrupted':
        agentSpeaking.value = null
        currentSpeaker.value = null
        appendMessage({
          id: generateId(),
          role: 'system',
          content: `${event.by} interrupted ${event.agent_id}`,
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
