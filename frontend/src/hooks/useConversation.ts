import { useEffect } from 'preact/hooks'
import { activeConversationId, conversations, upsertConversation } from '../state/conversations.ts'
import { fetchConversation } from '../api/client.ts'
import { wsManager } from '../api/ws.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function useConversation(convId: string) {
  useEffect(() => {
    activeConversationId.value = convId

    if (!USE_MOCKS) {
      // Only fetch if we don't already have messages (avoid overwriting local state)
      const existing = conversations.value.find((c) => c.id === convId)
      if (!existing || existing.messages.length === 0) {
        fetchConversation(convId)
          .then((conv) => upsertConversation(conv))
          .catch((err) => console.warn('Failed to fetch conversation', err))
      }

      wsManager.connect(convId)
    }

    return () => {
      wsManager.disconnect()
    }
  }, [convId])
}
