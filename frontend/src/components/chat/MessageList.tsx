import { useRef, useEffect } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { MessageBubble } from './MessageBubble.tsx'
import { streamingAgents } from '../../state/conversations.ts'
import { agentMap } from '../../state/agents.ts'
import { agentSpeaking, partialTranscript } from '../../state/call.ts'
import { Avatar } from '../shared/Avatar.tsx'

interface MessageListProps {
  messages: Message[]
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const streams = streamingAgents.value
  const transcript = partialTranscript.value

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streams.size, transcript])

  // Build typing/speaking names from streaming agents
  const activeNames = [...streams.values()]
    .map((s) => agentMap.value.get(s.agentId)?.name)
    .filter(Boolean)

  const isSpeaking = !!agentSpeaking.value
  const verb = isSpeaking ? 'speaking' : 'typing'

  return (
    <div class="absolute inset-0 overflow-y-auto py-4">
      {messages.length === 0 && streams.size === 0 && (
        <div class="flex items-center justify-center h-full text-zinc-400">
          Start a conversation...
        </div>
      )}
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {transcript && (
        <div class="flex gap-3 px-4 py-2 items-center">
          <Avatar name="You" size="sm" />
          <div class="flex items-center gap-1.5 text-sm text-zinc-400 italic">
            <span>{transcript}</span>
            <span class="flex gap-0.5 ml-0.5">
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-1" />
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-2" />
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-3" />
            </span>
          </div>
        </div>
      )}
      {activeNames.length > 0 && (
        <div class="flex gap-3 px-4 py-2 items-center">
          <div class="flex -space-x-2">
            {[...streams.values()].map((s) => {
              const agent = agentMap.value.get(s.agentId)
              return agent ? (
                <Avatar key={s.agentId} name={agent.name} src={agent.avatar} size="sm" />
              ) : null
            })}
          </div>
          <div class="flex items-center gap-1.5 text-sm text-zinc-400">
            <span>
              {activeNames.join(', ')} {activeNames.length === 1 ? 'is' : 'are'} {verb}
            </span>
            <span class="flex gap-0.5 ml-0.5">
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-1" />
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-2" />
              <span class="w-1 h-1 rounded-full bg-zinc-400 dot-pulse-3" />
            </span>
          </div>
        </div>
      )}
      <div ref={bottomRef} />
    </div>
  )
}
