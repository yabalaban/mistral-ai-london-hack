import { useState, useEffect, useRef } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { agentMap } from '../../state/agents.ts'
import { messageMap, revealingIds, onRevealComplete } from '../../state/conversations.ts'
import { Avatar } from '../shared/Avatar.tsx'
import { formatTime } from '../../utils/format.ts'
import { Markdown } from './Markdown.tsx'

interface MessageBubbleProps {
  message: Message
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'
  const agent = message.agent_id ? agentMap.value.get(message.agent_id) : null

  // Check once on mount whether this message should play reveal animation.
  // Set.delete returns true if the element was present (consumes the flag).
  const shouldReveal = useRef(
    message.role === 'assistant' && revealingIds.has(message.id)
  )
  const len = message.content.length
  const totalMs = shouldReveal.current
    ? Math.min(Math.max(len * 12, 400), 2000)
    : 0
  const [revealed, setRevealed] = useState(shouldReveal.current ? 0 : len)
  const done = revealed >= len

  useEffect(() => {
    if (!shouldReveal.current) return
    const start = performance.now()
    let raf: number

    const tick = (now: number) => {
      const p = Math.min((now - start) / totalMs, 1)
      setRevealed(Math.ceil(p * len))
      if (p < 1) {
        raf = requestAnimationFrame(tick)
      } else {
        onRevealComplete(message.id)
      }
    }

    raf = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(raf)
      // If unmounted before finishing, still signal completion
      if (!done) onRevealComplete(message.id)
    }
  }, [])

  if (isSystem) {
    return (
      <div class="flex justify-center px-4 py-1">
        <div class="max-w-[85%] text-center">
          <div class="inline-block rounded-lg px-3 py-1.5 text-xs bg-zinc-100 border border-zinc-200 text-zinc-400 italic">
            <span class="whitespace-pre-wrap">{message.content}</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div class={`flex gap-3 px-4 py-1 hover:bg-zinc-50 ${isUser ? 'flex-row-reverse' : ''}`}>
      {!isUser && (
        <div class="mt-1">
          <Avatar name={agent?.name ?? '?'} src={agent?.avatar} size="md" />
        </div>
      )}
      <div class={`max-w-[70%] ${isUser ? 'items-end' : 'items-start'}`}>
        {message.reply_to_id && (() => {
          const replyMsg = messageMap.value.get(message.reply_to_id!)
          if (!replyMsg) return null
          const replyAgent = replyMsg.agent_id ? agentMap.value.get(replyMsg.agent_id) : null
          const replyName = replyMsg.role === 'user' ? 'You' : replyAgent?.name ?? 'Agent'
          const replyText = replyMsg.content.length > 60 ? replyMsg.content.slice(0, 60) + '...' : replyMsg.content
          return (
            <div class="flex items-center gap-1.5 mb-1 ml-1 text-xs text-zinc-400">
              <div class="w-0.5 h-4 bg-indigo-400 rounded-full shrink-0" />
              <span class="font-medium text-zinc-500">{replyName}:</span>
              <span class="truncate">{replyText}</span>
            </div>
          )
        })()}
        <div class={`flex items-baseline gap-2 mb-0.5 ${isUser ? 'justify-end' : ''}`}>
          <span class="text-sm font-medium text-zinc-900">
            {isUser ? 'You' : agent?.name ?? 'Agent'}
          </span>
          {!isUser && agent?.role && (
            <span class="text-xs text-zinc-400">{agent.role}</span>
          )}
          <span class="text-xs text-zinc-400">{formatTime(message.timestamp)}</span>
        </div>
        <div
          class={`rounded-2xl px-3 py-2 text-sm ${
            isUser
              ? 'bg-accent text-white'
              : 'glass text-zinc-700'
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
          {done ? (
            <Markdown content={message.content} />
          ) : (
            <span class="whitespace-pre-wrap">
              {message.content.slice(0, revealed)}
              <span class="inline-block w-0.5 h-3.5 bg-accent animate-pulse ml-px align-text-bottom" />
            </span>
          )}
        </div>
      </div>
    </div>
  )
}
