import { useState } from 'preact/hooks'
import { agents, agentsLoading } from '../../state/agents.ts'
import { Header } from '../layout/Header.tsx'
import { AgentCard } from './AgentCard.tsx'
import { AgentDetail } from './AgentDetail.tsx'
import { CreateAgentModal } from './CreateAgentModal.tsx'
import { NewGroupModal } from './NewGroupModal.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { Button } from '../shared/Button.tsx'
import type { Agent } from '../../types/index.ts'
import { route } from 'preact-router'
import { createConversation } from '../../api/client.ts'
import { upsertConversation, activeConversationId } from '../../state/conversations.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function RosterPage() {
  const [selectedAgent, setSelectedAgent] = useState<Agent | null>(null)
  const [showCreateAgent, setShowCreateAgent] = useState(false)
  const [showNewGroup, setShowNewGroup] = useState(false)

  const handleCreateAgent = (agent: Agent) => {
    agents.value = [...agents.value, agent]
    setShowCreateAgent(false)
  }

  const handleCreateGroup = async (agentIds: string[]) => {
    setShowNewGroup(false)
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
        <Button variant="secondary" onClick={() => setShowNewGroup(true)}>New Group Chat</Button>
        <Button onClick={() => setShowCreateAgent(true)}>Add Agent</Button>
      </Header>
      <div class="flex-1 overflow-y-auto p-8">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 max-w-5xl">
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
      {showCreateAgent && (
        <CreateAgentModal onClose={() => setShowCreateAgent(false)} onCreate={handleCreateAgent} />
      )}
      {showNewGroup && (
        <NewGroupModal onClose={() => setShowNewGroup(false)} onCreate={handleCreateGroup} />
      )}
    </>
  )
}
