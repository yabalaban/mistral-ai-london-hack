import { useState } from 'preact/hooks'
import { useConversation } from '../../hooks/useConversation.ts'
import { useVoice } from '../../hooks/useVoice.ts'
import {
  activeConversation,
  addOptimisticMessage,
} from '../../state/conversations.ts'
import { activeCall, callMode } from '../../state/call.ts'
import { startCall, endCall, sendMessage } from '../../api/client.ts'
import { Header } from '../layout/Header.tsx'
import { ParticipantRing } from './ParticipantRing.tsx'
import { GroupMessages } from './GroupMessages.tsx'
import { CallControls } from './CallControls.tsx'
import { ChatInput } from '../chat/ChatInput.tsx'
import { AgentPicker } from './AgentPicker.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { Button } from '../shared/Button.tsx'
import { generateId } from '../../utils/format.ts'
import { route } from 'preact-router'
import type { Attachment } from '../../types/index.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

interface GroupPageProps {
  id?: string
}

export function GroupPage({ id }: GroupPageProps) {
  if (!id) return null

  useConversation(id)
  const { toggleMic } = useVoice()
  const [showPicker, setShowPicker] = useState(false)

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
      await startCall(id)
    } catch (err) {
      console.error('Failed to start call', err)
    }
  }

  const handleEndCall = async () => {
    if (USE_MOCKS) {
      activeCall.value = null
      route('/')
      return
    }
    try {
      await endCall(id)
    } catch (err) {
      console.error('Failed to end call', err)
    }
    route('/')
  }

  const handleToggleMode = () => {
    callMode.value = mode === 'text' ? 'voice' : 'text'
  }

  const handleSend = async (content: string, attachments?: Attachment[]) => {
    addOptimisticMessage({
      id: generateId(),
      role: 'user',
      content,
      timestamp: new Date().toISOString(),
      attachments,
    })

    if (!USE_MOCKS) {
      try {
        await sendMessage(
          id,
          content,
          attachments?.map((a) => ({ type: 'image', url: a.url })),
        )
      } catch (err) {
        console.error('Failed to send message', err)
      }
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

  return (
    <>
      <Header title="Group Call">
        {!call && (
          <Button onClick={handleStartCall}>Start Call</Button>
        )}
        <button
          onClick={() => setShowPicker(true)}
          class="p-2 text-dc-text-muted hover:text-dc-text transition-colors"
          title="Add agents"
        >
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z" />
          </svg>
        </button>
      </Header>

      <div class="flex-1 flex overflow-hidden">
        <div class="flex-1 flex flex-col">
          <ParticipantRing participantIds={participants} />
          {call ? (
            <>
              {mode === 'text' && (
                <ChatInput onSend={handleSend} placeholder="Type a message to the group..." />
              )}
              <CallControls
                onToggleMic={toggleMic}
                onEndCall={handleEndCall}
                onToggleMode={handleToggleMode}
              />
            </>
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
    </>
  )
}
