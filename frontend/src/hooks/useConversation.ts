import { useEffect } from 'preact/hooks'
import { activeConversationId, upsertConversation } from '../state/conversations.ts'
import { fetchConversation } from '../api/client.ts'
import { wsManager } from '../api/ws.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function useConversation(convId: string) {
  useEffect(() => {
    activeConversationId.value = convId

    if (!USE_MOCKS) {
      fetchConversation(convId)
        .then((conv) => upsertConversation(conv))
        .catch((err) => console.error('Failed to fetch conversation', err))

      wsManager.connect(convId)
    }

    return () => {
      wsManager.disconnect()
    }
  }, [convId])
}
