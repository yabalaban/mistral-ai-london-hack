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

  // Circular layout
  const total = agents.length + 1 // +1 for user
  const radius = Math.max(80, total * 30)

  return (
    <div class="flex-1 flex items-center justify-center">
      <div class="relative" style={{ width: `${radius * 2 + 100}px`, height: `${radius * 2 + 100}px` }}>
        {/* User at top */}
        <div
          class="absolute"
          style={{
            left: '50%',
            top: '50%',
            transform: `translate(-50%, -50%) translate(0px, ${-radius}px)`,
          }}
        >
          <ParticipantAvatar
            agent={{ id: 'user', name: 'You', role: '', bio: '', avatar: '', personality: '' }}
            isSpeaking={speaker === 'user'}
            isUser
          />
        </div>
        {/* Agents around the ring */}
        {agents.map((agent, i) => {
          if (!agent) return null
          const angle = ((i + 1) / total) * Math.PI * 2 - Math.PI / 2
          const x = Math.cos(angle) * radius
          const y = Math.sin(angle) * radius

          return (
            <div
              key={agent.id}
              class="absolute"
              style={{
                left: '50%',
                top: '50%',
                transform: `translate(-50%, -50%) translate(${x}px, ${y}px)`,
              }}
            >
              <ParticipantAvatar agent={agent} isSpeaking={speaker === agent.id} />
            </div>
          )
        })}
      </div>
    </div>
  )
}
