import type { Message } from '../../types/index.ts'
import { agentMap } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { formatTime } from '../../utils/format.ts'
import { StreamingText } from './StreamingText.tsx'

interface MessageBubbleProps {
  message: Message
  isStreaming?: boolean
}

export function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const agent = message.agent_id ? agentMap.value.get(message.agent_id) : null

  // System messages (oracle reasoning) — centered, muted, compact
  if (isSystem) {
    return (
      <div class="flex justify-center px-4 py-1">
        <div class="max-w-[85%] text-center">
          <div class="inline-block rounded-lg px-3 py-1.5 text-xs bg-white/[.04] border border-white/[.06] text-white/40 italic">
            <span class="whitespace-pre-wrap">{message.content}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div class={`flex gap-3 px-4 py-1 hover:bg-white/[.02] ${isUser ? 'flex-row-reverse' : ''}`}>
      {!isUser && (
        <div class="mt-1">
          <Avatar name={agent?.name ?? '?'} src={agent?.avatar} size="md" />
        </div>
      )}
      <div class={`max-w-[70%] ${isUser ? 'items-end' : 'items-start'}`}>
        <div class={`flex items-baseline gap-2 mb-0.5 ${isUser ? 'justify-end' : ''}`}>
          <span class="text-sm font-medium text-white">
            {isUser ? 'You' : agent?.name ?? 'Agent'}
          </span>
          <span class="text-xs text-white/40">{formatTime(message.timestamp)}</span>
        </div>
        <div
          class={`rounded-2xl px-3 py-2 text-sm ${
            isUser
              ? 'bg-accent/20 border border-accent/20 backdrop-blur-sm text-white'
              : 'glass text-white/90'
          }`}
        >
          {message.attachments?.map((att, i) => (
            <img
              key={i}
              src={att.url}
              alt={att.name ?? 'attachment'}
              class="max-w-xs rounded mb-2"
            />
          ))}
          {isStreaming ? (
            <StreamingText text={message.content} />
          ) : (
            <span class="whitespace-pre-wrap">{message.content}</span>
          )}
        </div>
      </div>
    </div>
  )
}
