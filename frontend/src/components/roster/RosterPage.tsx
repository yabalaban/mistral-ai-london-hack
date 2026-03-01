import { useState } from 'preact/hooks'
import { agents, agentsLoading } from '../../state/agents.ts'
import { Header } from '../layout/Header.tsx'
import { AgentCard } from './AgentCard.tsx'
import { CreateAgentModal } from './CreateAgentModal.tsx'
import { NewGroupModal } from './NewGroupModal.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { Button } from '../shared/Button.tsx'
import type { Agent } from '../../types/index.ts'
import { createGroupConversation } from '../../utils/conversations.ts'
import { createAgent } from '../../api/client.ts'

interface RosterPageProps {
  path?: string
}

export function RosterPage(_props: RosterPageProps) {
  const [showCreateAgent, setShowCreateAgent] = useState(false)
  const [showNewGroup, setShowNewGroup] = useState(false)

  const handleCreateAgent = async (agent: Agent) => {
    try {
      const created = await createAgent(agent)
      agents.value = [...agents.value, created]
    } catch (e) {
      console.error('Failed to create agent:', e)
      // Fallback: add locally
      agents.value = [...agents.value, agent]
    }
    setShowCreateAgent(false)
  }

  const handleCreateGroup = async (agentIds: string[]) => {
    setShowNewGroup(false)
    await createGroupConversation(agentIds)
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
      <div class="flex-1 overflow-y-auto p-4 md:p-8">
        <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5 max-w-5xl">
          {agents.value.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}
        </div>
      </div>
      {showCreateAgent && (
        <CreateAgentModal onClose={() => setShowCreateAgent(false)} onCreate={handleCreateAgent} />
      )}
      {showNewGroup && (
        <NewGroupModal onClose={() => setShowNewGroup(false)} onCreate={handleCreateGroup} />
      )}
    </>
  )
}
