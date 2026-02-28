import { useState } from 'preact/hooks'
import { agents, agentsLoading } from '../../state/agents.ts'
import { Header } from '../layout/Header.tsx'
import { AgentCard } from './AgentCard.tsx'
import { AgentDetail } from './AgentDetail.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { Button } from '../shared/Button.tsx'
import type { Agent } from '../../types/index.ts'
import { route } from 'preact-router'
import { createConversation } from '../../api/client.ts'
import { upsertConversation, activeConversationId } from '../../state/conversations.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function RosterPage() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)

  const startGroupCall = async () => {
    const agentIds = agents.value.slice(0, 3).map((a) => a.id)
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

  if (agentsLoading.value) {
    return (
      <>
        <Header title="Agents" />
        <div class="flex-1 flex items-center justify-center">
          <Spinner size="lg" />
        </div>
      </>
    )
  }

  return (
    <>
      <Header title="Agents">
        <Button onClick={startGroupCall}>New Group Call</Button>
      </Header>
      <div class="flex-1 overflow-y-auto p-6">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 max-w-5xl">
          {agents.value.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onViewProfile={setSelectedAgent}
            />
          ))}
        </div>
      </div>
      {selectedAgent && (
        <AgentDetail agent={selectedAgent} onClose={() => setSelectedAgent(null)} />
      )}
    </>
  )
}
