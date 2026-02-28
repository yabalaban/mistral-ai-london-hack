import { useEffect } from 'preact/hooks'
import { agents, agentsLoading, agentsError } from '../state/agents.ts'
import { fetchAgents, createConversation } from '../api/client.ts'
import { mockAgents } from '../mocks/agents.ts'
import { conversations, upsertConversation } from '../state/conversations.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

async function ensureConversations(agentList: typeof agents.value) {
  const existing = new Set(
    conversations.value
      .filter((c) => c.type === 'direct')
      .flatMap((c) => c.participants),
  )
  for (const agent of agentList) {
    if (!existing.has(agent.id)) {
      if (USE_MOCKS) {
        upsertConversation({
          id: `conv-${agent.id}`,
          type: 'direct',
          participants: [agent.id],
          messages: [],
          created_at: new Date().toISOString(),
        })
      } else {
        try {
          const conv = await createConversation('direct', [agent.id])
          upsertConversation(conv)
        } catch (err) {
          console.error(`Failed to create conversation for ${agent.id}`, err)
        }
      }
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
      .then(async (data) => {
        agents.value = data
        await ensureConversations(data)
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
