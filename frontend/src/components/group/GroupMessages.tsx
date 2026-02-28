import { useRef, useEffect } from 'preact/hooks'
import type { Message } from '../../types/index.ts'
import { formatTime } from '../../utils/format.ts'

interface GroupMessagesProps {
  messages: Message[]
}

export function GroupMessages({ messages }: GroupMessagesProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages.length])

  return (
    <div class="w-80 glass-strong border-l border-white/10 flex flex-col">
      <div class="px-4 py-2 border-b border-white/10">
        <h3 class="text-sm font-semibold text-white/40 uppercase tracking-wider">
          Oracle
        </h3>
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        {messages.map((msg) => (
          <div key={msg.id} class="text-sm">
            <span class="text-white/40 text-xs">{formatTime(msg.timestamp)}</span>
            <p class="text-white/70 mt-0.5">{msg.content}</p>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
