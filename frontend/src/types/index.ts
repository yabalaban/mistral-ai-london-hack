export interface Agent {
  id: string
  name: string
  role: string
  bio: string
  avatar: string
  personality: string
  voice_id?: string
  tools?: string[]
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  agent_id?: string
  content: string
  timestamp: string
  attachments?: Attachment[]
}

export interface Attachment {
  type: 'image'
  url: string
  name?: string
}

export interface Conversation {
  id: string
  type: 'direct' | 'group'
  participants: string[]
  messages: Message[]
  created_at: string
}

export interface GroupCall {
  id: string
  conversation_id: string
  participants: string[]
  oracle_agent_id: string
  status: 'active' | 'ended'
  mode: 'text' | 'voice'
}

export type WSEvent =
  | { type: 'message_chunk'; agent_id: string; content: string; message_id: string }
  | { type: 'message_complete'; message: Message }
  | { type: 'turn_change'; agent_id: string }
  | { type: 'call_started'; call: GroupCall }
  | { type: 'call_ended'; call_id: string }
  | { type: 'audio_chunk'; agent_id: string; data: string }
  | { type: 'transcription'; text: string }
  | { type: 'error'; message: string }
