import type { Agent } from '../../types/index.ts'
import { Avatar } from '../shared/Avatar.tsx'

interface AgentDetailProps {
  agent: Agent
  onClose: () => void
}

export function AgentDetail({ agent, onClose }: AgentDetailProps) {
  return (
    <div
      class="fixed inset-0 bg-black/60 flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div class="bg-dc-secondary rounded-lg max-w-md w-full mx-4 overflow-hidden">
        <div class="bg-dc-blurple h-20 relative">
          <button
            onClick={onClose}
            class="absolute top-2 right-2 text-white/80 hover:text-white text-xl leading-none p-1"
          >
            &times;
          </button>
        </div>
        <div class="px-6 pb-6">
          <div class="-mt-10 mb-4">
            <Avatar name={agent.name} src={agent.avatar} size="xl" />
          </div>
          <h2 class="text-xl font-bold text-dc-text">{agent.name}</h2>
          <p class="text-dc-blurple font-medium">{agent.role}</p>
          <div class="mt-4 space-y-3">
            <div>
              <h4 class="text-xs font-semibold text-dc-text-muted uppercase tracking-wider mb-1">
                About
              </h4>
              <p class="text-sm text-dc-text-secondary">{agent.bio}</p>
            </div>
            <div>
              <h4 class="text-xs font-semibold text-dc-text-muted uppercase tracking-wider mb-1">
                Personality
              </h4>
              <p class="text-sm text-dc-text-secondary">{agent.personality}</p>
            </div>
            {agent.tools && agent.tools.length > 0 && (
              <div>
                <h4 class="text-xs font-semibold text-dc-text-muted uppercase tracking-wider mb-1">
                  Skills
                </h4>
                <div class="flex flex-wrap gap-1">
                  {agent.tools.map((tool) => (
                    <span
                      key={tool}
                      class="text-xs px-2 py-1 rounded-full bg-dc-primary text-dc-text-muted"
                    >
                      {tool}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
