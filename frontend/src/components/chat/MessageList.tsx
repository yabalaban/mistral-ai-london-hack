import { useRef, useEffect } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { MessageBubble } from './MessageBubble.tsx'
import { streamingMessage, streamingAgentId } from '../../state/conversations.ts'

interface MessageListProps {
  messages: Message[]
}

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const streaming = streamingMessage.value
  const agentId = streamingAgentId.value

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length, streaming])

  return (
    <div class="flex-1 overflow-y-auto py-4">
      {messages.length === 0 && !streaming && (
        <div class="flex items-center justify-center h-full text-dc-text-muted">
          Start a conversation...
        </div>
      )}
      {messages.map((msg) => (
        <MessageBubble key={msg.id} message={msg} />
      ))}
      {streaming && agentId && (
        <MessageBubble
          message={{
            id: 'streaming',
            role: 'assistant',
            agent_id: agentId,
            content: streaming,
            timestamp: new Date().toISOString(),
          }}
          isStreaming
        />
      )}
      <div ref={bottomRef} />
    </div>
  )
}
