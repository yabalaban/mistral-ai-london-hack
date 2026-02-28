import { Avatar } from '../shared/Avatar.tsx'
import type { Agent } from '../../types/index.ts'

interface ParticipantAvatarProps {
  agent: Agent
  isSpeaking: boolean
  isUser?: boolean
}

export function ParticipantAvatar({ agent, isSpeaking, isUser = false }: ParticipantAvatarProps) {
  return (
    <div class="flex flex-col items-center gap-1">
      <div class={`relative ${isSpeaking ? 'scale-110' : ''} transition-transform`}>
        <Avatar
          name={isUser ? 'You' : agent.name}
          src={isUser ? undefined : agent.avatar}
          size="xl"
          speaking={isSpeaking}
        />
        {isSpeaking && (
          <div class="absolute -bottom-1 left-1/2 -translate-x-1/2">
            <div class="flex gap-0.5">
              <div class="w-1 h-3 bg-dc-green rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
              <div class="w-1 h-4 bg-dc-green rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
              <div class="w-1 h-3 bg-dc-green rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
          </div>
        )}
      </div>
      <span class={`text-xs font-medium ${isSpeaking ? 'text-dc-green' : 'text-dc-text-secondary'}`}>
        {isUser ? 'You' : agent.name}
      </span>
    </div>
  )
}
