import { eventRounds } from '../../state/activity.ts'
import { RoundCard } from './RoundCard.tsx'

export function ActivityFeed() {
  const rounds = eventRounds.value

  if (rounds.length === 0) {
    return (
      <div class="flex-1 flex flex-col items-center justify-center text-zinc-400 gap-2">
        <div class="text-4xl">📡</div>
        <p class="text-sm">Waiting for events...</p>
        <p class="text-xs text-zinc-300">Send a message in Discord or web chat to see real-time activity</p>
      </div>
    )
  }

  return (
    <div class="flex-1 overflow-y-auto p-4 space-y-2">
      {rounds.map((round) => (
        <RoundCard key={round.id} round={round} />
      ))}
    </div>
  )
}
