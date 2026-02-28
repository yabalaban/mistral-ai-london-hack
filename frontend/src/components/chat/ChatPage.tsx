import { useState } from 'preact/hooks'
import { useConversation } from '../../hooks/useConversation.ts'
import {
  activeConversation,
  addOptimisticMessage,
} from '../../state/conversations.ts'
import { agentMap } from '../../state/agents.ts'
import { sendMessage } from '../../api/client.ts'
import { Header } from '../layout/Header.tsx'
import { MessageList } from './MessageList.tsx'
import { ChatInput } from './ChatInput.tsx'
import { Spinner } from '../shared/Spinner.tsx'
import { LogsPanel } from '../shared/LogsPanel.tsx'
import type { LogEntry } from '../shared/LogsPanel.tsx'
import { generateId } from '../../utils/format.ts'
import type { Attachment } from '../../types/index.ts'

const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true'

interface ChatPageProps {
  id?: string
}

export function ChatPage({ id }: ChatPageProps) {
  if (!id) return null

  useConversation(id)
  const [logsOpen, setLogsOpen] = useState(false)
  const [logEntries] = useState<LogEntry[]>([])

  const conv = activeConversation.value

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

  const agentId = conv?.participants.find((p) => p !== 'user')
  const agent = agentId ? agentMap.value.get(agentId) : null
  const title = agent?.name ? `Chat with ${agent.name}` : 'Chat'

  return (
    <>
      <Header title={title} onToggleLogs={() => setLogsOpen((o) => !o)} />
      {!conv ? (
        <div class="flex-1 flex items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <>
          <MessageList messages={conv.messages} />
          <ChatInput onSend={handleSend} placeholder={`Message ${agent?.name ?? 'agent'}...`} />
        </>
      )}
      <LogsPanel open={logsOpen} onClose={() => setLogsOpen(false)} entries={logEntries} />
    </>
  )
}
