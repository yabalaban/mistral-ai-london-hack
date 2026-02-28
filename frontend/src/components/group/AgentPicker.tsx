import { useState } from 'preact/hooks'
import { agents } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { Button } from '../shared/Button.tsx'
import type { Agent } from '../../types/index.ts'

interface AgentPickerProps {
  onSelect: (agentIds: string[]) => void
  onClose: () => void
  excludeIds?: string[]
}

export function AgentPicker({ onSelect, onClose, excludeIds = [] }: AgentPickerProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const available = agents.value.filter((a) => !excludeIds.includes(a.id))

  const toggle = (agent: Agent) => {
    const next = new Set(selected)
    if (next.has(agent.id)) {
      next.delete(agent.id)
    } else {
      next.add(agent.id)
    }
    setSelected(next)
  }

  return (
    <div
      class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div class="glass-strong rounded-2xl glow-soft max-w-sm w-full mx-4 p-4">
        <h3 class="text-lg font-semibold text-white mb-3">Add Agents</h3>
        <div class="space-y-1 max-h-64 overflow-y-auto">
          {available.map((agent) => (
            <button
              key={agent.id}
              onClick={() => toggle(agent)}
              class={`w-full flex items-center gap-3 px-3 py-2 rounded-xl transition-colors ${
                selected.has(agent.id)
                  ? 'bg-accent/15 border border-accent/20 text-white'
                  : 'hover:bg-white/10 text-white/70'
              }`}
            >
              <Avatar name={agent.name} src={agent.avatar} size="sm" />
              <div class="text-left min-w-0">
                <div class="text-sm font-medium truncate">{agent.name}</div>
                <div class="text-xs text-white/40 truncate">{agent.role}</div>
              </div>
              {selected.has(agent.id) && (
                <svg class="w-5 h-5 ml-auto text-accent flex-shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path
                    fill-rule="evenodd"
                    d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                    clip-rule="evenodd"
                  />
                </svg>
              )}
            </button>
          ))}
        </div>
        <div class="flex gap-2 mt-4">
          <Button variant="secondary" onClick={onClose} class="flex-1">
            Cancel
          </Button>
          <Button
            onClick={() => onSelect([...selected])}
            disabled={selected.size === 0}
            class="flex-1"
          >
            Add ({selected.size})
          </Button>
        </div>
      </div>
    </div>
  )
}
