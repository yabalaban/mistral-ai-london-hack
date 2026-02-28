import { useState } from 'preact/hooks'
import { agents } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { Button } from '../shared/Button.tsx'

interface NewGroupModalProps {
  onClose: () => void
  onCreate: (agentIds: string[]) => void
}

export function NewGroupModal({ onClose, onCreate }: NewGroupModalProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    const next = new Set(selected)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelected(next)
  }

  return (
    <div
      class="fixed inset-0 bg-black/20 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div class="glass-strong rounded-2xl glow-soft max-w-sm w-full mx-4 p-4">
        <h3 class="text-lg font-semibold text-zinc-900 mb-1">New Group Chat</h3>
        <p class="text-sm text-zinc-400 mb-3">Select agents to start a shared conversation</p>
        <div class="space-y-1 max-h-64 overflow-y-auto">
          {agents.value.map((agent) => (
            <button
              key={agent.id}
              onClick={() => toggle(agent.id)}
              class={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-colors ${
                selected.has(agent.id)
                  ? 'bg-indigo-50 border border-indigo-200 text-zinc-900'
                  : 'hover:bg-zinc-50 text-zinc-600'
              }`}
            >
              <Avatar name={agent.name} src={agent.avatar} size="sm" />
              <div class="text-left min-w-0">
                <div class="text-sm font-medium truncate">{agent.name}</div>
                <div class="text-xs text-zinc-400 truncate">{agent.role}</div>
              </div>
              {selected.has(agent.id) && (
                <svg class="w-5 h-5 ml-auto text-accent flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd" />
                </svg>
              )}
            </button>
          ))}
        </div>
        <div class="flex gap-2 mt-4">
          <Button variant="secondary" onClick={onClose} class="flex-1">Cancel</Button>
          <Button onClick={() => onCreate([...selected])} disabled={selected.size < 2} class="flex-1">
            Create ({selected.size})
          </Button>
        </div>
      </div>
    </div>
  )
}
