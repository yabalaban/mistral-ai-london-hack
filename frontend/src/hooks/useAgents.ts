import { useEffect } from 'preact/hooks'
import { agents, agentsLoading } from '../state/agents.ts'
import { fetchAgents } from '../api/client.ts'

export function useAgents() {
  useEffect(() => {
    if (agents.value.length > 0) return

    agentsLoading.value = true
    fetchAgents()
      .then((data) => {
        agents.value = data
      })
      .catch((err) => {
        console.error('Failed to fetch agents', err)
      })
      .finally(() => {
        agentsLoading.value = false
      })
  }, [])
}
