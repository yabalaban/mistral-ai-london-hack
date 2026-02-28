import { signal, computed } from '@preact/signals'
import type { Conversation, Message } from '../types/index.ts'

export const conversations = signal<Conversation[]>([])
export const activeConversationId = signal<string | null>(null)

/** Per-agent streaming state — tracks who is typing and accumulates content. */
export interface StreamingEntry {
  agentId: string
  content: string
  replyToId?: string
}
export const streamingAgents = signal<Map<string, StreamingEntry>>(new Map())

export const activeConversation = computed(() => {
  const id = activeConversationId.value
  if (!id) return null
  return conversations.value.find((c) => c.id === id) ?? null
})

export const messageMap = computed(() => {
  const conv = activeConversation.value
  if (!conv) return new Map<string, Message>()
  return new Map(conv.messages.map((m) => [m.id, m]))
})

export function upsertConversation(conv: Conversation) {
  const existing = conversations.value.findIndex((c) => c.id === conv.id)
  if (existing >= 0) {
    const updated = [...conversations.value]
    updated[existing] = conv
    conversations.value = updated
  } else {
    conversations.value = [...conversations.value, conv]
  }
}

export function appendMessage(message: Message) {
  const id = activeConversationId.value
  if (!id) return
  const conv = conversations.value.find((c) => c.id === id)
  if (!conv) return
  upsertConversation({
    ...conv,
    messages: [...conv.messages, message],
  })
}

/**
 * Commit a completed agent message: remove from streaming state and
 * append to conversation. Called on message_complete (text) and will
 * be called on voice drain completion for interruption support.
 */
export function commitMessage(agentId: string, message: Message) {
  const next = new Map(streamingAgents.value)
  next.delete(agentId)
  streamingAgents.value = next
  appendMessage(message)
}

/** Discard an agent's in-progress stream without committing. */
export function discardStream(agentId: string) {
  const next = new Map(streamingAgents.value)
  next.delete(agentId)
  streamingAgents.value = next
}

export function updateConversationTopic(topic: string) {
  const id = activeConversationId.value
  if (!id) return
  const conv = conversations.value.find((c) => c.id === id)
  if (!conv) return
  upsertConversation({ ...conv, topic })
}
