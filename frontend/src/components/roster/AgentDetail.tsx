import type { Agent } from '../../types/index.ts'
import { Avatar } from '../shared/Avatar.tsx'

interface AgentDetailProps {
  agent: Agent
  onClose: () => void
}

export function AgentDetail({ agent, onClose }: AgentDetailProps) {
  return (
    <div
      class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div class="glass-strong rounded-2xl glow-soft max-w-md w-full mx-4 overflow-hidden">
        <div class="h-20 relative bg-gradient-to-r from-accent/30 to-purple-600/30">
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
          <h2 class="text-xl font-bold text-white">{agent.name}</h2>
          <p class="text-accent font-medium">{agent.role}</p>
          <div class="mt-4 space-y-3">
            <div>
              <h4 class="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
                About
              </h4>
              <p class="text-sm text-white/70">{agent.bio}</p>
            </div>
            <div>
              <h4 class="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
                Personality
              </h4>
              <p class="text-sm text-white/70">{agent.personality}</p>
            </div>
            {agent.tools && agent.tools.length > 0 && (
              <div>
                <h4 class="text-xs font-semibold text-white/40 uppercase tracking-wider mb-1">
                  Skills
                </h4>
                <div class="flex flex-wrap gap-1">
                  {agent.tools.map((tool) => (
                    <span
                      key={tool}
                      class="text-xs px-2 py-1 rounded-full bg-white/5 border border-white/10 text-white/40"
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
