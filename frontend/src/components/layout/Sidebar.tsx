import { useState } from 'preact/hooks'
import { conversations } from '../../state/conversations.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { truncate } from '../../utils/format.ts'
import { agentMap } from '../../state/agents.ts'
import { NewGroupModal } from '../roster/NewGroupModal.tsx'
import { createGroupConversation } from '../../utils/conversations.ts'
import { mobileSidebarOpen } from '../../state/ui.ts'

export function Sidebar() {
  const [showNewGroup, setShowNewGroup] = useState(false)
  const isOpen = mobileSidebarOpen.value

  const handleCreateGroup = async (agentIds: string[]) => {
    setShowNewGroup(false)
    await createGroupConversation(agentIds)
  }

  const closeSidebar = () => {
    mobileSidebarOpen.value = false
  }

  return (
    <>
      {/* Mobile overlay backdrop */}
      {isOpen && (
        <div
          class="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={closeSidebar}
        />
      )}
      <div class={`
        w-60 min-w-60 glass-strong border-r border-zinc-200 flex flex-col h-full
        fixed inset-y-0 left-0 z-50 transition-transform duration-200
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
        md:static md:translate-x-0
      `}>
        <div class="h-14 min-h-14 flex items-center px-4 border-b border-zinc-200">
          <div class="flex items-center gap-2">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <circle cx="10" cy="14" r="8" stroke="#6366F1" stroke-width="2" fill="none" opacity="0.8" />
              <circle cx="18" cy="14" r="8" stroke="#6366F1" stroke-width="2" fill="none" opacity="0.5" />
            </svg>
            <h1 class="font-bold text-zinc-900 tracking-wide" style="font-family: 'Sora', sans-serif">Circles</h1>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto p-2">
          {conversations.value.length === 0 && (
            <div class="text-sm text-zinc-400 text-center py-8">No conversations yet</div>
          )}
          {conversations.value.map((conv) => {
            const agentIds = conv.participants.filter((p) => p !== 'user')
            const convAgents = agentIds.map((id) => agentMap.value.get(id)).filter(Boolean)
            const isGroup = conv.type === 'group'
            const label = isGroup
              ? (conv.topic && conv.topic !== 'General discussion'
                  ? truncate(conv.topic, 28)
                  : convAgents.map((a) => a!.name).join(', ') || truncate(conv.id, 16))
              : convAgents[0]?.name ?? truncate(conv.id, 16)

            return (
              <a
                key={conv.id}
                href={isGroup ? `/group/${conv.id}` : `/chat/${conv.id}`}
                onClick={closeSidebar}
                class="flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-zinc-100 text-zinc-500 hover:text-zinc-900 transition-colors"
              >
                {isGroup ? (
                  <div class="w-8 h-8 flex-shrink-0 rounded-full bg-indigo-50 flex items-center justify-center text-accent text-xs font-bold">
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

        <div class="p-2 border-t border-zinc-200">
          <button
            onClick={() => setShowNewGroup(true)}
            class="w-full flex items-center gap-2 px-2 py-1.5 rounded-xl hover:bg-zinc-100 text-zinc-400 hover:text-zinc-900 transition-colors"
          >
            <div class="w-8 h-8 flex-shrink-0 rounded-full bg-zinc-100 border border-dashed border-zinc-300 flex items-center justify-center">
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
