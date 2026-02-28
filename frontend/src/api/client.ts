/**
 * Backend REST API client.
 *
 * Base URL: /api (proxied by Vite to backend :8000)
 *
 * Endpoints:
 *   GET    /api/agents                          → Agent[]
 *   GET    /api/conversations/:id               → Conversation
 *   POST   /api/conversations  {type, participants}  → Conversation
 *   POST   /api/conversations/:id/call          → GroupCall
 *   DELETE /api/conversations/:id/call          → GroupCall
 *
 * WebSocket:
 *   ws://host/ws/conversations/:id  (see ws.ts for protocol)
 */

import type { Agent, Conversation, GroupCall } from '../types/index.ts'

const BASE = '/api'

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`)
  return res.json()
}

export function fetchAgents(): Promise<Agent[]> {
  return request('/agents')
}

export function fetchConversation(id: string): Promise<Conversation> {
  return request(`/conversations/${id}`)
}

export function createConversation(
  type: 'direct' | 'group',
  participants: string[],
): Promise<Conversation> {
  return request('/conversations', {
    method: 'POST',
    body: JSON.stringify({ type, participants }),
  })
}

export function startCall(conversationId: string): Promise<GroupCall> {
  return request(`/conversations/${conversationId}/call`, { method: 'POST' })
}

export function endCall(conversationId: string): Promise<GroupCall> {
  return request(`/conversations/${conversationId}/call`, { method: 'DELETE' })
}
