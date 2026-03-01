import type { SystemEvent } from '../../state/activity.ts'
import { agentMap } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'

const EVENT_CONFIG: Record<string, { icon: string; color: string; label: string }> = {
  user_message:  { icon: '💬', color: 'border-blue-400',    label: 'User Message' },
  oracle_start:  { icon: '🔮', color: 'border-purple-400',  label: 'Oracle Start' },
  oracle:        { icon: '🧠', color: 'border-purple-300',  label: 'Oracle Reasoning' },
  oracle_end:    { icon: '🔮', color: 'border-purple-200',  label: 'Oracle End' },
  turn_change:   { icon: '🎯', color: 'border-indigo-400',  label: 'Turn Change' },
  message:       { icon: '💬', color: 'border-emerald-400', label: 'Agent Message' },
  grader:        { icon: '✅', color: 'border-amber-400',   label: 'Grader' },
  agent_verdict: { icon: '⚖️', color: 'border-orange-400',  label: 'Verdict' },
  topic_set:     { icon: '📌', color: 'border-cyan-400',    label: 'Topic Set' },
  summary:       { icon: '📋', color: 'border-teal-400',    label: 'Summary' },
  tool_call:     { icon: '🔧', color: 'border-rose-400',    label: 'Tool Call' },
  tool_result:   { icon: '📦', color: 'border-rose-300',    label: 'Tool Result' },
}

const DEFAULT_CONFIG = { icon: '📡', color: 'border-zinc-300', label: 'Event' }

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '…' : s
}

interface EventCardProps {
  event: SystemEvent
}

export function EventCard({ event }: EventCardProps) {
  const cfg = EVENT_CONFIG[event.type] || DEFAULT_CONFIG
  const agentId = (event.data.agent_id as string) || ''
  const agent = agentId ? agentMap.value.get(agentId) : null

  return (
    <div class={`glass rounded-xl p-3 border-l-4 ${cfg.color} flex gap-3 items-start`}>
      {/* Icon */}
      <div class="text-lg flex-shrink-0 mt-0.5">{cfg.icon}</div>

      {/* Body */}
      <div class="flex-1 min-w-0">
        {/* Header row */}
        <div class="flex items-center gap-2 flex-wrap">
          <span class="text-xs font-semibold text-zinc-700">{cfg.label}</span>
          <span class={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
            event.source === 'discord'
              ? 'bg-indigo-100 text-indigo-700'
              : 'bg-emerald-100 text-emerald-700'
          }`}>
            {event.source === 'discord' ? 'Discord' : 'Web'}
          </span>
          <span class="text-[10px] text-zinc-400">{event.source_label}</span>
          <span class="text-[10px] text-zinc-400 ml-auto flex-shrink-0">{formatTime(event.timestamp)}</span>
        </div>

        {/* Agent avatar + name */}
        {agent && (
          <div class="flex items-center gap-1.5 mt-1">
            <Avatar name={agent.name} src={agent.avatar} size="xs" />
            <span class="text-xs font-medium text-zinc-600">{agent.name}</span>
          </div>
        )}

        {/* Content body */}
        <EventBody type={event.type} data={event.data} />
      </div>
    </div>
  )
}

function EventBody({ type, data }: { type: string; data: Record<string, unknown> }) {
  switch (type) {
    case 'user_message':
      return <p class="text-sm text-zinc-600 mt-1">{truncate(String(data.content || ''), 200)}</p>

    case 'oracle_start':
      return (
        <div class="text-xs text-zinc-500 mt-1">
          {data.directed ? `Directed → ${data.directed_agent}` : 'Open round'}
          {data.goal ? <span class="ml-2 text-zinc-400">Goal: {truncate(String(data.goal), 80)}</span> : null}
        </div>
      )

    case 'oracle':
      return (
        <div class="mt-1">
          {data.reasoning && (
            <pre class="text-xs text-zinc-500 bg-zinc-50 rounded p-2 whitespace-pre-wrap overflow-hidden max-h-24">{truncate(String(data.reasoning), 300)}</pre>
          )}
          {Array.isArray(data.speakers) && data.speakers.length > 0 && (
            <div class="flex gap-1 mt-1 flex-wrap">
              {(data.speakers as Array<Record<string, unknown>>).map((s, i) => (
                <span key={i} class={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  s.should_respond ? 'bg-emerald-100 text-emerald-700' : 'bg-zinc-100 text-zinc-400'
                }`}>
                  {String(s.agent_name || s.agent_id)}
                </span>
              ))}
            </div>
          )}
        </div>
      )

    case 'turn_change':
      return <p class="text-xs text-zinc-500 mt-1">Next speaker: <span class="font-medium">{String(data.agent_id || '')}</span></p>

    case 'message':
      return <p class="text-sm text-zinc-600 mt-1 line-clamp-3">{truncate(String(data.content || ''), 300)}</p>

    case 'grader':
      return (
        <div class="text-xs text-zinc-500 mt-1">
          <span class={`font-medium ${data.done ? 'text-emerald-600' : 'text-amber-600'}`}>
            {data.done ? 'Done' : 'Continue'}
          </span>
          {data.reasoning && <span class="ml-2">{truncate(String(data.reasoning), 150)}</span>}
        </div>
      )

    case 'agent_verdict':
      return (
        <p class="text-xs text-zinc-500 mt-1">
          {String(data.agent_name || data.agent_id)}: <span class="font-medium">{String(data.verdict || '')}</span>
        </p>
      )

    case 'topic_set':
      return <p class="text-xs text-zinc-500 mt-1 font-medium">{String(data.topic || '')}</p>

    case 'summary':
      return <p class="text-sm text-zinc-500 mt-1 line-clamp-3">{truncate(String(data.content || ''), 300)}</p>

    case 'tool_call':
      return <p class="text-xs text-zinc-500 mt-1 font-mono">{String(data.tool_name || '')}({truncate(JSON.stringify(data.args || {}), 100)})</p>

    default:
      if (Object.keys(data).length > 0) {
        return <pre class="text-[10px] text-zinc-400 mt-1 whitespace-pre-wrap overflow-hidden max-h-16">{truncate(JSON.stringify(data, null, 1), 200)}</pre>
      }
      return null
  }
}
