import { useState } from 'preact/hooks'
import { conversations } from '../../state/conversations.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { truncate } from '../../utils/format.ts'
import { agentMap } from '../../state/agents.ts'
import { NewGroupModal } from '../roster/NewGroupModal.tsx'
import { createGroupConversation } from '../../utils/conversations.ts'

export function Sidebar() {
  const [showNewGroup, setShowNewGroup] = useState(false)

  const handleCreateGroup = async (agentIds: string[]) => {
    setShowNewGroup(false)
    await createGroupConversation(agentIds)
  }

  return (
    <>
      <div class="w-60 min-w-60 glass-strong border-r border-white/10 flex flex-col h-full">
        <div class="h-14 min-h-14 flex items-center px-4 border-b border-white/10">
          <div class="flex items-center gap-2">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <circle cx="10" cy="14" r="8" stroke="#06b6d4" stroke-width="2" fill="none" opacity="0.8" />
              <circle cx="18" cy="14" r="8" stroke="#06b6d4" stroke-width="2" fill="none" opacity="0.5" />
            </svg>
            <h1 class="font-bold text-white tracking-wide">Circles</h1>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto p-2">
          {conversations.value.length === 0 && (
            <div class="text-sm text-white/30 text-center py-8">No conversations yet</div>
          )}
          {conversations.value.map((conv) => {
            const agentIds = conv.participants.filter((p) => p !== 'user')
            const convAgents = agentIds.map((id) => agentMap.value.get(id)).filter(Boolean)
            const isGroup = conv.type === 'group'
            const label = isGroup
              ? convAgents.map((a) => a!.name).join(', ') || truncate(conv.id, 16)
              : convAgents[0]?.name ?? truncate(conv.id, 16)

            return (
              <a
                key={conv.id}
                href={isGroup ? `/group/${conv.id}` : `/chat/${conv.id}`}
                class="flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-white/10 text-white/60 hover:text-white transition-colors"
              >
                {isGroup ? (
                  <div class="w-8 h-8 flex-shrink-0 rounded-full bg-accent/20 flex items-center justify-center text-accent text-xs font-bold">
                    {agentIds.length}
                  </div>
                ) : (
                  <Avatar name={convAgents[0]?.name ?? '?'} src={convAgents[0]?.avatar} size="sm" />
                )}
                <span class="text-sm truncate">{label}</span>
              </a>
            )
          })}
        </div>

        <div class="p-2 border-t border-white/10">
          <button
            onClick={() => setShowNewGroup(true)}
            class="w-full flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-white/10 text-white/40 hover:text-white transition-colors"
          >
            <div class="w-8 h-8 flex-shrink-0 rounded-full bg-white/5 border border-dashed border-white/20 flex items-center justify-center">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
              </svg>
            </div>
            <span class="text-sm">New Group</span>
          </button>
        </div>
      </div>

      {showNewGroup && (
        <NewGroupModal onClose={() => setShowNewGroup(false)} onCreate={handleCreateGroup} />
      )}
    </>
  )
}
