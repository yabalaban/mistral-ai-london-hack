import { signal, computed } from '@preact/signals'
import type { Conversation, Message } from '../types/index.ts'

export const conversations = signal<Conversation[]>([])
export const activeConversationId = signal<string | null>(null)
export const streamingMessage = signal<string | null>(null)
export const streamingAgentId = signal<string | null>(null)
export const lastTranscription = signal<string | null>(null)

export const activeConversation = computed(() => {
  const id = activeConversationId.value
  if (!id) return null
  return conversations.value.find((c) => c.id === id) ?? null
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

export function addOptimisticMessage(message: Message) {
  appendMessage(message)
}

export function updateConversationTopic(topic: string) {
  const id = activeConversationId.value
  if (!id) return
  const conv = conversations.value.find((c) => c.id === id)
  if (!conv) return
  upsertConversation({ ...conv, topic })
}
