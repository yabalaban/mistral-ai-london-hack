import { pushEvent } from '../state/activity.ts'
import type { SystemEvent } from '../state/activity.ts'

let ws: WebSocket | null = null
let reconnectTimer: ReturnType<typeof setTimeout> | null = null

function getWsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/events`
}

export function connectEventsFeed() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return
  }

  ws = new WebSocket(getWsUrl())

  ws.onopen = () => {
    console.log('[events-ws] connected')
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
  }

  ws.onmessage = (ev) => {
    try {
      const event: SystemEvent = JSON.parse(ev.data)
      pushEvent(event)
    } catch (err) {
      console.warn('[events-ws] bad message', err)
    }
  }

  ws.onclose = () => {
    console.log('[events-ws] disconnected, reconnecting in 3s')
    ws = null
    reconnectTimer = setTimeout(connectEventsFeed, 3000)
  }

  ws.onerror = (err) => {
    console.warn('[events-ws] error', err)
    ws?.close()
  }
}

export function disconnectEventsFeed() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.onclose = null
    ws.close()
    ws = null
  }
}
