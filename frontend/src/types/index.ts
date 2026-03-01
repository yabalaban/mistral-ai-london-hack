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
  role: 'user' | 'assistant' | 'system'
  agent_id?: string
  content: string
  timestamp: string
  attachments?: Attachment[]
  reply_to_id?: string
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
  topic?: string | null
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
  | { type: 'message_partial'; message: Message }
  | { type: 'turn_change'; agent_id: string; reply_to_id?: string }
  | { type: 'oracle_start'; directed: boolean; directed_agent?: string; goal?: string }
  | { type: 'oracle_end' }
  | { type: 'oracle_reasoning'; reasoning: string; speakers: Array<{ agent_id: string; agent_name: string; should_respond: boolean; hint: string | null }>; round: number; mode: string }
  | { type: 'topic_set'; topic: string }
  | { type: 'summary'; content: string }
  | { type: 'grader'; reasoning: string; done: boolean; round: number }
  | { type: 'agent_verdict'; agent_id: string; agent_name: string; verdict: 'responded' | 'passed' | 'skipped' | 'filtered' | 'interrupted' }
  | { type: 'call_started'; call: GroupCall }
  | { type: 'call_ended'; call_id: string }
  | { type: 'audio_chunk'; agent_id: string; data: string }
  | { type: 'transcription'; text: string; final?: boolean }
  | { type: 'partial_transcript'; text: string }
  | { type: 'agent_speaking'; agent_id: string }
  | { type: 'agent_done'; agent_id: string }
  | { type: 'interrupt' }
  | { type: 'agent_interrupted'; agent_id: string; by: string }
  | { type: 'error'; message: string }
