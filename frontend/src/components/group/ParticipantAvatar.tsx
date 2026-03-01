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
      <div class="relative">
        <Avatar
          name={isUser ? 'You' : agent.name}
          src={isUser ? undefined : agent.avatar}
          size="xl"
          speaking={isSpeaking}
        />
      </div>
      <span class={`text-xs font-medium ${isSpeaking ? 'text-accent' : 'text-zinc-500'}`}>
        {isUser ? 'You' : agent.name}
      </span>
    </div>
  )
}
