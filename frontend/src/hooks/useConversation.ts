import { useEffect } from 'preact/hooks'
import { route } from 'preact-router'
import { activeConversationId, conversations, upsertConversation } from '../state/conversations.ts'
import { fetchConversation } from '../api/client.ts'
import { wsManager } from '../api/ws.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function useConversation(convId: string) {
  useEffect(() => {
    if (!convId) return
    activeConversationId.value = convId

    if (USE_MOCKS) return

    // Check if conversation exists locally first
    const existing = conversations.value.find((c) => c.id === convId)
    if (existing) {
      wsManager.connect(convId)
    } else {
      // Try to fetch from backend — redirect home if not found
      fetchConversation(convId)
        .then((conv) => {
          upsertConversation(conv)
          wsManager.connect(convId)
        })
        .catch(() => {
          route('/', true)
        })
    }

    return () => {
      activeConversationId.value = null
      wsManager.disconnect()
    }
  }, [convId])
}
