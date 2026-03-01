import type { Agent } from '../../types/index.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { createConversation, deleteAgent } from '../../api/client.ts'
import { agents } from '../../state/agents.ts'
import { upsertConversation, activeConversationId } from '../../state/conversations.ts'
import { route } from 'preact-router'
import { USE_MOCKS } from '../../config.ts'

interface AgentCardProps {
  agent: Agent
}

export function AgentCard({ agent }: AgentCardProps) {
  const startChat = async () => {
    if (USE_MOCKS) {
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

  const handleDelete = async (e: Event) => {
    e.stopPropagation()
    if (!confirm(`Remove ${agent.name}?`)) return
    try {
      await deleteAgent(agent.id)
      agents.value = agents.value.filter((a) => a.id !== agent.id)
    } catch (err) {
      console.error('Failed to delete agent', err)
    }
  }

  return (
    <div
      onClick={startChat}
      class="glass rounded-2xl p-4 hover:-translate-y-1 hover:glow-soft transition-all duration-200 cursor-pointer group"
    >
      <div class="flex items-start gap-3">
        <Avatar name={agent.name} src={agent.avatar} size="lg" />
        <div class="min-w-0 flex-1">
          <h3 class="font-semibold text-zinc-900">{agent.name}</h3>
          <p class="text-sm text-accent">{agent.role}</p>
        </div>
        <button
          onClick={handleDelete}
          class="opacity-0 group-hover:opacity-100 p-1 text-zinc-300 hover:text-red-400 transition-all"
          title="Remove agent"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <p class="mt-3 text-sm text-zinc-500 line-clamp-2">{agent.bio}</p>
      <div class="mt-2 flex flex-wrap gap-1">
        {agent.tools?.map((tool) => (
          <span
            key={tool}
            class="text-xs px-2 py-0.5 rounded-full bg-zinc-100 border border-zinc-200 text-zinc-500"
          >
            {tool}
          </span>
        ))}
      </div>
    </div>
  )
}
