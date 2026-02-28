import { useEffect } from 'preact/hooks'
import { agents, agentsLoading, agentsError } from '../state/agents.ts'
import { fetchAgents } from '../api/client.ts'
import { mockAgents } from '../mocks/agents.ts'
import { conversations, upsertConversation } from '../state/conversations.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

function ensureConversations(agentList: typeof agents.value) {
  const existing = new Set(
    conversations.value
      .filter((c) => c.type === 'direct')
      .flatMap((c) => c.participants.filter((p) => p !== 'user')),
  )
  for (const agent of agentList) {
    if (!existing.has(agent.id)) {
      upsertConversation({
        id: `conv-${agent.id}`,
        type: 'direct',
        participants: ['user', agent.id],
        messages: [],
        created_at: new Date().toISOString(),
      })
    }
  }
}

export function useAgents() {
  useEffect(() => {
    if (agents.value.length > 0) return

    if (USE_MOCKS) {
      agents.value = mockAgents
      ensureConversations(mockAgents)
      return
    }

    agentsLoading.value = true
    fetchAgents()
      .then((data) => {
        agents.value = data
        ensureConversations(data)
      })
      .catch((err) => {
        agentsError.value = err.message
        agents.value = mockAgents
        ensureConversations(mockAgents)
      })
      .finally(() => {
        agentsLoading.value = false
      })
  }, [])
}
