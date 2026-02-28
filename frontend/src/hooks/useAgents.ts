import { useEffect } from 'preact/hooks'
import { agents, agentsLoading, agentsError } from '../state/agents.ts'
import { fetchAgents } from '../api/client.ts'
import { mockAgents } from '../mocks/agents.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

export function useAgents() {
  useEffect(() => {
    if (agents.value.length > 0) return

    if (USE_MOCKS) {
      agents.value = mockAgents
      return
    }

    agentsLoading.value = true
    fetchAgents()
      .then((data) => {
        agents.value = data
      })
      .catch((err) => {
        agentsError.value = err.message
        // Fallback to mocks on error
        agents.value = mockAgents
      })
      .finally(() => {
        agentsLoading.value = false
      })
  }, [])
}
