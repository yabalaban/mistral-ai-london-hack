import type { Agent } from '../../types/index.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { createConversation } from '../../api/client.ts'
import { upsertConversation, activeConversationId } from '../../state/conversations.ts'
import { route } from 'preact-router'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

interface AgentCardProps {
  agent: Agent
  onViewProfile: (agent: Agent) => void
}

export function AgentCard({ agent, onViewProfile }: AgentCardProps) {
  const startChat = async () => {
    if (USE_MOCKS) {
      // Create a mock conversation
      const mockConv = {
        id: `conv-${agent.id}`,
        type: 'direct' as const,
        participants: ['user', agent.id],
        messages: [],
        created_at: new Date().toISOString(),
      }
      upsertConversation(mockConv)
      activeConversationId.value = mockConv.id
      route(`/chat/${mockConv.id}`)
      return
    }

    try {
      const conv = await createConversation('direct', [agent.id])
      upsertConversation(conv)
      activeConversationId.value = conv.id
      route(`/chat/${conv.id}`)
    } catch (err) {
      console.error('Failed to create conversation', err)
    }
  }

  return (
    <div class="bg-dc-secondary rounded-lg p-4 hover:bg-dc-tertiary transition-colors group">
      <div class="flex items-start gap-3">
        <Avatar name={agent.name} src={agent.avatar} size="lg" />
        <div class="min-w-0 flex-1">
          <h3 class="font-semibold text-dc-text">{agent.name}</h3>
          <p class="text-sm text-dc-blurple">{agent.role}</p>
        </div>
      </div>
      <p class="mt-3 text-sm text-dc-text-secondary line-clamp-2">{agent.bio}</p>
      <div class="mt-2 flex flex-wrap gap-1">
        {agent.tools?.map((tool) => (
          <span
            key={tool}
            class="text-xs px-2 py-0.5 rounded-full bg-dc-primary text-dc-text-muted"
          >
            {tool}
          </span>
        ))}
      </div>
      <div class="mt-4 flex gap-2">
        <button
          onClick={startChat}
          class="flex-1 px-3 py-1.5 bg-dc-blurple hover:bg-dc-blurple-hover text-white text-sm rounded transition-colors"
        >
          Message
        </button>
        <button
          onClick={() => onViewProfile(agent)}
          class="px-3 py-1.5 bg-dc-primary hover:bg-dc-tertiary text-dc-text-secondary text-sm rounded transition-colors"
        >
          Profile
        </button>
      </div>
    </div>
  )
}
