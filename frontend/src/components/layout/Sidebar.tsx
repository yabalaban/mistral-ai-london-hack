import { agents } from '../../state/agents.ts'
import { conversations } from '../../state/conversations.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { truncate } from '../../utils/format.ts'
import { agentMap } from '../../state/agents.ts'

export function Sidebar() {
  return (
    <div class="w-60 min-w-60 bg-dc-secondary flex flex-col h-full">
      <div class="h-12 min-h-12 flex items-center px-4 border-b border-dc-primary shadow-sm">
        <h1 class="font-bold text-dc-text tracking-wide">Ensemble</h1>
      </div>

      <div class="flex-1 overflow-y-auto">
        {/* Recent conversations */}
        {conversations.value.length > 0 && (
          <div class="p-2">
            <div class="px-2 py-1 text-xs font-semibold text-dc-text-muted uppercase tracking-wider">
              Conversations
            </div>
            {conversations.value.map((conv) => {
              const agentId = conv.participants.find((p) => p !== 'user')
              const agent = agentId ? agentMap.value.get(agentId) : null
              return (
                <a
                  key={conv.id}
                  href={conv.type === 'direct' ? `/chat/${conv.id}` : `/group/${conv.id}`}
                  class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-dc-tertiary text-dc-text-secondary hover:text-dc-text transition-colors"
                >
                  <Avatar name={agent?.name ?? '?'} src={agent?.avatar} size="sm" />
                  <span class="text-sm truncate">
                    {agent?.name ?? truncate(conv.id, 16)}
                  </span>
                </a>
              )
            })}
          </div>
        )}

        {/* Agent list */}
        <div class="p-2">
          <div class="px-2 py-1 text-xs font-semibold text-dc-text-muted uppercase tracking-wider">
            Agents
          </div>
          {agents.value.map((agent) => (
            <a
              key={agent.id}
              href="/"
              class="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-dc-tertiary text-dc-text-secondary hover:text-dc-text transition-colors"
            >
              <Avatar name={agent.name} src={agent.avatar} size="sm" />
              <div class="min-w-0">
                <div class="text-sm truncate">{agent.name}</div>
                <div class="text-xs text-dc-text-muted truncate">{agent.role}</div>
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
