import { agentMap } from '../../state/agents.ts'
import { currentSpeaker } from '../../state/call.ts'
import { ParticipantAvatar } from './ParticipantAvatar.tsx'

interface ParticipantRingProps {
  participantIds: string[]
}

export function ParticipantRing({ participantIds }: ParticipantRingProps) {
  const speaker = currentSpeaker.value
  const agents = participantIds
    .filter((id) => id !== 'user')
    .map((id) => agentMap.value.get(id))
    .filter(Boolean)

  return (
    <div class="flex items-center justify-center gap-4 py-3 px-4">
      {/* User */}
      <ParticipantAvatar
        agent={{ id: 'user', name: 'You', role: '', bio: '', avatar: '', personality: '' }}
        isSpeaking={speaker === 'user'}
        isUser
      />
      {/* Agents */}
      {agents.map((agent) => {
        if (!agent) return null
        return (
          <ParticipantAvatar
            key={agent.id}
            agent={agent}
            isSpeaking={speaker === agent.id}
          />
        )
      })}
    </div>
  )
}
