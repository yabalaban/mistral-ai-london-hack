import { signal, computed } from '@preact/signals'
import type { Agent } from '../types/index.ts'

export const agents = signal<Agent[]>([])
export const agentsLoading = signal(false)
export const agentsError = signal<string | null>(null)

export const agentMap = computed(() => {
  const map = new Map<string, Agent>()
  for (const a of agents.value) {
    map.set(a.id, a)
  }
  return map
})
