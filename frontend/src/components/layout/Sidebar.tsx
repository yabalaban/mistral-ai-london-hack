import { agents } from '../../state/agents.ts'
import { conversations } from '../../state/conversations.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { truncate } from '../../utils/format.ts'
import { agentMap } from '../../state/agents.ts'

export function Sidebar() {
  return (
    <div class="w-60 min-w-60 glass-strong border-r border-white/10 flex flex-col h-full">
      <div class="h-14 min-h-14 flex items-center px-4 border-b border-white/10">
        <div class="flex items-center gap-2">
          {/* Two overlapping circles logo */}
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <circle cx="10" cy="14" r="8" stroke="#06b6d4" stroke-width="2" fill="none" opacity="0.8" />
            <circle cx="18" cy="14" r="8" stroke="#06b6d4" stroke-width="2" fill="none" opacity="0.5" />
          </svg>
          <h1 class="font-bold text-white tracking-wide">Circles</h1>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto">
        {conversations.value.length > 0 && (
          <div class="p-2">
            <div class="px-2 py-1 text-xs font-semibold text-white/40 uppercase tracking-wider">
              Conversations
            </div>
            {conversations.value.map((conv) => {
              const agentId = conv.participants.find((p) => p !== 'user')
              const agent = agentId ? agentMap.value.get(agentId) : null
              return (
                <a
                  key={conv.id}
                  href={conv.type === 'direct' ? `/chat/${conv.id}` : `/group/${conv.id}`}
                  class="flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-white/10 text-white/60 hover:text-white transition-colors"
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

        <div class="p-2">
          <div class="px-2 py-1 text-xs font-semibold text-white/40 uppercase tracking-wider">
            Agents
          </div>
          {agents.value.map((agent) => (
            <a
              key={agent.id}
              href="/"
              class="flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-white/10 text-white/60 hover:text-white transition-colors"
            >
              <Avatar name={agent.name} src={agent.avatar} size="sm" />
              <div class="min-w-0">
                <div class="text-sm truncate">{agent.name}</div>
                <div class="text-xs text-white/40 truncate">{agent.role}</div>
              </div>
            </a>
          ))}
        </div>
      </div>
    </div>
  )
}
