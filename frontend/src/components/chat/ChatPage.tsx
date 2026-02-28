import { useConversation } from '../../hooks/useConversation.ts'
import { useVoice } from '../../hooks/useVoice.ts'
import {
  activeConversation,
  addOptimisticMessage,
} from '../../state/conversations.ts'
import { agentMap } from '../../state/agents.ts'
import { activeCall, callMode, isMicOn, partialTranscript } from '../../state/call.ts'
import { startCall, endCall } from '../../api/client.ts'
import { wsManager } from '../../api/ws.ts'
import { Header } from '../layout/Header.tsx'
import { MessageList } from './MessageList.tsx'
import { ChatInput } from './ChatInput.tsx'
import { AgentProfilePanel } from './AgentProfilePanel.tsx'
import { CallControls } from '../group/CallControls.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { generateId } from '../../utils/format.ts'
import type { Attachment } from '../../types/index.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

interface ChatPageProps {
  path?: string
  id?: string
}

export function ChatPage({ id }: ChatPageProps) {
  useConversation(id ?? '')
  const { toggleMic } = useVoice()

  if (!id) return null

  const conv = activeConversation.value
  const call = activeCall.value
  const mode = callMode.value

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

  const handleStartCall = async () => {
    if (USE_MOCKS) {
      activeCall.value = {
        id: `call-${Date.now()}`,
        conversation_id: id,
        participants: conv?.participants.filter((p) => p !== 'user') ?? [],
        oracle_agent_id: conv?.participants.find((p) => p !== 'user') ?? '',
        status: 'active',
        mode: 'text',
      }
      return
    }
    try {
      const call = await startCall(id)
      activeCall.value = call
      callMode.value = 'voice'
      toggleMic()
    } catch (err) {
      console.error('Failed to start call', err)
    }
  }

  const handleEndCall = async () => {
    if (USE_MOCKS) {
      activeCall.value = null
      return
    }
    if (isMicOn.value) {
      toggleMic()
    }
    try {
      await endCall(id)
    } catch (err) {
      console.error('Failed to end call', err)
    }
    activeCall.value = null
    callMode.value = 'text'
  }

  const handleToggleMode = () => {
    callMode.value = mode === 'text' ? 'voice' : 'text'
  }

  const agentId = conv?.participants.find((p) => p !== 'user')
  const agent = agentId ? agentMap.value.get(agentId) : null

  let title: string
  if (conv?.type === 'group') {
    if (conv.topic && conv.topic !== 'General discussion') {
      title = conv.topic.length > 60 ? conv.topic.slice(0, 57) + '...' : conv.topic
    } else {
      const names = conv.participants
        .map((id) => agentMap.value.get(id)?.name ?? id)
        .join(', ')
      title = names
    }
  } else {
    title = agent?.name ? `Chat with ${agent.name}` : 'Chat'
  }

  return (
    <>
      <Header title={title}>
        {!call ? (
          <button
            onClick={handleStartCall}
            class="p-2 text-white/40 hover:text-accent transition-colors"
            title={`Call ${agent?.name ?? 'agent'}`}
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
      </Header>
      {!conv ? (
        <div class="flex-1 flex items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <div class="flex-1 flex overflow-hidden">
          <div class="flex-1 flex flex-col min-w-0">
            <div class="flex-1 overflow-hidden relative">
              <MessageList messages={conv.messages} />
              {call && mode === 'voice' && partialTranscript.value && (
                <div class="absolute bottom-2 left-4 right-4 px-4 py-2 glass rounded-lg text-white/60 text-sm italic animate-pulse">
                  🎤 {partialTranscript.value}
                </div>
              )}
            </div>
            {(!call || mode === 'text') && (
              <ChatInput onSend={handleSend} placeholder={`Message ${agent?.name ?? 'agent'}...`} />
            )}
            {call && (
              <CallControls
                onToggleMic={toggleMic}
                onEndCall={handleEndCall}
                onToggleMode={handleToggleMode}
              />
            )}
          </div>
          {agent && <AgentProfilePanel agent={agent} />}
        </div>
      )}
    </>
  )
}
