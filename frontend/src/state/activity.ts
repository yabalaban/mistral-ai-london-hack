import { signal, computed } from '@preact/signals'

export interface SystemEvent {
  type: string
  conversation_id: string
  source: 'discord' | 'web'
  source_label: string
  data: Record<string, unknown>
  timestamp: number
}

const MAX_EVENTS = 500

export const allEvents = signal<SystemEvent[]>([])
export const activeConversationFilter = signal<string | null>(null)

export const conversationIds = computed(() => {
  const ids = new Set<string>()
  for (const e of allEvents.value) {
    ids.add(e.conversation_id)
  }
  return Array.from(ids)
})

export const conversationLabels = computed(() => {
  const map = new Map<string, string>()
  for (const e of allEvents.value) {
    if (!map.has(e.conversation_id)) {
      map.set(e.conversation_id, e.source_label)
    }
  }
  return map
})

export const filteredEvents = computed(() => {
  const filter = activeConversationFilter.value
  if (!filter) return allEvents.value
  return allEvents.value.filter((e) => e.conversation_id === filter)
})

/** A round groups a user_message with all subsequent pipeline events for that conversation. */
export interface EventRound {
  id: string
  conversation_id: string
  source: 'discord' | 'web'
  source_label: string
  trigger: string // user message content
  events: SystemEvent[] // all events in chronological order (oldest first)
  timestamp: number // round start time
}

export const eventRounds = computed((): EventRound[] => {
  const events = filteredEvents.value
  if (events.length === 0) return []

  // Events are newest-first — reverse to process chronologically
  const chrono = [...events].reverse()

  const rounds: EventRound[] = []
  let current: EventRound | null = null

  for (const e of chrono) {
    if (e.type === 'user_message') {
      // Start a new round
      current = {
        id: `${e.conversation_id}-${e.timestamp}`,
        conversation_id: e.conversation_id,
        source: e.source,
        source_label: e.source_label,
        trigger: String(e.data.content || ''),
        events: [e],
        timestamp: e.timestamp,
      }
      rounds.push(current)
    } else if (current && e.conversation_id === current.conversation_id) {
      // Append to current round
      current.events.push(e)
    } else {
      // Orphan event (no user_message before it) — wrap in its own round
      rounds.push({
        id: `${e.conversation_id}-${e.timestamp}`,
        conversation_id: e.conversation_id,
        source: e.source,
        source_label: e.source_label,
        trigger: '',
        events: [e],
        timestamp: e.timestamp,
      })
      current = null
    }
  }

  // Return newest-first
  return rounds.reverse()
})

export function pushEvent(event: SystemEvent) {
  const current = allEvents.value
  const next = [event, ...current]
  if (next.length > MAX_EVENTS) next.length = MAX_EVENTS
  allEvents.value = next
}
