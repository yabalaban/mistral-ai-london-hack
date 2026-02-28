import { useState } from 'preact/hooks'
import { useConversation } from '../../hooks/useConversation.ts'
import { useVoice } from '../../hooks/useVoice.ts'
import {
  activeConversation,
  addOptimisticMessage,
} from '../../state/conversations.ts'
import { agentMap } from '../../state/agents.ts'
import { activeCall, callMode } from '../../state/call.ts'
import { startCall, endCall } from '../../api/client.ts'
import { wsManager } from '../../api/ws.ts'
import { Header } from '../layout/Header.tsx'
import { ParticipantRing } from './ParticipantRing.tsx'
import { GroupMessages } from './GroupMessages.tsx'
import { CallControls } from './CallControls.tsx'
import { ChatInput } from '../chat/ChatInput.tsx'
import { MessageList } from '../chat/MessageList.tsx'
import { AgentPicker } from './AgentPicker.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { LogsPanel } from '../shared/LogsPanel.tsx'
import type { LogEntry } from '../shared/LogsPanel.tsx'
import { generateId } from '../../utils/format.ts'
import type { Attachment } from '../../types/index.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

interface GroupPageProps {
  path?: string
  id?: string
}

export function GroupPage({ id }: GroupPageProps) {
  if (!id) return null

  useConversation(id)
  const { toggleMic } = useVoice()
  const [showPicker, setShowPicker] = useState(false)
  const [logsOpen, setLogsOpen] = useState(false)
  const [logEntries] = useState<LogEntry[]>([])

  const conv = activeConversation.value
  const call = activeCall.value
  const mode = callMode.value

  const handleStartCall = async () => {
    if (USE_MOCKS) {
      activeCall.value = {
        id: `call-${Date.now()}`,
        conversation_id: id,
        participants: conv?.participants.filter((p) => p !== 'user') ?? [],
        oracle_agent_id: 'oracle',
        status: 'active',
        mode: 'text',
      }
      return
    }
    try {
      const call = await startCall(id)
      activeCall.value = call
    } catch (err) {
      console.error('Failed to start call', err)
    }
  }

  const handleEndCall = async () => {
    if (USE_MOCKS) {
      activeCall.value = null
      return
    }
    try {
      await endCall(id)
    } catch (err) {
      console.error('Failed to end call', err)
    }
    activeCall.value = null
  }

  const handleToggleMode = () => {
    callMode.value = mode === 'text' ? 'voice' : 'text'
  }

  const handleSend = (content: string, attachments?: Attachment[]) => {
    addOptimisticMessage({
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      attachments,
    })

    if (!USE_MOCKS) {
      wsManager.send({
        type: 'message',
        content,
        attachments: attachments?.map((a) => ({ type: 'image', url: a.url })) ?? [],
      })
    }
  }

  if (!conv) {
    return (
      <>
        <Header title="Group Call" />
        <div class="flex-1 flex items-center justify-center">
          <Spinner />
        </div>
      </>
    )
  }

  const participants = conv.participants
  const participantNames = participants
    .filter((p) => p !== 'user')
    .map((id) => agentMap.value.get(id)?.name)
    .filter(Boolean)
    .join(', ')
  const title = participantNames || 'Group Chat'

  return (
    <>
      <Header title={title} onToggleLogs={() => setLogsOpen((o) => !o)}>
        {!call ? (
          <button
            onClick={handleStartCall}
            class="p-2 text-white/40 hover:text-accent transition-colors"
            title="Call everyone"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 5a2 2 0 012-2h3.28a1 1 0 01.948.684l1.498 4.493a1 1 0 01-.502 1.21l-2.257 1.13a11.042 11.042 0 005.516 5.516l1.13-2.257a1 1 0 011.21-.502l4.493 1.498a1 1 0 01.684.949V19a2 2 0 01-2 2h-1C9.716 21 3 14.284 3 6V5z" />
            </svg>
          </button>
        ) : (
          <button
            onClick={handleEndCall}
            class="p-2 text-danger hover:text-red-400 transition-colors"
            title="End call"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 8l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2M5 3a2 2 0 00-2 2v1c0 8.284 6.716 15 15 15h1a2 2 0 002-2v-3.28a1 1 0 00-.684-.948l-4.493-1.498a1 1 0 00-1.21.502l-1.13 2.257a11.042 11.042 0 01-5.516-5.516l2.257-1.13a1 1 0 00.502-1.21L8.228 3.684A1 1 0 007.28 3H5z" />
            </svg>
          </button>
        )}
        <button
          onClick={() => setShowPicker(true)}
          class="p-2 text-white/40 hover:text-white transition-colors"
          title="Add agents"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
          </svg>
        </button>
      </Header>

      <div class="flex-1 flex overflow-hidden">
        <div class="flex-1 flex flex-col">
          {call && <ParticipantRing participantIds={participants} />}
          {!call && <MessageList messages={conv.messages} />}
          {call && mode === 'text' && (
            <ChatInput onSend={handleSend} placeholder="Type a message to the group..." />
          )}
          {call ? (
            <CallControls
              onToggleMic={toggleMic}
              onEndCall={handleEndCall}
              onToggleMode={handleToggleMode}
            />
          ) : (
            <ChatInput onSend={handleSend} placeholder="Type a message to the group..." />
          )}
        </div>
        <GroupMessages messages={conv.messages} />
      </div>

      {showPicker && (
        <AgentPicker
          excludeIds={participants}
          onSelect={(ids) => {
            console.log('Add agents:', ids)
            setShowPicker(false)
          }}
          onClose={() => setShowPicker(false)}
        />
      )}

      <LogsPanel open={logsOpen} onClose={() => setLogsOpen(false)} entries={logEntries} />
    </>
  )
}
