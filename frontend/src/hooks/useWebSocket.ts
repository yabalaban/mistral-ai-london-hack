import { useEffect } from 'preact/hooks'
import type { WSEvent } from '../types/index.ts'
import { wsManager } from '../api/ws.ts'

export function useWebSocket(handler: (event: WSEvent) => void) {
  useEffect(() => {
    return wsManager.onEvent(handler)
  }, [handler])
}
