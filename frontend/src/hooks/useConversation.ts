import { useEffect } from 'preact/hooks'
import { activeConversationId, conversations, upsertConversation } from '../state/conversations.ts'
import { fetchConversation } from '../api/client.ts'
import { wsManager } from '../api/ws.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function useConversation(convId: string) {
  useEffect(() => {
    activeConversationId.value = convId

    if (USE_MOCKS) return

    // Check if conversation exists locally first
    const existing = conversations.value.find((c) => c.id === convId)
    if (existing) {
      // Already have it — just connect WS
      wsManager.connect(convId)
    } else {
      // Try to fetch from backend, then connect WS
      fetchConversation(convId)
        .then((conv) => {
          upsertConversation(conv)
          wsManager.connect(convId)
        })
        .catch((err) => {
          console.warn('Conversation not found, skipping WS connect', err)
        })
    }

    return () => {
      wsManager.disconnect()
    }
  }, [convId])
}
