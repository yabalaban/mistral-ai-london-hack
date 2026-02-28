import { useRef, useEffect } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { agentMap } from '../../state/agents.ts'
import { streamingMessage, streamingAgentId } from '../../state/conversations.ts'
import { formatTime } from '../../utils/format.ts'

interface GroupMessagesProps {
  messages: Message[]
}

export function GroupMessages({ messages }: GroupMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const streaming = streamingMessage.value
  const agentId = streamingAgentId.value

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streaming])

  return (
    <div class="w-80 glass-strong border-l border-white/10 flex flex-col">
      <div class="px-4 py-2 border-b border-white/10">
        <h3 class="text-sm font-semibold text-white/40 uppercase tracking-wider">
          Transcript
        </h3>
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.map((msg) => {
          const agent = msg.agent_id ? agentMap.value.get(msg.agent_id) : null
          return (
            <div key={msg.id} class="text-sm">
              <span class="font-medium text-white">
                {msg.role === 'user' ? 'You' : agent?.name ?? 'Agent'}
              </span>
              <span class="text-white/40 text-xs ml-1">{formatTime(msg.timestamp)}</span>
              <p class="text-white/70 mt-0.5">{msg.content}</p>
            </div>
          )
        })}
        {streaming && agentId && (
          <div class="text-sm">
            <span class="font-medium text-white">
              {agentMap.value.get(agentId)?.name ?? 'Agent'}
            </span>
            <p class="text-white/70 mt-0.5">
              {streaming}
              <span class="inline-block w-1.5 h-3 bg-accent/60 rounded-sm animate-pulse ml-0.5" />
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
