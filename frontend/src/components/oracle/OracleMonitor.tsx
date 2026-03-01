/**
 * Oracle Monitor — real-time dashboard showing oracle decision-making.
 *
 * Displays:
 * - Active/inactive status
 * - Current goal & topic
 * - Classification (directed vs parallel)
 * - Per-round: speaker selection, reasoning, hints
 * - Agent verdicts (responded/passed/interrupted)
 * - Grader results
 * - Summary
 */

import { oracleState, type OracleRound, type AgentVerdict } from '../../state/oracle.ts'
import { agentMap } from '../../state/agents.ts'

const verdictColors: Record<string, string> = {
  responded: 'bg-emerald-100 text-emerald-700 border-emerald-200',
  passed: 'bg-zinc-100 text-zinc-500 border-zinc-200',
  skipped: 'bg-amber-100 text-amber-700 border-amber-200',
  filtered: 'bg-red-100 text-red-600 border-red-200',
  interrupted: 'bg-violet-100 text-violet-700 border-violet-200',
}

const verdictIcons: Record<string, string> = {
  responded: '✅',
  passed: '⏭️',
  skipped: '⚠️',
  filtered: '🚫',
  interrupted: '⚡',
}

function VerdictBadge({ verdict }: { verdict: AgentVerdict }) {
  const agent = agentMap.value.get(verdict.agentId)
  return (
    <span
      class={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border ${
        verdictColors[verdict.verdict] ?? 'bg-zinc-100 text-zinc-500'
      }`}
    >
      {verdictIcons[verdict.verdict] ?? '•'} {agent?.name ?? verdict.agentName}
    </span>
  )
}

function RoundCard({ round }: { round: OracleRound }) {
  return (
    <div class="glass rounded-xl p-4 space-y-3">
      <div class="flex items-center justify-between">
        <h4 class="text-sm font-semibold text-zinc-800">
          Round {round.round}
          <span class="ml-2 text-xs font-normal text-accent">{round.mode}</span>
        </h4>
        {round.grader && (
          <span
            class={`text-xs px-2 py-0.5 rounded-full ${
              round.grader.done
                ? 'bg-emerald-100 text-emerald-700'
                : 'bg-amber-100 text-amber-700'
            }`}
          >
            {round.grader.done ? '✓ Complete' : '⟳ Continue'}
          </span>
        )}
      </div>

      {/* Reasoning */}
      {round.reasoning && (
        <div class="text-xs text-zinc-500 bg-zinc-50 rounded-lg p-2 font-mono leading-relaxed">
          {round.reasoning}
        </div>
      )}

      {/* Speakers */}
      <div class="space-y-1">
        {round.speakers.map((s) => {
          const agent = agentMap.value.get(s.agent_id)
          return (
            <div
              key={s.agent_id}
              class={`flex items-center gap-2 text-xs rounded-lg px-2 py-1 ${
                s.should_respond ? 'bg-cyan-50 text-cyan-800' : 'bg-zinc-50 text-zinc-400'
              }`}
            >
              <span class="font-medium">{agent?.name ?? s.agent_name}</span>
              {s.should_respond ? (
                <span class="text-cyan-500">● speaking</span>
              ) : (
                <span class="text-zinc-300">○ silent</span>
              )}
              {s.hint && <span class="text-zinc-400 italic ml-auto truncate max-w-48">"{s.hint}"</span>}
            </div>
          )
        })}
      </div>

      {/* Verdicts */}
      {round.verdicts.length > 0 && (
        <div class="flex flex-wrap gap-1">
          {round.verdicts.map((v) => (
            <VerdictBadge key={v.agentId} verdict={v} />
          ))}
        </div>
      )}

      {/* Grader reasoning */}
      {round.grader?.reasoning && (
        <div class="text-xs text-zinc-400 italic border-t border-zinc-100 pt-2">
          🧠 {round.grader.reasoning}
        </div>
      )}
    </div>
  )
}

export function OracleMonitor() {
  const state = oracleState.value

  return (
    <div class="flex flex-col h-full">
      {/* Header */}
      <div class="px-4 py-3 border-b border-zinc-200 flex items-center justify-between">
        <div class="flex items-center gap-2">
          <h3 class="text-sm font-semibold text-zinc-800">Oracle Monitor</h3>
          <span
            class={`w-2 h-2 rounded-full ${
              state.active ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-300'
            }`}
          />
        </div>
        {state.directed && state.directedAgent && (
          <span class="text-xs px-2 py-0.5 rounded-full bg-violet-100 text-violet-700">
            Directed → {agentMap.value.get(state.directedAgent)?.name ?? state.directedAgent}
          </span>
        )}
      </div>

      {/* Content */}
      <div class="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Goal */}
        {state.goal && (
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] font-medium text-zinc-400 uppercase tracking-wider mb-1">Goal</div>
            <div class="text-sm text-zinc-700">{state.goal}</div>
          </div>
        )}

        {/* Topic */}
        {state.topic && (
          <div class="glass rounded-xl p-3">
            <div class="text-[10px] font-medium text-zinc-400 uppercase tracking-wider mb-1">Topic</div>
            <div class="text-sm text-zinc-700">{state.topic}</div>
          </div>
        )}

        {/* Rounds */}
        {state.rounds.map((round) => (
          <RoundCard key={round.round} round={round} />
        ))}

        {/* Summary */}
        {state.summary && (
          <div class="glass rounded-xl p-4 border-l-2 border-accent">
            <div class="text-[10px] font-medium text-zinc-400 uppercase tracking-wider mb-1">Summary</div>
            <div class="text-sm text-zinc-700 leading-relaxed">{state.summary}</div>
          </div>
        )}

        {/* Empty state */}
        {!state.active && state.rounds.length === 0 && (
          <div class="text-center text-zinc-400 text-sm py-8">
            <div class="text-2xl mb-2">🔮</div>
            <p>Oracle is idle</p>
            <p class="text-xs mt-1">Send a message to see decision-making in real time</p>
          </div>
        )}
      </div>
    </div>
  )
}
