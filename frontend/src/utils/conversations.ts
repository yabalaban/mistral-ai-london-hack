import { route } from 'preact-router'
import { createConversation } from '../api/client.ts'
import { upsertConversation, activeConversationId } from '../state/conversations.ts'
import { USE_MOCKS } from '../config.ts'

export async function createGroupConversation(agentIds: string[]) {
  if (USE_MOCKS) {
    const mockConv = {
      id: `group-${Date.now()}`,
      type: 'group' as const,
      participants: ['user', ...agentIds],
      messages: [],
      created_at: new Date().toISOString(),
    }
    upsertConversation(mockConv)
    activeConversationId.value = mockConv.id
    route(`/group/${mockConv.id}`)
    return
  }
  try {
    const conv = await createConversation('group', agentIds)
    upsertConversation(conv)
    activeConversationId.value = conv.id
    route(`/group/${conv.id}`)
  } catch (err) {
    console.error('Failed to create group', err)
  }
}
