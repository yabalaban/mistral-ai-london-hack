import type { Agent } from '../../types/index.ts'
import { Avatar } from '../shared/Avatar.tsx'

interface AgentProfilePanelProps {
  agent: Agent
}

export function AgentProfilePanel({ agent }: AgentProfilePanelProps) {
  return (
    <div class="w-72 glass-strong border-l border-white/10 flex flex-col overflow-y-auto">
      <div class="h-16 bg-gradient-to-r from-accent/20 to-purple-600/20 flex-shrink-0" />
      <div class="px-4 pb-4">
        <div class="-mt-8 mb-3">
          <Avatar name={agent.name} src={agent.avatar} size="xl" />
        </div>
        <h3 class="text-lg font-bold text-white">{agent.name}</h3>
        <p class="text-sm text-accent font-medium">{agent.role}</p>

        <div class="mt-4 space-y-3">
          <div>
            <h4 class="text-[10px] font-semibold text-white/40 uppercase tracking-wider mb-1">About</h4>
            <p class="text-sm text-white/70">{agent.bio}</p>
          </div>
          {agent.personality && (
            <div>
              <h4 class="text-[10px] font-semibold text-white/40 uppercase tracking-wider mb-1">Personality</h4>
              <p class="text-sm text-white/70">{agent.personality}</p>
            </div>
          )}
          {agent.tools && agent.tools.length > 0 && (
            <div>
              <h4 class="text-[10px] font-semibold text-white/40 uppercase tracking-wider mb-1">Skills</h4>
              <div class="flex flex-wrap gap-1">
                {agent.tools.map((tool) => (
                  <span
                    key={tool}
                    class="text-xs px-2 py-0.5 rounded-full bg-white/5 border border-white/10 text-white/40"
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
  )
}
