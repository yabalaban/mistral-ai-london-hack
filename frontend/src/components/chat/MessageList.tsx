import { useRef, useEffect } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { MessageBubble } from './MessageBubble.tsx'
import { streamingAgents } from '../../state/conversations.ts'
import { agentMap } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'

interface MessageListProps {
  messages: Message[]
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const streams = streamingAgents.value

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streams.size])

  // Build typing names from streaming agents
  const typingNames = [...streams.values()]
    .map((s) => agentMap.value.get(s.agentId)?.name)
    .filter(Boolean)

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
      {typingNames.length > 0 && (
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
              {typingNames.join(', ')} {typingNames.length === 1 ? 'is' : 'are'} typing
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
