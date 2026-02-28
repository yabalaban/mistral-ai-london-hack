import { useRef, useEffect } from 'preact/hooks'
import { oracleState } from '../../state/oracle.ts'
import type { OracleRound, AgentVerdict } from '../../state/oracle.ts'
import { agentMap } from '../../state/agents.ts'
import { Avatar } from '../shared/Avatar.tsx'

function VerdictPill({ v }: { v: AgentVerdict }) {
  const agent = agentMap.value.get(v.agentId)
  const colors = {
    responded: 'bg-emerald-100 text-emerald-700',
    passed: 'bg-zinc-100 text-zinc-500',
    skipped: 'bg-amber-100 text-amber-600',
  }
  return (
    <span class={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[11px] font-medium ${colors[v.verdict]}`}>
      {agent && <Avatar src={agent.avatar} name={agent.name} size="xs" />}
      {v.agentName}
    </span>
  )
}

function ModeBadge({ mode }: { mode: string }) {
  const styles: Record<string, string> = {
    parallel: 'bg-blue-100 text-blue-700',
    sequential: 'bg-violet-100 text-violet-700',
    directed: 'bg-cyan-100 text-cyan-700',
  }
  return (
    <span class={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide ${styles[mode] ?? 'bg-zinc-100 text-zinc-600'}`}>
      {mode}
    </span>
  )
}

function RoundCard({ round, directed, directedAgent }: { round: OracleRound; directed: boolean; directedAgent: string | null }) {
  const directedName = directedAgent ? agentMap.value.get(directedAgent)?.name : null

  return (
    <div class="rounded-lg border border-zinc-200 bg-white/60 p-2.5 space-y-2">
      <div class="flex items-center gap-2">
        <span class="text-xs font-semibold text-zinc-700">
          {directed && directedName
            ? `Directed → ${directedName}`
            : `Round ${round.round}`}
        </span>
        <ModeBadge mode={round.mode} />
      </div>

      {round.reasoning && (
        <p class="text-xs text-zinc-400 italic">{round.reasoning}</p>
      )}

      {round.speakers.length > 0 && (
        <div class="flex flex-wrap gap-1">
          {round.speakers.map((s) => (
            <span key={s.agent_id} class="text-[11px] text-zinc-500">
              {s.agent_name}{s.hint && s.hint !== round.mode ? ` (${s.hint})` : ''}
            </span>
          ))}
        </div>
      )}

      {round.verdicts.length > 0 && (
        <div class="flex flex-wrap gap-1">
          {round.verdicts.map((v) => (
            <VerdictPill key={v.agentId} v={v} />
          ))}
        </div>
      )}

      {round.grader && (
        <div class={`text-[11px] font-medium ${round.grader.done ? 'text-emerald-600' : 'text-amber-600'}`}>
          {round.grader.done ? 'Done' : 'Continuing...'}{' '}
          <span class="font-normal text-zinc-400">— {round.grader.reasoning}</span>
        </div>
      )}
    </div>
  )
}

export function GroupMessages() {
  const bottomRef = useRef<HTMLDivElement>(null)
  const state = oracleState.value

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [state.rounds.length, state.summary])

  return (
    <div class="w-80 glass-strong border-l border-zinc-200 flex flex-col">
      <div class="px-4 py-2 border-b border-zinc-200 flex items-center gap-2">
        <h3 class="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
          Oracle
        </h3>
        {state.active && (
          <span class="w-2 h-2 rounded-full bg-cyan-400 animate-pulse" />
        )}
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        {state.topic && (
          <div class="px-2 py-1 rounded bg-zinc-100 text-xs font-medium text-zinc-600">
            {state.topic}
          </div>
        )}

        {state.rounds.length === 0 && !state.summary && (
          <p class="text-xs text-zinc-400 italic">Waiting for oracle activity...</p>
        )}

        {state.rounds.map((round) => (
          <RoundCard
            key={round.round}
            round={round}
            directed={state.directed}
            directedAgent={state.directedAgent}
          />
        ))}

        {state.summary && (
          <div class="rounded-lg border border-zinc-200 bg-emerald-50/50 p-2.5">
            <div class="text-[11px] font-semibold text-emerald-700 uppercase tracking-wide mb-1">Summary</div>
            <p class="text-xs text-zinc-600 whitespace-pre-line">{state.summary}</p>
          </div>
        )}

        <div ref={bottomRef} />
      </div>
    </div>
  )
}
