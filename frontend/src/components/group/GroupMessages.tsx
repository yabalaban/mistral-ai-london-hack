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
    <div class="w-80 bg-dc-secondary border-l border-dc-primary flex flex-col">
      <div class="px-4 py-2 border-b border-dc-primary">
        <h3 class="text-sm font-semibold text-dc-text-muted uppercase tracking-wider">
          Transcript
        </h3>
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.map((msg) => {
          const agent = msg.agent_id ? agentMap.value.get(msg.agent_id) : null
          return (
            <div key={msg.id} class="text-sm">
              <span class="font-medium text-dc-text">
                {msg.role === 'user' ? 'You' : agent?.name ?? 'Agent'}
              </span>
              <span class="text-dc-text-muted text-xs ml-1">{formatTime(msg.timestamp)}</span>
              <p class="text-dc-text-secondary mt-0.5">{msg.content}</p>
            </div>
          )
        })}
        {streaming && agentId && (
          <div class="text-sm">
            <span class="font-medium text-dc-text">
              {agentMap.value.get(agentId)?.name ?? 'Agent'}
            </span>
            <p class="text-dc-text-secondary mt-0.5">
              {streaming}
              <span class="inline-block w-1.5 h-3 bg-dc-text-muted animate-pulse ml-0.5" />
            </p>
          </div>
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
