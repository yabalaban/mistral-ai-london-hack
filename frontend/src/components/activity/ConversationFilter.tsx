import { conversationIds, conversationLabels, activeConversationFilter } from '../../state/activity.ts'

export function ConversationFilter() {
  const ids = conversationIds.value
  const labels = conversationLabels.value
  const active = activeConversationFilter.value

  return (
    <div class="flex flex-col gap-1">
      <h3 class="text-xs font-semibold text-zinc-400 uppercase tracking-wider px-2 mb-1">Conversations</h3>
      <button
        onClick={() => { activeConversationFilter.value = null }}
        class={`text-left text-sm px-2 py-1 rounded-lg transition-colors ${
          active === null ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-zinc-500 hover:bg-zinc-100'
        }`}
      >
        All
      </button>
      {ids.map((id) => (
        <button
          key={id}
          onClick={() => { activeConversationFilter.value = id }}
          class={`text-left text-sm px-2 py-1 rounded-lg truncate transition-colors ${
            active === id ? 'bg-indigo-50 text-indigo-700 font-medium' : 'text-zinc-500 hover:bg-zinc-100'
          }`}
          title={id}
        >
          {labels.get(id) || id.slice(0, 12)}
        </button>
      ))}
      {ids.length === 0 && (
        <span class="text-xs text-zinc-400 px-2">No events yet</span>
      )}
    </div>
  )
}
