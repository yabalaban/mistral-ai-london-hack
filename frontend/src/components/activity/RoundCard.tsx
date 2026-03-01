import { useState } from 'preact/hooks'
import type { EventRound } from '../../state/activity.ts'
import type { SystemEvent } from '../../state/activity.ts'
import { agentMap } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'

function formatTime(ts: number): string {
  const d = new Date(ts * 1000)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function truncate(s: string, n: number): string {
  return s.length > n ? s.slice(0, n) + '...' : s
}

/** Extract a quick summary from a round's events. */
function roundSummary(round: EventRound) {
  const agents = new Set<string>()
  let graderDone: boolean | null = null
  let topic = ''
  let hasSummary = false

  for (const e of round.events) {
    if (e.type === 'message' && e.data.agent_id) agents.add(String(e.data.agent_id))
    if (e.type === 'turn_change' && e.data.agent_id) agents.add(String(e.data.agent_id))
    if (e.type === 'grader') graderDone = e.data.done as boolean
    if (e.type === 'topic_set' && e.data.topic) topic = String(e.data.topic)
    if (e.type === 'summary') hasSummary = true
  }

  return { agents: Array.from(agents), graderDone, topic, hasSummary }
}

const STEP_ICON: Record<string, string> = {
  user_message: '💬',
  oracle_start: '🔮',
  oracle: '🧠',
  oracle_end: '🔮',
  turn_change: '🎯',
  message: '💬',
  grader: '✅',
  agent_verdict: '⚖️',
  topic_set: '📌',
  summary: '📋',
  tool_call: '🔧',
  tool_result: '📦',
}

const STEP_LABEL: Record<string, string> = {
  user_message: 'User',
  oracle_start: 'Oracle Start',
  oracle: 'Reasoning',
  oracle_end: 'Oracle End',
  turn_change: 'Turn',
  message: 'Response',
  grader: 'Grader',
  agent_verdict: 'Verdict',
  topic_set: 'Topic',
  summary: 'Summary',
  tool_call: 'Tool Call',
  tool_result: 'Tool Result',
}

interface RoundCardProps {
  round: EventRound
}

export function RoundCard({ round }: RoundCardProps) {
  const [expanded, setExpanded] = useState(false)
  const { agents: agentIds, graderDone, topic } = roundSummary(round)
  const agentProfiles = agentIds.map((id) => agentMap.value.get(id)).filter(Boolean)
  const eventCount = round.events.length

  return (
    <div class="glass rounded-xl overflow-hidden">
      {/* Header — always visible, clickable */}
      <button
        onClick={() => setExpanded(!expanded)}
        class="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-zinc-50/50 transition-colors"
      >
        {/* Source badge */}
        <div class={`mt-0.5 text-[10px] px-1.5 py-0.5 rounded-full font-medium flex-shrink-0 ${
          round.source === 'discord-voice'
            ? 'bg-violet-100 text-violet-700'
            : round.source === 'discord'
              ? 'bg-indigo-100 text-indigo-700'
              : 'bg-emerald-100 text-emerald-700'
        }`}>
          {round.source === 'discord-voice' ? '🎙 Voice' : round.source === 'discord' ? 'Discord' : 'Web'}
        </div>

        {/* Content */}
        <div class="flex-1 min-w-0">
          {/* Trigger message */}
          {round.trigger ? (
            <p class="text-sm text-zinc-800 font-medium">{truncate(round.trigger, 120)}</p>
          ) : (
            <p class="text-sm text-zinc-400 italic">System event</p>
          )}

          {/* Agents + status pills */}
          <div class="flex items-center gap-2 mt-1.5 flex-wrap">
            {/* Agent avatars */}
            {agentProfiles.length > 0 && (
              <div class="flex -space-x-1.5">
                {agentProfiles.map((a) => (
                  <Avatar key={a!.id} name={a!.name} src={a!.avatar} size="xs" />
                ))}
              </div>
            )}
            {agentProfiles.length > 0 && (
              <span class="text-xs text-zinc-500">
                {agentProfiles.map((a) => a!.name).join(', ')}
              </span>
            )}

            {/* Grader pill */}
            {graderDone !== null && (
              <span class={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                graderDone ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'
              }`}>
                {graderDone ? 'Done' : 'Continue'}
              </span>
            )}

            {/* Topic */}
            {topic && (
              <span class="text-[10px] px-1.5 py-0.5 rounded-full bg-cyan-50 text-cyan-700">
                {truncate(topic, 30)}
              </span>
            )}
          </div>
        </div>

        {/* Right side: time + count + chevron */}
        <div class="flex items-center gap-2 flex-shrink-0 mt-0.5">
          <span class="text-[10px] text-zinc-400">{formatTime(round.timestamp)}</span>
          <span class="text-[10px] text-zinc-300 bg-zinc-100 px-1.5 py-0.5 rounded-full">{eventCount}</span>
          <svg
            class={`w-4 h-4 text-zinc-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded: timeline of sub-events */}
      {expanded && (
        <div class="border-t border-zinc-100 px-4 py-2 space-y-0">
          {round.events.map((e, i) => (
            <StepRow key={i} event={e} isLast={i === round.events.length - 1} />
          ))}
        </div>
      )}
    </div>
  )
}

function StepRow({ event, isLast }: { event: SystemEvent; isLast: boolean }) {
  const icon = STEP_ICON[event.type] || '📡'
  const label = STEP_LABEL[event.type] || event.type
  const agentId = (event.data.agent_id as string) || ''
  const agent = agentId ? agentMap.value.get(agentId) : null

  return (
    <div class="flex gap-3 relative">
      {/* Timeline line */}
      <div class="flex flex-col items-center w-6 flex-shrink-0">
        <span class="text-xs leading-6">{icon}</span>
        {!isLast && <div class="w-px flex-1 bg-zinc-200" />}
      </div>

      {/* Content */}
      <div class="flex-1 min-w-0 pb-2">
        <div class="flex items-center gap-2">
          <span class="text-[11px] font-medium text-zinc-500">{label}</span>
          {agent && (
            <span class="text-[10px] text-zinc-400">{agent.name}</span>
          )}
          <span class="text-[10px] text-zinc-300 ml-auto">{formatTime(event.timestamp)}</span>
        </div>
        <StepDetail type={event.type} data={event.data} />
      </div>
    </div>
  )
}

function StepDetail({ type, data }: { type: string; data: Record<string, unknown> }) {
  switch (type) {
    case 'user_message':
      return <p class="text-xs text-zinc-500 mt-0.5">{truncate(String(data.content || ''), 150)}</p>

    case 'oracle_start':
      return (
        <p class="text-[11px] text-zinc-400 mt-0.5">
          {data.directed ? `Directed → ${data.directed_agent}` : 'Open round'}
          {data.goal ? ` · Goal: ${truncate(String(data.goal), 60)}` : ''}
        </p>
      )

    case 'oracle':
      return (
        <div class="mt-0.5">
          {data.reasoning && (
            <pre class="text-[11px] text-zinc-400 bg-zinc-50 rounded px-2 py-1 whitespace-pre-wrap overflow-hidden max-h-16">{truncate(String(data.reasoning), 200)}</pre>
          )}
          {Array.isArray(data.speakers) && data.speakers.length > 0 && (
            <div class="flex gap-1 mt-1 flex-wrap">
              {(data.speakers as Array<Record<string, unknown>>).map((s, i) => (
                <span key={i} class={`text-[10px] px-1 py-0.5 rounded ${
                  s.should_respond ? 'bg-emerald-50 text-emerald-600' : 'bg-zinc-50 text-zinc-400'
                }`}>
                  {String(s.agent_name || s.agent_id)}
                </span>
              ))}
            </div>
          )}
        </div>
      )

    case 'message':
      return <p class="text-xs text-zinc-500 mt-0.5 line-clamp-2">{truncate(String(data.content || ''), 200)}</p>

    case 'grader':
      return (
        <p class="text-[11px] mt-0.5">
          <span class={data.done ? 'text-emerald-600' : 'text-amber-600'}>{data.done ? 'Done' : 'Continue'}</span>
          {data.reasoning && <span class="text-zinc-400 ml-1">{truncate(String(data.reasoning), 100)}</span>}
        </p>
      )

    case 'agent_verdict':
      return <p class="text-[11px] text-zinc-400 mt-0.5">{String(data.agent_name || data.agent_id)}: {String(data.verdict || '')}</p>

    case 'turn_change':
      return <p class="text-[11px] text-zinc-400 mt-0.5">→ {String(data.agent_id || '')}</p>

    case 'topic_set':
      return <p class="text-[11px] text-zinc-500 mt-0.5 font-medium">{String(data.topic || '')}</p>

    case 'summary':
      return <p class="text-xs text-zinc-400 mt-0.5 line-clamp-2">{truncate(String(data.content || ''), 200)}</p>

    case 'tool_call':
      return <p class="text-[11px] text-zinc-400 mt-0.5 font-mono">{String(data.tool_name || '')}()</p>

    default:
      return null
  }
}
